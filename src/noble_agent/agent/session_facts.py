"""Session facts — bộ nhớ XÁC ĐỊNH của phiên, do CODE ghi từ kết quả tool.

Vì sao: hồ sơ khách trong system prompt bị đóng băng cả phiên (giữ prefix cache), còn
summary là văn xuôi do LLM viết — mã căn, tài liệu, lịch hẹn hay rơi khi nén. Ở đây
dispatcher ghi lại đúng những thứ đã ĐƯA CHO KHÁCH (căn đã giới thiệu, tài liệu / ảnh
đã gửi, lịch đã chốt, đã chuyển chuyên viên) vào `state.scratchpad["session_facts"]`,
rồi `render()` dựng khối "[Ngữ cảnh hiện tại …]" cùng hồ sơ MỚI NHẤT của khách. Runner
chèn khối này vào đầu user message cuối của REQUEST (không persist) — phần đuôi vốn thay
đổi mỗi lượt nên prefix cache không bị ảnh hưởng.

Chỉ ghi khi tool trả kết quả thật (JSON hợp lệ, không `ok: false` / `error`); không
bao giờ raise — đây là bộ nhớ phụ, không được làm hỏng lượt.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("noble_agent.agent.session_facts")

KEY = "session_facts"
MAX_UNITS = 8
MAX_DOCS = 4
MAX_MEDIA = 6
HEADER = "[Ngữ cảnh hiện tại — hệ thống tự cập nhật, không phải lời khách]"


def format_price(v) -> str:
    """3200000000 → '3,2 tỷ'; 800000000 → '800 triệu'; 0/None → 'chưa có giá'."""
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        n = 0.0
    if n <= 0:
        return "chưa có giá"
    if n >= 1e9:
        s = f"{n / 1e9:.1f}".rstrip("0").rstrip(".")
        return f"{s.replace('.', ',')} tỷ"
    return f"{int(round(n / 1e6))} triệu"


def format_unit(u: dict) -> str:
    """'A-1203 (2PN, 3,2 tỷ, Noble Crystal)' — chỉ những trường có."""
    parts: list[str] = []
    bedrooms = u.get("bedrooms")
    if bedrooms not in (None, "", 0):
        parts.append(f"{bedrooms}PN")
    parts.append(format_price(u.get("price_vnd")))
    project = u.get("project_name") or u.get("project_code") or u.get("project")
    if project:
        parts.append(str(project))
    return f"{u.get('unit_code') or u.get('code') or '?'} ({', '.join(parts)})"


def _load(state) -> dict:
    raw = state.scratchpad.get(KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _merge_front(new: list, old: list, key, cap: int) -> list:
    seen = {key(x) for x in new}
    return (new + [x for x in old if key(x) not in seen])[:cap]


def record(state, name: str, args: dict, result: str) -> None:
    """Ghi fact từ kết quả `name`; im lặng bỏ qua kết quả lỗi / không phải JSON."""
    try:
        data = json.loads(result)
    except (TypeError, ValueError):
        return
    if not isinstance(data, dict) or data.get("ok") is False or data.get("error"):
        return
    try:
        facts = _load(state)
        args = args or {}
        if name == "search_units" and isinstance(data.get("units"), list):
            fresh = [
                {
                    "unit_code": u.get("unit_code"),
                    "bedrooms": u.get("bedrooms"),
                    "price_vnd": u.get("price_vnd"),
                    "project_name": u.get("project_name") or u.get("project_code"),
                }
                for u in data["units"]
                if isinstance(u, dict) and u.get("unit_code")
            ]
            if fresh:
                facts["units"] = _merge_front(fresh, facts.get("units", []), lambda u: u["unit_code"], MAX_UNITS)
        elif name == "get_document" and isinstance(data.get("documents"), list):
            titles = [d.get("title") for d in data["documents"] if isinstance(d, dict) and d.get("title")]
            if titles:
                facts["docs"] = _merge_front(titles, facts.get("docs", []), lambda t: t, MAX_DOCS)
        elif name == "send_media" and data.get("items"):
            label = data.get("caption") or f"media dự án {data.get('project_name', '')}".strip()
            facts["media"] = _merge_front([label], facts.get("media", []), lambda t: t, MAX_MEDIA)
        elif name == "booking" and data.get("appointment_id"):
            cur = facts.get("booking") or {}
            facts["booking"] = {
                "id": data["appointment_id"],
                "project": data.get("project") or cur.get("project", ""),
                "date": data.get("preferred_date") or data.get("new_preferred_date") or cur.get("date", ""),
                "time": data.get("preferred_time") or data.get("new_preferred_time") or cur.get("time", ""),
            }
        elif name == "escalate" and data.get("status") == "transfer_completed":
            facts["escalated"] = data.get("department") or "có"
        else:
            return
        state.scratchpad[KEY] = facts
    except Exception:  # noqa: BLE001 — bộ nhớ phụ không được làm hỏng lượt
        logger.warning("session_facts.record thất bại (%s)", name, exc_info=True)


def _project_label(code: str) -> str:
    """'Noble Crystal (NCR)' khi roster đã dựng, else mã trần — persona cấm đọc mã cho khách."""
    try:
        from noble_agent.agent.tools import find_project

        idx = find_project.get_index()
        c = idx.lookup(code) if idx is not None else None
        return f"{c.name} ({code})" if c is not None and getattr(c, "name", "") else code
    except Exception:  # noqa: BLE001
        return code


def _profile_line(customer) -> str:
    name = customer.full_name or customer.name
    parts: list[str] = []
    if name:
        honorific = {"M": "anh", "F": "chị"}.get(customer.gender or "", "anh/chị")
        parts.append(f"{honorific} {name}")
    if customer.project_interest:
        parts.append(f"dự án quan tâm {_project_label(customer.project_interest)}")
    if customer.budget:
        parts.append(f"ngân sách {customer.budget}")
    if customer.preferred_area:
        parts.append(f"khu vực muốn mua {customer.preferred_area}")
    if customer.bedroom_count:
        parts.append(f"{customer.bedroom_count}")
    if customer.purpose:
        parts.append(f"mục đích {customer.purpose}")
    if customer.is_buyer is False:
        parts.append("chỉ tham khảo")
    if customer.notes:
        parts.append(f"ghi chú: {customer.notes}")
    return ", ".join(parts)


def render(state, customer) -> str:
    """Khối ngữ cảnh ephemeral; '' khi không có gì đáng nói (đầu phiên, khách ẩn danh)."""
    lines: list[str] = []
    profile = _profile_line(customer)
    if profile:
        lines.append(f"Hồ sơ: {profile}.")
    facts = _load(state)
    if facts.get("units"):
        lines.append("Đã giới thiệu căn: " + "; ".join(format_unit(u) for u in facts["units"]) + ".")
    if facts.get("docs"):
        lines.append("Đã gửi tài liệu: " + "; ".join(facts["docs"]) + ".")
    if facts.get("media"):
        lines.append("Đã gửi qua app: " + "; ".join(facts["media"]) + ".")
    b = facts.get("booking")
    if b:
        lines.append(f"Lịch hẹn đã chốt: {b.get('id')} {b.get('date')} {b.get('time')} ({b.get('project')}).")
    if facts.get("escalated"):
        lines.append(f"Đã chuyển chuyên viên: có ({facts['escalated']}).")
    if not lines:
        return ""
    return HEADER + "\n" + "\n".join(lines)
