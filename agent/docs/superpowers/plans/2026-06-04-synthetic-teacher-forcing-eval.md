# Synthetic Teacher-Forcing Eval — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new top-level `src/eval/` package that evaluates the Noble agent (Luna) on the synthetic SFT reference file via teacher forcing — one LLM completion per assistant turn — and scores tool calls + response quality, mirroring the `santa-post-training` two-phase pipeline.

**Architecture:** Two CLI phases. `run` replays each reference conversation's prefix and asks the agent's own LLM (`.env` provider chain) for the next assistant message, writing `predictions.jsonl`. `score` reads predictions, computes dependency-free rule-based tool-call metrics + 6 Luna response axes + an optional LLM-judge, and writes `details.jsonl` + `report.json`.

**Tech Stack:** Python 3.11+, stdlib (`asyncio`, `json`, `difflib`, `argparse`, `re`, `datetime`, `pathlib`), `pydantic-settings`, in-repo `noble_agent` LLM stack (prediction), `openai`/`anthropic` SDK objects (critic). No new dependencies.

**Reference spec:** `docs/superpowers/specs/2026-06-04-synthetic-teacher-forcing-eval-design.md`

**Conventions:**
- Tests live under `tests/unit/eval/`; `tests/conftest.py` already inserts `src/` on `sys.path`, so `from eval.X import …` works.
- Run modules with `PYTHONPATH=src python -m eval …`.
- `pytest asyncio_mode=auto` (no `@pytest.mark.asyncio` needed); ruff line-length 120, rules `E,F,W,I,UP,B,SIM`.
- Commit on the current feature branch only (never `develop`); no push.

---

## Task 1: Package scaffold + config

**Files:**
- Create: `src/eval/__init__.py`
- Create: `src/eval/config.py`
- Create: `tests/unit/eval/__init__.py`
- Test: `tests/unit/eval/test_config.py`

- [ ] **Step 1: Create empty package markers**

`src/eval/__init__.py`:
```python
"""Teacher-forcing evaluation for the synthetic SFT reference data.

Two phases (CLI: ``PYTHONPATH=src python -m eval run|score``):
  run   — replay each reference prefix, ask the agent LLM for the next turn.
  score — rule-based tool-call metrics + Luna response axes + optional LLM judge.
"""
```

`tests/unit/eval/__init__.py`:
```python
```

- [ ] **Step 2: Write the failing test**

`tests/unit/eval/test_config.py`:
```python
from eval.config import EvalSettings


def test_defaults():
    s = EvalSettings()
    assert s.eval_file.endswith("data/synthetic_sft/eval_sft.jsonl")
    assert s.results_dir.endswith("data/eval_results")
    assert s.temperature == 0.2
    assert s.max_tokens == 1024
    assert s.workers == 8
    assert s.tfidf_threshold == 0.7


def test_env_override(monkeypatch):
    monkeypatch.setenv("EVAL_CRITIC_MODEL", "gpt-4o-mini")
    s = EvalSettings()
    assert s.critic_model == "gpt-4o-mini"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.config'`

- [ ] **Step 4: Write minimal implementation**

`src/eval/config.py`:
```python
"""Eval configuration. Reads .env so it inherits the agent's provider config."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class EvalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── paths ─────────────────────────────────────────────────────────────
    eval_file: str = "data/synthetic_sft/eval_sft.jsonl"
    results_dir: str = "data/eval_results"

    # ── run phase ─────────────────────────────────────────────────────────
    temperature: float = 0.2
    max_tokens: int = 1024
    workers: int = 8

    # ── score phase ───────────────────────────────────────────────────────
    # Generic similarity threshold for tool-arg value comparison.
    # Kept the name `tfidf_threshold` for parity with santa-post-training.
    tfidf_threshold: float = 0.7

    # ── critic (LLM judge) — default resolves to the .env Anthropic provider ─
    critic_model: str = ""        # EVAL_CRITIC_MODEL
    critic_base_url: str = ""      # EVAL_CRITIC_BASE_URL
    critic_api_key: str = ""       # EVAL_CRITIC_API_KEY
```

Note: pydantic-settings matches the field name case-insensitively to env vars, so
`EVAL_CRITIC_MODEL` → `critic_model` only if prefixed. Add an explicit alias to be safe.

Replace the critic fields with aliased versions:
```python
    from pydantic import Field  # add at top with other imports

    critic_model: str = Field("", alias="EVAL_CRITIC_MODEL")
    critic_base_url: str = Field("", alias="EVAL_CRITIC_BASE_URL")
    critic_api_key: str = Field("", alias="EVAL_CRITIC_API_KEY")
```
(Move `from pydantic import Field` to the import block at the top of the file.)

- [ ] **Step 5: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/eval/__init__.py src/eval/config.py tests/unit/eval/__init__.py tests/unit/eval/test_config.py
git commit -m "feat(eval): scaffold eval package + EvalSettings"
```

---

## Task 2: Turn enumeration (`data.py`)

**Files:**
- Create: `src/eval/data.py`
- Test: `tests/unit/eval/test_data.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/eval/test_data.py`:
```python
from eval.data import TurnSample, enumerate_turns


def _record():
    return {
        "conversation_id": "synth-abc",
        "tools": [{"type": "function", "function": {"name": "update_customer", "parameters": {}}}],
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "alo em"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "update_customer", "arguments": "{\"name\": \"Anh Nam\"}"}}]},
            {"role": "tool", "tool_call_id": "c1", "name": "update_customer", "content": "{}"},
            {"role": "assistant", "content": "Dạ chào anh Nam, em là Luna ạ"},
            {"role": "user", "content": "giá sao em"},
            {"role": "assistant", "content": "Dạ em kiểm tra giúp anh ạ. Cảm ơn anh đã quan tâm Noble"},
        ],
    }


def test_enumerate_counts_and_flags():
    samples = enumerate_turns(_record())
    assert len(samples) == 3
    assert all(isinstance(s, TurnSample) for s in samples)
    assert samples[0].is_first_assistant is True
    assert samples[0].is_final_assistant is False
    assert samples[-1].is_final_assistant is True


