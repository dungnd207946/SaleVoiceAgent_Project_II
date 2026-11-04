"""Aggregate detail rows into report.json (summary + per-turn)."""

from __future__ import annotations

from collections import defaultdict

from eval.response_rules import aggregate_rules
from eval.tool_metrics import aggregate_fc


def _aggregate_llm(rows: list[dict]) -> dict | None:
    llms = [r["response_llm"] for r in rows if r.get("response_llm")]
    if not llms:
        return None
    aggs = [x["aggregate"] for x in llms if "aggregate" in x]
    facts = [1 if x.get("factual_pass") else 0 for x in llms]
    return {
        "n_evaluated": len(llms),
        "aggregate": sum(aggs) / len(aggs) if aggs else 0.0,
        "factual_pass_rate": sum(facts) / len(facts) if facts else 0.0,
    }


def _summary(rows: list[dict], response_eval_mode: str) -> dict:
    summary: dict = {"n_total_turns": len(rows), "fc_metrics": aggregate_fc(rows)}
    if response_eval_mode in ("rule", "both") and any(r.get("response_rule") for r in rows):
        summary["response_rule"] = aggregate_rules(
            [{"rule": r["response_rule"]} for r in rows if r.get("response_rule")]
        )
    if response_eval_mode in ("llm", "both"):
        llm = _aggregate_llm(rows)
        if llm:
            summary["response_llm"] = llm
    return summary


def build_report(
    details: list[dict], *, slug: str, eval_file: str, response_eval_mode: str, tfidf_threshold: float
) -> dict:
    by_turn: dict[int, list[dict]] = defaultdict(list)
    for r in details:
        by_turn[r["turn_idx"]].append(r)

    convs = {r["conversation_id"] for r in details}
    per_turn = {str(t): _summary(rows, response_eval_mode) for t, rows in sorted(by_turn.items())}
    return {
        "slug": slug,
        "eval_file": eval_file,
        "response_eval_mode": response_eval_mode,
        "n_conversations": len(convs),
        "max_turns": max(by_turn) if by_turn else 0,
        "tfidf_threshold": tfidf_threshold,
        "summary": _summary(details, response_eval_mode),
        "per_turn": per_turn,
    }
