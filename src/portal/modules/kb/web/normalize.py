"""Chuẩn hoá URL, băm nội dung, dọn nhãn từ output LLM. Hàm thuần, không I/O."""

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_KEYS = {"fbclid", "gclid", "zarsrc", "zaloapp", "_ga"}
_BLANK = {"", "null", "none", "n/a", "-"}


def canonical_url(url: str) -> str:
    """Bỏ scheme hoa, cổng mặc định, slash cuối, và tham số theo dõi (utm_*/fbclid/...)."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_KEYS
    ]
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(query), ""))


def domain_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def fold(text: str) -> str:
    """NFC + casefold + gộp khoảng trắng — dùng để so khớp không phân biệt hoa/thường/dấu cách."""
    return " ".join(unicodedata.normalize("NFC", text or "").casefold().split())


def contains_word(hay_folded: str, needle: str) -> bool:
    """`hay_folded` phải đã qua `fold()`. Khớp theo RANH GIỚI TỪ, không khớp trong từ dài hơn."""
    n = fold(needle)
    return bool(n) and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", hay_folded) is not None


def content_hash(text: str) -> str:
    norm = fold(text)
    return hashlib.sha256(norm.encode()).hexdigest() if norm else ""


def clean_labels(values: Iterable[str] | None) -> tuple[str, ...]:
    """Dọn nhãn LLM trả về: bỏ None/rỗng/giá trị rỗng-nghĩa (`null`,...), gộp trùng, giữ thứ tự xuất hiện."""
    out: list[str] = []
    seen: set[str] = set()
    for v in values or []:
        if not isinstance(v, str):
            continue
        s = " ".join(unicodedata.normalize("NFC", v).split()).strip(" ,.;")
        if s.casefold() in _BLANK or s.casefold() in seen:
            continue
        seen.add(s.casefold())
        out.append(s)
    return tuple(out)


_BRACKETED = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
_LEADING_DIGIT = re.compile(r"[0-9]")
_JOINERS = re.compile(r"[-–—&]")


def display_project(name: str) -> str:
    """Tên dự án bỏ phần trong ngoặc tròn/vuông, gộp khoảng trắng; GIỮ hoa thường (dùng trong câu search)."""
    return " ".join(_BRACKETED.sub(" ", unicodedata.normalize("NFC", name or "")).split())


def norm_project(name: str) -> str:
    """Dạng chuẩn của tên dự án: NFC, bỏ phần trong ngoặc tròn/vuông, gộp khoảng trắng, hạ chữ; giữ dấu."""
    return " ".join(display_project(name).casefold().split()).strip(" ,.;")


def project_labels(values: Iterable[object] | None) -> tuple[str, ...]:
    return clean_labels(norm_project(v) for v in values or () if isinstance(v, str))


_NAME_SPLIT = re.compile(r"\s+[-–—]\s+")
_PAREN_TEXT = re.compile(r"\(([^()]*)\)")


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt ("Hạ Long" → "Ha Long", "đ" → "d")."""
    decomposed = unicodedata.normalize("NFD", text or "").replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFC", "".join(c for c in decomposed if unicodedata.category(c) != "Mn"))


def project_names(name: str) -> tuple[str, ...]:
    """Các tên dùng để khớp bài với dự án: tên chuẩn, vế ĐẦU trước " – " (vế sau hay là đại dự án chứa nó),
    phần trong ngoặc (≥ 2 từ), và dạng "nhà ở xã hội" của "NOXH"."""
    base = unicodedata.normalize("NFC", name or "")
    raw = [base, *_PAREN_TEXT.findall(base)]
    raw.append(_NAME_SPLIT.split(display_project(base))[0])
    names: list[str] = []
    for v in raw:
        n = norm_project(v)
        if len(n.split()) < 2 and n != norm_project(base):
            continue
        names.append(n)
        if re.search(r"\bnoxh\b", n):
            long = re.sub(r"\bnoxh\b", "nhà ở xã hội", n)
            names += [long, re.sub(r"^khu ", "", long)]
    return clean_labels(names)


NON_PROJECT_PREFIXES = (
    "tuyến",
    "metro",
    "đường sắt",
    "đường",
    "cầu",
    "nút giao",
    "sân bay",
    "ga",
    "khu công nghiệp",
    "kcn",
    "bệnh viện",
    "vinmec",
    "trường",
    "sân golf",
    "vinpearl golf",
    "vinwonders",
    "trung tâm thương mại",
    "công viên",
    "cao tốc",
    "vành đai",
    "quốc lộ",
)
"""Nhãn `projects` mở đầu bằng một trong các từ này là hạ tầng/tiện ích, không phải dự án nhà ở."""


