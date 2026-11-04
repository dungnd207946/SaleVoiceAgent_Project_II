"""Dependency-free rule-based tool-call metrics (pairing + classification + aggregate)."""

from __future__ import annotations

import json
from difflib import SequenceMatcher

ERROR_LABELS = (
    "unwanted_function_call",
    "missing_function_call",
    "incorrect_function_format",
    "wrong_argument_value",
    "missing_argument",
)


def extract_tool_calls(message: dict) -> list[dict]:
    """Return [{name, args}] from an OpenAI-shaped assistant message."""
    out: list[dict] = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        raw = fn.get("arguments")
        if isinstance(raw, dict):
            args = raw
        else:
            try:
                args = json.loads(raw) if raw else {}
            except (ValueError, TypeError):
                args = {}
        out.append({"name": name, "args": args})
    return out


def value_similarity(a: object, b: object) -> float:
    return SequenceMatcher(None, str(a), str(b)).ratio()


def build_schema_index(tools: list[dict]) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for t in tools:
        fn = t.get("function") or {}
        name = fn.get("name")
        if name:
            idx[name] = fn.get("parameters") or {}
    return idx


_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _type_ok(value: object, json_type: str) -> bool:
    py = _TYPE_MAP.get(json_type)
    if py is None:
        return True
    if json_type == "integer" and isinstance(value, bool):
        return False
    return isinstance(value, py)


def schema_format_bad(args: dict, schema: dict) -> bool:
    """True if args violate the schema (undeclared key / bad enum / bad type)."""
    props = schema.get("properties") or {}
    if not props:
        return False
    if set(args.keys()) - set(props.keys()):
        return True
    for key, value in args.items():
        spec = props.get(key) or {}
        enum = spec.get("enum")
        if enum is not None and value not in enum:
            return True
        json_type = spec.get("type")
        if json_type and not _type_ok(value, json_type):
            return True
    return False


def pair_calls(predicted: list[dict], expected: list[dict]) -> list[tuple[dict | None, dict | None]]:
    """Greedy match by tool name; leftovers paired with None.

    Matching is greedy by tool name in predicted order: each predicted call is paired with
    the first still-unmatched expected call of the same name. When a tool name appears
    multiple times with differing argument order across the two lists, the predicted↔expected
    argument pairing for those duplicates is not guaranteed to be positionally correct
    (argument-level accuracy is undefined for duplicate-name calls).
    """
    remaining = list(range(len(expected)))
    matched: list[tuple[dict | None, dict | None]] = []
    unmatched_pred: list[dict] = []
    for p in predicted:
        hit = next((j for j in remaining if expected[j]["name"] == p["name"]), None)
        if hit is None:
            unmatched_pred.append(p)
        else:
            matched.append((p, expected[hit]))
            remaining.remove(hit)
    matched.extend((p, None) for p in unmatched_pred)
    matched.extend((None, expected[j]) for j in remaining)
    return matched


def classify_pair(predicted: dict | None, expected: dict | None, *, schema_index: dict, threshold: float) -> list[str]:
    if predicted is None and expected is None:
        return []
    if predicted is None:
        return ["missing_function_call"]
    if expected is None:
        return ["unwanted_function_call"]

    errors: list[str] = []
    schema = schema_index.get(predicted["name"]) or {}
    p_args = predicted.get("args") or {}
    e_args = expected.get("args") or {}

    if schema and schema_format_bad(p_args, schema):
        errors.append("incorrect_function_format")

    schema_required = schema.get("required")
    required = set(schema_required if schema_required is not None else e_args.keys())
    if any(k in e_args and k not in p_args for k in required):
        errors.append("missing_argument")

    # wrong_argument_value is a per-pair flag — fires once even if multiple args mismatch.
    for k in e_args.keys() & p_args.keys():
        if value_similarity(p_args[k], e_args[k]) < threshold:
            errors.append("wrong_argument_value")
            break
    return errors


def score_turn_fc(predicted_msg: dict, expected_msg: dict, *, tools: list[dict], threshold: float) -> dict:
    pred = extract_tool_calls(predicted_msg)
    exp = extract_tool_calls(expected_msg)
    schema_index = build_schema_index(tools)
    pairs_out = []
    for p, e in pair_calls(pred, exp):
        errors = classify_pair(p, e, schema_index=schema_index, threshold=threshold)
        pairs_out.append({"predicted": p, "expected": e, "errors": errors})
    return {"has_tool_calls": bool(pred or exp), "pairs": pairs_out}


def aggregate_fc(rows: list[dict]) -> dict:
    """Aggregate over detail rows. Each row has row['fc'] == score_turn_fc output."""
    fcs = [r["fc"] for r in rows if r.get("fc")]
    turns_with = [fc for fc in fcs if fc.get("has_tool_calls")]
    all_pairs = [pair for fc in turns_with for pair in fc["pairs"]]
    n_pairs = len(all_pairs)

    def rate(label: str) -> float:
        if n_pairs == 0:
            return 0.0
        return sum(1 for p in all_pairs if label in p["errors"]) / n_pairs

    # Heuristic proxy: a turn with BOTH an unwanted and a missing call likely called a wrong-named tool.
    wrong_name = sum(
        1
        for fc in turns_with
        if any("unwanted_function_call" in p["errors"] for p in fc["pairs"])
        and any("missing_function_call" in p["errors"] for p in fc["pairs"])
    )
    return {
        "n_turns_with_tool_calls": len(turns_with),
        "n_total_pairs": n_pairs,
        "unwanted_function_call_rate": rate("unwanted_function_call"),
        "missing_function_call_rate": rate("missing_function_call"),
        "incorrect_function_format_rate": rate("incorrect_function_format"),
        "wrong_argument_value_rate": rate("wrong_argument_value"),
        "missing_argument_rate": rate("missing_argument"),
        "wrong_tool_name_rate": (wrong_name / len(turns_with)) if turns_with else 0.0,
    }
