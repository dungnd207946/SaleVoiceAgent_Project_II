"""agent/tools/upsell.py — dữ liệu + chỉ đạo chèo kéo gắn vào tool result.

Ba mảnh: headroom theo tỷ lệ (thay hằng 500tr), highlights cắt từ amenities
(instruction chỉ được đòi thứ payload cung cấp), guard mỗi-dự-án-pitch-một-lần.
Kèm policy lint: mọi directive là mệnh lệnh trình bày, KHÔNG phải câu hỏi
xin phép — đúng yêu cầu "có thông tin thì giới thiệu luôn, không hỏi lại".
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from noble_agent.agent.tools import upsell

_REPO = Path(__file__).parents[3]


def _state():
    return SimpleNamespace(scratchpad={})


# ---- headroom: biên nới ngân sách theo tỷ lệ, sàn 500tr ----------------------


def test_headroom_small_budget_uses_floor():
    # 12% của 3 tỷ = 360tr < sàn 500tr → giữ sàn (khớp hành vi cũ ở dải này).
    assert upsell.headroom(3_000_000_000) == 500_000_000


def test_headroom_large_budget_scales_by_pct():
    # 500tr trên căn 20 tỷ chỉ là 2.5% — không còn là biên chèo kéo. 12% → 2.4 tỷ.
    assert upsell.headroom(10_000_000_000) == 1_200_000_000
    assert upsell.headroom(20_000_000_000) == 2_400_000_000


def test_headroom_zero_budget_is_zero():
    assert upsell.headroom(0) == 0


# ---- delta_pct ---------------------------------------------------------------


def test_delta_pct_rounds():
    assert upsell.delta_pct(3_200_000_000, 3_000_000_000) == 7


def test_delta_pct_floors_at_one_when_over():
    # Vượt 0.3% mà báo "~0%" là vô nghĩa với khách — sàn 1%.
    assert upsell.delta_pct(3_010_000_000, 3_000_000_000) == 1


def test_delta_pct_zero_budget_guard():
    assert upsell.delta_pct(3_000_000_000, 0) == 0


# ---- highlights: điểm bán hàng cắt từ amenities -------------------------------


def test_highlights_splits_and_caps_three():
    got = upsell.highlights("Bể bơi vô cực; Gym; Công viên 5ha; Trường liên cấp")
    assert got == ["Bể bơi vô cực", "Gym", "Công viên 5ha"]


def test_highlights_comma_and_newline_separators():
    assert upsell.highlights("Bể bơi, gym\nspa") == ["Bể bơi", "gym", "spa"]


def test_highlights_empty_and_none():
    assert upsell.highlights(None) == []
    assert upsell.highlights("") == []
    assert upsell.highlights("  ;  ; ") == []


def test_highlights_truncates_long_fragment():
    long = "x" * 200
    (h,) = upsell.highlights(long)
    assert len(h) <= 60


# ---- guard: mỗi dự án chỉ pitch vượt-ngân-sách MỘT lần / phiên ----------------


def test_guard_pitch_once_then_remembered():
    st = _state()
    assert upsell.already_pitched(st, "NCR") is False
    upsell.remember_pitched(st, "NCR")
    assert upsell.already_pitched(st, "NCR") is True


def test_guard_caps_and_dedupes():
    st = _state()
    for i in range(15):
        upsell.remember_pitched(st, f"P{i}")
        upsell.remember_pitched(st, f"P{i}")  # gọi lại không nhân đôi
    pitched = st.scratchpad[upsell.KEY]
    assert len(pitched) == upsell.MAX_PITCHED
    assert pitched[0] == "P14"  # mới nhất đứng đầu


def test_guard_tolerates_none_state():
    # Đường gọi cũ / test không truyền state → không pitch-guard, không nổ.
    assert upsell.already_pitched(None, "NCR") is False
    upsell.remember_pitched(None, "NCR")  # no-op


# ---- policy lint: directive là mệnh lệnh trình bày, không phải câu hỏi --------


def _all_directives() -> list[str]:
    from noble_agent.agent.tools import projects_info as pi

    return [
        upsell.project_pitch(7),
        upsell.group_pitch(4, 12_450_000_000, "UP-01"),
        pi._NO_PRICE_INSTRUCTION,
        pi._UNITS_NEXT_STEP_INSTRUCTION,
        pi._ALL_PROJECTS_INSTRUCTION,
    ]


def test_group_pitch_carries_concrete_numbers():
    s = upsell.group_pitch(4, 12_450_000_000, "UP-01")
    # Chèo kéo kiểu nâng-ngân-sách với số thật: % chênh + mức giá đích + mã căn.
    assert "nâng ngân sách" in s and "~4%" in s and "12,45 tỷ" in s and "UP-01" in s
    assert "KHÔNG hỏi" in s


def test_fmt_ty():
    assert upsell.fmt_ty(12_450_000_000) == "12,45 tỷ"
    assert upsell.fmt_ty(12_000_000_000) == "12 tỷ"
    assert upsell.fmt_ty(10_200_000_000) == "10,2 tỷ"


def test_directives_never_end_with_question():
    for s in _all_directives():
        assert not s.rstrip().endswith("?"), s
        assert "không ạ?" not in s, s


def test_pitch_directives_demand_immediate_presentation():
    assert "GIỚI THIỆU LUÔN" in upsell.project_pitch(7)
    assert "7%" in upsell.project_pitch(7)
    # unit_pitch (per-unit, kiểu search cũ) đã xoá theo merge 2026-09-07 —
    # pitch căn sống ở mức nhóm (group_pitch) cho CẢ hai scope.
    assert not hasattr(upsell, "unit_pitch")


def test_rules_no_longer_teach_ask_permission_close():
    """Regression: mẫu chốt câu 'muốn em giới thiệu kỹ căn này không ạ?' trong
    persona từng dạy đúng hành vi hỏi-xin-phép cần diệt — phải biến mất."""
    chat = (_REPO / "src/noble_agent/persona/chat/RULES.md").read_text(encoding="utf-8")
    voice = (_REPO / "src/noble_agent/persona/voice/RULES.md").read_text(encoding="utf-8")
    assert "muốn {{ identity.honorific_self }} giới thiệu kỹ" not in chat
    assert "muốn {{ identity.honorific_self }} nói kỹ" not in voice
