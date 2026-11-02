"""Follow-up suggestion chips — pure helpers (no I/O, no settings import).

Given the last user/assistant exchange, build a small prompt asking a side LLM
for 2–3 quick-reply suggestions the CUSTOMER could send next, and parse the
model's JSON response into ``[{"label", "text"}]``. Kept pure so they unit-test
with plain strings/fakes.
"""

from __future__ import annotations

import json
import re

_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def build_suggestions_prompt(user_text: str, assistant_text: str, customer, *, agent_name: str = "Luna") -> str:
    """Vietnamese prompt asking a side LLM for up to 3 follow-up chips.

    The suggestions are phrased as what the CUSTOMER could say/ask next. Each has
    a short ``label`` (<= 24 chars, shown on the button) and a full ``text`` (the
    message sent when tapped). Instructs an EMPTY array when nothing fits
    (farewell / already escalated / booking closed). JSON-only output. Light
    profile hints (project_interest, purpose) are injected when present.
    """
    profile_lines = []
    project_interest = getattr(customer, "project_interest", None)
    purpose = getattr(customer, "purpose", None)
    if project_interest:
        profile_lines.append(f"- Dự án khách quan tâm: {project_interest}")
    if purpose:
        profile_lines.append(f"- Mục đích: {purpose}")
    profile_block = ("\nHồ sơ khách (để gợi ý sát hơn):\n" + "\n".join(profile_lines)) if profile_lines else ""

    return (
        f"Bạn hỗ trợ trợ lý bán hàng {agent_name} của NobleX. Dựa vào đoạn hội thoại dưới đây giữa "
        f"khách và {agent_name}, hãy đề xuất TỐI ĐA 3 câu mà KHÁCH có thể nói/hỏi {agent_name} ở lượt tiếp theo.\n\n"
        f"[Khách]: {user_text}\n"
        f"[{agent_name}]: {assistant_text}\n"
        f"{profile_block}\n\n"
        "BƯỚC 0 — KIỂM TRA KẾT THÚC (làm trước tiên): Nếu cuộc trò chuyện đã kết thúc thì BẮT "
        "BUỘC trả về đúng mảng rỗng [] và DỪNG — KHÔNG gợi ý gì, KHÔNG tự nghĩ ra lý do để "
        'tiếp tục. Coi là đã kết thúc khi: khách chào/muốn dừng (vd "thôi", "để hôm khác", '
        f'"bận rồi", "cảm ơn nhé", "chào em", "ok vậy thôi"); HOẶC {agent_name} vừa chào tạm biệt/kết '
        'thúc (vd "hẹn gặp lại", "em chào anh", "cảm ơn anh đã quan tâm"); HOẶC khách đã được '
        "chuyển cho chuyên viên; HOẶC đã chốt xong lịch hẹn.\n\n"
        "Nếu cuộc trò chuyện VẪN đang tiếp diễn, áp dụng các quy tắc sau:\n"
        f"1. Mỗi gợi ý là LỜI CỦA KHÁCH nói với {agent_name} — KHÔNG phải lời {agent_name}. Khách tự xưng "
        f'"tôi/mình" (hoặc không xưng), gọi trợ lý là "{agent_name}/em"; khách KHÔNG tự xưng "em" '
        f'("em" là {agent_name}). Ví dụ SAI (đây là lời {agent_name}): "Anh cho em xem…", "Để em gửi anh…". '
        'Ví dụ ĐÚNG (lời khách): "Cho tôi xem vài hình ảnh dự án này với".\n'
        "2. Chỉ bám vào NỘI DUNG đã xuất hiện trong hội thoại và hồ sơ khách. TUYỆT ĐỐI KHÔNG "
        "bịa tên dự án, tên căn hộ, con số, hay tính năng chưa được nhắc tới. Chưa có dự án cụ "
        "thể thì nói chung chung, không nêu tên.\n"
        f"3. Chỉ gợi ý những việc {agent_name} THỰC SỰ làm được: hỏi thêm về dự án/căn hộ đang nói tới "
        "(vị trí, giá, tiện ích, mặt bằng, pháp lý), xin xem hình ảnh dự án/căn hộ, đặt lịch "
        "tham quan, hoặc nhờ chuyên viên tư vấn liên hệ lại. KHÔNG gợi ý gửi tài liệu/brochure "
        "qua Zalo/email/kênh ngoài — mọi thứ diễn ra ngay trong cuộc trò chuyện này.\n"
        "4. Thà trả ÍT gợi ý còn hơn bịa. Không có gợi ý phù hợp nào → trả về mảng rỗng [].\n\n"
        "Mỗi gợi ý gồm:\n"
        '- "label": nhãn ngắn (tối đa 24 ký tự) hiển thị trên nút bấm.\n'
        '- "text": câu đầy đủ khách sẽ gửi khi bấm nút (đúng vai khách).\n\n'
        'Chỉ trả JSON dạng: [{"label":"…","text":"…"}]. Không giải thích gì thêm.'
    )


def _load_array(raw: str):
    """Parse ``raw`` into a Python object, tolerating ```json fences / prose.

    Tries a direct ``json.loads`` first; on failure, extracts the first ``[...]``
    array (DOTALL) and parses that. Returns whatever parsed (may not be a list).
    """
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        pass
    match = _ARRAY_RE.search(raw or "")
    if not match:
        return None
    return json.loads(match.group(0))


def parse_suggestions(raw: str, max_n: int = 3) -> list[dict]:
    """Parse the side-LLM response into ``[{"label", "text"}]`` (max ``max_n``).

    Robust to fenced / prose-wrapped JSON. Drops any item missing a non-empty
    string ``label`` or ``text``; truncates ``label`` to 24 chars (``text`` is
    left intact). Any parse error → ``[]`` (never raises).
    """
    try:
        data = _load_array(raw)
        if not isinstance(data, list):
            return []
        out: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            text = item.get("text")
            if not isinstance(label, str) or not isinstance(text, str):
                continue
            label = label.strip()
            text = text.strip()
            if not label or not text:
                continue
            out.append({"label": label[:24], "text": text})
            if len(out) >= max_n:
                break
        return out
    except Exception:
        return []
