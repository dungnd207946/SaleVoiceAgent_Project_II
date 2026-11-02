"""Text normalization for TTS backends.

Two independent layers:
1. normalize_for_voice() — Vietnamese voice normalization run in the hotline agent
   BEFORE sending text to the TTS service (numbers, units, prices, phones, codes,
   dates/times, abbreviations, ALL-CAPS spelling, URL/markdown strip). Reading/abbrev
   maps come from data/tts_normalize_vi.json ({reading, abbrev}); env TTS_NORMALIZE_PATH
   overrides the path.
2. load_normalize_map() + apply_normalize() — flat {word: replacement} maps used by
   the ElevenLabs / VieNeu backends for their own normalization.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def load_normalize_map(json_path: Path) -> dict[str, str]:
    """Load a flat {word: replacement} JSON. "_"-keys skipped; VieNeu phoneme
    dicts {"preferred": "normalized", "normalized": str} also handled."""
    if not json_path.exists():
        logger.warning("[TTS normalize] File not found: %s", json_path)
        return {}

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    result: dict[str, str] = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, str) and value:
            result[key] = value
        elif isinstance(value, dict):
            if value.get("preferred") == "normalized" and value.get("normalized"):
                result[key] = value["normalized"]

    logger.info("[TTS normalize] Loaded %d entries from %s", len(result), json_path.name)
    return result


def apply_normalize(text: str, nmap: dict[str, str], word_boundary: bool = False) -> str:
    """Apply a map, longest keys first. word_boundary wraps in \\b (ElevenLabs);
    False for VieNeu (Vietnamese words often lack ASCII boundaries)."""
    if not nmap:
        return text
    for word in sorted(nmap.keys(), key=len, reverse=True):
        if word_boundary:
            pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
        else:
            pattern = re.compile(re.escape(word), re.IGNORECASE)
        text = pattern.sub(nmap[word], text)
    return text


# ═════════════════════════════════════════════════════════════════════════════
# Vietnamese voice normalization — numbers, units, prices, phones, codes, abbrevs
# ═════════════════════════════════════════════════════════════════════════════

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
NORMALIZE_PATH = os.environ.get("TTS_NORMALIZE_PATH", "") or str(
    _PROJECT_ROOT / "data" / "tts_normalize_vi.json"
)

# ── Number → Vietnamese words ────────────────────────────────────────────────

_DIGITS = {
    "0": "không", "1": "một", "2": "hai", "3": "ba", "4": "bốn",
    "5": "năm", "6": "sáu", "7": "bảy", "8": "tám", "9": "chín",
}
_TEENS = {
    10: "mười", 11: "mười một", 12: "mười hai", 13: "mười ba", 14: "mười bốn",
    15: "mười lăm", 16: "mười sáu", 17: "mười bảy", 18: "mười tám", 19: "mười chín",
}
_TENS = {
    2: "hai mươi", 3: "ba mươi", 4: "bốn mươi", 5: "năm mươi",
    6: "sáu mươi", 7: "bảy mươi", 8: "tám mươi", 9: "chín mươi",
}

# Numeric captures are length-bounded ({1,15}, same cap as _PLAIN_NUMBER_RE): an
# unbounded "\d+" before a required suffix backtracks O(n²) on a long digit run
# (LLM repetition loop → blocked event loop) and would overflow int() in py3.11+.
_NUM = r"\d{1,15}"


def _int_to_vi(n: int) -> str:
    """Non-negative int → Vietnamese words, grouped by tỷ (scales past 999 tỷ)."""
    if n < 0:
        return "âm " + _int_to_vi(-n)
    if n <= 9:
        return _DIGITS[str(n)]
    if n <= 19:
        return _TEENS[n]
    if n <= 99:
        tens, ones = divmod(n, 10)
        result = _TENS[tens]
        if ones == 0:
            return result
        if ones == 1:
            return result + " mốt"
        if ones == 5:
            return result + " lăm"
        return result + " " + _DIGITS[str(ones)]
    if n <= 999:
        hundreds, remainder = divmod(n, 100)
        result = _DIGITS[str(hundreds)] + " trăm"
        if remainder == 0:
            return result
        if remainder < 10:
            return result + " lẻ " + _DIGITS[str(remainder)]
        return result + " " + _int_to_vi(remainder)
    if n <= 999_999:
        thousands, remainder = divmod(n, 1000)
        result = _int_to_vi(thousands) + " nghìn"
        if remainder == 0:
            return result
        if remainder < 100:
            return result + " không trăm " + _int_to_vi(remainder)
        return result + " " + _int_to_vi(remainder)
    if n <= 999_999_999:
        millions, remainder = divmod(n, 1_000_000)
        result = _int_to_vi(millions) + " triệu"
        if remainder == 0:
            return result
        if remainder < 1000:
            return result + " không nghìn " + _int_to_vi(remainder)
        return result + " " + _int_to_vi(remainder)
    billions, remainder = divmod(n, 1_000_000_000)  # billions may exceed 999 → recurses
    result = _int_to_vi(billions) + " tỷ"
    if remainder == 0:
        return result
    if remainder < 1_000_000:
        return result + " không triệu " + _int_to_vi(remainder)
    return result + " " + _int_to_vi(remainder)


# ── Money / measure amounts ──────────────────────────────────────────────────
# Money reads the true value: "2,5 tỷ" → "hai tỷ rưỡi" (½ unit → "rưỡi"), "12,7
# triệu" → "mười hai triệu bảy trăm nghìn". Measure units read the decimal as "phẩy".

_MONEY_MULT = {
    "tỷ": 1_000_000_000, "tỉ": 1_000_000_000,
    "trăm triệu": 100_000_000,
    "triệu": 1_000_000, "tr": 1_000_000,
    "nghìn": 1_000, "ngàn": 1_000,
}
_MONEY_SPOKEN = {"tr": "triệu", "tỉ": "tỷ"}  # alias → spoken form


def _format_amount(num_str: str, unit: str, trail: str | None = None) -> str:
    """Read "<number> <unit>". `trail` = compact trailing digit in "5tr5"."""
    u = unit.lower()
    mult = _MONEY_MULT.get(u)

    if trail is not None:
        int_str, dec = num_str, trail
    elif "." in num_str or "," in num_str:
        int_str, dec = re.split(r"[.,]", num_str, maxsplit=1)
    else:
        int_str, dec = num_str, ""

    if mult is None:  # measure unit
        spoken = _UNIT_MAP.get(u, u)
        if dec:
            return f"{_int_to_vi(int(int_str))} phẩy {_int_to_vi(int(dec))} {spoken}"
        return f"{_int_to_vi(int(int_str))} {spoken}"

    x = int(int_str)
    frac = int(dec) * (mult // (10 ** len(dec))) if dec and 10 ** len(dec) <= mult else 0
    spoken = _MONEY_SPOKEN.get(u, u)
    if frac and frac * 2 == mult and x > 0:  # exactly half → "rưỡi"
        return f"{_int_to_vi(x)} {spoken} rưỡi"
    return _int_to_vi(x * mult + frac)


def _expand_price(m: re.Match) -> str:
    """"3.5 tỷ" → "ba tỷ rưỡi", "5tr5" → "năm triệu rưỡi"."""
    return _format_amount(m.group(1), m.group(2), trail=m.group(3))


def _expand_range(m: re.Match) -> str:
    """"1,2-2,5 tỷ" → "một tỷ hai trăm triệu đến hai tỷ rưỡi"."""
    unit = m.group(3)
    return f"{_format_amount(m.group(1), unit)} đến {_format_amount(m.group(2), unit)}"


def _degroup_thousands(m: re.Match) -> str:
    """Strip dot thousands-separators: "1.200.000" → "1200000" (comma decimal kept)."""
    return m.group(0).replace(".", "")


def _expand_decimal(m: re.Match) -> str:
    """Bare decimal: "3.4" → "ba phẩy bốn"; zero fraction dropped: "2.0" → "hai"."""
    int_part, dec = re.split(r"[.,]", m.group(0), maxsplit=1)
    dec = dec.rstrip("0")
    if not dec:
        return _int_to_vi(int(int_part))
    return f"{_int_to_vi(int(int_part))} phẩy {_int_to_vi(int(dec))}"


def _expand_plain_number(m: re.Match) -> str:
    """"2048" → "hai nghìn không trăm bốn mươi tám"."""
    try:
        return _int_to_vi(int(m.group(0)))
    except ValueError:
        return m.group(0)


def _expand_currency(m: re.Match) -> str:
    """"đ"/"₫" after digits → " đồng"."""
    return f"{m.group(1)} đồng"


# ── Phones: read digit-by-digit ──────────────────────────────────────────────
# Anchored on VN markers (leading 0, +84, 1800/1900, "(0xx)") so it never grabs a
# price. "+84…" reads as "0…".
_PHONE_RE = re.compile(
    r"""(?<![\w+])(?:
        \+?84[\s.\-]?\d(?:[\s.\-]?\d){8}          # +84 / 84 + 9 digits
      | 0\d(?:[\s.\-]?\d){8,9}                    # 0 + 9..10 digits
      | 1[89]00[\s.\-]?\d{3}(?:[\s.\-]?\d{1,3})?  # 1800 / 1900 hotline
      | \(0\d{1,2}\)[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}  # (0xx) landline
    )(?!\d)""",
    re.VERBOSE,
)


def _read_phone(m: re.Match) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    if digits.startswith("84") and len(digits) == 11:  # +84… → 0…
        digits = "0" + digits[2:]
    return " ".join(_DIGITS[d] for d in digits)


# ── Long bare digit IDs (CCCD, accounts) → digit-by-digit ────────────────────
# ≥10 digits with no separators = an identifier, not a quantity. Runs after phone
# and before the degroup, so a dot-grouped price ("15.224.565.224") is untouched.
_ID_RE = re.compile(r"(?<![\d.,])\d{10,}(?!\d)(?![.,]\d)")


def _read_id(m: re.Match) -> str:
    return " ".join(_DIGITS[d] for d in m.group(0))


# ── Codes (apartment/contract/unit) → read literal ───────────────────────────
# A code = a run of uppercase letters/digits (optionally joined by . / -) with BOTH
# an uppercase letter AND a digit. The lookaheads require the mix, so pure-digit
# dates/ranges, lowercase phrases and letterless numbers are left alone. Runs before
# the maps/num-range so "HĐMB-2026-001"/"2A-15" read literally (not expanded/ranged);
# roman runs first so "quý IV/2026" isn't captured.
_CODE_RE = re.compile(
    r"\b(?=[A-ZĐ0-9./\-]*[A-ZĐ])(?=[A-ZĐ0-9./\-]*\d)[A-ZĐ0-9]+(?:[./\-][A-ZĐ0-9]+)*\b"
)


def _read_code(m: re.Match) -> str:
    out = []
    for ch in m.group(0):
        if ch.isdigit():
            out.append(_DIGITS[ch])
        elif ch in "./-":
            continue
        else:
            out.append(_LETTER_PRONUNCIATION.get(ch.upper(), ch.lower()))
    return " ".join(out)


# ── Roman numerals after a keyword: "quý I/2026" → "quý một năm 2026" ─────────
# Only after a keyword (so "Tòa C" is left alone). Charset I/V/X only — C/D/L/M are
# far more likely block/section labels ("Mục C") than 100/500/…. Optional "/YYYY".
_ROMAN = {"I": 1, "V": 5, "X": 10}
_ROMAN_RE = re.compile(
    r"\b((?i:quý|thế kỷ|đợt|kỳ|khóa|chương|phần|mục|tập|quận|thứ|giai đoạn))"
    r"\s+([IVX]+)\b(?:\s*/\s*(\d{4}))?"
)


def _roman_to_int(s: str) -> int:
    total = prev = 0
    for ch in reversed(s):
        v = _ROMAN[ch]
        if v < prev:
            total -= v
        else:
            total += v
            prev = v
    return total


def _expand_roman(m: re.Match) -> str:
    kw, roman, year = m.group(1), m.group(2), m.group(3)
    num = _int_to_vi(_roman_to_int(roman))
    return f"{kw} {num} năm {year}" if year else f"{kw} {num}"


# ── Dates + month/year + year span ───────────────────────────────────────────
# Full date takes / - . (4-digit year disambiguates from 3-grouped prices). Yearless
# dd/mm is a date after ngày/mùng OR when day is 13-31 (so "3/4"/"1/2" stay
# fractions); "24/7"/"24/24" idiom excluded.
_DATE_SEP = r"[/.\-]"
_DATE_RE = re.compile(
    r"\b(?:(?:ngày|mùng|mồng)\s+)?(\d{1,2})" + _DATE_SEP + r"(\d{1,2})" + _DATE_SEP + r"(\d{4})\b",
    re.IGNORECASE,
)
_DATE_DM_RE = re.compile(r"\b(ngày|mùng|mồng)\s+(\d{1,2})/(\d{1,2})(?!\s*/)\b", re.IGNORECASE)
_DATE_DM_BARE_RE = re.compile(r"(?<!\d)(?!24/(?:7|24)\b)(\d{1,2})/(\d{1,2})(?!\s*[/\d])")
_MONTH_YEAR_RE = re.compile(r"\b(?:(tháng|thg|quý|kỳ|đợt)\s+)?(\d{1,2})\s*/\s*(\d{4})\b", re.IGNORECASE)
_YEAR_SLASH_RE = re.compile(r"\b(\d{4})\s*/\s*(\d{4})\b")


def _expand_date(m: re.Match) -> str:
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= d <= 31 and 1 <= mo <= 12):
        return m.group(0)
    return f"ngày {_int_to_vi(d)} tháng {_int_to_vi(mo)} năm {_int_to_vi(y)}"


def _expand_date_dm(m: re.Match) -> str:
    kw, d, mo = m.group(1), int(m.group(2)), int(m.group(3))
    if not (1 <= d <= 31 and 1 <= mo <= 12):
        return m.group(0)
    return f"{kw} {_int_to_vi(d)} tháng {_int_to_vi(mo)}"


def _expand_date_dm_bare(m: re.Match) -> str:
    d, mo = int(m.group(1)), int(m.group(2))
    if not (13 <= d <= 31 and 1 <= mo <= 12):  # day≥13 → a date, not a fraction
        return m.group(0)
    return f"ngày {_int_to_vi(d)} tháng {_int_to_vi(mo)}"


def _expand_month_year(m: re.Match) -> str:
    kw, num, year = m.group(1), int(m.group(2)), m.group(3)
    if not (1 <= num <= 12):
        return m.group(0)
    return f"{kw if kw else 'tháng'} {_int_to_vi(num)} năm {year}"


# ── Times + ratios ───────────────────────────────────────────────────────────
# "8:00"/"9h30"/"08:30:15" → words; ranges "8:00-11:30"/"8h-11h"/"8-9h" → "… đến …".
# Range-checked (h≤23, m/s≤59). Any leftover "N:M" that isn't a valid time → ratio.
_TIME_RANGE_RE = re.compile(r"(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})")
_TIME_H_RANGE_RE = re.compile(r"\b(\d{1,2})(?:h(\d{2})?)?\s*[-–—]\s*(\d{1,2})h(\d{2})?\b", re.IGNORECASE)
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b")
_TIME_H_RE = re.compile(r"\b(\d{1,2})h(\d{2})?\b", re.IGNORECASE)
_RATIO_RE = re.compile(r"\b(" + _NUM + r")\s*:\s*(" + _NUM + r")\b")


def _valid_time(h: int, mnt: int, sec: int = 0) -> bool:
    return h <= 23 and mnt <= 59 and sec <= 59


def _spoken_time(h: int, mnt: int, sec: int = 0) -> str:
    out = f"{_int_to_vi(h)} giờ"
    if mnt:
        out += f" {_int_to_vi(mnt)} phút"
    if sec:
        out += f" {_int_to_vi(sec)} giây"
    return out


def _expand_time(m: re.Match) -> str:
    h, mnt = int(m.group(1)), int(m.group(2))
    sec = int(m.group(3)) if m.group(3) else 0
    return _spoken_time(h, mnt, sec) if _valid_time(h, mnt, sec) else m.group(0)


def _expand_time_h(m: re.Match) -> str:
    h, mnt = int(m.group(1)), int(m.group(2)) if m.group(2) else 0
    return _spoken_time(h, mnt) if _valid_time(h, mnt) else m.group(0)


def _expand_h_range(m: re.Match) -> str:
    h1, mnt1 = int(m.group(1)), int(m.group(2)) if m.group(2) else 0
    h2, mnt2 = int(m.group(3)), int(m.group(4)) if m.group(4) else 0
    if not (_valid_time(h1, mnt1) and _valid_time(h2, mnt2)):
        return m.group(0)
    return f"{_spoken_time(h1, mnt1)} đến {_spoken_time(h2, mnt2)}"


def _expand_ratio(m: re.Match) -> str:
    return f"{_int_to_vi(int(m.group(1)))} trên {_int_to_vi(int(m.group(2)))}"


# ── Numeric range "2-3" → "hai đến ba" ───────────────────────────────────────
# Runs after money/measure ranges and after phone/code/date/time. Endpoints read
# here (works for single digits). Trailing guard allows a sentence dot ("5-10.").
_NUM_RANGE_RE = re.compile(r"(?<![\d.,])(" + _NUM + r")\s*[-–—]\s*(" + _NUM + r")(?!\d)(?![.,]\d)")


def _expand_num_range(m: re.Match) -> str:
    return f"{_int_to_vi(int(m.group(1)))} đến {_int_to_vi(int(m.group(2)))}"


# ── Colloquial metre "3m5" → "ba mét rưỡi" (excludes m2/m3) ──────────────────
_METER_COLLOQ_RE = re.compile(r"\b(" + _NUM + r")m([14-9])\b")


def _expand_meter_colloq(m: re.Match) -> str:
    whole, dec = int(m.group(1)), m.group(2)
    tail = "rưỡi" if dec == "5" else _DIGITS[dec]
    return f"{_int_to_vi(whole)} mét {tail}"


# ── Colloquial spaced money "1 tỷ 2" → true amount ───────────────────────────
# Trailing digit = tenths. Guarded against a counter noun so "3 tỷ 5 căn" isn't
# read as 3,5 tỷ. Runs before the price pass.
_MONEY_COLLOQ_RE = re.compile(
    r"(" + _NUM + r")\s+(tỷ|tỉ|triệu)\s+(\d)\b"
    r"(?!\s*(?:căn|suất|lô|nền|phòng|tầng|t[òo]a|block|người|nhà|năm|tháng|ngày|m²|m2|m3|ha))",
    re.IGNORECASE,
)


def _expand_money_colloq(m: re.Match) -> str:
    return _format_amount(m.group(1), m.group(2), trail=m.group(3))


# ── "k" = nghìn ("500k", "2k5"=2500) — lowercase k only (not "4K") ───────────
_K_MONEY_RE = re.compile(r"\b(" + _NUM + r")k(\d)?\b")


def _expand_k_money(m: re.Match) -> str:
    val = int(m.group(1)) * 1000
    if m.group(2):
        val += int(m.group(2)) * 100
    return _int_to_vi(val)


# ── Units ────────────────────────────────────────────────────────────────────

_UNIT_MAP = {
    "m²": "mét vuông", "m2": "mét vuông",
    "km²": "ki lô mét vuông", "km2": "ki lô mét vuông",
    "km": "ki lô mét",
    "m³": "mét khối", "m3": "mét khối",
    "m": "mét",  # bare metre — kept AFTER m2/m³ (longest-first)
    "ha": "héc ta",
    "%": "phần trăm", "°C": "độ C", "°": "độ",
}

_LETTER_PRONUNCIATION = {
    "A": "a", "B": "bê", "C": "xê", "D": "đê", "E": "e", "F": "ép", "G": "gờ",
    "H": "hát", "I": "i", "J": "gi", "K": "ca", "L": "lờ", "M": "mờ", "N": "nờ",
    "O": "o", "P": "pê", "Q": "quy", "R": "rờ", "S": "ét", "T": "tê", "U": "u",
    "V": "vê", "W": "vê kép", "X": "ích", "Y": "i dài", "Z": "dét", "Đ": "đê",
}


_VOWELS = frozenset("AEIOUY")
_SPELL_MAX_LEN = 4


def _spell_out(word: str) -> str:
    """"HVAC" → "hát vê a xê"."""
    return " ".join(_LETTER_PRONUNCIATION.get(ch, ch) for ch in word.upper())


# ── Compiled patterns ────────────────────────────────────────────────────────

# Units longest-first; "tr" last so it can't shadow "triệu". Trailing lookahead
# stops a money word matching inside a normal word; final (\d)? captures "5tr5".
_MONEY_ALT = r"trăm triệu|triệu|tỷ|tỉ|nghìn|ngàn|tr"
_LETTER_LOOKAHEAD = r"(?![A-Za-zÀ-ỹ])"
_PRICE_RE = re.compile(
    r"(" + _NUM + r"(?:[.,]" + _NUM + r")?)\s*(" + _MONEY_ALT + r")" + _LETTER_LOOKAHEAD + r"(\d)?",
    re.IGNORECASE,
)
_MEASURE_ALT = "|".join(re.escape(u) for u in sorted(_UNIT_MAP, key=len, reverse=True))
_RANGE_RE = re.compile(
    r"(" + _NUM + r"(?:[.,]" + _NUM + r")?)\s*[-–]\s*(" + _NUM + r"(?:[.,]" + _NUM + r")?)\s*"
    r"(" + _MONEY_ALT + "|" + _MEASURE_ALT + r")" + _LETTER_LOOKAHEAD,
    re.IGNORECASE,
)
# Trailing guard: a bare "m" in "1200 mét"/"metro" must not read as metres.
_UNIT_RE = re.compile(r"(" + _NUM + r"(?:[.,]" + _NUM + r")?)\s*(" + _MEASURE_ALT + r")(?![A-Za-zÀ-ỹĐđ])")
# Per-unit slash ("VNĐ/m²", "50 triệu/m2") → "… một <unit>" (the "/" means "per").
# Trailing guard (not \b — "²" is a non-word char so \b would backtrack to bare "m").
_PER_UNIT_SPOKEN = {
    "m²": "mét vuông", "m2": "mét vuông",
    "km²": "ki lô mét vuông", "km2": "ki lô mét vuông",
    "km": "ki lô mét", "m³": "mét khối", "m3": "mét khối", "m": "mét",
    "tháng": "tháng", "năm": "năm", "ngày": "ngày", "tuần": "tuần", "quý": "quý",
    "giờ": "giờ", "phút": "phút", "giây": "giây", "đêm": "đêm",
    "căn": "căn", "người": "người", "suất": "suất", "lượt": "lượt",
    "kg": "ki lô gam", "tấn": "tấn", "ha": "héc ta",
}
_PER_UNIT_RE = re.compile(
    r"\s*/\s*(" + "|".join(re.escape(u) for u in sorted(_PER_UNIT_SPOKEN, key=len, reverse=True)) + r")"
    r"(?![A-Za-zÀ-ỹĐđ0-9])",
    re.IGNORECASE,
)
# VN convention: "." is thousands-grouping, "," is decimal.
_THOUSANDS_RE = re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})+(?![\d.])")
_DECIMAL_RE = re.compile(r"\d+[.,]\d+")
_PLAIN_NUMBER_RE = re.compile(r"\b(\d{2,15})\b")
_CURRENCY_RE = re.compile(r"(\d)\s*[đ₫](?!\w)")
# "$" adjacent to digits → "đô la" (else the special-char pass drops it).
_USD_PREFIX_RE = re.compile(r"\$\s*(\d(?:[\d.,]*\d)?)")
_USD_SUFFIX_RE = re.compile(r"(\d(?:[\d.,]*\d)?)\s*\$")

# "TP"/"TP." → "thành phố" (won't touch "TPBank" — \bTP\b fails).
_TP_RE = re.compile(r"\bTP\b\.?\s*", re.IGNORECASE)

_ALLCAPS_RE = re.compile(r"\b([A-ZĐ]{2,})\b")
_PAREN_ABBREV_RE = re.compile(r"\s*\(\s*[A-ZĐ]{2,}\s*\)")
_SPECIAL_CHARS_RE = re.compile(r"[★●•◆▪→←↔|~`@#$^&*\[\]{}<>\\]")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_MARKDOWN_RE = re.compile(r"```[\s\S]*?```|`[^`]+`")

# Misc: room shorthand, versus, email, quarter, dimensions, word-slash.
_ROOM_GLUE_RE = re.compile(r"(\d)(PN|PK|WC|VS)(?![A-Za-zÀ-ỹĐđ])")  # "2PN" → "2 PN " (abbrev then expands)
_VS_RE = re.compile(r"\bvs\b")  # lowercase "vs" = versus → "so với" (UPPERCASE VS = vệ sinh, abbrev)
_EMAIL_AT_RE = re.compile(r"(?<=\w)\s*@\s*(?=\w)")  # "a@b" → "a còng b" (before "@" is stripped)
_QUARTER_RE = re.compile(r"\bQ([1-4])\b(?:\s*/\s*(\d{4}))?", re.IGNORECASE)  # "Q1/2026" → "quý một năm 2026"
_DIM_RE = re.compile(r"(?<![\w.,])(" + _NUM + r")\s*[x×]\s*(" + _NUM + r")")  # "5x20" → "năm nhân hai mươi"
# Bare "/" between two words → space ("Đông/Nam" → "Đông Nam"); digit/digit is left as a fraction.
_WORD_SLASH_RE = re.compile(r"(?<=[A-Za-zÀ-ỹĐđ])\s*/\s*(?=[A-Za-zÀ-ỹĐđ])")


def _expand_quarter(m: re.Match) -> str:
    q = _int_to_vi(int(m.group(1)))
    return f"quý {q} năm {m.group(2)}" if m.group(2) else f"quý {q}"


def _expand_dim(m: re.Match) -> str:
    return f"{_int_to_vi(int(m.group(1)))} nhân {_int_to_vi(int(m.group(2)))}"


def _is_caps_word(token: str) -> bool:
    """Token liền kề có phải một từ viết HOA (đã bỏ dấu câu hai đầu)."""
    token = token.strip(".,;:!?()[]\"\u2019'\u201c\u201d")
    return len(token) >= 2 and token.isupper() and any(c.isalpha() for c in token)


def _in_caps_phrase(m: re.Match) -> bool:
    """Token HOA có láng giềng (cách đúng một khoảng trắng) cũng viết HOA.

    Đây là vế nhận diện TÊN RIÊNG: viết tắt đứng lẻ giữa câu chữ thường ("hệ thống
    HVAC hiện đại"), còn tên dự án đi thành cụm ("NOBLE CRYSTAL TÂY HỒ", "SUNSHINE
    SKY CITY") — nên chỉ ngưỡng độ dài là không đủ, "CITY"/"PARK"/"BAY" đều ngắn.
    """
    truoc = re.search(r"(\S+)[ \t]$", m.string[: m.start()])
    sau = re.match(r"[ \t](\S+)", m.string[m.end() :])
    return any(g and _is_caps_word(g.group(1)) for g in (truoc, sau))


def _spell_or_roman(m: re.Match) -> str:
    """ALL-CAPS token: a pure I/V/X run (≥2) → its Roman value ("III" → "ba",
    phân khu/tòa labels); từ viết tắt đánh vần từng chữ cái.

    Tên riêng thì giữ nguyên, chỉ hạ về dạng Hoa đầu — tên dự án trong DB tenant lưu
    HOA TOÀN BỘ ("NOBLE CRYSTAL TÂY HỒ"), đánh vần ra là đọc tên dự án theo từng chữ
    cái. Nhận ra tên riêng bằng hai vế: nằm trong cụm HOA, hoặc dài hơn
    _SPELL_MAX_LEN và có nguyên âm (ALLUVIA, VINHOMES đứng lẻ). Viết tắt tiếng
    Việt/Anh gần như luôn ≤ 4 chữ (NCLB, HVAC, USD) hoặc không có nguyên âm nào
    (NPTTL, GCNQSDĐ).
    """
    word = m.group(0)
    if re.fullmatch(r"[IVX]{2,}", word):
        return _int_to_vi(_roman_to_int(word))
    if _in_caps_phrase(m) or (len(word) > _SPELL_MAX_LEN and set(word) & _VOWELS):
        return word.capitalize()
    return _spell_out(word)


# ── Reading/abbrev map loading (nested {reading, abbrev}) ─────────────────────


def _load_reading_abbrev(json_path: str) -> tuple[dict[str, str], dict[str, str]]:
    """Load the nested map → (reading, abbrev). "_"-keys skipped; missing → empty."""
    path = Path(json_path)
    if not path.exists():
        logger.warning("[normalize] file not found: %s — normalization limited to numbers/units", path)
        return {}, {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    def _section(name: str) -> dict[str, str]:
        return {
            k: v
            for k, v in (data.get(name) or {}).items()
            if not k.startswith("_") and isinstance(v, str) and v
        }

    reading, abbrev = _section("reading"), _section("abbrev")
    logger.info("[normalize] loaded %d reading + %d abbrev entries from %s", len(reading), len(abbrev), path.name)
    return reading, abbrev


_READING_MAP: dict[str, str] | None = None
_ABBREV_MAP: dict[str, str] | None = None


_TENANT_MAP: dict[str, str] = {}
_EFFECTIVE_MAPS: tuple[dict[str, str], dict[str, str]] | None = None


def _ensure_maps() -> tuple[dict[str, str], dict[str, str]]:
    """Baseline maps with the tenant's own keys removed.

    Dropping them matters: the tenant pass runs first, but its replacement text then flows
    through these maps too — so a tenant respelling "Vietcombank" would have the baseline
    entry rewrite its own output. Keys the tenant defined are theirs alone; every OTHER
    baseline rule still applies to the output, which is what makes numbers and dates inside
    a replacement still read correctly.
    """
    global _READING_MAP, _ABBREV_MAP, _EFFECTIVE_MAPS
    if _EFFECTIVE_MAPS is None:
        if _READING_MAP is None:
            _READING_MAP, _ABBREV_MAP = _load_reading_abbrev(NORMALIZE_PATH)
        if _TENANT_MAP:
            bo = {k.casefold() for k in _TENANT_MAP}
            _EFFECTIVE_MAPS = (
                {k: v for k, v in _READING_MAP.items() if k.casefold() not in bo},
                {k: v for k, v in (_ABBREV_MAP or {}).items() if k.casefold() not in bo},
            )
        else:
            _EFFECTIVE_MAPS = (_READING_MAP, _ABBREV_MAP or {})
    return _EFFECTIVE_MAPS


def set_tenant_overrides(nmap: dict[str, str]) -> None:
    """Set the tenant's reading dictionary, layered over the platform baseline.

    A module-level holder is correct here: an agent pod is single-tenant (TenantContext is
    resolved once at boot from TENANT_ID), so threading the map through every
    normalize_for_voice() call site would add a parameter at four places for no isolation
    gain.
    """
    global _TENANT_MAP, _EFFECTIVE_MAPS
    _TENANT_MAP = {k: v for k, v in (nmap or {}).items() if k and v}
    _EFFECTIVE_MAPS = None


def reset_tenant_overrides() -> None:
    global _TENANT_MAP, _EFFECTIVE_MAPS
    _TENANT_MAP = {}
    _EFFECTIVE_MAPS = None


def _apply_map(text: str, nmap: dict[str, str], strict_upper: bool = False) -> str:
    """Substitute map entries, longest key first, on word boundaries. Case-insensitive
    EXCEPT when strict_upper and the key is all-uppercase (has cased letters, none
    lower): those match case-sensitively so a lowercased same-spelling word ("vs",
    "vat", "hd") is left alone. Mixed-case keys ("Anh/chị") stay case-insensitive."""
    for word in sorted(nmap, key=len, reverse=True):
        strict = strict_upper and word == word.upper() and word != word.lower()
        pattern = re.compile(r"\b" + re.escape(word) + r"\b", 0 if strict else re.IGNORECASE)
        text = pattern.sub(lambda _m, r=nmap[word]: r, text)
    return text


# ── Main entry point ─────────────────────────────────────────────────────────


def normalize_for_voice(text: str) -> str:
    """Normalize text for Vietnamese voice synthesis. Order matters — see the
    per-step comments below; each pass consumes its tokens before the next runs."""
    if not text:
        return text
    reading, abbrev = _ensure_maps()

    text = _URL_RE.sub("", text)
    text = _MARKDOWN_RE.sub("", text)
    text = _PAREN_ABBREV_RE.sub("", text)  # drop "(NCLB)" (redundant after full name)
    text = _EMAIL_AT_RE.sub(" a còng ", text)  # "a@b" → "a còng b" (before "@" is stripped)

    # Tenant layer runs first among the substitution passes: _CODE_RE below spells anything
    # code-shaped letter by letter, so placing this after it means a tenant can never teach
    # the agent how to read a unit code. The replacement text still flows through every
    # later pass, so numbers inside it are still expanded.
    if _TENANT_MAP:
        text = _apply_map(text, _TENANT_MAP, strict_upper=True)

    text = _ROMAN_RE.sub(_expand_roman, text)  # before CODE: "quý IV/2026" is roman, not a code
    text = _QUARTER_RE.sub(_expand_quarter, text)  # "Q1/2026" → "quý một năm 2026" (before CODE)
    text = _ROOM_GLUE_RE.sub(r"\1 \2 ", text)  # "2PN" → "2 PN " (before CODE; abbrev expands it below)
    text = _CODE_RE.sub(_read_code, text)  # before maps/num-range: codes read literal

    text = _TP_RE.sub("thành phố ", text)  # before maps so "TP.HCM" → HCM still expands
    text = _apply_map(text, reading)  # bank/brand reading overrides
    text = _VS_RE.sub("so với", text)  # lowercase "vs" = versus (before abbrev; UPPERCASE VS = vệ sinh)
    text = _apply_map(text, abbrev, strict_upper=True)  # abbrevs match UPPERCASE only (words "vs"/"vat" safe)

    text = _PHONE_RE.sub(_read_phone, text)
    text = _ID_RE.sub(_read_id, text)  # long bare digits (CCCD) → digit-by-digit
    text = _DATE_RE.sub(_expand_date, text)  # dd/mm/yyyy (/ - .)
    text = _YEAR_SLASH_RE.sub(r"\1 đến \2", text)  # "2026/2027" → "… đến …"
    text = _MONTH_YEAR_RE.sub(_expand_month_year, text)  # "Tháng 7/2026"
    text = _DATE_DM_RE.sub(_expand_date_dm, text)  # "ngày 5/5"
    text = _DATE_DM_BARE_RE.sub(_expand_date_dm_bare, text)  # bare "31/12" (day≥13)
    text = _TIME_RANGE_RE.sub(r"\1 đến \2", text)  # "8:00-11:30"
    text = _TIME_H_RANGE_RE.sub(_expand_h_range, text)  # "8h-11h" / "8-9h"
    text = _TIME_RE.sub(_expand_time, text)  # "8:00", "08:30:15"
    text = _TIME_H_RE.sub(_expand_time_h, text)  # "9h30"
    text = _RATIO_RE.sub(_expand_ratio, text)  # "1:100" → "một trên một trăm"
    text = _ALLCAPS_RE.sub(_spell_or_roman, text)  # unknown caps → spell; pure I/V/X run → roman

    text = _PER_UNIT_RE.sub(lambda m: f" một {_PER_UNIT_SPOKEN[m.group(1).lower()]}", text)  # "/m²"
    text = _WORD_SLASH_RE.sub(" ", text)  # "Đông/Nam" → "Đông Nam" (digit/digit fraction stays)
    text = _USD_PREFIX_RE.sub(r"\1 đô la", text)  # "$5000" → "5000 đô la"
    text = _USD_SUFFIX_RE.sub(r"\1 đô la", text)  # "5000$" → "5000 đô la"
    text = _CURRENCY_RE.sub(_expand_currency, text)  # "850.000đ" → "… đồng"
    text = _THOUSANDS_RE.sub(_degroup_thousands, text)  # "1.200.000" → "1200000"
    text = _DIM_RE.sub(_expand_dim, text)  # "5x20" → "năm nhân hai mươi"
    text = _RANGE_RE.sub(_expand_range, text)  # "1,2-2,5 tỷ"
    text = _NUM_RANGE_RE.sub(_expand_num_range, text)  # bare "2-3" → "hai đến ba"
    text = _METER_COLLOQ_RE.sub(_expand_meter_colloq, text)  # "3m5" (before unit)
    text = _UNIT_RE.sub(lambda m: f"{m.group(1)} {_UNIT_MAP.get(m.group(2), m.group(2))}", text)
    text = _MONEY_COLLOQ_RE.sub(_expand_money_colloq, text)  # "1 tỷ 2" (before price)
    text = _PRICE_RE.sub(_expand_price, text)  # "3.5 tỷ"
    text = _K_MONEY_RE.sub(_expand_k_money, text)  # "500k" (before plain number)
    text = _DECIMAL_RE.sub(_expand_decimal, text)  # "3.4"
    text = _PLAIN_NUMBER_RE.sub(_expand_plain_number, text)  # remaining numbers

    text = _SPECIAL_CHARS_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)  # "2 WC ," → "2 WC," (room-split trailing space)
    return text
