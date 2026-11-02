"""Dựng prompt dò mâu thuẫn và đọc kết quả LLM. Hàm thuần."""

from dataclasses import dataclass

from portal.modules.kb.conflicts.facts import normalize

PROFILE = "conflict_check"

_SIDE = {
    "type": "object",
    "properties": {"ref": {"type": "string"}, "quote": {"type": "string"}, "value": {"type": "string"}},
    "required": ["ref", "quote", "value"],
}
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "attribute": {"type": "string"},
                    "left": _SIDE,
                    "right": _SIDE,
                },
                "required": ["summary", "attribute", "left", "right"],
            },
        }
    },
    "required": ["conflicts"],
}


@dataclass(frozen=True)
class Item:
    ref: str
    label: str
    text: str


@dataclass(frozen=True)
class Finding:
    summary: str
    left_ref: str
    left_quote: str
    right_ref: str
    right_quote: str
    attribute: str = ""
    left_value: str = ""
    right_value: str = ""


def build_user_text(block: str, items: list[Item], candidates: list[Item]) -> str:
    """Khối trường đứng đầu: cùng dự án thì giống nhau ở mọi lượt, để tận dụng cache tiền tố."""
    parts = ["## Trường đã điền", block or "(không có)", "", "## Đoạn cần kiểm"]
    parts += [f"[{i.ref}] {i.label}\n{i.text}\n" for i in items]
    parts += ["## Đoạn đối chiếu"]
    parts += [f"[{c.ref}] {c.label}\n{c.text}\n" for c in candidates] or ["(không có)"]
    return "\n".join(parts)


def _side(raw: object) -> tuple[str, str, str] | None:
    if not isinstance(raw, dict):
        return None
    ref, quote, value = raw.get("ref"), raw.get("quote"), raw.get("value")
    if not all(isinstance(x, str) and x.strip() for x in (ref, quote, value)):
        return None
    return str(ref).strip(), str(quote).strip(), str(value).strip()


def parse_findings(raw: dict, *, valid_refs: set[str]) -> list[Finding]:
    items = raw.get("conflicts")
    if not isinstance(items, list):
        return []
    out: list[Finding] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        summary = str(it.get("summary") or "").strip()
        attribute = str(it.get("attribute") or "").strip()
        left, right = _side(it.get("left")), _side(it.get("right"))
        if not summary or not attribute or left is None or right is None:
            continue
        if normalize(left[2]) == normalize(right[2]):
            continue
        if not left[0].startswith("D"):
            left, right = right, left
        if not left[0].startswith("D") or left[0] == right[0]:
            continue
        if left[0] not in valid_refs or right[0] not in valid_refs or right[0].startswith("D"):
            continue
        out.append(Finding(summary, left[0], left[1], right[0], right[1], attribute, left[2], right[2]))
    return out