def is_non_project(name: str) -> bool:
    """Khớp theo từ nguyên vẹn ở đầu tên chuẩn hoá: "Ga Hà Nội" bị loại, "Gamuda Gardens" thì không."""
    n = norm_project(name)
    return any(n == w or n.startswith(w + " ") for w in NON_PROJECT_PREFIXES)


def tag_projects(values: Iterable[object] | None) -> tuple[str, ...]:
    """Nhãn `projects` của một trang: `project_labels` rồi bỏ hạ tầng/tiện ích."""
    return tuple(v for v in project_labels(values) if not is_non_project(v))


def _variant(label: str, base: str) -> bool:
    """`label` là `base` hoặc `base` + đuôi không mở đầu bằng chữ số ("... ocean park 2" là dự án khác)."""
    if not base:
        return False
    if label == base:
        return True
    return label.startswith(base + " ") and _LEADING_DIGIT.match(label, len(base) + 1) is None


def project_matches(label: str, name: str) -> bool:
    """Nhãn `projects` (đã chuẩn hoá) có thuộc dự án `name` không, so không dấu. Cùng luật với SQL ở `repo.py`."""
    return _variant(strip_accents(label), strip_accents(norm_project(name)))


_GENERIC_HEAD = re.compile(r"^(?:khu |noxh |nha o xa hoi |chung cu |du an )+")


def _core(name: str) -> str:
    """Tên chuẩn hoá, bỏ dấu, bỏ đầu chung chung ("khu", "NOXH", "nhà ở xã hội", "chung cư", "dự án")."""
    return _GENERIC_HEAD.sub("", strip_accents(norm_project(name))).strip()


def twin_names(a: str, b: str) -> bool:
    """Hai tên chung phần đầu ≥ 2 từ (bỏ dấu, bỏ đầu chung chung) và phần khác nhau không mở đầu bằng số
    ("sunrise home thanh trì" / "noxh sunrise home ngọc hồi"; KHÔNG "ocean park 2" / "ocean park 3") — CÓ THỂ là
    một dự án dưới hai tên. Chỉ coi là một khi còn cùng xã/phường (bên gọi tự kiểm)."""
    x, y = _core(a).split(), _core(b).split()
    k = 0
    while k < min(len(x), len(y)) and x[k] == y[k]:
        k += 1
    if k < 2 or k == len(x) == len(y):
        return False
    rest = [t for t in (x[k : k + 1] + y[k : k + 1])]
    return not any(_LEADING_DIGIT.match(t) for t in rest)


def same_project(a: str, b: str) -> bool:
    """Hai tên coi là một dự án (so không dấu, bỏ đầu chung chung): biến thể có đuôi theo cả hai chiều,
    hoặc tên này là hậu tố của tên kia."""
    a, b = _core(a), _core(b)
    if not a or not b:
        return False
    return _variant(a, b) or _variant(b, a) or a.endswith(" " + b) or b.endswith(" " + a)


def _unjoin(text: str) -> str:
    return " ".join(_JOINERS.sub(" ", text).split())


def mentions_project(text: str, name: str) -> bool:
    """`text` nhắc tên dự án: tên đầy đủ, hoặc (tên ≥ 3 từ) tên bỏ từ đầu ("Royal Island")."""
    hay = _unjoin(fold(text))
    words = _unjoin(norm_project(name)).split()
    if not words:
        return False
    return contains_word(hay, " ".join(words)) or (len(words) >= 3 and contains_word(hay, " ".join(words[1:])))


# câu nói một tên là tên khác / một phần của dự án kia — thẻ như vậy không phải "dự án lân cận"
_ALIAS_PHRASES = (
    "tên thương mại",
    "tên pháp lý",
    "tên gọi khác",
    "tên khác",
    "tên cũ",
    "còn gọi là",
    "còn được gọi là",
    "còn được biết đến",
    "hay còn gọi",
    "tức là",
    "bao gồm",
    "là một phần của",
    "phân khu của",
    "thuộc dự án",
)
_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")


def alias_of(text: str, name: str, card_name: str = "") -> bool:
    """Có câu nào vừa nhắc `name` vừa mang cụm "tên thương mại/còn gọi là/bao gồm…" không —
    vd thẻ "Vinhomes Đan Phượng (tên thương mại Vinhomes Wonder City)" là alias của Wonder City.
    Có `card_name` thì bắt thêm dạng ngoặc: "Vinhomes Wonder City (Vinhomes Đan Phượng)" và ngược lại."""
    if card_name:
        hay = _unjoin(fold(text)).replace("( ", "(")
        a, b = _unjoin(norm_project(name)), _unjoin(norm_project(card_name))
        if a and b and (f"{a} ({b}" in hay or f"{b} ({a}" in hay):
            return True
    for sentence in _SENTENCE.split(text or ""):
        folded = fold(sentence)
        if any(p in folded for p in _ALIAS_PHRASES) and mentions_project(sentence, name):
            return True
    return False
