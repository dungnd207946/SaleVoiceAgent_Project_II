"""Similarity channels for project-name matching. Each returns 0..1.

trigram + token_set run on raw-normalized text; phonetic runs on folded text.

Each channel has a "raw" entrypoint (takes two raw strings, normalizes/folds
internally) plus a prebuilt-form entrypoint (takes already-normalized/folded
text or trigram sets). Callers that score one query against many static
entries (e.g. ``index.ProjectNameIndex.resolve``) should normalize/fold the
query once and precompute the entry forms at build time, then call the
prebuilt-form functions in the hot loop — the raw functions just normalize/fold
both sides and delegate, so results are identical either way.
"""

from __future__ import annotations

from noble_agent.data.project_matching import fold


def trigram_set(s: str) -> set[str]:
    """Character-trigram set of an already-normalized string."""
    s = f"  {s} "  # pad so short strings still yield boundary grams
    return {s[i : i + 3] for i in range(len(s) - 2)}


def trigram_score_sets(ta: set[str], tb: set[str]) -> float:
    """Dice coefficient over two prebuilt trigram sets."""
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return 2 * inter / (len(ta) + len(tb))


def trigram_score(a: str, b: str) -> float:
    return trigram_score_sets(trigram_set(fold.normalize_text(a)), trigram_set(fold.normalize_text(b)))


def token_set_score_normalized(a_norm: str, b_norm: str) -> float:
    """rapidfuzz token_set_ratio on two already-normalized strings."""
    from rapidfuzz import fuzz

    return fuzz.token_set_ratio(a_norm, b_norm) / 100.0


def token_set_score(a: str, b: str) -> float:
    return token_set_score_normalized(fold.normalize_text(a), fold.normalize_text(b))


def phonetic_score_folded(a_folded: str, b_folded: str) -> float:
    """rapidfuzz token_set_ratio on two already phonetic-folded strings."""
    from rapidfuzz import fuzz

    return fuzz.token_set_ratio(a_folded, b_folded) / 100.0


def phonetic_score(a_raw: str, b_raw: str) -> float:
    return phonetic_score_folded(fold.fold_text(a_raw), fold.fold_text(b_raw))
