"""Evaluation helpers — tool accuracy, keyword match, FAQ hit."""

from __future__ import annotations

import unicodedata


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s


def evaluate_case(
    scenario: dict,
    tool_called: str,
    answer: str,
) -> dict:
    """Return per-case eval dict.

    Fields:
      tool_accuracy  bool   — expected_tool matched actual (or both absent)
      keyword_match  float? — fraction of expected_keywords found in answer (None if no kws)
      faq_hit        bool   — no tool called AND keyword_match >= 0.5
      expected_tool  str?   — from scenario
      actual_tool    str    — what was called (empty string if none)
    """
    expected_tool = scenario.get("expected_tool")  # may be None
    expected_kws: list[str] = scenario.get("expected_keywords") or []

    # Tool accuracy:
    # - expected_tool is None → correct iff no tool called
    # - else                  → correct iff tool_called contains expected_tool
    if expected_tool is None:
        tool_accuracy = not bool(tool_called)
    else:
        tool_accuracy = expected_tool in (tool_called or "")

    # Keyword match (normalised, diacritic-stripped comparison)
    if expected_kws:
        ans_norm = _norm(answer)
        matches = sum(1 for kw in expected_kws if _norm(kw) in ans_norm)
        keyword_match: float | None = matches / len(expected_kws)
    else:
        keyword_match = None

    # FAQ hit: LLM answered from FAQ (no tool) AND keywords present at ≥50%
    faq_hit = not bool(tool_called) and keyword_match is not None and keyword_match >= 0.5

    return {
        "tool_accuracy": bool(tool_accuracy),
        "keyword_match": keyword_match,
        "faq_hit": faq_hit,
        "expected_tool": expected_tool,
        "actual_tool": tool_called or "",
    }
