"""Deterministic feng-shui direction advice (Bát trạch + ngũ hành).

Pure, no I/O. ``compute(...)`` picks the strongest method the supplied customer
data allows (degradation ladder):

  birth_year + gender  -> Bát trạch (cung phi -> Đông/Tây Tứ Mệnh -> 4 hướng)
  birth_year           -> nạp âm ngũ hành -> hướng hợp
  menh (stated)        -> ngũ hành -> hướng hợp
  zodiac (con giáp)    -> địa chi ngũ hành (estimate) -> hướng hợp
  nothing              -> not applied

Output is always DIRECTIONS only (no colour/floor/tử vi). Birth hour is ignored.
See docs/superpowers/specs/2026-07-14-recommend-units-feng-shui-design.md.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class FengShuiResult:
    applied: bool
    method: str | None
    menh: str | None
    cung_phi: str | None
    group: str | None
    good_directions: frozenset[str]
    note: str | None


# 8 canonical directions
BAC, NAM, DONG, TAY = "Bắc", "Nam", "Đông", "Tây"
DB, DN, TB, TN = "Đông Bắc", "Đông Nam", "Tây Bắc", "Tây Nam"

EAST = frozenset({BAC, NAM, DONG, DN})  # Đông Tứ Mệnh
WEST = frozenset({TAY, TB, TN, DB})  # Tây Tứ Mệnh

# Kua (cung phi) -> (cung name, group dirs)
_KUA: dict[int, tuple[str, frozenset[str]]] = {
    1: ("Khảm", EAST),
    9: ("Ly", EAST),
    3: ("Chấn", EAST),
    4: ("Tốn", EAST),
    6: ("Càn", WEST),
    2: ("Khôn", WEST),
    8: ("Cấn", WEST),
    7: ("Đoài", WEST),
}

# Ngũ hành bản mệnh -> hướng hợp (bản mệnh + hành tương sinh nuôi bản mệnh)
_MENH_DIRS: dict[str, frozenset[str]] = {
    "Kim": WEST,
    "Mộc": frozenset({DONG, BAC}),
    "Thủy": frozenset({BAC, TAY, TB}),
    "Hỏa": frozenset({NAM, DONG, DN}),
    "Thổ": frozenset({TN, DB, NAM}),
}

# Con giáp key -> địa chi ngũ hành (fallback estimate)
_CHI_MENH: dict[str, str] = {
    "ty": "Thủy",
    "suu": "Thổ",
    "dan": "Mộc",
    "mao": "Mộc",
    "thin": "Thổ",
    "ti": "Hỏa",
    "ngo": "Hỏa",
    "mui": "Thổ",
    "than": "Kim",
    "dau": "Kim",
    "tuat": "Thổ",
    "hoi": "Thủy",
}

# Nạp âm ngũ hành over the 60-year cycle, one element per 2-year pair
# (pair 0 = Giáp Tý, years where (year-4) % 60 in {0, 1}).
_NAP_AM_PAIRS: tuple[str, ...] = (
    "Kim",
    "Hỏa",
    "Mộc",
    "Thổ",
    "Kim",
    "Hỏa",
    "Thủy",
    "Thổ",
    "Kim",
    "Mộc",
    "Thủy",
    "Thổ",
    "Hỏa",
    "Mộc",
    "Thủy",
    "Kim",
    "Hỏa",
    "Mộc",
    "Thổ",
    "Kim",
    "Hỏa",
    "Thủy",
    "Thổ",
    "Kim",
    "Mộc",
    "Thủy",
    "Thổ",
    "Hỏa",
    "Mộc",
    "Thủy",
)

# menh param value -> canonical element
_MENH_CANON: dict[str, str] = {
    "kim": "Kim",
    "moc": "Mộc",
    "thuy": "Thủy",
    "hoa": "Hỏa",
    "tho": "Thổ",
}


def _digit_root(n: int) -> int:
    n = abs(int(n))
    while n > 9:
        n = sum(int(c) for c in str(n))
    return n


def _nap_am(birth_year: int) -> str:
    return _NAP_AM_PAIRS[((birth_year - 4) % 60) // 2]


def _kua(birth_year: int, gender: str) -> int:
    d = _digit_root(birth_year % 100)
    if gender == "M":  # noqa: SIM108 - two independent formulas, ternary misparses
        k = (9 - d) if birth_year >= 2000 else (10 - d)
    else:
        k = (d + 6) if birth_year >= 2000 else (d + 5)
    k = _digit_root(k)
    if k == 5:
        return 2 if gender == "M" else 8
    return k or 9


def compute(*, birth_year=None, gender=None, menh=None, zodiac=None) -> FengShuiResult:
    g = gender if gender in ("M", "F") else None
    if birth_year:
        element = _nap_am(int(birth_year))
        if g:
            cung, dirs = _KUA[_kua(int(birth_year), g)]
            grp = "Đông Tứ Mệnh" if dirs is EAST else "Tây Tứ Mệnh"
            return FengShuiResult(True, "bat_trach", element, cung, grp, dirs, None)
        return FengShuiResult(True, "ngu_hanh", element, None, None, _MENH_DIRS[element], None)
    if menh:
        e = _MENH_CANON.get(str(menh).strip().lower())
        if e:
            return FengShuiResult(True, "ngu_hanh", e, None, None, _MENH_DIRS[e], None)
    if zodiac:
        e = _CHI_MENH.get(str(zodiac).strip().lower())
        if e:
            return FengShuiResult(
                True,
                "dia_chi",
                e,
                None,
                None,
                _MENH_DIRS[e],
                "ước lượng từ con giáp, nên xác nhận năm sinh",
            )
    return FengShuiResult(False, None, None, None, None, frozenset(), None)


# ── direction normalization ───────────────────────────────────────────────────


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


# accent-free, lower-case, đ->d token -> canonical direction
_DIR_ALIASES: dict[str, str] = {
    "bac": BAC,
    "nam": NAM,
    "dong": DONG,
    "tay": TAY,
    "dong bac": DB,
    "dong nam": DN,
    "tay bac": TB,
    "tay nam": TN,
    "db": DB,
    "dn": DN,
    "tb": TB,
    "tn": TN,
}


def normalize_direction(raw: str) -> str | None:
    t = _strip_accents((raw or "").strip().lower()).replace("đ", "d")
    t = t.replace("-", " ").replace("_", " ").replace("/", " ")
    t = " ".join(t.split())
    return _DIR_ALIASES.get(t)


def direction_matches(unit_huong: str, good: frozenset[str]) -> bool:
    d = normalize_direction(unit_huong)
    return d is not None and d in good
