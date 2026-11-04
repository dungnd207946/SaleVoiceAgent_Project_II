"""Pure helpers for the run/score phases: dedup, JSONL/manifest IO, per-row scoring."""

from __future__ import annotations

import json
from pathlib import Path

from eval.data import TurnSample
from eval.response_rules import score_turn_rules
from eval.tool_metrics import score_turn_fc


def sample_from_row(row: dict) -> TurnSample:
    """Reconstruct a TurnSample from a persisted prediction/detail row."""
    return TurnSample(
        conversation_id=row["conversation_id"],
        turn_idx=row["turn_idx"],
        step_idx_in_turn=row["step_idx_in_turn"],
        is_first_assistant=row.get("is_first_assistant", False),
        is_final_assistant=row.get("is_final_assistant", False),
        user_message=row.get("user_message", ""),
        prefix=row.get("prefix", []),
        reference_response=row.get("reference_response", {}),
        tools=row.get("tools", []),
    )


def existing_keys(path: str | Path) -> set[tuple[str, int, int]]:
    path = Path(path)
    if not path.exists():
        return set()
    keys: set[tuple[str, int, int]] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            keys.add((r["conversation_id"], r["turn_idx"], r["step_idx_in_turn"]))
    return keys


def write_manifest(path: str | Path, entry: dict) -> None:
    path = Path(path)
    data = []
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    data.append(entry)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def score_prediction_row(pred_row: dict, *, response_eval_mode: str, tfidf_threshold: float, judge=None) -> dict:
    """Compute all enabled metrics for one prediction row.

    `judge` is an OPTIONAL sync callable (sample, predicted_msg) -> dict | None;
    the async caller pre-runs judging concurrently and passes a cache-lookup here.
    """
    predicted = pred_row["predicted_response"]
    reference = pred_row["reference_response"]
    out = {
        "conversation_id": pred_row["conversation_id"],
        "turn_idx": pred_row["turn_idx"],
        "step_idx_in_turn": pred_row["step_idx_in_turn"],
        "is_first_assistant": pred_row.get("is_first_assistant", False),
        "is_final_assistant": pred_row.get("is_final_assistant", False),
        "user_message": pred_row.get("user_message", ""),
        "reference_response": reference,
        "predicted_response": predicted,
        "fc": score_turn_fc(predicted, reference, tools=pred_row.get("tools", []), threshold=tfidf_threshold),
    }
    if response_eval_mode in ("rule", "both"):
        out["response_rule"] = score_turn_rules(sample_from_row(pred_row), predicted)
    if response_eval_mode in ("llm", "both") and judge is not None:
        res = judge(sample_from_row(pred_row), predicted)
        if res is not None:
            out["response_llm"] = res
    return out
