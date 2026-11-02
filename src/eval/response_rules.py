"""Luna-adapted rule-based response axes (ported from santa-post-training, tuned to RULES.md)."""

from __future__ import annotations

import json
import re

from eval.data import TurnSample

AXES = (
    "opening_compliance",
    "closing_compliance",
    "forbidden_words",
    "conciseness_clarity",
    "politeness_markers",
    "name_usage",
)

_FORBIDDEN = ("nhé", "nhá", "nhỉ")
# Leading space in " ạ" is intentional: the politeness particle "ạ" always follows a space in well-formed output.
_POLITE = ("dạ", "vâng", "vui lòng", "cảm ơn", " ạ")
_INTRO = ("luna", "tư vấn", "noble")


def _sentences(text: str) -> list[str]:
    # Don't split on a '.' sitting between digits (e.g. "5.5 tỷ" is one sentence).
    return [s for s in re.split(r"(?<!\d)[.!?…]+(?!\d)", text) if s.strip()]


def extract_customer_name(prefix: list[dict]) -> str | None:
    """Recover a customer name from update_customer tool calls in the prefix."""
    for m in prefix:
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") != "update_customer":
                continue
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (ValueError, TypeError):
                args = {}
            for key in ("name", "full_name"):
                if args.get(key):
                    return str(args[key])
    return None


def score_turn_rules(sample: TurnSample, predicted_msg: dict) -> dict:
    content = (predicted_msg.get("content") or "").strip()
    low = content.lower()
    has_text = bool(content)

    opening = None
    if sample.is_first_assistant and has_text:
        starts = low.startswith("dạ") or low.startswith("vâng")
        opening = int(starts and any(k in low for k in _INTRO))

    closing = None
    if sample.is_final_assistant and has_text:
        closing = int(("cảm ơn" in low) and ("noble" in low))

    forbidden = int(not any(w in low for w in _FORBIDDEN)) if has_text else None
    # RULES.md: "2–3 câu max" → constraint is at most 3 sentences (has_text guarantees >=1).
    concise = int(1 <= len(_sentences(content)) <= 3) if has_text else None
    polite = int(any(m in low for m in _POLITE)) if has_text else None

    name = None
    cust = extract_customer_name(sample.prefix)
    if cust and has_text:
        name = int(bool(re.search(rf"\b{re.escape(cust.lower())}\b", low)))

    return {
        "opening_compliance": opening,
        "closing_compliance": closing,
        "forbidden_words": forbidden,
        "conciseness_clarity": concise,
        "politeness_markers": polite,
        "name_usage": name,
    }


def aggregate_rules(rows: list[dict]) -> dict:
    """Per-axis pass_rate + n_evaluated (None values excluded), plus mean aggregate.

    Note: the mean ``aggregate`` only averages axes that had at least one evaluated turn,
    so aggregates are not directly comparable across runs covering different turn mixes.
    """
    out: dict[str, object] = {}
    pass_rates: list[float] = []
    for axis in AXES:
        vals = [r["rule"][axis] for r in rows if r.get("rule") and r["rule"].get(axis) is not None]
        if vals:
            pr = sum(vals) / len(vals)
            out[axis] = {"pass_rate": pr, "n_evaluated": len(vals)}
            pass_rates.append(pr)
        else:
            out[axis] = {"pass_rate": None, "n_evaluated": 0}
    out["aggregate"] = sum(pass_rates) / len(pass_rates) if pass_rates else 0.0
    return out