def test_turn_and_step_indices():
    samples = enumerate_turns(_record())
    # turn 0: two assistant steps (tool-call step, then answer step)
    assert (samples[0].turn_idx, samples[0].step_idx_in_turn) == (0, 0)
    assert (samples[1].turn_idx, samples[1].step_idx_in_turn) == (0, 1)
    # turn 1: one assistant step
    assert (samples[2].turn_idx, samples[2].step_idx_in_turn) == (1, 0)


def test_prefix_and_user_message():
    samples = enumerate_turns(_record())
    assert samples[0].user_message == "alo em"
    assert len(samples[0].prefix) == 2          # system + user
    assert samples[1].prefix[-1]["role"] == "tool"
    assert samples[2].user_message == "giá sao em"
    assert samples[0].tools == _record()["tools"]


def test_reference_response_is_the_assistant_message():
    samples = enumerate_turns(_record())
    assert samples[0].reference_response["tool_calls"][0]["function"]["name"] == "update_customer"
    assert "Luna" in samples[1].reference_response["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.data'`

- [ ] **Step 3: Write minimal implementation**

`src/eval/data.py`:
```python
"""Load the reference JSONL and enumerate per-assistant-turn samples for teacher forcing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TurnSample:
    conversation_id: str
    turn_idx: int
    step_idx_in_turn: int
    is_first_assistant: bool
    is_final_assistant: bool
    user_message: str
    prefix: list[dict]
    reference_response: dict
    tools: list[dict]

    def dedup_key(self) -> tuple[str, int, int]:
        return (self.conversation_id, self.turn_idx, self.step_idx_in_turn)


def load_eval_file(path: str | Path) -> list[dict]:
    """Read a JSONL file into a list of conversation records."""
    records: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def enumerate_turns(record: dict) -> list[TurnSample]:
    """One TurnSample per assistant message; prefix = messages before it."""
    messages: list[dict] = record.get("messages") or []
    tools: list[dict] = record.get("tools") or []
    cid: str = record.get("conversation_id", "")

    asst_indices = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    if not asst_indices:
        return []
    first_i, last_i = asst_indices[0], asst_indices[-1]

    samples: list[TurnSample] = []
    turn_idx = -1
    step = 0
    last_user = ""
    for i, m in enumerate(messages):
        role = m.get("role")
        if role == "user":
            turn_idx += 1
            step = 0
            last_user = m.get("content") or ""
        elif role == "assistant":
            samples.append(
                TurnSample(
                    conversation_id=cid,
                    turn_idx=max(turn_idx, 0),
                    step_idx_in_turn=step,
                    is_first_assistant=(i == first_i),
                    is_final_assistant=(i == last_i),
                    user_message=last_user,
                    prefix=messages[:i],
                    reference_response=m,
                    tools=tools,
                )
            )
            step += 1
    return samples
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_data.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/eval/data.py tests/unit/eval/test_data.py
git commit -m "feat(eval): turn enumeration for teacher forcing"
```

---

## Task 3: Tool-call metrics (`tool_metrics.py`)

**Files:**
- Create: `src/eval/tool_metrics.py`
- Test: `tests/unit/eval/test_tool_metrics.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/eval/test_tool_metrics.py`:
```python
from eval.tool_metrics import aggregate_fc, extract_tool_calls, score_turn_fc, value_similarity

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_project_financial",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_code": {"type": "string"},
                    "info_type": {"type": "string", "enum": ["pricing", "fees"]},
                },
                "required": ["project_code", "info_type"],
            },
        },
    },
    {"type": "function", "function": {"name": "update_customer", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}}}},
]


def _asst(*calls):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": a}}
        for i, (n, a) in enumerate(calls)
    ]}


def test_extract_parses_arguments_json():
    msg = _asst(("update_customer", '{"name": "Nam"}'))
    calls = extract_tool_calls(msg)
    assert calls == [{"name": "update_customer", "args": {"name": "Nam"}}]


def test_value_similarity_bounds():
    assert value_similarity("NCTH", "NCTH") == 1.0
    assert value_similarity("NCTH", "SSLC") < 0.7


def test_exact_match_no_errors():
    pred = _asst(("get_project_financial", '{"project_code": "NCTH", "info_type": "pricing"}'))
    exp = _asst(("get_project_financial", '{"project_code": "NCTH", "info_type": "pricing"}'))
    out = score_turn_fc(pred, exp, tools=TOOLS, threshold=0.7)
    assert out["has_tool_calls"] is True
    assert out["pairs"][0]["errors"] == []


def test_missing_function_call():
    pred = {"role": "assistant", "content": "Dạ", "tool_calls": []}
    exp = _asst(("update_customer", '{"name": "Nam"}'))
    out = score_turn_fc(pred, exp, tools=TOOLS, threshold=0.7)
    assert out["pairs"][0]["errors"] == ["missing_function_call"]


def test_unwanted_function_call():
    pred = _asst(("update_customer", '{"name": "Nam"}'))
    exp = {"role": "assistant", "content": "Dạ", "tool_calls": []}
    out = score_turn_fc(pred, exp, tools=TOOLS, threshold=0.7)
    assert out["pairs"][0]["errors"] == ["unwanted_function_call"]


def test_incorrect_format_undeclared_key_and_bad_enum():
    pred = _asst(("get_project_financial", '{"project_code": "NCTH", "info_type": "weather"}'))
    exp = _asst(("get_project_financial", '{"project_code": "NCTH", "info_type": "pricing"}'))
    out = score_turn_fc(pred, exp, tools=TOOLS, threshold=0.7)
    assert "incorrect_function_format" in out["pairs"][0]["errors"]


def test_missing_argument():
    pred = _asst(("get_project_financial", '{"project_code": "NCTH"}'))
    exp = _asst(("get_project_financial", '{"project_code": "NCTH", "info_type": "pricing"}'))
    out = score_turn_fc(pred, exp, tools=TOOLS, threshold=0.7)
    assert "missing_argument" in out["pairs"][0]["errors"]


def test_wrong_argument_value():
    pred = _asst(("get_project_financial", '{"project_code": "SSLC", "info_type": "pricing"}'))
    exp = _asst(("get_project_financial", '{"project_code": "NCTH", "info_type": "pricing"}'))
    out = score_turn_fc(pred, exp, tools=TOOLS, threshold=0.7)
    assert "wrong_argument_value" in out["pairs"][0]["errors"]


def test_aggregate_rates():
    rows = [
        {"fc": {"has_tool_calls": True, "pairs": [{"predicted": {"name": "x"}, "expected": None, "errors": ["unwanted_function_call"]}]}},
        {"fc": {"has_tool_calls": True, "pairs": [{"predicted": None, "expected": {"name": "y"}, "errors": ["missing_function_call"]}]}},
    ]
    agg = aggregate_fc(rows)
    assert agg["n_turns_with_tool_calls"] == 2
    assert agg["n_total_pairs"] == 2
    assert agg["unwanted_function_call_rate"] == 0.5
    assert agg["missing_function_call_rate"] == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_tool_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.tool_metrics'`

- [ ] **Step 3: Write minimal implementation**

`src/eval/tool_metrics.py`:
```python
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
    """Greedy match by tool name; leftovers paired with None."""
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


def classify_pair(
    predicted: dict | None, expected: dict | None, *, schema_index: dict, threshold: float
) -> list[str]:
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

    required = set(schema.get("required") or list(e_args.keys()))
    if any(k in e_args and k not in p_args for k in required):
        errors.append("missing_argument")

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
        pairs_out.append({"predicted": p, "expected": e, "errors": classify_pair(p, e, schema_index=schema_index, threshold=threshold)})
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_tool_metrics.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add src/eval/tool_metrics.py tests/unit/eval/test_tool_metrics.py
git commit -m "feat(eval): dependency-free tool-call metrics"
```

---

## Task 4: Response rules (`response_rules.py`)

**Files:**
- Create: `src/eval/response_rules.py`
- Test: `tests/unit/eval/test_response_rules.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/eval/test_response_rules.py`:
```python
from eval.data import TurnSample
from eval.response_rules import aggregate_rules, extract_customer_name, score_turn_rules


def _sample(*, first=False, final=False, prefix=None):
    return TurnSample(
        conversation_id="c", turn_idx=0, step_idx_in_turn=0,
        is_first_assistant=first, is_final_assistant=final,
        user_message="alo", prefix=prefix or [], reference_response={}, tools=[],
    )


def test_opening_compliance_pass_and_fail():
    s = _sample(first=True)
    assert score_turn_rules(s, {"content": "Dạ chào anh, em là Luna ạ"})["opening_compliance"] == 1
    assert score_turn_rules(s, {"content": "Chào anh"})["opening_compliance"] == 0


def test_opening_is_none_when_not_first():
    s = _sample(first=False)
    assert score_turn_rules(s, {"content": "Dạ em là Luna"})["opening_compliance"] is None


def test_closing_compliance():
    s = _sample(final=True)
    assert score_turn_rules(s, {"content": "Cảm ơn anh đã quan tâm Noble ạ"})["closing_compliance"] == 1
    assert score_turn_rules(s, {"content": "Dạ vâng ạ"})["closing_compliance"] == 0


def test_forbidden_words():
    s = _sample()
    assert score_turn_rules(s, {"content": "Dạ vâng ạ"})["forbidden_words"] == 1
    assert score_turn_rules(s, {"content": "Anh chờ chút nhé"})["forbidden_words"] == 0


def test_conciseness_2_to_3_sentences():
    s = _sample()
    assert score_turn_rules(s, {"content": "Câu một. Câu hai."})["conciseness_clarity"] == 1
    assert score_turn_rules(s, {"content": "Một. Hai. Ba. Bốn."})["conciseness_clarity"] == 0


def test_politeness_markers():
    s = _sample()
    assert score_turn_rules(s, {"content": "Dạ được ạ"})["politeness_markers"] == 1
    assert score_turn_rules(s, {"content": "Ok xong"})["politeness_markers"] == 0


def test_tool_only_turn_skips_text_axes():
    s = _sample()
    out = score_turn_rules(s, {"content": ""})
    assert out["forbidden_words"] is None
    assert out["conciseness_clarity"] is None
    assert out["politeness_markers"] is None


def test_extract_customer_name_and_name_usage():
    prefix = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "update_customer", "arguments": '{"name": "Nam"}'}}]},
    ]
    assert extract_customer_name(prefix) == "Nam"
    s = _sample(prefix=prefix)
    assert score_turn_rules(s, {"content": "Dạ cảm ơn anh Nam ạ"})["name_usage"] == 1
    assert score_turn_rules(s, {"content": "Dạ cảm ơn anh ạ"})["name_usage"] == 0


def test_aggregate_rules_pass_rate():
    rows = [
        {"rule": {"forbidden_words": 1, "politeness_markers": 1, "opening_compliance": None}},
        {"rule": {"forbidden_words": 0, "politeness_markers": 1, "opening_compliance": 1}},
    ]
    agg = aggregate_rules(rows)
    assert agg["forbidden_words"]["pass_rate"] == 0.5
    assert agg["forbidden_words"]["n_evaluated"] == 2
    assert agg["opening_compliance"]["n_evaluated"] == 1
    assert 0.0 <= agg["aggregate"] <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_response_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.response_rules'`

- [ ] **Step 3: Write minimal implementation**

`src/eval/response_rules.py`:
```python
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
_POLITE = ("dạ", "vâng", "vui lòng", "cảm ơn", " ạ")
_INTRO = ("luna", "tư vấn", "noble")


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"[.!?…]+", text) if s.strip()]


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
    concise = int(2 <= len(_sentences(content)) <= 3) if has_text else None
    polite = int(any(m in low for m in _POLITE)) if has_text else None

    name = None
    cust = extract_customer_name(sample.prefix)
    if cust and has_text:
        name = int(cust.lower() in low)

    return {
        "opening_compliance": opening,
        "closing_compliance": closing,
        "forbidden_words": forbidden,
        "conciseness_clarity": concise,
        "politeness_markers": polite,
        "name_usage": name,
    }


def aggregate_rules(rows: list[dict]) -> dict:
    """Per-axis pass_rate + n_evaluated (None values excluded), plus mean aggregate."""
    out: dict = {}
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_response_rules.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add src/eval/response_rules.py tests/unit/eval/test_response_rules.py
git commit -m "feat(eval): Luna response rule axes"
```

---

## Task 5: Teacher-forcing predictor (`predict.py`)

**Files:**
- Create: `src/eval/predict.py`
- Test: `tests/unit/eval/test_predict.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/eval/test_predict.py`:
```python
from eval.data import TurnSample
from eval.predict import predict_turn


class _FakeClient:
    def __init__(self, content, tool_calls):
        self._content = content
        self._tool_calls = tool_calls
        self.calls = []

    async def stream_completion(self, *, messages, tools, model, temperature, max_tokens, on_token, primary=None):
        self.calls.append({"messages": messages, "tools": tools, "primary": primary})
        await on_token("ignored")
        return self._content, self._tool_calls


def _sample():
    return TurnSample(
        conversation_id="c", turn_idx=0, step_idx_in_turn=0,
        is_first_assistant=True, is_final_assistant=False, user_message="alo",
        prefix=[{"role": "system", "content": "s"}, {"role": "user", "content": "alo"}],
        reference_response={}, tools=[{"type": "function", "function": {"name": "x"}}],
    )


async def test_predict_turn_shapes_response():
    client = _FakeClient("Dạ chào anh", [{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}])
    out = await predict_turn(client, _sample(), model="m", primary="anthropic", temperature=0.2, max_tokens=1024)
    assert out["role"] == "assistant"
    assert out["content"] == "Dạ chào anh"
    assert out["tool_calls"][0]["function"]["name"] == "x"
    assert client.calls[0]["primary"] == "anthropic"
    assert client.calls[0]["tools"] == _sample().tools


async def test_predict_turn_handles_none_tool_calls():
    client = _FakeClient("Dạ vâng ạ", None)
    out = await predict_turn(client, _sample(), model="m", primary=None, temperature=0.2, max_tokens=1024)
    assert out["tool_calls"] == []
    assert out["content"] == "Dạ vâng ạ"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_predict.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.predict'`

- [ ] **Step 3: Write minimal implementation**

`src/eval/predict.py`:
```python
"""Teacher-forcing prediction: one LLM completion per turn using the agent's provider chain."""

from __future__ import annotations

from eval.data import TurnSample


async def _noop(_token: str) -> None:
    return None


def build_predictor():
    """Build (StreamingClient, model_map, primary_provider) from the agent's .env config.

    Returns the same provider chain the live agent uses, so predictions reflect
    the production model (NOBLE_AGENT_MODEL primary, openai/gemini fallback).
    """
    from noble_agent.agent.facade import build_llm_providers
    from noble_agent.agent.llm.client import StreamingClient
    from noble_agent.config import get_settings, primary_for, provider_model_map

    settings = get_settings()
    client = StreamingClient(build_llm_providers())
    model = provider_model_map(settings)
    primary = primary_for(settings, settings.agent_model)
    return client, model, primary


async def predict_turn(client, sample: TurnSample, *, model, primary, temperature: float, max_tokens: int) -> dict:
    """One non-iterating completion. Returns an OpenAI-shaped assistant message."""
    content, tool_calls = await client.stream_completion(
        messages=sample.prefix,
        tools=sample.tools,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        on_token=_noop,
        primary=primary,
    )
    return {"role": "assistant", "content": content or "", "tool_calls": tool_calls or []}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_predict.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/eval/predict.py tests/unit/eval/test_predict.py
git commit -m "feat(eval): teacher-forcing predictor"
```

---

## Task 6: LLM judge (`response_llm.py`) + rubric prompt

**Files:**
- Create: `src/eval/prompts/critic_multiturn_luna.txt`
- Create: `src/eval/response_llm.py`
- Test: `tests/unit/eval/test_response_llm.py`

- [ ] **Step 1: Create the rubric prompt file**

`src/eval/prompts/critic_multiturn_luna.txt`:
```text
Bạn là expert reviewer cho MỘT lượt (turn) của Luna — chuyên viên hotline BĐS Noble.
Cho một prefix (lịch sử + câu user) và 2 response (reference + predicted), chấm
predicted response theo rubric. Chấm ĐỘC LẬP — KHÔNG mặc định điểm cao chỉ vì
predicted "trông giống" reference.

=== RUBRIC (mỗi tiêu chí thang 1-5) ===
{criteria_list}

=== FACTUAL AXIS (boolean, blocking) ===
{factual_axis}

=== HƯỚNG DẪN ===
1. Đọc HISTORY để hiểu ngữ cảnh.
2. Đọc USER_MESSAGE: xác định ý định.
3. So predicted với reference (reference là gold; predicted có thể paraphrase tự
   nhiên → vẫn 5đ nếu đúng ý/đủ thông tin). Thiếu thông tin / lệch ý / bịa fact → trừ điểm.
4. KHÔNG chấm tool_correctness ở đây (đã đánh giá bằng rule-based riêng).
5. factual_pass = false nếu predicted bịa fact hoặc mâu thuẫn với kết quả tool trong history.

=== HISTORY ===
{history_block}

=== USER_MESSAGE ===
{user_message}

=== REFERENCE_RESPONSE (gold) ===
{reference_response}

=== PREDICTED_RESPONSE (cần chấm) ===
{predicted_response}

=== OUTPUT ===
Chỉ trả JSON, không thêm chữ nào khác:
{{
  "scores": {{ "<criterion_id>": <int 1..5>, ... }},
  "rationale": {{ "<criterion_id>": "<lý do ngắn>", ... }},
  "factual_pass": <true|false>,
  "factual_notes": "<lý do nếu fail, '' nếu pass>"
}}
```

Note the doubled braces `{{ }}` for the literal JSON example so `str.format` doesn't treat them as fields.

- [ ] **Step 2: Write the failing test**

`tests/unit/eval/test_response_llm.py`:
```python
import json

from eval.data import TurnSample
from eval.response_llm import build_prompt, judge_turn, parse_judge_json


def _sample():
    return TurnSample(
        conversation_id="c", turn_idx=1, step_idx_in_turn=0,
        is_first_assistant=False, is_final_assistant=False, user_message="giá NCTH sao em",
        prefix=[{"role": "system", "content": "s"}, {"role": "user", "content": "giá NCTH sao em"}],
        reference_response={"role": "assistant", "content": "Dạ giá khoảng 5 tỷ ạ"}, tools=[],
    )


def test_parse_judge_json_strips_fences():
    raw = "```json\n{\"scores\": {\"clarity\": 4}, \"factual_pass\": true}\n```"
    out = parse_judge_json(raw)
    assert out["scores"]["clarity"] == 4
    assert out["factual_pass"] is True


def test_build_prompt_contains_sections():
    p = build_prompt(_sample(), {"role": "assistant", "content": "Dạ tầm 5 tỷ ạ"})
    assert "USER_MESSAGE" in p and "giá NCTH" in p
    assert "PREDICTED_RESPONSE" in p and "5 tỷ" in p
    assert "{criteria_list}" not in p  # template fully filled


class _FakeMessage:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeMessage(content)]


class _FakeCritic:
    def __init__(self, content):
        self._content = content
        self.chat = type("C", (), {"completions": self})()

    async def create(self, **kwargs):
        self._kwargs = kwargs
        return _FakeResp(self._content)


async def test_judge_turn_aggregates_weighted_scores():
    payload = {"scores": {"clarity": 4, "informativeness": 5, "relevance": 5,
                          "coherence": 4, "empathy": 4, "engagement": 4},
               "rationale": {}, "factual_pass": True, "factual_notes": ""}
    critic = _FakeCritic(json.dumps(payload))
    out = await judge_turn(critic, _sample(), {"role": "assistant", "content": "Dạ tầm 5 tỷ ạ"}, model="m")
    assert out["factual_pass"] is True
    assert 1.0 <= out["aggregate"] <= 5.0
    assert "tool_correctness" not in out["scores"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_response_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.response_llm'`

- [ ] **Step 4: Write minimal implementation**

`src/eval/response_llm.py`:
```python
"""LLM-as-judge for one turn. Critic reuses the .env Anthropic provider by default."""

from __future__ import annotations

import json
import re
from pathlib import Path

from eval.data import TurnSample

_PROMPT_PATH = Path(__file__).parent / "prompts" / "critic_multiturn_luna.txt"

# (id, description, weight). tool_correctness intentionally excluded — covered by rule-based metrics.
CRITERIA = [
    {"id": "clarity", "desc": "Câu trả lời rõ ràng, dễ hiểu", "weight": 1.0},
    {"id": "informativeness", "desc": "Cung cấp đủ thông tin user cần", "weight": 1.5},
    {"id": "relevance", "desc": "Đúng trọng tâm câu hỏi", "weight": 1.5},
    {"id": "coherence", "desc": "Mạch lạc với lịch sử hội thoại", "weight": 1.0},
    {"id": "empathy", "desc": "Thái độ lịch sự, đồng cảm", "weight": 1.0},
    {"id": "engagement", "desc": "Dẫn dắt cuộc gọi tự nhiên", "weight": 1.0},
]
_FACTUAL = {"id": "factual_pass", "desc": "Không bịa fact, không mâu thuẫn kết quả tool trong history"}


def _format_response(msg: dict) -> str:
    content = msg.get("content") or ""
    calls = msg.get("tool_calls") or []
    if not calls:
        return content or "(không có nội dung)"
    names = ", ".join((c.get("function") or {}).get("name", "") for c in calls)
    return f"{content}\n[tool_calls: {names}]"


def _format_history(prefix: list[dict]) -> str:
    lines = []
    for m in prefix:
        role = m.get("role")
        if role == "system":
            continue
        lines.append(f"[{role}] {_format_response(m) if role == 'assistant' else (m.get('content') or '')}")
    return "\n".join(lines) if lines else "(trống)"


def build_prompt(sample: TurnSample, predicted_msg: dict) -> str:
    criteria_list = "\n".join(f"- `{c['id']}`: {c['desc']} (1-5)" for c in CRITERIA)
    factual_axis = f"- `{_FACTUAL['id']}`: {_FACTUAL['desc']}"
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(
        criteria_list=criteria_list,
        factual_axis=factual_axis,
        history_block=_format_history(sample.prefix),
        user_message=sample.user_message,
        reference_response=_format_response(sample.reference_response),
        predicted_response=_format_response(predicted_msg),
    )


def parse_judge_json(raw: str) -> dict:
    """Defensive parse: strip ``` fences, then take the first {...} block."""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


async def judge_turn(critic, sample: TurnSample, predicted_msg: dict, *, model: str) -> dict:
    prompt = build_prompt(sample, predicted_msg)
    resp = await critic.chat.completions.create(
        model=model,
        temperature=0.2,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    payload = parse_judge_json(resp.choices[0].message.content)
    scores = {k: int(v) for k, v in (payload.get("scores") or {}).items() if k != "tool_correctness"}
    weights = {c["id"]: c["weight"] for c in CRITERIA}
    total = sum(scores.get(cid, 0) * w for cid, w in weights.items())
    wsum = sum(w for cid, w in weights.items() if cid in scores)
    return {
        "scores": scores,
        "rationale": payload.get("rationale", {}),
        "factual_pass": bool(payload.get("factual_pass", False)),
        "factual_notes": payload.get("factual_notes", ""),
        "aggregate": (total / wsum) if wsum else 0.0,
    }


def build_critic():
    """Resolve (critic_client, model). EVAL_CRITIC_* wins; else the .env Anthropic provider."""
    from noble_agent.agent.facade import build_llm_providers
    from noble_agent.config import get_settings, provider_model_map

    from eval.config import EvalSettings

    cfg = EvalSettings()
    if cfg.critic_model:
        import openai

        kwargs = {"api_key": cfg.critic_api_key or "EMPTY"}
        if cfg.critic_base_url:
            kwargs["base_url"] = cfg.critic_base_url
        return openai.AsyncOpenAI(**kwargs), cfg.critic_model

    settings = get_settings()
    providers = build_llm_providers()
    for name, prov in providers:
        if name == "anthropic":
            return prov, settings.anthropic_model
    name, prov = providers[0]
    return prov, provider_model_map(settings)[name]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_response_llm.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/eval/prompts/critic_multiturn_luna.txt src/eval/response_llm.py tests/unit/eval/test_response_llm.py
git commit -m "feat(eval): LLM judge + Luna rubric prompt"
```

---

## Task 7: Report aggregation (`report.py`)

**Files:**
- Create: `src/eval/report.py`
- Test: `tests/unit/eval/test_report.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/eval/test_report.py`:
```python
from eval.report import build_report


def _detail(turn_idx, fc, rule=None, llm=None):
    row = {"conversation_id": "c", "turn_idx": turn_idx, "step_idx_in_turn": 0, "fc": fc}
    if rule is not None:
        row["response_rule"] = rule
    if llm is not None:
        row["response_llm"] = llm
    return row


def test_build_report_summary_and_per_turn():
    details = [
        _detail(0, {"has_tool_calls": True, "pairs": [{"predicted": {"name": "x"}, "expected": {"name": "x"}, "errors": []}]},
                rule={"forbidden_words": 1, "politeness_markers": 1}),
        _detail(1, {"has_tool_calls": False, "pairs": []},
                rule={"forbidden_words": 0, "politeness_markers": 1}),
    ]
    report = build_report(details, slug="20260604_x", eval_file="f.jsonl", response_eval_mode="rule", tfidf_threshold=0.7)
    assert report["n_conversations"] == 1
    assert report["summary"]["n_total_turns"] == 2
    assert report["summary"]["fc_metrics"]["n_turns_with_tool_calls"] == 1
    assert report["summary"]["response_rule"]["forbidden_words"]["pass_rate"] == 0.5
    assert set(report["per_turn"].keys()) == {"0", "1"}
    assert report["max_turns"] == 1


def test_build_report_includes_llm_when_present():
    details = [_detail(0, {"has_tool_calls": False, "pairs": []},
                       llm={"aggregate": 4.0, "factual_pass": True, "scores": {"clarity": 4}})]
    report = build_report(details, slug="s", eval_file="f", response_eval_mode="both", tfidf_threshold=0.7)
    assert "response_llm" in report["summary"]
    assert report["summary"]["response_llm"]["factual_pass_rate"] == 1.0
    assert report["summary"]["response_llm"]["aggregate"] == 4.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.report'`

- [ ] **Step 3: Write minimal implementation**

`src/eval/report.py`:
```python
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
    per_turn = {
        str(t): _summary(rows, response_eval_mode) for t, rows in sorted(by_turn.items())
    }
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_report.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/eval/report.py tests/unit/eval/test_report.py
git commit -m "feat(eval): report aggregation"
```

---

## Task 8: CLI wiring (`__main__.py`)

**Files:**
- Create: `src/eval/runner.py`
- Create: `src/eval/__main__.py`
- Test: `tests/unit/eval/test_runner.py`

Split the orchestration into a testable `runner.py` (pure-ish helpers: scoring a row,
reading/writing JSONL, dedup) and a thin `__main__.py` (argparse + asyncio + provider wiring).

- [ ] **Step 1: Write the failing test**

`tests/unit/eval/test_runner.py`:
```python
import json

from eval.runner import existing_keys, score_prediction_row, write_manifest


def test_score_prediction_row_rule_only():
    pred_row = {
        "conversation_id": "c", "turn_idx": 0, "step_idx_in_turn": 0,
        "is_first_assistant": True, "is_final_assistant": False,
        "user_message": "alo", "prefix": [],
        "reference_response": {"role": "assistant", "content": "Dạ chào anh, em là Luna ạ", "tool_calls": []},
        "predicted_response": {"role": "assistant", "content": "Dạ chào anh, em là Luna ạ", "tool_calls": []},
        "tools": [],
    }
    row = score_prediction_row(pred_row, response_eval_mode="rule", tfidf_threshold=0.7, judge=None)
    assert row["fc"]["has_tool_calls"] is False
    assert row["response_rule"]["opening_compliance"] == 1
    assert "response_llm" not in row


def test_existing_keys_reads_dedup_keys(tmp_path):
    p = tmp_path / "predictions.jsonl"
    p.write_text(json.dumps({"conversation_id": "c", "turn_idx": 0, "step_idx_in_turn": 0}) + "\n", encoding="utf-8")
    assert existing_keys(p) == {("c", 0, 0)}


def test_existing_keys_missing_file(tmp_path):
    assert existing_keys(tmp_path / "nope.jsonl") == set()


def test_write_manifest_appends(tmp_path):
    mpath = tmp_path / "eval_manifest.json"
    write_manifest(mpath, {"slug": "a"})
    write_manifest(mpath, {"slug": "b"})
    data = json.loads(mpath.read_text(encoding="utf-8"))
    assert [e["slug"] for e in data] == ["a", "b"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.runner'`

- [ ] **Step 3: Write minimal implementation**

`src/eval/runner.py`:
```python
"""Pure helpers for the run/score phases: dedup, JSONL/manifest IO, per-row scoring."""

from __future__ import annotations

import json
from pathlib import Path

from eval.response_rules import score_turn_rules
from eval.tool_metrics import score_turn_fc


class _PrefixSample:
    """Lightweight TurnSample-shaped view over a prediction row (for response_rules)."""

    def __init__(self, row: dict):
        self.conversation_id = row["conversation_id"]
        self.turn_idx = row["turn_idx"]
        self.step_idx_in_turn = row["step_idx_in_turn"]
        self.is_first_assistant = row.get("is_first_assistant", False)
        self.is_final_assistant = row.get("is_final_assistant", False)
        self.user_message = row.get("user_message", "")
        self.prefix = row.get("prefix", [])
        self.reference_response = row.get("reference_response", {})
        self.tools = row.get("tools", [])


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
    """Compute all enabled metrics for one prediction row. `judge` is a sync callable
    (sample, predicted_msg) -> dict or None; the async caller supplies the wrapper."""
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
        out["response_rule"] = score_turn_rules(_PrefixSample(pred_row), predicted)
    if response_eval_mode in ("llm", "both") and judge is not None:
        out["response_llm"] = judge(_PrefixSample(pred_row), predicted)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_runner.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Write the CLI entrypoint**

`src/eval/__main__.py`:
```python
"""CLI: PYTHONPATH=src python -m eval run|score ...

run   — teacher forcing: write data/eval_results/<slug>/predictions.jsonl
score — metrics: write details.jsonl + report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from eval.config import EvalSettings
from eval.data import enumerate_turns, load_eval_file
from eval.predict import build_predictor, predict_turn
from eval.report import build_report
from eval.runner import existing_keys, score_prediction_row, write_manifest


def _run_dir(cfg: EvalSettings, slug: str) -> Path:
    d = Path(cfg.results_dir) / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _cmd_run(args) -> int:
    cfg = EvalSettings()
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    slug = f"{stamp}_{args.slug}"
    out_dir = _run_dir(cfg, slug)
    pred_path = out_dir / "predictions.jsonl"

    records = load_eval_file(args.eval_file or cfg.eval_file)
    samples = [s for rec in records for s in enumerate_turns(rec)]
    if args.limit:
        samples = samples[: args.limit]

    done = existing_keys(pred_path)
    todo = [s for s in samples if s.dedup_key() not in done]

    client, model, primary = build_predictor()
    sem = asyncio.Semaphore(args.workers or cfg.workers)
    lock = asyncio.Lock()
    counter = {"ok": 0, "fail": 0}

    async def _one(sample) -> None:
        async with sem:
            try:
                predicted = await predict_turn(
                    client, sample, model=model, primary=primary,
                    temperature=args.temperature if args.temperature is not None else cfg.temperature,
                    max_tokens=cfg.max_tokens,
                )
            except Exception as e:  # noqa: BLE001
                counter["fail"] += 1
                print(f"[run] FAIL {sample.dedup_key()}: {e}")
                return
            row = {
                "conversation_id": sample.conversation_id,
                "turn_idx": sample.turn_idx,
                "step_idx_in_turn": sample.step_idx_in_turn,
                "is_first_assistant": sample.is_first_assistant,
                "is_final_assistant": sample.is_final_assistant,
                "user_message": sample.user_message,
                "prefix": sample.prefix,
                "reference_response": sample.reference_response,
                "predicted_response": predicted,
                "tools": sample.tools,
            }
            line = json.dumps(row, ensure_ascii=False) + "\n"
            async with lock:
                with open(pred_path, "a", encoding="utf-8") as f:
                    f.write(line)
                counter["ok"] += 1

    await asyncio.gather(*(_one(s) for s in todo))

    write_manifest(
        out_dir / "eval_manifest.json",
        {
            "started_at": stamp,
            "slug": slug,
            "eval_file": args.eval_file or cfg.eval_file,
            "agent_model": __import__("noble_agent.config", fromlist=["get_settings"]).get_settings().agent_model,
            "primary_provider": primary,
            "n_conv": len(records),
            "n_samples": len(samples),
            "resume_skipped": len(samples) - len(todo),
            "temperature": args.temperature if args.temperature is not None else cfg.temperature,
            "workers": args.workers or cfg.workers,
        },
    )
    print(f"[run] done slug={slug} ok={counter['ok']} fail={counter['fail']} skipped={len(samples) - len(todo)}")
    print(f"[run] → {pred_path}")
    return 0


async def _cmd_score(args) -> int:
    cfg = EvalSettings()
    out_dir = Path(cfg.results_dir) / args.slug
    pred_path = out_dir / "predictions.jsonl"
    if not pred_path.exists():
        print(f"[score] missing {pred_path} — run the `run` phase first")
        return 1

    pred_rows = load_eval_file(pred_path)
    if args.limit:
        pred_rows = pred_rows[: args.limit]

    threshold = args.tfidf_threshold if args.tfidf_threshold is not None else cfg.tfidf_threshold
    mode = args.response_eval

    judge_sync = None
    if mode in ("llm", "both"):
        from eval.response_llm import build_critic, judge_turn

        critic, critic_model = build_critic()
        if args.critic_model:
            critic_model = args.critic_model
        sem = asyncio.Semaphore(args.workers or cfg.workers)

        async def _judge_async(sample, predicted):
            async with sem:
                return await judge_turn(critic, sample, predicted, model=critic_model)

        # Pre-compute judge results concurrently, then attach synchronously.
        # (judge_turn needs the TurnSample-shaped view built inside score_prediction_row,
        #  so we run scoring twice: once for rule/fc, once to fill llm. Simpler: judge here.)
        judge_cache: dict[tuple, dict] = {}

        async def _prime():
            from eval.runner import _PrefixSample

            tasks = []
            keys = []
            for r in pred_rows:
                s = _PrefixSample(r)
                keys.append((r["conversation_id"], r["turn_idx"], r["step_idx_in_turn"]))
                tasks.append(_judge_async(s, r["predicted_response"]))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for k, res in zip(keys, results, strict=True):
                judge_cache[k] = {} if isinstance(res, Exception) else res

        await _prime()

        def judge_sync(sample, predicted):  # noqa: F811
            return judge_cache.get((sample.conversation_id, sample.turn_idx, sample.step_idx_in_turn))

    details = [
        score_prediction_row(r, response_eval_mode=mode, tfidf_threshold=threshold, judge=judge_sync)
        for r in pred_rows
    ]

    details_path = out_dir / "details.jsonl"
    with open(details_path, "w", encoding="utf-8") as f:
        for row in details:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = build_report(
        details, slug=args.slug, eval_file=cfg.eval_file, response_eval_mode=mode, tfidf_threshold=threshold
    )
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[score] slug={args.slug} turns={report['summary']['n_total_turns']} mode={mode}")
    print(f"[score] fc={report['summary']['fc_metrics']}")
    print(f"[score] → {out_dir / 'report.json'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="eval", description="Teacher-forcing eval for synthetic SFT data")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="generate predictions via teacher forcing")
    pr.add_argument("--slug", required=True)
    pr.add_argument("--eval-file", default=None)
    pr.add_argument("--temperature", type=float, default=None)
    pr.add_argument("--workers", type=int, default=None)
    pr.add_argument("--limit", type=int, default=None)

    ps = sub.add_parser("score", help="score predictions")
    ps.add_argument("--slug", required=True)
    ps.add_argument("--response-eval", choices=["rule", "llm", "both"], default="both")
    ps.add_argument("--critic-model", default=None)
    ps.add_argument("--tfidf-threshold", type=float, default=None)
    ps.add_argument("--workers", type=int, default=None)
    ps.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()
    if args.cmd == "run":
        return asyncio.run(_cmd_run(args))
    return asyncio.run(_cmd_score(args))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run the runner test to verify it still passes**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval/test_runner.py -v`
Expected: PASS (4 passed)

- [ ] **Step 7: Verify the CLI parses (no network)**

Run: `PYTHONPATH=src python -m eval --help && PYTHONPATH=src python -m eval score --help`
Expected: usage text for both, exit 0.

- [ ] **Step 8: Commit**

```bash
git add src/eval/runner.py src/eval/__main__.py tests/unit/eval/test_runner.py
git commit -m "feat(eval): run/score CLI orchestration"
```

---

## Task 9: README + full suite + lint + smoke

**Files:**
- Create: `src/eval/README.md`

- [ ] **Step 1: Write the README**

`src/eval/README.md`:
```markdown
# eval — teacher-forcing evaluation for synthetic SFT data

Evaluates the Noble agent (Luna) on `data/synthetic_sft/eval_sft.jsonl` by replaying
each conversation's prefix and asking the agent's own LLM (the `.env` provider chain)
for the next assistant turn — one completion, no tool loop. Mirrors the
`santa-post-training` two-phase eval.

## Run

```bash
# 1) generate predictions (uses NOBLE_AGENT_MODEL primary from .env)
PYTHONPATH=src python -m eval run --slug myrun

# 2) score them (rule-based tool metrics + Luna response axes + LLM judge)
PYTHONPATH=src python -m eval score --slug <YYYYMMDD_HHMMSS>_myrun --response-eval both
```

Outputs land in `data/eval_results/<slug>/`:
`predictions.jsonl`, `details.jsonl`, `eval_manifest.json`, `report.json`.

## Phases

- **run** — `enumerate_turns` → one `StreamingClient.stream_completion` per assistant
  turn. Resume-friendly (dedup by `conversation_id/turn_idx/step_idx_in_turn`).
- **score**
  - Tool-call metrics (always, rule-based): unwanted / missing / incorrect-format /
    wrong-argument-value / missing-argument. Arg similarity via `difflib` (threshold
    `--tfidf-threshold`, default 0.7); schema check is a small hand-rolled validator.
  - Response rules (6 Luna axes): opening / closing / forbidden-words / conciseness /
    politeness / name-usage.
  - LLM judge (`--response-eval llm|both`): per-turn rubric. Critic defaults to the
    `.env` Anthropic provider (`claude-sonnet-4-6`); override with `EVAL_CRITIC_MODEL`
    (+ `EVAL_CRITIC_BASE_URL` / `EVAL_CRITIC_API_KEY`) or `--critic-model`.

## Tests

```bash
PYTHONPATH=src python -m pytest tests/unit/eval -v
```
```

- [ ] **Step 2: Run the full eval test suite**

Run: `PYTHONPATH=src python -m pytest tests/unit/eval -v`
Expected: PASS (all tests across Tasks 1–8 green).

- [ ] **Step 3: Lint**

Run: `ruff check src/eval tests/unit/eval`
Expected: no errors. (If `score_prediction_row`'s `judge` redefinition trips `F811`,
the `# noqa: F811` is already on the inner `def judge_sync`; fix any other findings.)

Run: `ruff format src/eval tests/unit/eval`

- [ ] **Step 4: Smoke test against the real reference file (2 samples, rule-only — no LLM cost)**

This actually calls the agent LLM, so it needs a working provider in `.env`. Keep it tiny.

Run:
```bash
PYTHONPATH=src python -m eval run --slug smoke --limit 2 --workers 1
PYTHONPATH=src python -m eval score --slug $(ls -t data/eval_results | head -1) --response-eval rule
```
Expected: `run` writes 2 predictions; `score` prints an `fc=...` summary and writes
`report.json`. Inspect `data/eval_results/<slug>/report.json` for sane numbers.

If no provider is reachable, skip this step and note it — the unit suite (Step 2) is the
gate; this smoke is best-effort.

- [ ] **Step 5: Commit**

```bash
git add src/eval/README.md
git commit -m "docs(eval): README + smoke instructions"
```

---

## Self-Review notes (for the implementer)

- **Spec coverage:** run phase (Task 5/8), score phase tool metrics (Task 3), response
  rules (Task 4), LLM judge + critic default (Task 6), report shapes (Task 7), CLI +
  manifest + resume (Task 8), README/run commands (Task 9). All spec sections map to a task.
- **No new deps:** only stdlib + `pydantic-settings` + in-repo modules + existing SDK objects.
- **Type consistency:** `score_turn_fc(predicted, expected, *, tools, threshold)` →
  `{has_tool_calls, pairs}`; rows carry it under key `"fc"` everywhere (`aggregate_fc`,
  `score_prediction_row`, `build_report`). `score_turn_rules(sample, predicted_msg)` →
  dict over `AXES`; rows carry it under `"response_rule"`. `judge_turn(critic, sample,
  predicted_msg, *, model)` → `{scores, rationale, factual_pass, factual_notes, aggregate}`;
  rows carry it under `"response_llm"`.
- **Known nuance:** the critic may be the Anthropic provider whose adapter ignores
  `response_format`; the prompt instructs strict JSON and `parse_judge_json` strips
  fences + extracts the first `{...}`, so non-strict JSON still parses.
- **`eval` package name** shadows nothing at runtime (builtin `eval()` is a function);
  chosen per user request. `tests/conftest.py` puts `src/` on the path so imports resolve.
```
