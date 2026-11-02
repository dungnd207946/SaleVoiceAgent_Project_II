"""Hàm thuần của bộ dò mâu thuẫn: lọc đoạn có dữ kiện, dấu tay, kiểm trích dẫn."""

import hashlib
import re
from collections.abc import Iterable

_MARKDOWN = re.compile(r"[*_`]+")
_SPACE = re.compile(r"\s+")
_FACT = re.compile(
    r"\d|%|\b(tỷ|triệu|đồng|vnd|m²|m2|ha)\b|\b(công ty|tập đoàn|ctcp|tnhh)\b|\bsố\s*\d|/qđ|/tb|/ubnd",
    re.IGNORECASE,
)
_MIN_QUOTE = 4
# Thứ tự là ưu tiên: «đồng/m²/tháng» là tiền, không phải diện tích hay thời gian.
_KINDS = (
    ("money", re.compile(r"đồng|\bvn[dđ]\b|triệu|\btỷ\b|\busd\b|\$|\d\s*đ\b")),
    ("percent", re.compile(r"%|phần trăm")),
    ("area", re.compile(r"m²|\bm2\b|\bha\b|hecta|km²")),
    ("time", re.compile(r"\b(tháng|năm|ngày|tuần|quý|giờ)\b")),
)


def normalize(text: str) -> str:
    return _SPACE.sub(" ", _MARKDOWN.sub("", text or "")).strip().lower()


def has_checkable_fact(text: str) -> bool:
    return bool(_FACT.search(normalize(text)))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def chunk_hash(text: str) -> str:
    return "c:" + _sha(normalize(text))


def field_hash(entity: str, record_id: int, field: str, value: str) -> str:
    return "f:" + _sha(f"{entity}.{record_id}.{field}={normalize(value)}")


def block_hash(hashes: Iterable[str]) -> str:
    return "b:" + _sha("|".join(sorted(hashes)))


def ordered(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def quote_found(quote: str, source: str) -> bool:
    q = normalize(quote).strip(" .…\"'«»")
    return len(q) >= _MIN_QUOTE and q in normalize(source)


def value_kind(text: str) -> str | None:
    t = normalize(text)
    return next((kind for kind, rx in _KINDS if rx.search(t)), None)


_DIGIT = re.compile(r"\d")
_QUANTITY_WORDS = 5
_WORD = re.compile(r"\w{2,}")


def _quantity(value: str) -> str | None:
    """Loại đại lượng nếu giá trị là một con số ngắn kèm đơn vị («24 tháng», «12.000 đồng/m²»)."""
    v = normalize(value)
    if not _DIGIT.search(v) or len(_WORD.findall(v)) > _QUANTITY_WORDS:
        return None
    return value_kind(v)


def same_kind(left: str, right: str) -> bool:
    """Hai con số khác loại đại lượng (số tháng ↔ số tiền), hoặc một bên là con số có đơn vị còn
    bên kia không có số nào (miễn phí ↔ 12.000 đồng), thì không thể là cùng một thuộc tính.
    Giá trị dài dạng chữ thì không xét: đơn vị trong đó chỉ là chi tiết phụ."""
    a, b = _quantity(left), _quantity(right)
    if a and b:
        return a == b
    return not (a and not _DIGIT.search(right) or b and not _DIGIT.search(left))


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def value_in_quote(value: str, quote: str) -> bool:
    """Mọi con số của giá trị và ít nhất nửa số từ của nó có trong câu trích — chặn giá trị
    LLM tự suy ra («0 tháng») hoặc câu trích không nói gì về giá trị."""
    v, q = normalize(value), normalize(quote)
    if not set(_NUMBER.findall(v)) <= set(_NUMBER.findall(q)):
        return False
    words = _WORD.findall(v)
    have = set(_WORD.findall(q))
    return bool(words) and sum(w in have for w in words) * 2 >= len(words)


def strip_label(quote: str, label: str) -> str:
    """LLM hay chép cả dòng «Nhãn: giá trị» của khối trường; popup chỉ cần phần giá trị."""
    head = f"{label}:"
    return quote[len(head) :].strip() if normalize(quote).startswith(normalize(head)) else quote
