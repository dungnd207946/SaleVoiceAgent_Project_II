"""Địa danh dự án lấy từ `address` và nhãn địa danh đã chuẩn hoá để so khớp. Hàm thuần, không I/O.

Mọi nhãn `location` lưu xuống Postgres/Qdrant và mọi nhãn đem đi so đều qua `place_labels` —
hai phía của một phép so luôn cùng một dạng.
"""

import re
import unicodedata
from collections.abc import Iterable

from portal.modules.kb.web.normalize import clean_labels

_HOUSE = re.compile(r"^(số\s*)?\d+[0-9a-z/\-]*\s+", re.IGNORECASE)
_HOUSE_ONLY = re.compile(r"(số\s*)?\d+[0-9a-z/\-]*", re.IGNORECASE)
_BROAD_REGIONS = {"mien_bac", "mien_nam", "mien_trung"}
_PREFIX = re.compile(
    r"^(?:(tp|tx|p|q|h)\.\s*"
    r"|(thành phố|thị xã|thị trấn|khu đô thị|đại lộ|tỉnh|quận|huyện|xã|phường|đường|phố|kđt|tp)\s+)"
    r"(?=\S)"
)
_NUMBERED = re.compile(r"\d+[a-z]?")
_FULL = {"tp": "thành phố", "tx": "thị xã", "p": "phường", "q": "quận", "h": "huyện"}
_EDGE = " ,.;"
_SEPARATOR = re.compile(r",|\s+[-–&]\s+")
_PAREN = re.compile(r"\([^()]*\)")


# đầu mục kiểu liệt kê LLM hay chép theo nguồn: "số 1: xã nghĩa trụ…"
_LIST_NO = re.compile(r"^số\s*\d+\s*[:.\-–]\s*")


def norm_place(name: str) -> str:
    """Bỏ (lặp) tiền tố hành chính ở đầu, gộp khoảng trắng, hạ chữ; giữ dấu tiếng Việt.

    Phần còn lại chỉ là số ("Quận 7", "P.7A") thì GIỮ tiền tố, viết đầy đủ ("quận 7") —
    bỏ đi thì "Phường 7" và "Quận 7" cùng thành "7"."""
    s = unicodedata.normalize("NFC", " ".join(unicodedata.normalize("NFC", name or "").casefold().split()))
    s = _LIST_NO.sub("", s).strip(_EDGE)
    while True:
        m = _PREFIX.match(s)
        if m is None:
            return s
        rest = s[m.end() :].strip(_EDGE)
        if _NUMBERED.fullmatch(rest):
            word = m.group(1) or m.group(2)
            return f"{_FULL.get(word, word)} {rest}"
        s = rest


def place_labels(values: Iterable[object] | None) -> tuple[str, ...]:
    return clean_labels(norm_place(v) for v in values or () if isinstance(v, str))


def _split(text: str) -> list[str]:
    parts: list[str] = []
    for raw in _SEPARATOR.split(_PAREN.sub(" ", text)):
        part = " ".join(raw.split()).rstrip(".").strip()
        if _HOUSE_ONLY.fullmatch(part):
            continue
        part = _HOUSE.sub("", part)
        if part:
            parts.append(part)
    seen: set[str] = set()
    kept: list[str] = []
    for part in reversed(parts):
        key = norm_place(part)
        if key not in seen:
            seen.add(key)
            kept.append(part)
    return kept[::-1][-3:]


def address_parts(address: str | None, region: str | None = "") -> tuple[str, ...]:
    """3 phần cuối của địa chỉ (tách theo `,` và ` - `/` – `/` & `; bỏ số nhà, bỏ phần trùng giữ lần cuối);
    địa chỉ rỗng thì dùng `region`."""
    parts = _split(address or "")
    if not parts and (region or "").strip().casefold() not in _BROAD_REGIONS:
        parts = _split(region or "")
    return tuple(parts)


def location_text(address: str | None, region: str | None = "") -> str:
    """Giá trị `{location}` trong câu search."""
    return ", ".join(address_parts(address, region))


_OLD_NOTE = re.compile(r"\(([^()]*\b(?:cũ|nay là)\b[^()]*)\)", re.IGNORECASE)
_OLD_WORDS = re.compile(r"\b(?:cũ|nay là)\b", re.IGNORECASE)


def old_names(address: str | None) -> tuple[str, ...]:
    """Địa danh cũ/mới ghi trong ngoặc có chữ "cũ" hoặc "nay là" ("(xã Tân Lập, Đan Phượng cũ)") — bài báo và
    thẻ lân cận hay còn dùng tên trước sáp nhập. Ngoặc khác (tên đường, lô đất) không lấy."""
    parts = [_OLD_WORDS.sub(" ", part) for note in _OLD_NOTE.findall(address or "") for part in _SEPARATOR.split(note)]
    return tuple(lb for lb in place_labels(parts) if len(lb.split()) <= 4)


def match_labels(parts: tuple[str, ...]) -> tuple[str, ...]:
    """Nhãn so khớp của dự án: bỏ phần cuối (tỉnh/thành, quá rộng) khi có ≥ 2 phần."""
    return place_labels(parts[:-1] if len(parts) >= 2 else parts)


def levels(labels: Iterable[str]) -> list[tuple[str, ...]]:
    """Mỗi nhãn so khớp là một cấp, từ hẹp (đầu) ra rộng (cuối)."""
    return [(label,) for label in labels]
