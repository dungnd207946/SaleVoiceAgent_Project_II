"""Grep-based FAQ search — stdlib-only fallback when embeddings are unavailable.

Verbatim port of the legacy noble_kb `_query_via_grep_faq` algorithm so output
shape matches the SFT mock_noble_search data byte-for-byte.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("noble_agent.rag.grep")

_FAQ_DIR = Path(__file__).resolve().parents[4] / "data" / "faq"


def search(query: str, project_filter: str | None) -> str:
    """Substring grep over data/faq/<CODE>.md. Returns formatted hits or ''."""
    query = (query or "").strip()
    if not query:
        return ""

    from noble_agent.agent.catalog import all_projects

    codes: list[str]
    if project_filter:
        codes = [project_filter]
    else:
        codes = [p.code for p in all_projects()]

    all_chunks: list[str] = []
    for code in codes:
        md = _FAQ_DIR / f"{code}.md"
        if not md.is_file():
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        all_chunks.extend(_grep_chunks(text, query, max_chunks=2))
        if len(all_chunks) >= 5:
            break

    if not all_chunks:
        logger.info("grep_search: no match for query=%r project=%s", query[:60], project_filter or "ALL")
        return ""
    logger.info("grep_search: %d chunks (project=%s)", len(all_chunks[:5]), project_filter or "ALL")
    return "\n---\n".join(all_chunks[:5])


def _grep_chunks(text: str, query: str, window: int = 400, max_chunks: int = 3) -> list[str]:
    if not text:
        return []
    tokens = [t.lower() for t in query.split() if len(t) > 2]
    if not tokens:
        return [text[:window]]
    chunks: list[str] = []
    low = text.lower()
    seen_pos: set[int] = set()
    for tok in tokens:
        idx = 0
        while idx < len(low) and len(chunks) < max_chunks:
            pos = low.find(tok, idx)
            if pos < 0:
                break
            start = max(0, pos - window // 2)
            end = min(len(text), pos + window // 2)
            if any(abs(start - s) < window for s in seen_pos):
                idx = pos + len(tok)
                continue
            seen_pos.add(start)
            chunks.append(text[start:end])
            idx = end
    return chunks
