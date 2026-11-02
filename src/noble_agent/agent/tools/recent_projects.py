"""Scratchpad memory of the project codes Luna just read to the customer.

Written by the listing tools (discover_projects / search_units), read by
find_project as a resolution prior: a customer who answers a list with one
mangled word ("Sansai" for Sunshine) is almost always picking from that list.
Backend-agnostic — it does not matter which STT produced the mangling.
"""

from __future__ import annotations

from collections.abc import Iterable

KEY = "recent_projects"
MAX_RECENT = 6


def recall(state) -> list[str]:
    """Codes most-recently-listed first; [] when nothing recorded or corrupt."""
    raw = state.scratchpad.get(KEY)
    if not isinstance(raw, list):
        return []
    return [c for c in raw if isinstance(c, str) and c]


def remember(state, codes: Iterable[str]) -> None:
    """Record a listing: its codes go first (deduped), older ones follow, capped."""
    fresh: list[str] = []
    for c in codes:
        if isinstance(c, str) and c and c not in fresh:
            fresh.append(c)
    if not fresh:
        return
    merged = fresh + [c for c in recall(state) if c not in fresh]
    state.scratchpad[KEY] = merged[:MAX_RECENT]
