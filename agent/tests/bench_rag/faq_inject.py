"""FAQ injection for bench_llm — port of production _load_project_faq with multi-project support."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAQ_DIR = ROOT / "data" / "faq"

_MAX_PROJECTS = 3  # cap to avoid prompt explosion
_HEADER = (
    "═══ FAQ DỰ ÁN — PRIORITY SOURCE ═══\n"
    "QUAN TRỌNG: Nếu câu hỏi khách KHỚP với bất kỳ Q nào dưới đây, "
    "TRẢ LỜI NGAY bằng A tương ứng — KHÔNG gọi tool. "
    "Chỉ gọi tool khi FAQ KHÔNG có câu trả lời."
)


def _resolve_code(p: str) -> str | None:
    """Delegate to catalog.normalize. Returns None for unknown/ambiguous."""
    from noble_agent.agent import project_catalog as _catalog

    code = _catalog.normalize(p)
    return code or None


@lru_cache(maxsize=16)
def _load_md(path_str: str, max_chars: int) -> str:
    p = Path(path_str)
    if not p.exists():
        return ""
    try:
        txt = p.read_text(encoding="utf-8").strip()
        if len(txt) > max_chars:
            txt = txt[:max_chars] + "\n…[truncated]"
        return txt
    except Exception:
        return ""


def inject_faq(
    project_filter: str | list[str] | None,
    max_chars: int = 4000,
    include_common: bool = True,
) -> str:
    """
    Build FAQ block for system prompt injection.

    - None/"" with include_common=True  → only _COMMON.md (if exists)
    - Single code e.g. "NCLB"           → NCLB.md + optional _COMMON
    - "NCLB,NPLB" or ["NCLB","NPLB"]   → stacked blocks, max 3
    - Unknown/invalid codes silently skipped
    """
    if project_filter is None:
        project_filter = []
    elif isinstance(project_filter, str):
        project_filter = [p.strip() for p in project_filter.split(",") if p.strip()]

    codes: list[str] = []
    seen: set[str] = set()
    for raw in project_filter:
        code = _resolve_code(raw)
        if code and code not in seen:
            codes.append(code)
            seen.add(code)
        if len(codes) >= _MAX_PROJECTS:
            break

    blocks: list[str] = []
    if include_common:
        common_txt = _load_md(str(FAQ_DIR / "_COMMON.md"), max_chars)
        if common_txt:
            blocks.append("── FAQ CHUNG NOBLE ──\n" + common_txt)

    for code in codes:
        md_path = FAQ_DIR / f"{code}.md"
        txt = _load_md(str(md_path), max_chars)
        if txt:
            blocks.append(f"── DỰ ÁN {code} ──\n{txt}")

    if not blocks:
        return ""

    return _HEADER + "\n\n" + "\n\n".join(blocks)


def clear_faq_cache() -> None:
    _load_md.cache_clear()
