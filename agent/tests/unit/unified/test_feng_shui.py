"""Pure feng-shui module: Bát trạch / nạp âm / địa chi + direction matching."""
from __future__ import annotations

from noble_agent.agent import feng_shui as fs

# ── Bát trạch (year + gender) ──────────────────────────────────────────────────

def test_bat_trach_1990_male_is_kham_east():
    r = fs.compute(birth_year=1990, gender="M")
    assert r.applied and r.method == "bat_trach"
    assert r.cung_phi == "Khảm"
    assert r.group == "Đông Tứ Mệnh"
    assert r.good_directions == frozenset({"Bắc", "Nam", "Đông", "Đông Nam"})


def test_bat_trach_1990_female_is_can_west():
    r = fs.compute(birth_year=1990, gender="F")
    assert r.cung_phi == "Cấn"
    assert r.group == "Tây Tứ Mệnh"
    assert r.good_directions == frozenset({"Tây", "Tây Bắc", "Tây Nam", "Đông Bắc"})


def test_bat_trach_post_2000_uses_2000_formula():
    # 2001 male: digit_root(01)=1 -> 9-1=8 -> Cấn (Tây Tứ Mệnh)
    r = fs.compute(birth_year=2001, gender="M")
    assert r.cung_phi == "Cấn" and r.group == "Tây Tứ Mệnh"


def test_bat_trach_post_2000_female_uses_2000_formula():
    # 2005 female: digit_root(5)=5 -> d+6=11 -> digit_root=2 -> Kua 2 Khôn (Tây Tứ Mệnh).
    # Regression guard: a ternary rewrite of _kua misparsed this as the male formula.
    r = fs.compute(birth_year=2005, gender="F")
    assert r.cung_phi == "Khôn" and r.group == "Tây Tứ Mệnh"


# ── nạp âm (year only, no gender) ──────────────────────────────────────────────

def test_nap_am_anchors():
    assert fs.compute(birth_year=1984).menh == "Kim"   # Giáp Tý
    assert fs.compute(birth_year=1988).menh == "Mộc"   # Mậu Thìn
    assert fs.compute(birth_year=1990).menh == "Thổ"   # Canh Ngọ


def test_year_without_gender_is_ngu_hanh_not_bat_trach():
    r = fs.compute(birth_year=1990)
    assert r.method == "ngu_hanh" and r.cung_phi is None
    assert r.good_directions == frozenset({"Tây Nam", "Đông Bắc", "Nam"})  # Thổ


# ── menh stated directly ───────────────────────────────────────────────────────

def test_menh_moc_direct():
    r = fs.compute(menh="moc")
    assert r.method == "ngu_hanh" and r.menh == "Mộc"
    assert r.good_directions == frozenset({"Đông", "Bắc"})


# ── zodiac fallback (địa chi) ──────────────────────────────────────────────────

def test_zodiac_ti_is_hoa_estimate_with_note():
    r = fs.compute(zodiac="ti")
    assert r.method == "dia_chi" and r.menh == "Hỏa"
    assert r.good_directions == frozenset({"Nam", "Đông", "Đông Nam"})
    assert r.note and "ước lượng" in r.note


# ── priority: birth_year beats menh/zodiac ─────────────────────────────────────

def test_birth_year_takes_priority():
    r = fs.compute(birth_year=1990, gender="M", menh="hoa", zodiac="ti")
    assert r.method == "bat_trach"


def test_no_signal_not_applied():
    r = fs.compute()
    assert r.applied is False and r.good_directions == frozenset()


# ── direction normalization / matching ─────────────────────────────────────────

def test_direction_matches_accent_case_abbrev():
    good = frozenset({"Đông Nam"})
    assert fs.direction_matches("Đông Nam", good)
    assert fs.direction_matches("đông nam", good)
    assert fs.direction_matches("Đông-Nam", good)
    assert fs.direction_matches("DN", good)


def test_direction_no_match_and_garbage():
    good = frozenset({"Đông Nam"})
    assert fs.direction_matches("Tây Bắc", good) is False
    assert fs.direction_matches("", good) is False
    assert fs.direction_matches("view hồ", good) is False


def test_normalize_direction_handles_d_stroke():
    assert fs.normalize_direction("Đông") == "Đông"
    assert fs.normalize_direction("bắc") == "Bắc"
    assert fs.normalize_direction("xyz") is None
