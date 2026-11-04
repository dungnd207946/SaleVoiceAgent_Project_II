"""Chèo kéo (upsell) — dữ liệu + chỉ đạo một-lượt gắn vào tool result.

Cùng triết lý với ``_auto_escalate`` / ``finish_turn``: code quyết CÓ chèo kéo
và chèo kéo CÁI GÌ, model chỉ diễn đạt — thu hẹp bề mặt tuân thủ từ
"quyết định + hành động" xuống "hành động". Ba mảnh:

- ``headroom``: biên nới ngân sách theo tỷ lệ (sàn 500tr). Hằng số 500tr tuyệt
  đối cũ là 62% trên căn 800tr nhưng chỉ 2.5% trên căn 20 tỷ — margin chèo kéo
  của sale thật là tỷ lệ.
- ``highlights``: điểm bán hàng cắt từ ``amenities`` của dự án. Directive chỉ
  được đòi thứ payload đã cung cấp — bảo model "giới thiệu tính ưu việt" mà
  không đưa dữ liệu là ép nó bịa.
- Guard scratchpad ``upsell_pitched``: mỗi dự án chỉ pitch vượt-ngân-sách MỘT
  lần mỗi phiên — chèo một lần là tư vấn, mỗi lượt là phản cảm. Dữ liệu
  (``over_budget``/``price_delta_pct``/``highlights``) vẫn gắn; chỉ lời pitch
  không lặp.

Mọi directive ở đây là mệnh lệnh HÀNH ĐỘNG NGAY (không kết thúc bằng câu hỏi
xin phép) và bị gỡ khỏi history lúc persist (``orchestrator._strip_tool_directives``)
— chúng chỉ sống một lượt.
"""

from __future__ import annotations

import re

HEADROOM_MIN_VND = 500_000_000
HEADROOM_PCT = 0.12

# Căn "đúng tầm" = giá ≥ 75% ngân sách. Khách hỏi 10 tỷ mà giới thiệu căn 4-5
# tỷ là lạc đề — kho within toàn căn xa tầm thì chỉ giữ 1-2 căn sát giá nhất,
# slot còn lại nhường cho nhóm vượt-trong-biên (chèo kéo).
NEAR_BUDGET_RATIO = 0.75

KEY = "upsell_pitched"
MAX_PITCHED = 10

_SPLIT_RE = re.compile(r"[;,\n]")
_HIGHLIGHT_MAX_LEN = 60


def headroom(budget_vnd: int) -> int:
    """Biên nới trên ngân sách khách đưa: max(sàn 500tr, 12%)."""
    if budget_vnd <= 0:
        return 0
    return max(HEADROOM_MIN_VND, int(budget_vnd * HEADROOM_PCT))


def delta_pct(price_vnd: int, budget_vnd: int) -> int:
    """% vượt ngân sách, làm tròn, sàn 1% khi có vượt (báo '~0%' là vô nghĩa)."""
    if budget_vnd <= 0 or price_vnd <= budget_vnd:
        return 0
    return max(1, round((price_vnd - budget_vnd) / budget_vnd * 100))


def highlights(amenities: str | None, limit: int = 3) -> list[str]:
    """Cắt ``amenities`` (text tự do, phân tách ;/,/xuống dòng) thành tối đa
    ``limit`` điểm bán hàng ngắn cho model trích khi pitch."""
    if not amenities:
        return []
    out: list[str] = []
    for frag in _SPLIT_RE.split(amenities):
        frag = frag.strip()
        if frag:
            out.append(frag[:_HIGHLIGHT_MAX_LEN])
        if len(out) >= limit:
            break
    return out


# ---- guard: mỗi dự án pitch một lần / phiên ----------------------------------


def already_pitched(state, project_code: str) -> bool:
    if state is None or not project_code:
        return False
    pitched = getattr(state, "scratchpad", {}).get(KEY)
    return isinstance(pitched, list) and project_code in pitched


def remember_pitched(state, project_code: str) -> None:
    if state is None or not project_code:
        return
    pitched = state.scratchpad.get(KEY)
    if not isinstance(pitched, list):
        pitched = []
    merged = [project_code] + [c for c in pitched if c != project_code]
    state.scratchpad[KEY] = merged[:MAX_PITCHED]


# ---- directives ---------------------------------------------------------------
# Viết theo khuôn answer-first / present-forward: trả lời xong GIỚI THIỆU LUÔN,
# chốt bằng một bước tiến — tuyệt đối không dạy model hỏi "có muốn... không ạ?".


def fmt_ty(vnd: int) -> str:
    """12_450_000_000 → '12,45 tỷ' (kiểu đọc Việt, bỏ số 0 thừa)."""
    s = f"{vnd / 1e9:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") + " tỷ"


def group_pitch(delta: int, price_vnd: int, unit_code: str) -> str:
    """Directive mức NHÓM cho `upsell_units` của search_units — chèo kéo kiểu
    nâng-ngân-sách với số liệu thật (delta %, giá đích, mã căn dẫn đầu)."""
    return (
        f"NGAY SAU khi giới thiệu nhóm `units`, CHÈO KÉO nhóm `upsell_units`: gợi ý khách nâng "
        f"ngân sách thêm ~{delta}% (khoảng {fmt_ty(price_vnd)}) để lấy căn {unit_code} — nêu lợi ích "
        "CỤ THỂ từ số liệu (highlights nếu có; rộng hơn / nhiều phòng ngủ hơn so với các căn trong "
        "`units` CHỈ KHI số liệu đúng vậy, KHÔNG bịa), rồi chốt bằng một bước tiến (mời xem kỹ căn "
        "hoặc đặt lịch tham quan). KHÔNG hỏi xin phép, KHÔNG chờ khách tự gợi ý."
    )


def project_pitch(delta: int) -> str:
    return (
        f"Dự án này có giá khởi điểm vượt ngân sách khách ~{delta}% nhưng trong biên đáng cân nhắc. "
        "GIỚI THIỆU LUÔN 1-2 điểm đáng tiền (từ highlights nếu có) để lý giải mức chênh, KHÔNG bịa "
        "thêm. Trình bày xong chốt bằng một bước tiến (mời nghe kỹ dự án hoặc xem căn phù hợp), "
        "KHÔNG hỏi xin phép trước khi giới thiệu."
    )
