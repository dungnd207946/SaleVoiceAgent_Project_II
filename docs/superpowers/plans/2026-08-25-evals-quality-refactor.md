# Evals Quality Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tách đo chất lượng agent / RAG thành hai suite độc lập với scorer theo 4 nhóm metric (correctness/groundedness/tool-selection/trajectory) + multi-turn, golden schema v2 cho cả hai, và labeller v2 có server.

**Architecture:** Refactor tại chỗ trong `evals/` — scorer kích hoạt theo NỘI DUNG block của case (`expect`→policy, `golden.tools`→tool_selection, `golden.answer`→judge), `axis` thay bằng `tags` chỉ để filter. Hạ tầng judge (cache/budget/retry) tách ra `evals/judge_client.py` dùng chung. RAG thêm golden nhiều chunk + stage generation cô lập. Labeller = stdlib HTTP server ghi thẳng JSONL, validate bằng chính loader.

**Tech Stack:** Python 3.11+ stdlib (không dependency mới), openai SDK (đã có) cho judge, pytest (`asyncio_mode=auto`), ruff (line-length 120).

**Spec:** `docs/superpowers/specs/2026-08-25-evals-quality-refactor-design.md` — đọc spec trước; plan này viện dẫn section spec bằng "§N".

## Global Constraints

- **Branch:** làm trên `feat/share-agent` (branch hiện tại của user). KHÔNG đụng `develop`, không push, không tạo branch mới.
- **Không dependency mới.** Labeller dùng `http.server` stdlib.
- **Scorer/metric/loader phải THUẦN** (no I/O, no env, no `noble_agent` import) — chỉ `quality/runner.py`, `rag/runner.py`, `rag/generate.py`, `rag/golden_gen.py`, `judge_client.py` được chạm network, và chỉ 2 runner được import `noble_agent`.
- **Fail-closed:** metric có gate mà mẫu rỗng → `None` (KHÔNG phải giá trị pass). Đã có sẵn trong `scorecard.evaluate_gates` — đừng đổi module đó.
- **Ruff:** line-length 120, rules `E,F,W,I,UP,B,SIM`. Chạy `make lint` trước mỗi commit.
- **Test:** `python -m pytest tests/unit/evals/ -q` phải xanh ở CUỐI MỖI TASK. Chú ý: ~30 test khác của repo fail sẵn do .env/data (memory `unit-suite-env-dependent-failures`) — chỉ quan tâm `tests/unit/evals/`.
- **Commit mỗi task một lần**, message tiếng Việt kiểu các commit gần đây (`feat(evals): …`), kết thúc bằng `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **Bẫy môi trường:** hook rtk làm hỏng output grep/diff trong Bash — dùng Read tool hoặc `rtk proxy <cmd>` khi cần ground truth.

---

### Task 1: `evals/judge_client.py` — tách hạ tầng judge dùng chung

Tách phần KHÔNG-rubric của `evals/quality/judge.py` hiện tại (SQLite cache, budget cap, cost tracking, `_call_openai`, retry) ra module dùng chung, thêm tham số `json_mode` (generator RAG cần trả prose). Task này CHƯA sửa `judge.py` (Task 6 mới rewrite nó) — chỉ tạo module mới + test; `judge.py` cũ vẫn chạy song song tới Task 6.

**Files:**
- Create: `evals/judge_client.py`
- Test: `tests/unit/evals/test_judge_client.py`

**Interfaces:**
- Produces (Task 6, 11 dùng):
  - `set_cache_path(p: Path | None) -> None`, `cache_get(key: str) -> dict | None`, `cache_put(key: str, value: dict) -> None`, `cache_key(*parts: str) -> str`
  - `set_budget(usd: float | None) -> None`, `reset_cost() -> None`, `get_cost_usd() -> float`, `class BudgetExceeded(RuntimeError)`
  - `async call_llm(model, system, user, *, json_mode=True, max_tokens=800) -> str` (raise `BudgetExceeded`; áp dụng qwen `enable_thinking` workaround)
  - `async call_llm_json(model, system, user, *, max_tokens=800) -> tuple[str, dict | None]` (retry JSON parse như `_call_with_retry` cũ)
  - Hằng env: `JUDGE_MODEL`, `JUDGE_BASE_URL`, `JUDGE_API_KEY`, `JUDGE_TIMEOUT_S`, `JUDGE_RETRY`, `_PRICING`

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/evals/test_judge_client.py
"""judge_client — cache/budget/call thuần, network mock hết."""
import json

import pytest

from evals import judge_client as jc


def test_cache_roundtrip(tmp_path):
    jc.set_cache_path(tmp_path / "c.db")
    key = jc.cache_key("case-1", "output", "model", "rubric-v1")
    assert jc.cache_get(key) is None
    jc.cache_put(key, {"x": 1})
    assert jc.cache_get(key) == {"x": 1}
    jc.set_cache_path(None)  # tắt → get trả None
    assert jc.cache_get(key) is None


def test_cache_key_differs_by_rubric():
    assert jc.cache_key("a", "b", "m", "v1") != jc.cache_key("a", "b", "m", "v2")


async def test_budget_exceeded_raises(monkeypatch):
    jc.reset_cost()
    jc.set_budget(0.0)
    monkeypatch.setattr(jc, "_COST_USD", 1.0)
    with pytest.raises(jc.BudgetExceeded):
        await jc.call_llm("gpt-4o", "s", "u")
    jc.set_budget(None)
    jc.reset_cost()


async def test_call_llm_json_retries_then_none(monkeypatch):
    calls = []

    async def fake_call(model, system, user, *, json_mode=True, max_tokens=800):
        calls.append(1)
        return "not json"

    monkeypatch.setattr(jc, "call_llm", fake_call)
    monkeypatch.setattr(jc.asyncio, "sleep", _no_sleep)
    raw, parsed = await jc.call_llm_json("m", "s", "u")
    assert parsed is None
    assert len(calls) == jc.JUDGE_RETRY + 1


async def test_call_llm_json_parses(monkeypatch):
    async def fake_call(model, system, user, *, json_mode=True, max_tokens=800):
        return json.dumps({"ok": 1})

    monkeypatch.setattr(jc, "call_llm", fake_call)
    raw, parsed = await jc.call_llm_json("m", "s", "u")
    assert parsed == {"ok": 1}


async def _no_sleep(_s):
    return None
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `python -m pytest tests/unit/evals/test_judge_client.py -q`
Expected: FAIL — `ModuleNotFoundError: evals.judge_client`

- [ ] **Step 3: Implement `evals/judge_client.py`**

Copy nguyên các khối sau từ `evals/quality/judge.py` (giữ hành vi, đổi tên public):
- Env config (dòng 27–35): `JUDGE_MODEL/JUDGE_BASE_URL/JUDGE_API_KEY/JUDGE_TEMP/JUDGE_TIMEOUT_S/JUDGE_RETRY` (bỏ `JUDGE_MAX_TOKENS` — thành param).
- SQLite cache (dòng 49–85): public `set_cache_path`, `cache_get`, `cache_put`; thêm `def cache_key(*parts: str) -> str: return hashlib.sha1("|".join(parts).encode()).hexdigest()`.
- Budget/cost (dòng 89–122): `_PRICING`, `BudgetExceeded`, `set_budget`, `reset_cost`, `get_cost_usd`.
- `_call_openai` (dòng 128–160) → đổi thành:

```python
async def call_llm(model: str, system: str, user: str, *, json_mode: bool = True, max_tokens: int = 800) -> str:
    """One-shot OpenAI-compat call. Raise BudgetExceeded khi chạm cap. Patched in tests."""
    global _COST_USD
    if _BUDGET_USD is not None and _COST_USD >= _BUDGET_USD:
        raise BudgetExceeded(f"judge cost ${_COST_USD:.4f} ≥ cap ${_BUDGET_USD:.4f}")
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=JUDGE_BASE_URL, api_key=JUDGE_API_KEY)
    extra: dict = {"extra_body": {"enable_thinking": False}} if model.startswith("qwen") else {}
    if json_mode:
        extra["response_format"] = {"type": "json_object"}
    resp = await asyncio.wait_for(
        client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=JUDGE_TEMP,
            max_completion_tokens=max_tokens,
            **extra,
        ),
        timeout=JUDGE_TIMEOUT_S,
    )
    usage = resp.usage
    if usage and model in _PRICING:
        in_rate, out_rate = _PRICING[model]
        _COST_USD += (usage.prompt_tokens / 1_000_000) * in_rate
        _COST_USD += (usage.completion_tokens / 1_000_000) * out_rate
    return resp.choices[0].message.content or ""
```

- `_call_with_retry` (dòng 163–180) → `call_llm_json` (gọi `call_llm(..., json_mode=True)` — qua module attr để test patch được: gọi `await call_llm(...)` ở module level là đủ, monkeypatch `jc.call_llm` hoạt động vì lookup qua global).

Docstring module: ghi rõ "tách từ quality/judge.py 2026-08-25, hành vi giữ nguyên; quality/judge.py và rag/generate.py là 2 consumer".

- [ ] **Step 4: Chạy test pass + lint**

Run: `python -m pytest tests/unit/evals/test_judge_client.py -q && make lint`
Expected: PASS, lint sạch (lint chỉ được phép báo lỗi ở file có sẵn nếu vốn có — bình thường là 0 finding).

- [ ] **Step 5: Commit**

```bash
git add evals/judge_client.py tests/unit/evals/test_judge_client.py
git commit -m "feat(evals): tách judge_client dùng chung (cache/budget/retry) khỏi quality/judge

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Schema case v2 — `evals/quality/cases.py`

Rewrite theo spec §4: `axis` → `tags`, `golden` per-turn thành `{answer, tools, banned_tools}`, `expect` cấm 3 key tool. Viết lại `tests/unit/evals/quality/test_cases.py` từ đầu (test cũ toàn schema cũ).

**Files:**
- Rewrite: `evals/quality/cases.py`
- Rewrite: `tests/unit/evals/quality/test_cases.py`

**Interfaces:**
- Produces (mọi task sau dùng):

```python
TAGS: frozenset[str]        # {"policy","tool","qa","multiturn","smoke"}
ORIGINS: frozenset[str]     # giữ nguyên {"structured","kb","document","unanswerable","handwritten"}
CHANNELS: frozenset[str]    # {"chat","voice"}
FORBIDDEN_EXPECT_KEYS: frozenset[str]  # {"tool_called","tool_not_called","tool_arg"}

@dataclass(frozen=True)
class GoldenTool:
    name: str
    args: dict          # arg_name -> {"contains": str} | {"equals": <json>}

@dataclass(frozen=True)
class TurnGolden:
    answer: str = ""
    tools: tuple[GoldenTool, ...] = ()
    banned_tools: tuple[str, ...] = ()

@dataclass(frozen=True)
class EvalTurn:
    user: str
    expect: dict                    # đã validate: chỉ key policy
    golden: TurnGolden | None = None

@dataclass(frozen=True)
class EvalCase:
    id: str; origin: str; tenant: str; channel: str; reviewed: bool
    tags: tuple[str, ...]
    turns: tuple[EvalTurn, ...]
    customer: dict | None = None

def parse_case(data: dict, *, source: str = "<dict>") -> EvalCase   # raise ValueError
def load_cases(path: Path) -> list[EvalCase]
def load_case_dir(directory: Path) -> list[EvalCase]                # unique ids
```

- [ ] **Step 1: Viết lại test (fail trước)**

Ghi đè toàn bộ `tests/unit/evals/quality/test_cases.py`:

```python
"""Schema case v2 — validation strict, lỗi phải kể tên file:line/field."""
import json

import pytest

from evals.quality.cases import EvalCase, load_case_dir, load_cases, parse_case


def _base(**over):
    d = {
        "id": "QA-001", "tenant": "t1", "origin": "handwritten", "reviewed": True,
        "tags": ["qa"], "channel": "chat",
        "turns": [{"user": "hỏi gì đó", "golden": {"answer": "trả lời chuẩn"}}],
    }
    d.update(over)
    return d


def test_parse_minimal_ok():
    case = parse_case(_base())
    assert case.tags == ("qa",)
    assert case.turns[0].golden.answer == "trả lời chuẩn"
    assert case.turns[0].expect == {}


def test_unknown_top_key_rejected():
    with pytest.raises(ValueError, match="unknown"):
        parse_case(_base(axis="tool"))  # schema cũ phải bị TỪ CHỐI


def test_unknown_tag_rejected():
    with pytest.raises(ValueError, match="tag"):
        parse_case(_base(tags=["qa", "banana"]))


def test_tool_keys_in_expect_rejected():
    for key in ("tool_called", "tool_not_called", "tool_arg"):
        with pytest.raises(ValueError, match="golden.tools"):
            parse_case(_base(turns=[{"user": "u", "expect": {key: "kb_search"}}]))


def test_policy_expect_keys_ok():
    case = parse_case(_base(turns=[{"user": "u", "expect": {"reply_contains": ["x"], "escalated": True}}]))
    assert case.turns[0].expect["escalated"] is True


def test_golden_tools_matchers():
    turns = [{"user": "u", "golden": {"tools": [
        {"name": "kb_search", "args": {"query": {"contains": "khoáng nóng"}}},
        {"name": "find_project"},
    ], "banned_tools": ["escalate"]}}]
    case = parse_case(_base(turns=turns))
    g = case.turns[0].golden
    assert g.tools[0].args == {"query": {"contains": "khoáng nóng"}}
    assert g.tools[1].args == {}
    assert g.banned_tools == ("escalate",)


def test_bad_matcher_rejected():
    for bad in ({"regex": "x"}, {"contains": "a", "equals": "b"}, {}, "not-a-dict"):
        turns = [{"user": "u", "golden": {"tools": [{"name": "kb_search", "args": {"query": bad}}]}}]
        with pytest.raises(ValueError, match="matcher"):
            parse_case(_base(turns=turns))


def test_contains_matcher_must_be_str():
    turns = [{"user": "u", "golden": {"tools": [{"name": "t", "args": {"a": {"contains": 5}}}]}}]
    with pytest.raises(ValueError, match="contains"):
        parse_case(_base(turns=turns))


def test_unknown_golden_key_rejected():
    with pytest.raises(ValueError, match="unknown golden"):
        parse_case(_base(turns=[{"user": "u", "golden": {"evidence": "schema cũ"}}]))


def test_empty_turns_rejected():
    with pytest.raises(ValueError, match="turns"):
        parse_case(_base(turns=[]))


def test_load_cases_names_file_line(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text(json.dumps(_base()) + "\n" + "{bad json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="x.jsonl:2"):
        load_cases(p)


def test_load_case_dir_duplicate_id(tmp_path):
    (tmp_path / "a.jsonl").write_text(json.dumps(_base()) + "\n", encoding="utf-8")
    (tmp_path / "b.jsonl").write_text(json.dumps(_base()) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_case_dir(tmp_path)
```

- [ ] **Step 2: Chạy, xác nhận fail**

Run: `python -m pytest tests/unit/evals/quality/test_cases.py -q`
Expected: FAIL (import `EvalCase` không có field `tags`, `parse_case` nhận `axis`…).

- [ ] **Step 3: Rewrite `evals/quality/cases.py`**

Ghi đè toàn bộ file:

```python
"""Eval case schema v2 + JSONL loader (spec 2026-08-25 §4).

Scorer kích hoạt theo NỘI DUNG block: `expect` → policy, `golden.tools` →
tool_selection, `golden.answer` → judge. `tags` CHỈ để filter/report — không
scorer nào đọc nó để quyết định chấm gì (đó là lý do axis cũ bị bỏ).

Validation strict — unknown key raise tại load time, lỗi kể tên file:line.
Pure: no agent import, no I/O ngoài đọc JSONL được đưa.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tests.e2e_scenarios.assertions import KNOWN_KEYS

TAGS: frozenset[str] = frozenset({"policy", "tool", "qa", "multiturn", "smoke"})
ORIGINS: frozenset[str] = frozenset({"structured", "kb", "document", "unanswerable", "handwritten"})
CHANNELS: frozenset[str] = frozenset({"chat", "voice"})

# 3 key tool bị đuổi khỏi expect: chúng sống ở golden.tools/banned_tools để
# vocabulary của policy scorer và tool scorer disjoint (hết double-count, hết
# cần axis làm nguồn sự thật). e2e_scenarios giữ vocabulary đầy đủ của nó.
FORBIDDEN_EXPECT_KEYS: frozenset[str] = frozenset({"tool_called", "tool_not_called", "tool_arg"})
EXPECT_KEYS: frozenset[str] = KNOWN_KEYS - FORBIDDEN_EXPECT_KEYS

_CASE_KEYS = {"id", "tenant", "origin", "reviewed", "tags", "channel", "turns", "customer"}
_TURN_KEYS = {"user", "expect", "golden"}
_GOLDEN_KEYS = {"answer", "tools", "banned_tools"}
_TOOL_KEYS = {"name", "args"}
_MATCHER_KEYS = frozenset({"contains", "equals"})


@dataclass(frozen=True)
class GoldenTool:
    name: str
    args: dict  # arg_name -> {"contains": str} | {"equals": <json value>}


@dataclass(frozen=True)
class TurnGolden:
    answer: str = ""
    tools: tuple[GoldenTool, ...] = ()
    banned_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvalTurn:
    user: str
    expect: dict
    golden: TurnGolden | None = None


@dataclass(frozen=True)
class EvalCase:
    id: str
    origin: str
    tenant: str
    channel: str
    reviewed: bool
    tags: tuple[str, ...]
    turns: tuple[EvalTurn, ...]
    customer: dict | None = None


def _req_str(data: dict, key: str, source: str) -> str:
    value = data.get(key)
    if not value or not isinstance(value, str):
        raise ValueError(f"{source}: case needs a non-empty string {key!r}")
    return value


def _parse_matcher(raw, *, source: str, where: str) -> dict:
    if not isinstance(raw, dict) or set(raw) - _MATCHER_KEYS or len(raw) != 1:
        raise ValueError(f"{source}: {where} matcher must be exactly one of {sorted(_MATCHER_KEYS)}, got {raw!r}")
    if "contains" in raw and not isinstance(raw["contains"], str):
        raise ValueError(f"{source}: {where} 'contains' must be a string")
    return dict(raw)


def _parse_golden_tool(raw, *, source: str, index: int, ti: int) -> GoldenTool:
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: turn {index} golden.tools[{ti}] must be a mapping")
    unknown = set(raw) - _TOOL_KEYS
    if unknown:
        raise ValueError(f"{source}: turn {index} golden.tools[{ti}] unknown keys {sorted(unknown)}")
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise ValueError(f"{source}: turn {index} golden.tools[{ti}] needs a non-empty string 'name'")
    args_raw = raw.get("args") or {}
    if not isinstance(args_raw, dict):
        raise ValueError(f"{source}: turn {index} golden.tools[{ti}] 'args' must be a mapping")
    args = {
        arg: _parse_matcher(m, source=source, where=f"turn {index} golden.tools[{ti}].args[{arg!r}]")
        for arg, m in args_raw.items()
    }
    return GoldenTool(name=name, args=args)


def _parse_golden(raw, *, source: str, index: int) -> TurnGolden | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: turn {index} 'golden' must be a mapping")
    unknown = set(raw) - _GOLDEN_KEYS
    if unknown:
        raise ValueError(f"{source}: turn {index} unknown golden keys {sorted(unknown)}")
    tools_raw = raw.get("tools") or []
    if not isinstance(tools_raw, list):
        raise ValueError(f"{source}: turn {index} golden.tools must be a list")
    banned_raw = raw.get("banned_tools") or []
    if not isinstance(banned_raw, list) or not all(isinstance(b, str) and b for b in banned_raw):
        raise ValueError(f"{source}: turn {index} golden.banned_tools must be a list of non-empty strings")
    return TurnGolden(
        answer=str(raw.get("answer", "") or ""),
        tools=tuple(_parse_golden_tool(t, source=source, index=index, ti=i) for i, t in enumerate(tools_raw)),
        banned_tools=tuple(banned_raw),
    )


def _parse_turn(rt, *, source: str, index: int) -> EvalTurn:
    if not isinstance(rt, dict):
        raise ValueError(f"{source}: turn {index} must be a mapping")
    unknown = set(rt) - _TURN_KEYS
    if unknown:
        raise ValueError(f"{source}: turn {index} unknown keys {sorted(unknown)}")
    user = rt.get("user")
    if not user or not isinstance(user, str):
        raise ValueError(f"{source}: turn {index} needs a non-empty string 'user'")
    expect = rt.get("expect") or {}
    if not isinstance(expect, dict):
        raise ValueError(f"{source}: turn {index} 'expect' must be a mapping")
    forbidden = set(expect) & FORBIDDEN_EXPECT_KEYS
    if forbidden:
        raise ValueError(
            f"{source}: turn {index} expect keys {sorted(forbidden)} moved to golden.tools/golden.banned_tools (schema v2)"
        )
    unknown = set(expect) - EXPECT_KEYS
    if unknown:
        raise ValueError(f"{source}: turn {index} unknown expect keys {sorted(unknown)}; allowed: {sorted(EXPECT_KEYS)}")
    return EvalTurn(user=user, expect=expect, golden=_parse_golden(rt.get("golden"), source=source, index=index))


def parse_case(data: dict, *, source: str = "<dict>") -> EvalCase:
    """Validate a parsed-JSON dict into an `EvalCase`. Raises `ValueError`."""
    if not isinstance(data, dict):
        raise ValueError(f"{source}: case must be a mapping, got {type(data).__name__}")
    unknown = set(data) - _CASE_KEYS
    if unknown:
        raise ValueError(f"{source}: unknown case keys {sorted(unknown)} (schema v2 — 'axis' đã thay bằng 'tags')")

    case_id = _req_str(data, "id", source)
    tenant = _req_str(data, "tenant", source)

    origin = data.get("origin")
    if origin not in ORIGINS:
        raise ValueError(f"{source}: unknown origin {origin!r}; allowed: {sorted(ORIGINS)}")

    channel = data.get("channel", "chat") or "chat"
    if channel not in CHANNELS:
        raise ValueError(f"{source}: unknown channel {channel!r}; allowed: {sorted(CHANNELS)}")

    tags_raw = data.get("tags") or []
    if not isinstance(tags_raw, list):
        raise ValueError(f"{source}: 'tags' must be a list")
    bad = [t for t in tags_raw if t not in TAGS]
    if bad:
        raise ValueError(f"{source}: unknown tag(s) {bad}; allowed: {sorted(TAGS)}")

    raw_turns = data.get("turns")
    if not isinstance(raw_turns, list) or not raw_turns:
        raise ValueError(f"{source}: case {case_id!r} needs a non-empty 'turns' list")

    customer = data.get("customer")
    if customer is not None and not isinstance(customer, dict):
        raise ValueError(f"{source}: case {case_id!r} 'customer' must be a mapping")

    return EvalCase(
        id=case_id,
        origin=origin,
        tenant=tenant,
        channel=channel,
        reviewed=bool(data.get("reviewed", False)),
        tags=tuple(tags_raw),
        turns=tuple(_parse_turn(rt, source=source, index=i) for i, rt in enumerate(raw_turns)),
        customer=customer,
    )
```

`load_cases` + `load_case_dir`: copy NGUYÊN VĂN từ file hiện tại (dòng 150–177) — không đổi.

- [ ] **Step 4: Chạy test pass**

Run: `python -m pytest tests/unit/evals/quality/test_cases.py -q`
Expected: PASS. Lưu ý: các test khác (`test_cli`, `test_scorer_*`, `test_shipped_cases`) sẽ ĐỎ từ giờ tới Task 8/13 — chấp nhận, chỉ chạy file test của task hiện hành cho tới Task 8 (nơi cả suite phải xanh lại, trừ phần labeller/data chưa tới).

- [ ] **Step 5: Commit**

```bash
git add evals/quality/cases.py tests/unit/evals/quality/test_cases.py
git commit -m "feat(evals): schema case v2 — tags thay axis, golden {answer,tools,banned_tools}, expect cấm tool_*

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `trace.py` + `runner.py` — `axis` → `tags`

Trace là artifact hạng nhất; case line đổi `"axis": str` → `"tags": [str]`. Trace cũ trong `evals/reports/` không cần đọc lại được (data reset ở Task 13).

**Files:**
- Modify: `evals/quality/trace.py` (dòng 38–52 `TraceCase`, 105–122 serialize, 137–151 deserialize)
- Modify: `evals/quality/runner.py` (dòng 190–198 và 207–214 — hai chỗ dựng `TraceCase`)
- Modify: `tests/unit/evals/quality/test_trace.py`, `tests/unit/evals/quality/test_runner.py` (đổi mọi `axis="..."` thành `tags=(...)`)

**Interfaces:**
- Produces: `TraceCase(case_id, tags: tuple[str, ...], tenant, channel, reviewed, turns, error, pinned_version, temperature)` — mọi field khác giữ nguyên; `TraceTurn`/`TracedToolCall`/`TraceHeader` KHÔNG đổi.

- [ ] **Step 1: Sửa test trước**

Trong `test_trace.py` và `test_runner.py`: thay mọi `axis="policy"` / `axis="tool"` bằng `tags=("policy",)`, và assertion đọc `.axis` thành `.tags`. Đọc 2 file test hiện có rồi sửa từng chỗ (chúng dựng `TraceCase(...)` bằng keyword). Nếu test_runner dựng `EvalCase` schema cũ, cập nhật sang v2 (dùng helper `_base()` như Task 2).

- [ ] **Step 2: Chạy, xác nhận fail**

Run: `python -m pytest tests/unit/evals/quality/test_trace.py tests/unit/evals/quality/test_runner.py -q`
Expected: FAIL — `TraceCase` chưa có field `tags`.

- [ ] **Step 3: Sửa implementation**

- `trace.py`: field `axis: str` → `tags: tuple[str, ...] = ()`; serialize `"tags": list(case.tags)`; deserialize `tags=tuple(data.get("tags") or ())`.
- `runner.py`: hai chỗ `TraceCase(case_id=case.id, axis=case.axis, ...)` → `tags=case.tags`.

- [ ] **Step 4: Chạy test pass**

Run: `python -m pytest tests/unit/evals/quality/test_trace.py tests/unit/evals/quality/test_runner.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add evals/quality/trace.py evals/quality/runner.py tests/unit/evals/quality/test_trace.py tests/unit/evals/quality/test_runner.py
git commit -m "feat(evals): trace v2 — case line mang tags thay axis

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `scorers/tool_selection.py` (thay `tool_traj.py`)

Đọc `golden.tools`/`banned_tools` thay vì `expect.tool_*`. Giữ quy ước từ tool_traj.py: `_rate` (ungated, có default rỗng) vs `_gated_rate` (None khi mẫu rỗng), `checks` pessimistic, invariant findings ≠ ∅ ⇒ pass_rate < 1.

**Files:**
- Create: `evals/quality/scorers/tool_selection.py`
- Delete: `evals/quality/scorers/tool_traj.py`
- Create: `tests/unit/evals/quality/test_scorer_tool_selection.py`
- Delete: `tests/unit/evals/quality/test_scorer_tool_traj.py`

**Interfaces:**
- Consumes: `EvalCase`/`GoldenTool` (Task 2), `TraceCase` (Task 3), `AxisScore`/`Finding` (không đổi).
- Produces: `score_tool_selection(cases: Sequence[EvalCase], traces: Sequence[TraceCase]) -> AxisScore` — `axis="tool_selection"`, metrics: `tool_selection_accuracy` (ungated, empty=1.0), `arg_accuracy` (gated→None), `banned_call_rate` (gated→None), `irrelevant_call_rate` (ungated, empty=0.0), `tool_error_rate` (ungated, empty=0.0). Hằng `_EXEMPT_TOOLS = frozenset({"update_customer"})`.

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/evals/quality/test_scorer_tool_selection.py
"""tool_selection — chấm golden.tools/banned_tools trên trace, thuần."""
from evals.quality.cases import EvalCase, EvalTurn, GoldenTool, TurnGolden
from evals.quality.scorers.tool_selection import score_tool_selection
from evals.quality.trace import TraceCase, TracedToolCall, TraceTurn


def _case(golden: TurnGolden, *, reviewed=True) -> EvalCase:
    return EvalCase(id="C1", origin="handwritten", tenant="t", channel="chat", reviewed=reviewed,
                    tags=("tool",), turns=(EvalTurn(user="u", expect={}, golden=golden),))


def _trace(calls: list[TracedToolCall], *, error=None) -> TraceCase:
    return TraceCase(case_id="C1", tags=("tool",), tenant="t", channel="chat", reviewed=True,
                     turns=(TraceTurn(user="u", reply="r", tool_calls=tuple(calls)),), error=error)


def test_selection_hit_and_contains_arg():
    g = TurnGolden(tools=(GoldenTool("kb_search", {"query": {"contains": "Khoáng Nóng"}}),))
    tr = _trace([TracedToolCall("kb_search", {"query": "alumi có khoáng nóng không"})])
    s = score_tool_selection([_case(g)], [tr])
    assert s.metrics["tool_selection_accuracy"] == 1.0
    assert s.metrics["arg_accuracy"] == 1.0
    assert s.failures == 0


def test_selection_miss_and_missing_tool_fails_args():
    g = TurnGolden(tools=(GoldenTool("kb_search", {"query": {"contains": "x"}}),))
    s = score_tool_selection([_case(g)], [_trace([])])
    assert s.metrics["tool_selection_accuracy"] == 0.0
    assert s.metrics["arg_accuracy"] == 0.0  # tool không gọi ⇒ arg matcher fail luôn
    kinds = {f.kind for f in s.findings}
    assert {"tool_selection", "tool_arg"} <= kinds


def test_equals_matcher():
    g = TurnGolden(tools=(GoldenTool("booking", {"num_guests": {"equals": 2}}),))
    ok = _trace([TracedToolCall("booking", {"num_guests": 2})])
    bad = _trace([TracedToolCall("booking", {"num_guests": 3})])
    assert score_tool_selection([_case(g)], [ok]).metrics["arg_accuracy"] == 1.0
    assert score_tool_selection([_case(g)], [bad]).metrics["arg_accuracy"] == 0.0


def test_any_call_of_name_may_satisfy_args():
    g = TurnGolden(tools=(GoldenTool("kb_search", {"query": {"contains": "pháp lý"}}),))
    tr = _trace([TracedToolCall("kb_search", {"query": "giá bán"}),
                 TracedToolCall("kb_search", {"query": "pháp lý sổ hồng"})])
    assert score_tool_selection([_case(g)], [tr]).metrics["arg_accuracy"] == 1.0


def test_banned_call_rate_gated():
    g = TurnGolden(banned_tools=("escalate",))
    hit = _trace([TracedToolCall("escalate", {})])
    clean = _trace([])
    assert score_tool_selection([_case(g)], [hit]).metrics["banned_call_rate"] == 1.0
    assert score_tool_selection([_case(g)], [clean]).metrics["banned_call_rate"] == 0.0
    # không case nào khai banned → None (fail-closed ở gate), KHÔNG phải 0.0
    g2 = TurnGolden(tools=(GoldenTool("kb_search", {}),))
    tr2 = _trace([TracedToolCall("kb_search", {})])
    assert score_tool_selection([_case(g2)], [tr2]).metrics["banned_call_rate"] is None


def test_irrelevant_call_exempts_update_customer():
    g = TurnGolden(tools=(GoldenTool("kb_search", {}),))
    tr = _trace([TracedToolCall("kb_search", {}), TracedToolCall("update_customer", {"name": "Nam"})])
    s = score_tool_selection([_case(g)], [tr])
    assert s.metrics["irrelevant_call_rate"] == 0.0
    tr2 = _trace([TracedToolCall("kb_search", {}), TracedToolCall("send_media", {})])
    assert score_tool_selection([_case(g)], [tr2]).metrics["irrelevant_call_rate"] == 1.0


def test_tool_error_rate():
    g = TurnGolden(tools=(GoldenTool("kb_search", {}),))
    tr = _trace([TracedToolCall("kb_search", {}, raw_result='{"error": "boom"}')])
    s = score_tool_selection([_case(g)], [tr])
    assert s.metrics["tool_error_rate"] == 1.0  # 1 call, 1 lỗi
    assert any(f.kind == "tool_error" for f in s.findings)


def test_unreviewed_and_no_golden_skipped():
    g = TurnGolden(tools=(GoldenTool("kb_search", {}),))
    s = score_tool_selection([_case(g, reviewed=False)], [_trace([])])
    assert s.checks == 0 and s.metrics["arg_accuracy"] is None


def test_missing_trace_and_case_error_are_findings():
    g = TurnGolden(tools=(GoldenTool("kb_search", {}),))
    s = score_tool_selection([_case(g)], [])
    assert any(f.kind == "missing_trace" for f in s.findings)
    s2 = score_tool_selection([_case(g)], [_trace([], error="Boom: x")])
    assert any(f.kind == "case_error" for f in s2.findings)


def test_findings_imply_pass_rate_below_one():
    g = TurnGolden(tools=(GoldenTool("kb_search", {}),))
    s = score_tool_selection([_case(g)], [_trace([])])
    assert s.findings and s.pass_rate < 1.0
```

- [ ] **Step 2: Chạy, xác nhận fail**

Run: `python -m pytest tests/unit/evals/quality/test_scorer_tool_selection.py -q`
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 3: Implement**

`evals/quality/scorers/tool_selection.py` — tái dùng từ `tool_traj.py`: `_rate`, `_gated_rate`, `_is_error_result` (copy nguyên văn dòng 41–68, kèm docstring của chúng). Logic chính:

```python
AXIS = "tool_selection"
_EXEMPT_TOOLS = frozenset({"update_customer"})  # agent được khuyến khích gọi bất cứ lúc nào — đếm là nhiễu


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _arg_matches(actual, matcher: dict) -> bool:
    if "contains" in matcher:
        return _norm(matcher["contains"]) in _norm(str(actual))
    return actual == matcher["equals"]


def score_tool_selection(cases, traces) -> AxisScore:
    by_id = {t.case_id: t for t in traces}
    findings, checks = [], 0
    sel_total = sel_ok = arg_total = arg_ok = 0
    banned_total = banned_bad = irrel_total = irrel_bad = 0
    calls_total = calls_error = 0

    for case in cases:
        turns_with_golden = [
            (i, t) for i, t in enumerate(case.turns) if t.golden and (t.golden.tools or t.golden.banned_tools)
        ]
        if not case.reviewed or not turns_with_golden:
            continue
        trace = by_id.get(case.id)
        # missing_trace / case_error: checks += 1 + finding, continue (copy khối tool_traj.py dòng 92–99)
        ...
        for i, case_turn in turns_with_golden:
            if i >= len(trace.turns):
                checks += 1
                findings.append(Finding(case.id, i, "missing_turn", "trace has fewer turns than the case"))
                continue
            trace_turn = trace.turns[i]
            names = [tc.name for tc in trace_turn.tool_calls]
            golden = case_turn.golden

            calls_total += len(trace_turn.tool_calls)
            for tc in trace_turn.tool_calls:
                if _is_error_result(tc.raw_result):
                    calls_error += 1
                    checks += 1
                    findings.append(Finding(case.id, i, "tool_error", f"{tc.name} → {tc.raw_result}"))

            if golden.tools:
                wanted = [gt.name for gt in golden.tools]
                sel_total += 1
                checks += 1
                if all(w in names for w in wanted):
                    sel_ok += 1
                else:
                    missing = [w for w in wanted if w not in names]
                    findings.append(Finding(case.id, i, "tool_selection", f"missing {missing}; called={names}"))

                for gt in golden.tools:
                    matching_calls = [tc for tc in trace_turn.tool_calls if tc.name == gt.name]
                    for arg, matcher in gt.args.items():
                        arg_total += 1
                        checks += 1
                        # ANY call của tool đó thoả matcher là đạt (mirror e2e tool_arg cũ)
                        if any(arg in (tc.args or {}) and _arg_matches(tc.args[arg], matcher) for tc in matching_calls):
                            arg_ok += 1
                        else:
                            detail = (f"{gt.name}.{arg} không khớp {matcher!r}; "
                                      f"calls={[tc.args for tc in matching_calls] or 'tool not called'}")
                            findings.append(Finding(case.id, i, "tool_arg", detail))

                # irrelevant: call ngoài (golden.tools ∪ exempt) — banned đếm riêng bên dưới
                allowed = set(wanted) | _EXEMPT_TOOLS
                extras = sorted({n for n in names if n not in allowed and n not in golden.banned_tools})
                irrel_total += 1
                if extras:
                    irrel_bad += 1
                    checks += 1
                    findings.append(Finding(case.id, i, "irrelevant_call", f"called ngoài golden.tools: {extras}"))

            if golden.banned_tools:
                banned_total += 1
                hit = [b for b in golden.banned_tools if b in names]
                if hit:
                    banned_bad += 1
                for b in golden.banned_tools:
                    checks += 1
                    if b in names:
                        findings.append(Finding(case.id, i, "banned_call", f"tool {b!r} must not be called"))

    return AxisScore(
        axis=AXIS, checks=checks, failures=len(findings), findings=tuple(findings),
        metrics={
            "tool_selection_accuracy": _rate(sel_ok, sel_total, empty=1.0),
            "tool_error_rate": _rate(calls_error, calls_total, empty=0.0),
            "irrelevant_call_rate": _rate(irrel_bad, irrel_total, empty=0.0),
            "arg_accuracy": _gated_rate(arg_ok, arg_total),
            "banned_call_rate": _gated_rate(banned_bad, banned_total),
        },
    )
```

(Chỗ `...` = copy nguyên khối missing_trace/case_error của tool_traj.py dòng 92–99, đổi `trace is None` check giữ nguyên.) Docstring module: chép lại lời giải thích checks-pessimistic của tool_traj.py (dòng 12–24) vì invariant giữ nguyên. Xoá `evals/quality/scorers/tool_traj.py` và `tests/unit/evals/quality/test_scorer_tool_traj.py` (`git rm`).

- [ ] **Step 4: Chạy test pass**

Run: `python -m pytest tests/unit/evals/quality/test_scorer_tool_selection.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git rm evals/quality/scorers/tool_traj.py tests/unit/evals/quality/test_scorer_tool_traj.py
git add evals/quality/scorers/tool_selection.py tests/unit/evals/quality/test_scorer_tool_selection.py
git commit -m "feat(evals): scorer tool_selection từ golden.tools — thay tool_traj, thêm banned/irrelevant tách gate

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `scorers/trajectory.py`

Scorer mới, chấm MỌI case reviewed (không cần golden): loop exhaustion (chuyển từ tool_traj cũ sang đây), gọi lặp y hệt, step thừa.

**Files:**
- Create: `evals/quality/scorers/trajectory.py`
- Test: `tests/unit/evals/quality/test_scorer_trajectory.py`

**Interfaces:**
- Produces: `score_trajectory(cases, traces) -> AxisScore` — `axis="trajectory"`, metrics: `loop_exhaustion_rate` (gated→None khi 0 turn), `repeated_call_rate` (ungated, empty=0.0), `steps_overhead` (ungated; None khi không turn nào có golden.tools — không gate nên None ở đây chỉ là "không đo").

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/evals/quality/test_scorer_trajectory.py
from evals.quality.cases import EvalCase, EvalTurn, GoldenTool, TurnGolden
from evals.quality.scorers.trajectory import score_trajectory
from evals.quality.trace import TraceCase, TracedToolCall, TraceTurn


def _case(*turns: EvalTurn, reviewed=True) -> EvalCase:
    return EvalCase(id="C1", origin="handwritten", tenant="t", channel="chat", reviewed=reviewed,
                    tags=("tool",), turns=tuple(turns))


def _turn(golden=None):
    return EvalTurn(user="u", expect={}, golden=golden)


def _trace(*turns: TraceTurn) -> TraceCase:
    return TraceCase(case_id="C1", tags=("tool",), tenant="t", channel="chat", reviewed=True, turns=tuple(turns))


def test_loop_exhaustion_rate():
    s = score_trajectory([_case(_turn())], [_trace(TraceTurn(user="u", reply="r", loop_exhausted=True))])
    assert s.metrics["loop_exhaustion_rate"] == 1.0
    assert any(f.kind == "loop_exhausted" for f in s.findings)


def test_repeated_identical_call_is_dead_end():
    calls = (TracedToolCall("kb_search", {"query": "giá"}), TracedToolCall("kb_search", {"query": "giá"}))
    s = score_trajectory([_case(_turn())], [_trace(TraceTurn(user="u", reply="r", tool_calls=calls))])
    assert s.metrics["repeated_call_rate"] == 1.0
    assert any(f.kind == "repeated_call" for f in s.findings)


def test_different_args_not_repeated():
    calls = (TracedToolCall("kb_search", {"query": "giá"}), TracedToolCall("kb_search", {"query": "pháp lý"}))
    s = score_trajectory([_case(_turn())], [_trace(TraceTurn(user="u", reply="r", tool_calls=calls))])
    assert s.metrics["repeated_call_rate"] == 0.0


def test_steps_overhead_floor_one():
    g = TurnGolden(tools=(GoldenTool("kb_search", {}),))
    one = _trace(TraceTurn(user="u", reply="r", tool_calls=(TracedToolCall("kb_search", {}),)))
    three = _trace(TraceTurn(user="u", reply="r", tool_calls=(
        TracedToolCall("kb_search", {"query": "1"}), TracedToolCall("kb_search", {"query": "2"}),
        TracedToolCall("find_project", {}),)))
    assert score_trajectory([_case(_turn(g))], [one]).metrics["steps_overhead"] == 1.0
    assert score_trajectory([_case(_turn(g))], [three]).metrics["steps_overhead"] == 3.0
    # ít call hơn golden không được "thưởng" dưới 1.0
    zero = _trace(TraceTurn(user="u", reply="r"))
    assert score_trajectory([_case(_turn(g))], [zero]).metrics["steps_overhead"] == 1.0


def test_no_golden_tools_steps_overhead_none():
    s = score_trajectory([_case(_turn())], [_trace(TraceTurn(user="u", reply="r"))])
    assert s.metrics["steps_overhead"] is None


def test_empty_selection_gated_none():
    s = score_trajectory([], [])
    assert s.metrics["loop_exhaustion_rate"] is None


def test_unreviewed_skipped():
    s = score_trajectory([_case(_turn(), reviewed=False)],
                         [_trace(TraceTurn(user="u", reply="r", loop_exhausted=True))])
    assert s.checks == 0 and s.metrics["loop_exhaustion_rate"] is None
```

- [ ] **Step 2: Chạy, xác nhận fail** — `python -m pytest tests/unit/evals/quality/test_scorer_trajectory.py -q` → ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# evals/quality/scorers/trajectory.py
"""Trajectory efficiency — agent có chạy dài dòng / kẹt dead-end không.

Deterministic, không judge, chấm MỌI case reviewed có trace (không cần golden):
- loop_exhaustion_rate: turn chạm MAX_TOOL_ITERATIONS (tín hiệu từ trace, do
  runner nghe warning của noble_agent.runner — xem quality/runner.py).
- repeated_call_rate: turn có ≥2 tool call trùng hệt (name, args) — agent lặp
  cùng một hành động là dấu dead-end loop; args so sánh sau json.dumps(sort_keys).
- steps_overhead: trên turn có golden.tools — số call thực (trừ tool miễn trừ)
  chia số tool golden, floor 1.0 (gọi ít hơn là việc của tool_selection, không
  phải "hiệu quả hơn").
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from evals.quality.cases import EvalCase
from evals.quality.scorers import AxisScore, Finding
from evals.quality.scorers.tool_selection import _EXEMPT_TOOLS, _gated_rate, _rate
from evals.quality.trace import TraceCase

AXIS = "trajectory"


def _call_key(name: str, args: dict) -> str:
    return f"{name}|{json.dumps(args or {}, sort_keys=True, ensure_ascii=False)}"


def score_trajectory(cases: Sequence[EvalCase], traces: Sequence[TraceCase]) -> AxisScore:
    by_id = {t.case_id: t for t in traces}
    findings: list[Finding] = []
    checks = 0
    turns_total = turns_exhausted = turns_repeated = 0
    overheads: list[float] = []

    for case in cases:
        if not case.reviewed:
            continue
        trace = by_id.get(case.id)
        if trace is None or trace.error:
            continue  # run_integrity đã tính crash/thiếu trace — đây là scorer hiệu quả, không phải toàn vẹn
        for i, case_turn in enumerate(case.turns):
            if i >= len(trace.turns):
                continue
            trace_turn = trace.turns[i]
            turns_total += 1

            if trace_turn.loop_exhausted:
                turns_exhausted += 1
                checks += 1
                # keep in sync with src/noble_agent/agent/runner.py:MAX_TOOL_ITERATIONS
                findings.append(Finding(case.id, i, "loop_exhausted", "turn hit MAX_TOOL_ITERATIONS (=7)"))

            keys = [_call_key(tc.name, tc.args) for tc in trace_turn.tool_calls]
            dupes = sorted({k for k in keys if keys.count(k) > 1})
            if dupes:
                turns_repeated += 1
                checks += 1
                findings.append(Finding(case.id, i, "repeated_call", f"gọi lặp y hệt: {dupes}"))

            golden = case_turn.golden
            if golden and golden.tools:
                actual = sum(1 for tc in trace_turn.tool_calls if tc.name not in _EXEMPT_TOOLS)
                overheads.append(max(1.0, actual / len(golden.tools)))

    return AxisScore(
        axis=AXIS,
        checks=checks,
        failures=len(findings),
        findings=tuple(findings),
        metrics={
            "loop_exhaustion_rate": _gated_rate(turns_exhausted, turns_total),
            "repeated_call_rate": _rate(turns_repeated, turns_total, empty=0.0),
            "steps_overhead": (sum(overheads) / len(overheads)) if overheads else None,
        },
    )
```

Lưu ý: import `_rate`/`_gated_rate`/`_EXEMPT_TOOLS` từ `tool_selection` — nếu ruff phàn nàn private import nội package thì vẫn giữ (cùng package scorers, cố ý DRY); nếu muốn sạch, export chúng không gạch dưới trong tool_selection và import tên đó.

- [ ] **Step 4: Chạy test pass** — `python -m pytest tests/unit/evals/quality/test_scorer_trajectory.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add evals/quality/scorers/trajectory.py tests/unit/evals/quality/test_scorer_trajectory.py
git commit -m "feat(evals): scorer trajectory — loop exhaustion + repeated-call dead-end + steps_overhead

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: `scorers/policy.py` — bỏ axis filter

**Files:**
- Modify: `evals/quality/scorers/policy.py` (dòng 28, 50–51)
- Modify: `tests/unit/evals/quality/test_scorer_policy.py`

**Interfaces:**
- Produces: `score_policy(cases, traces) -> AxisScore` — chữ ký và metrics (`policy_violations` gated, `policy_pass_rate`) KHÔNG đổi. Đổi duy nhất: chấm mọi case reviewed có ≥1 turn mang `expect` non-empty, thay vì `case.axis == "policy"`.

- [ ] **Step 1: Sửa test**

Đọc `test_scorer_policy.py` hiện có, cập nhật: (a) mọi chỗ dựng `EvalCase` sang schema v2 (`tags=("policy",)`, không `axis`); (b) mọi `TraceCase(axis=...)` → `tags=(...)`; (c) thêm test mới:

```python
def test_scores_any_case_with_expect_regardless_of_tags():
    case = EvalCase(id="C1", origin="handwritten", tenant="t", channel="chat", reviewed=True,
                    tags=("tool",),  # tag KHÔNG phải policy — vẫn phải chấm vì có expect
                    turns=(EvalTurn(user="u", expect={"reply_contains": ["chào"]}, golden=None),))
    trace = TraceCase(case_id="C1", tags=("tool",), tenant="t", channel="chat", reviewed=True,
                      turns=(TraceTurn(user="u", reply="xin chào anh"),))
    s = score_policy([case], [trace])
    assert s.checks == 1 and s.failures == 0


def test_case_without_expect_not_counted():
    case = EvalCase(id="C1", origin="handwritten", tenant="t", channel="chat", reviewed=True,
                    tags=("qa",), turns=(EvalTurn(user="u", expect={}, golden=None),))
    trace = TraceCase(case_id="C1", tags=("qa",), tenant="t", channel="chat", reviewed=True,
                      turns=(TraceTurn(user="u", reply="r"),))
    s = score_policy([case], [trace])
    assert s.checks == 0 and s.metrics["policy_violations"] is None
```

- [ ] **Step 2: Chạy, xác nhận fail** — `python -m pytest tests/unit/evals/quality/test_scorer_policy.py -q`.

- [ ] **Step 3: Sửa `policy.py`**

Thay filter dòng 50–51:

```python
    for case in cases:
        if not case.reviewed or not any(t.expect for t in case.turns):
            continue
```

Trong vòng turn (dòng 62–70): thêm `if not case_turn.expect: continue` trước khi đếm missing_turn/evaluate — turn không có expect thì không phải assertion nào cả (missing_turn chỉ đáng đếm khi turn đó CÓ expect). Cập nhật docstring module: bỏ đoạn nói về axis (dòng 7–14), thay bằng: "Chấm mọi case reviewed có `expect`. Vocabulary expect ở schema v2 không còn key tool_* (loader từ chối), nên không thể double-count với tool_selection — đó là lý do không cần axis filter nữa."

- [ ] **Step 4: Chạy test pass** — file test policy PASS.

- [ ] **Step 5: Commit**

```bash
git add evals/quality/scorers/policy.py tests/unit/evals/quality/test_scorer_policy.py
git commit -m "feat(evals): policy scorer chấm theo nội dung expect, bỏ axis filter (vocabulary đã disjoint)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: `quality/judge.py` v2 — 3 rubric

Rewrite hoàn toàn: dùng `judge_client`, 3 rubric correctness / groundedness / multiturn (spec §5.2), trả `list[AxisScore]`.

**Files:**
- Rewrite: `evals/quality/judge.py`
- Rewrite: `tests/unit/evals/quality/test_judge.py`

**Interfaces:**
- Consumes: `judge_client` (Task 1), `EvalCase`/`TurnGolden` (Task 2), `TraceCase` (Task 3).
- Produces: `async score_judge(cases, traces, *, model: str = judge_client.JUDGE_MODEL) -> list[AxisScore]` — 3 AxisScore:
  - `axis="correctness"`: metrics `answer_correctness_mean`, `intent_alignment_rate`, `hallucination_rate`, `correctness_coverage`; finding kinds `hallucination`, `judge_ungraded`.
  - `axis="groundedness"`: metrics `grounded_rate`, `groundedness_coverage`; finding kinds `ungrounded`, `judge_ungraded`.
  - `axis="multiturn"`: metrics `context_retention_score`, `consistency_score`, `multiturn_coverage`; finding kinds `multiturn_issue`, `judge_ungraded`.
- Rubric versions: `_RUBRIC_V = {"correctness": "v1", "groundedness": "v1", "multiturn": "v1"}` — đổi khi sửa prompt để invalidate cache.

- [ ] **Step 1: Viết lại test (fail trước)**

Ghi đè `tests/unit/evals/quality/test_judge.py`:

```python
"""Judge 3-rubric — mock judge_client.call_llm_json, không network."""
import json

from evals import judge_client
from evals.quality import judge
from evals.quality.cases import EvalCase, EvalTurn, TurnGolden
from evals.quality.trace import TraceCase, TracedToolCall, TraceTurn


def _case(*turns, reviewed=True):
    return EvalCase(id="C1", origin="handwritten", tenant="t", channel="chat", reviewed=reviewed,
                    tags=("qa",), turns=tuple(turns))


def _qa_turn(answer="đáp án chuẩn"):
    return EvalTurn(user="hỏi", expect={}, golden=TurnGolden(answer=answer))


def _trace(*turns, error=None):
    return TraceCase(case_id="C1", tags=("qa",), tenant="t", channel="chat", reviewed=True,
                     turns=tuple(turns), error=error)


def _kb_turn(reply="trả lời", result='{"chunks": ["giá 2 tỷ"]}'):
    return TraceTurn(user="hỏi", reply=reply,
                     tool_calls=(TracedToolCall("kb_search", {"query": "giá"}, raw_result=result),))


def _patch(monkeypatch, payloads: dict[str, dict]):
    """payloads: map rubric-name → dict judge trả về. Nhận diện rubric qua system prompt."""
    async def fake(model, system, user, *, max_tokens=800):
        for name, payload in payloads.items():
            if judge._SYSTEMS[name] == system:
                return json.dumps(payload), payload
        raise AssertionError(f"unexpected system prompt: {system[:60]}")
    monkeypatch.setattr(judge_client, "call_llm_json", fake)
    judge_client.set_cache_path(None)


async def test_correctness_and_groundedness_graded(monkeypatch):
    _patch(monkeypatch, {
        "correctness": {"correct": 0.8, "intent_aligned": True, "hallucinated": False, "rationale": "ok"},
        "groundedness": {"grounded": True, "unsupported_claims": [], "rationale": "ok"},
    })
    axes = await judge.score_judge([_case(_qa_turn())], [_trace(_kb_turn())])
    by = {a.axis: a for a in axes}
    assert by["correctness"].metrics["answer_correctness_mean"] == 0.8
    assert by["correctness"].metrics["hallucination_rate"] == 0.0
    assert by["correctness"].metrics["intent_alignment_rate"] == 1.0
    assert by["groundedness"].metrics["grounded_rate"] == 1.0
    assert by["multiturn"].metrics["context_retention_score"] is None  # case 1 turn → không chấm multiturn


async def test_hallucination_and_ungrounded_findings(monkeypatch):
    _patch(monkeypatch, {
        "correctness": {"correct": 0.2, "intent_aligned": False, "hallucinated": True, "rationale": "bịa"},
        "groundedness": {"grounded": False, "unsupported_claims": ["sổ hồng trao tay"], "rationale": "x"},
    })
    axes = await judge.score_judge([_case(_qa_turn())], [_trace(_kb_turn())])
    by = {a.axis: a for a in axes}
    assert by["correctness"].metrics["hallucination_rate"] == 1.0
    assert any(f.kind == "hallucination" for f in by["correctness"].findings)
    assert any("sổ hồng" in f.detail for f in by["groundedness"].findings)


async def test_groundedness_skipped_without_tool_calls(monkeypatch):
    _patch(monkeypatch, {
        "correctness": {"correct": 1.0, "intent_aligned": True, "hallucinated": False, "rationale": ""},
    })
    bare = TraceTurn(user="hỏi", reply="trả lời")  # 0 tool call
    axes = await judge.score_judge([_case(_qa_turn())], [_trace(bare)])
    by = {a.axis: a for a in axes}
    assert by["groundedness"].metrics["grounded_rate"] is None
    assert by["groundedness"].metrics["groundedness_coverage"] is None


async def test_multiturn_judged_on_multi_turn_case(monkeypatch):
    _patch(monkeypatch, {
        "correctness": {"correct": 1.0, "intent_aligned": True, "hallucinated": False, "rationale": ""},
        "groundedness": {"grounded": True, "unsupported_claims": [], "rationale": ""},
        "multiturn": {"context_retention": 0.9, "consistency": 1.0, "issues": [], "rationale": ""},
    })
    case = _case(_qa_turn(), _qa_turn())
    trace = _trace(_kb_turn(), _kb_turn())
    axes = await judge.score_judge([case], [trace])
    by = {a.axis: a for a in axes}
    assert by["multiturn"].metrics["context_retention_score"] == 0.9
    assert by["multiturn"].metrics["multiturn_coverage"] == 1.0


async def test_judge_error_drops_coverage_not_score(monkeypatch):
    async def boom(model, system, user, *, max_tokens=800):
        return "", None  # judge parse fail toàn tập
    monkeypatch.setattr(judge_client, "call_llm_json", boom)
    judge_client.set_cache_path(None)
    axes = await judge.score_judge([_case(_qa_turn())], [_trace(_kb_turn())])
    by = {a.axis: a for a in axes}
    assert by["correctness"].metrics["correctness_coverage"] == 0.0
    assert by["correctness"].metrics["answer_correctness_mean"] is None  # thiếu mẫu ≠ điểm 0
    assert any(f.kind == "judge_ungraded" for f in by["correctness"].findings)


async def test_unreviewed_and_no_answer_skipped(monkeypatch):
    _patch(monkeypatch, {})
    no_answer = EvalTurn(user="u", expect={"reply_contains": ["x"]}, golden=None)
    axes = await judge.score_judge([_case(no_answer)], [_trace(_kb_turn())])
    assert all(a.checks == 0 for a in axes)
```

- [ ] **Step 2: Chạy, xác nhận fail** — `python -m pytest tests/unit/evals/quality/test_judge.py -q`.

- [ ] **Step 3: Rewrite `evals/quality/judge.py`**

```python
"""LLM judge — 3 rubric: correctness / groundedness / multiturn (spec §5.2).

Grader duy nhất trong evals/quality gọi network, chạy ở pha SCORE (đọc trace,
không đụng agent), gated --judge. Hạ tầng (cache sqlite, budget, retry) nằm ở
evals/judge_client.py.

Turn ungraded (lỗi/hết budget) trừ vào *_coverage, KHÔNG trừ vào điểm — thiếu
mẫu phải hiện ra là thiếu, không phải là điểm 0.
"""

from __future__ import annotations

import logging

from evals import judge_client
from evals.quality.scorers import AxisScore, Finding

logger = logging.getLogger("evals.quality.judge")

_RUBRIC_V = {"correctness": "v1", "groundedness": "v1", "multiturn": "v1"}

_SYSTEMS = {
    "correctness": (
        "Bạn là giám khảo chấm độ ĐÚNG của câu trả lời tư vấn viên BĐS so với đáp án chuẩn.\n"
        "Chấm khách quan, trả JSON đúng schema, không thêm prose."
    ),
    "groundedness": (
        "Bạn là giám khảo kiểm tra câu trả lời của tư vấn viên có được ĐỠ bởi dữ liệu tool trả về không.\n"
        "Chấm khách quan, trả JSON đúng schema, không thêm prose."
    ),
    "multiturn": (
        "Bạn là giám khảo đánh giá CẢ HỘI THOẠI nhiều lượt giữa khách và tư vấn viên BĐS.\n"
        "Chấm khách quan, trả JSON đúng schema, không thêm prose."
    ),
}


def _user_correctness(user: str, golden_answer: str, reply: str) -> str:
    return (
        f"[KHÁCH HỎI]\n{user}\n\n[ĐÁP ÁN CHUẨN]\n{golden_answer}\n\n[TƯ VẤN VIÊN TRẢ LỜI]\n{reply}\n\n"
        "NHIỆM VỤ:\n"
        '1. "correct" 0..1: mức khớp NỘI DUNG với đáp án chuẩn (khác cách diễn đạt không trừ điểm).\n'
        '2. "intent_aligned": true nếu trả lời đúng trọng tâm câu khách hỏi.\n'
        '3. "hallucinated": true nếu có khẳng định factual mâu thuẫn hoặc vượt ra ngoài đáp án chuẩn.\n'
        '4. "rationale": 1-2 câu tiếng Việt.\n\n'
        'OUTPUT JSON: {"correct": 0.0..1.0, "intent_aligned": true|false, "hallucinated": true|false, "rationale": "..."}'
    )


def _user_groundedness(reply: str, tool_evidence: str) -> str:
    return (
        f"[DỮ LIỆU TOOL TRẢ VỀ]\n{tool_evidence}\n\n[TƯ VẤN VIÊN TRẢ LỜI]\n{reply}\n\n"
        "NHIỆM VỤ:\n"
        '1. "grounded": true nếu MỌI khẳng định factual trong câu trả lời được dữ liệu tool đỡ; '
        "false nếu có chi tiết bịa ngoài dữ liệu.\n"
        '2. "unsupported_claims": list các khẳng định không được đỡ (rỗng nếu grounded).\n'
        '3. "rationale": 1-2 câu tiếng Việt.\n\n'
        'OUTPUT JSON: {"grounded": true|false, "unsupported_claims": ["..."], "rationale": "..."}'
    )


def _user_multiturn(transcript: str, customer: str) -> str:
    return (
        f"[THÔNG TIN KHÁCH BAN ĐẦU]\n{customer or '(trống)'}\n\n[HỘI THOẠI]\n{transcript}\n\n"
        "NHIỆM VỤ:\n"
        '1. "context_retention" 0..1: tư vấn viên có GIỮ và DÙNG thông tin khách đã nói ở các lượt trước không, '
        "có hỏi lại điều đã biết không (hỏi lại = trừ nặng).\n"
        '2. "consistency" 0..1: các lượt có tự mâu thuẫn về fact/cam kết không.\n'
        '3. "issues": list vấn đề cụ thể (rỗng nếu sạch).\n'
        '4. "rationale": 1-2 câu tiếng Việt.\n\n'
        'OUTPUT JSON: {"context_retention": 0.0..1.0, "consistency": 0.0..1.0, "issues": ["..."], "rationale": "..."}'
    )


async def _graded_call(rubric: str, case_id: str, payload: str, model: str) -> dict | None:
    """Gọi judge có cache; None = ungraded (lỗi/parse fail/budget)."""
    key = judge_client.cache_key(rubric, _RUBRIC_V[rubric], case_id, payload, model)
    if hit := judge_client.cache_get(key):
        return hit
    try:
        _raw, parsed = await judge_client.call_llm_json(model, _SYSTEMS[rubric], payload)
    except judge_client.BudgetExceeded:
        return None
    except Exception as e:  # noqa: BLE001 — lỗi transient judge không được sập cả pha score
        logger.warning("judge %s transient error for %s: %s", rubric, case_id, e)
        return None
    if parsed is None:
        return None
    judge_client.cache_put(key, parsed)
    return parsed


def _clamp(x, default=0.0) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return default


def _mean_or_none(xs: list[float]) -> float | None:
    return (sum(xs) / len(xs)) if xs else None
```

Hàm chính:

```python
async def score_judge(cases, traces, *, model: str = judge_client.JUDGE_MODEL) -> list[AxisScore]:
    trace_by_id = {t.case_id: t for t in traces}

    c_total = c_graded = 0
    corrects: list[float] = []
    intents: list[float] = []
    hallus: list[float] = []
    c_findings: list[Finding] = []

    g_total = g_graded = 0
    grounded: list[float] = []
    g_findings: list[Finding] = []

    m_total = m_graded = 0
    retention: list[float] = []
    consistency: list[float] = []
    m_findings: list[Finding] = []

    for case in cases:
        if not case.reviewed:
            continue
        trace = trace_by_id.get(case.id)
        if trace is None or trace.error:
            continue

        for i, (case_turn, trace_turn) in enumerate(zip(case.turns, trace.turns, strict=False)):
            golden = case_turn.golden
            if not golden or not golden.answer:
                continue

            c_total += 1
            v = await _graded_call(
                "correctness", case.id, _user_correctness(trace_turn.user, golden.answer, trace_turn.reply), model
            )
            if v is None:
                c_findings.append(Finding(case.id, i, "judge_ungraded", "correctness: lỗi judge/budget"))
            else:
                c_graded += 1
                corrects.append(_clamp(v.get("correct")))
                intents.append(1.0 if v.get("intent_aligned") else 0.0)
                hallucinated = bool(v.get("hallucinated"))
                hallus.append(1.0 if hallucinated else 0.0)
                if hallucinated:
                    c_findings.append(Finding(case.id, i, "hallucination", str(v.get("rationale", ""))))

            tool_evidence = "\n---\n".join(
                f"[{tc.name}] {tc.raw_result}" for tc in trace_turn.tool_calls if tc.raw_result
            )
            if tool_evidence:
                g_total += 1
                v = await _graded_call(
                    "groundedness", case.id, _user_groundedness(trace_turn.reply, tool_evidence), model
                )
                if v is None:
                    g_findings.append(Finding(case.id, i, "judge_ungraded", "groundedness: lỗi judge/budget"))
                else:
                    g_graded += 1
                    is_grounded = bool(v.get("grounded"))
                    grounded.append(1.0 if is_grounded else 0.0)
                    if not is_grounded:
                        claims = "; ".join(str(c) for c in v.get("unsupported_claims") or [])
                        g_findings.append(Finding(case.id, i, "ungrounded", claims or str(v.get("rationale", ""))))

        if len(case.turns) >= 2 and len(trace.turns) >= 2:
            m_total += 1
            transcript = "\n".join(f"KHÁCH: {t.user}\nTƯ VẤN VIÊN: {t.reply}" for t in trace.turns)
            v = await _graded_call("multiturn", case.id, _user_multiturn(transcript, str(case.customer or "")), model)
            if v is None:
                m_findings.append(Finding(case.id, -1, "judge_ungraded", "multiturn: lỗi judge/budget"))
            else:
                m_graded += 1
                retention.append(_clamp(v.get("context_retention")))
                consistency.append(_clamp(v.get("consistency")))
                for issue in v.get("issues") or []:
                    m_findings.append(Finding(case.id, -1, "multiturn_issue", str(issue)))

    def _cov(graded: int, total: int) -> float | None:
        return None if total <= 0 else graded / total

    return [
        AxisScore(
            axis="correctness", checks=c_graded,
            failures=sum(1 for f in c_findings if f.kind == "hallucination"), findings=tuple(c_findings),
            metrics={
                "answer_correctness_mean": _mean_or_none(corrects),
                "intent_alignment_rate": _mean_or_none(intents),
                "hallucination_rate": _mean_or_none(hallus),
                "correctness_coverage": _cov(c_graded, c_total),
            },
        ),
        AxisScore(
            axis="groundedness", checks=g_graded,
            failures=sum(1 for f in g_findings if f.kind == "ungrounded"), findings=tuple(g_findings),
            metrics={"grounded_rate": _mean_or_none(grounded), "groundedness_coverage": _cov(g_graded, g_total)},
        ),
        AxisScore(
            axis="multiturn", checks=m_graded,
            failures=sum(1 for f in m_findings if f.kind == "multiturn_issue"), findings=tuple(m_findings),
            metrics={
                "context_retention_score": _mean_or_none(retention),
                "consistency_score": _mean_or_none(consistency),
                "multiturn_coverage": _cov(m_graded, m_total),
            },
        ),
    ]
```

- [ ] **Step 4: Chạy test pass** — `python -m pytest tests/unit/evals/quality/test_judge.py tests/unit/evals/test_judge_client.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add evals/quality/judge.py tests/unit/evals/quality/test_judge.py
git commit -m "feat(evals): judge 3 rubric correctness/groundedness/multiturn thay điểm quality gộp

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Wire CLI + thresholds v2 + xoá scorers/rag.py

Nối mọi thứ: `--axis`→`--tag`, axes list mới, judge trả list, xoá scorer rag khỏi quality, thresholds gate mới. Sau task này TOÀN BỘ `tests/unit/evals/quality/` + `test_cli` phải xanh.

**Files:**
- Modify: `evals/__main__.py`
- Modify: `evals/quality/data/thresholds.toml`
- Modify: `evals/quality/latency.py` (chỉ nếu nó đọc `case.axis` — đọc file trước; nếu không đụng axis thì thôi)
- Delete: `evals/quality/scorers/rag.py`, `tests/unit/evals/quality/test_scorer_rag.py`
- Modify: `tests/unit/evals/quality/test_cli.py`, `tests/unit/evals/quality/test_scorer_run_integrity.py`, `tests/unit/evals/quality/test_scorecard.py`, `tests/unit/evals/quality/test_latency.py` (đổi mọi chỗ dựng case/trace sang schema v2)

**Interfaces:**
- Consumes: mọi scorer Task 4–7.
- Produces: CLI `run|list|score` nhận `--tag` (bỏ `--axis`); `_score_and_report` dùng axes `[score_policy, score_tool_selection, score_trajectory, score_run_integrity, score_latency]` + `axes.extend(asyncio.run(score_judge(...)))` khi `--judge`.

- [ ] **Step 1: Sửa test CLI + test phụ cận (fail trước)**

- `test_cli.py`: đọc file hiện có; đổi case fixture sang schema v2, `--axis` → `--tag`; nếu có test khẳng định scorer rag trong axes, xoá.
- `test_scorer_run_integrity.py`, `test_scorecard.py`, `test_latency.py`: chỉ đổi construction sang schema v2 (`tags=`), logic test giữ nguyên.

- [ ] **Step 2: Chạy, xác nhận fail** — `python -m pytest tests/unit/evals/quality/ -q` (đỏ ở CLI/scorer imports).

- [ ] **Step 3: Sửa implementation**

`evals/__main__.py`:
- Import: bỏ `score_rag`, `score_tool_trajectory`; thêm `score_tool_selection`, `score_trajectory`.
- `_parse_args`: mọi `--axis` → `--tag` (help: "Only cases carrying this tag").
- `_select`: `if tag: cases = [c for c in cases if tag in c.tags]`.
- `_load(tenant, ids, tag)` đổi tên tham số tương ứng; `_filter_desc(case=..., tag=...)`.
- `_cmd_list` (dòng 116): in `",".join(case.tags) or "-"` thay `case.axis`.
- `_score_and_report` (dòng 189–203):

```python
    axes = [
        score_policy(cases, traces),
        score_tool_selection(cases, traces),
        score_trajectory(cases, traces),
        score_run_integrity(cases, traces),
        score_latency(cases, traces),
    ]
    if judge:
        from evals.judge_client import set_budget, set_cache_path
        from evals.quality.judge import score_judge

        set_cache_path(_RUNS / ".judge_cache.db")
        set_budget(judge_budget)
        axes.extend(asyncio.run(score_judge(cases, traces)))
```

- Help text `--judge` (dòng 56): "Also run the 3 LLM-judge rubrics (correctness/groundedness/multiturn)".

`thresholds.toml` — ghi đè:

```toml
# Gate loại 1 — ngưỡng TUYỆT ĐỐI. Chốt ngay, không chờ baseline.
# Spec: docs/superpowers/specs/2026-08-25-evals-quality-refactor-design.md §6
#
# Gate loại 2 (answer_correctness_mean, hallucination_rate, grounded_rate,
# context_retention_score, irrelevant_call_rate, repeated_call_rate,
# steps_overhead, p95 latency) CỐ Ý chưa có: chốt SAU baseline run, nếu không
# ngưỡng sẽ bị nới cho vừa kết quả và gate mất giá trị.

[[gates]]
name = "Vi phạm policy (giá riêng, cam kết, bịa SĐT/lịch, escalate sai)"
metric = "policy_violations"
op = "<="
limit = 0.0

[[gates]]
name = "Độ đúng tham số tool (bắt lệch đơn vị giá VNĐ/tỷ)"
metric = "arg_accuracy"
op = ">="
limit = 1.0

[[gates]]
name = "Tool bị cấm mà vẫn gọi (golden.banned_tools)"
metric = "banned_call_rate"
op = "<="
limit = 0.0

[[gates]]
name = "Lượt chạm MAX_TOOL_ITERATIONS (=7)"
metric = "loop_exhaustion_rate"
op = "<="
limit = 0.02

[[gates]]
name = "Case crash khi chạy (agent/infra ném exception)"
metric = "cases_errored"
op = "<="
limit = 0.0

[[gates]]
name = "Case thiếu trace / thiếu lượt (run dở dang)"
metric = "cases_missing_trace"
op = "<="
limit = 0.0
```

`latency.py`: đọc file (22 dòng); nếu tham chiếu `case.axis`/`trace.axis` thì sửa sang không dùng (latency chấm mọi case). Xoá `scorers/rag.py` + test của nó (`git rm`).

- [ ] **Step 4: Chạy cả suite quality pass**

Run: `python -m pytest tests/unit/evals/ -q --ignore=tests/unit/evals/quality/test_shipped_cases.py`
Expected: PASS toàn bộ trừ shipped_cases (data cũ vẫn nằm đó — Task 13 xử lý; nếu shipped_cases đỏ thì chấp nhận tới Task 13, các file khác phải xanh). `make lint` sạch.

- [ ] **Step 5: Commit**

```bash
git rm evals/quality/scorers/rag.py tests/unit/evals/quality/test_scorer_rag.py
git add -A evals/__main__.py evals/quality/data/thresholds.toml evals/quality/latency.py tests/unit/evals/quality/
git commit -m "feat(evals): wire scorer v2 vào CLI (--tag), thresholds v2, gỡ RAG khỏi quality suite

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: RAG golden v2 + metrics v2

**Files:**
- Rewrite: `evals/rag/golden.py`
- Rewrite: `evals/rag/metrics.py`
- Rewrite: `tests/unit/evals/rag/test_golden.py`, `tests/unit/evals/rag/test_metrics.py`

**Interfaces:**
- Produces:

```python
# golden.py
@dataclass(frozen=True)
class GoldenChunk:
    chunk_id: str = ""
    evidence: str = ""     # nguyên văn; ≥1 trong 2 field phải non-empty

@dataclass(frozen=True)
class GoldenCase:
    id: str; tenant: str; query: str
    chunks: tuple[GoldenChunk, ...]      # ≥1
    answer: str = ""                     # bắt buộc cho --judge, optional cho retrieval-only
    project_code: str = ""
    status: str = "draft"

def parse_golden(data: dict, *, source: str) -> GoldenCase       # raise ValueError; key JSONL: golden_chunks
def load_golden(path: Path) -> list[GoldenCase]                  # từ chối dòng không approved (giữ nguyên)
def ranks_of(case: GoldenCase, hits: list[dict]) -> list[int | None]
    # 1 phần tử / golden chunk. Greedy theo rank: mỗi hit chỉ match 1 golden chunk
    # (chunk_id ưu tiên, evidence normalized-substring sau), không double-count.

# metrics.py
def aggregate(per_case: list[list[int | None]], latencies_ms: list[float], *, ks=(1, 3, 5)) -> dict
    # per_case = output ranks_of mỗi case. Trả:
    # recall_at_{k}: mean(any rank<k)            — hit rate
    # context_recall_at_{k}: mean(#(rank<k)/n_golden)
    # context_precision_at_{k}: mean(#(rank<k)/k)   — LOWER BOUND vs golden set
    # mrr: mean(1/(min_rank+1), 0 nếu không hit)
    # retrieval_p50_ms / retrieval_p95_ms
```

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/evals/rag/test_golden.py (ghi đè)
import json

import pytest

from evals.rag.golden import GoldenCase, GoldenChunk, load_golden, parse_golden, ranks_of


def _raw(**over):
    d = {"id": "g1", "tenant": "t", "query": "q?", "status": "approved",
         "golden_chunks": [{"chunk_id": "c1", "evidence": "khoáng nóng tự nhiên"}],
         "answer": "có khoáng nóng"}
    d.update(over)
    return d


def test_parse_ok_multi_chunk():
    case = parse_golden(_raw(golden_chunks=[
        {"chunk_id": "c1", "evidence": "e một"}, {"evidence": "e hai"}, {"chunk_id": "c3"},
    ]), source="x:1")
    assert len(case.chunks) == 3 and case.chunks[2].evidence == ""


def test_chunk_needs_id_or_evidence():
    with pytest.raises(ValueError, match="chunk"):
        parse_golden(_raw(golden_chunks=[{}]), source="x:1")


def test_old_schema_rejected():
    with pytest.raises(ValueError, match="unknown"):
        parse_golden(_raw(evidence="schema cũ"), source="x:1")


def test_empty_chunks_rejected():
    with pytest.raises(ValueError, match="golden_chunks"):
        parse_golden(_raw(golden_chunks=[]), source="x:1")


def test_loader_rejects_draft(tmp_path):
    p = tmp_path / "g.jsonl"
    p.write_text(json.dumps(_raw(status="draft")) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="approved"):
        load_golden(p)


def _case(*chunks):
    return GoldenCase(id="g", tenant="t", query="q", chunks=tuple(chunks))


def test_ranks_of_greedy_no_double_count():
    # 2 golden chunk cùng evidence — 1 hit chỉ được match 1 chunk
    c = _case(GoldenChunk(evidence="cùng câu"), GoldenChunk(evidence="cùng câu"))
    hits = [{"id": "h1", "text": "… cùng câu …"}]
    assert ranks_of(c, hits) == [0, None]


def test_ranks_of_id_beats_evidence():
    c = _case(GoldenChunk(chunk_id="c9", evidence="không xuất hiện"))
    hits = [{"id": "x", "text": "y"}, {"id": "c9", "text": "z"}]
    assert ranks_of(c, hits) == [1]
```

```python
# tests/unit/evals/rag/test_metrics.py (ghi đè)
from evals.rag.metrics import aggregate


def test_single_chunk_case_matches_old_recall():
    out = aggregate([[0], [None], [2]], [10.0, 20.0, 30.0])
    assert out["recall_at_1"] == 1 / 3
    assert out["recall_at_3"] == 2 / 3
    assert out["mrr"] == (1.0 + 0.0 + 1 / 3) / 3


def test_context_recall_and_precision():
    # case 1: 2 golden, cả 2 trong top-3 (rank 0,2); case 2: 2 golden, 1 hit rank 1
    out = aggregate([[0, 2], [1, None]], [1.0, 1.0])
    assert out["context_recall_at_3"] == (2 / 2 + 1 / 2) / 2
    assert out["context_precision_at_3"] == (2 / 3 + 1 / 3) / 2
    assert out["recall_at_3"] == 1.0


def test_empty_input_none():
    out = aggregate([], [])
    assert out["recall_at_1"] is None and out["mrr"] is None
```

- [ ] **Step 2: Chạy, xác nhận fail** — `python -m pytest tests/unit/evals/rag/test_golden.py tests/unit/evals/rag/test_metrics.py -q`.

- [ ] **Step 3: Implement**

`golden.py` (ghi đè):

```python
"""Golden set retrieval v2: nhiều chunk vàng + golden answer (spec §7.1).

`evidence` phải NGUYÊN VĂN từ chunk — matcher normalized substring. `chunk_id`
ưu tiên khi backend trả id. Loader từ chối mọi dòng không 'approved'.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_KEYS = {"id", "tenant", "query", "golden_chunks", "answer", "project_code", "status"}
_CHUNK_KEYS = {"chunk_id", "evidence"}


@dataclass(frozen=True)
class GoldenChunk:
    chunk_id: str = ""
    evidence: str = ""


@dataclass(frozen=True)
class GoldenCase:
    id: str
    tenant: str
    query: str
    chunks: tuple[GoldenChunk, ...]
    answer: str = ""
    project_code: str = ""
    status: str = "draft"


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def parse_golden(data: dict, *, source: str) -> GoldenCase:
    if not isinstance(data, dict):
        raise ValueError(f"{source}: golden case must be a mapping")
    unknown = set(data) - _KEYS
    if unknown:
        raise ValueError(f"{source}: unknown golden keys {sorted(unknown)} (schema v2 — 'evidence' → 'golden_chunks')")
    for key in ("id", "tenant", "query"):
        if not data.get(key) or not isinstance(data[key], str):
            raise ValueError(f"{source}: needs a non-empty string {key!r}")
    raw_chunks = data.get("golden_chunks")
    if not isinstance(raw_chunks, list) or not raw_chunks:
        raise ValueError(f"{source}: needs a non-empty 'golden_chunks' list")
    chunks: list[GoldenChunk] = []
    for i, rc in enumerate(raw_chunks):
        if not isinstance(rc, dict) or set(rc) - _CHUNK_KEYS:
            raise ValueError(f"{source}: golden_chunks[{i}] must be a mapping with keys {sorted(_CHUNK_KEYS)}")
        chunk = GoldenChunk(chunk_id=str(rc.get("chunk_id", "") or ""), evidence=str(rc.get("evidence", "") or ""))
        if not chunk.chunk_id and not chunk.evidence:
            raise ValueError(f"{source}: golden_chunks[{i}] needs chunk_id or evidence")
        chunks.append(chunk)
    return GoldenCase(
        id=data["id"], tenant=data["tenant"], query=data["query"], chunks=tuple(chunks),
        answer=str(data.get("answer", "") or ""),
        project_code=str(data.get("project_code", "") or ""),
        status=str(data.get("status", "draft") or "draft"),
    )


def load_golden(path: Path) -> list[GoldenCase]:
    out: list[GoldenCase] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            case = parse_golden(json.loads(line), source=f"{path.name}:{lineno}")
            if case.status != "approved":
                raise ValueError(
                    f"{path.name}:{lineno}: case {case.id!r} has status {case.status!r} — "
                    "runner chỉ nhận file toàn 'approved' (duyệt bằng labeller trước)"
                )
            out.append(case)
    return out


def ranks_of(case: GoldenCase, hits: list[dict]) -> list[int | None]:
    """Rank của TỪNG golden chunk trong hits. Greedy theo rank — mỗi hit match
    tối đa một golden chunk (chunk_id trước, evidence-substring sau) để
    context_recall không double-count."""
    remaining = list(enumerate(case.chunks))
    ranks: dict[int, int] = {}
    for rank, hit in enumerate(hits):
        hit_id = str(hit.get("id", ""))
        hit_text = _norm(str(hit.get("text", "")))
        for j, (ci, chunk) in enumerate(remaining):
            id_match = chunk.chunk_id and hit_id == chunk.chunk_id
            ev_match = chunk.evidence and _norm(chunk.evidence) in hit_text
            if id_match or ev_match:
                ranks[ci] = rank
                remaining.pop(j)
                break
    return [ranks.get(i) for i in range(len(case.chunks))]
```

`metrics.py` (ghi đè):

```python
"""Aggregate retrieval metrics v2 — thuần, test được không cần Qdrant.

context_precision_at_k là LOWER BOUND: mẫu số là k chứ không phải số chunk
thật-sự-liên-quan trong top-k (golden set không phủ hết chunk liên quan).
Đọc nó như "ít nhất bao nhiêu phần top-k chắc chắn liên quan".
"""

from __future__ import annotations

from evals.common import percentiles_ms


def aggregate(per_case: list[list[int | None]], latencies_ms: list[float], *, ks: tuple[int, ...] = (1, 3, 5)) -> dict:
    n = len(per_case)
    out: dict[str, float | None] = {}
    for k in ks:
        hits_any: list[float] = []
        c_recall: list[float] = []
        c_precision: list[float] = []
        for ranks in per_case:
            found = [r for r in ranks if r is not None and r < k]
            hits_any.append(1.0 if found else 0.0)
            c_recall.append(len(found) / len(ranks))
            c_precision.append(len(found) / k)
        out[f"recall_at_{k}"] = (sum(hits_any) / n) if n else None
        out[f"context_recall_at_{k}"] = (sum(c_recall) / n) if n else None
        out[f"context_precision_at_{k}"] = (sum(c_precision) / n) if n else None
    rrs = []
    for ranks in per_case:
        found = [r for r in ranks if r is not None]
        rrs.append(1.0 / (min(found) + 1) if found else 0.0)
    out["mrr"] = (sum(rrs) / n) if n else None
    pcts = percentiles_ms(latencies_ms)
    out["retrieval_p50_ms"] = pcts.get("p50")
    out["retrieval_p95_ms"] = pcts.get("p95")
    return out
```

- [ ] **Step 4: Chạy test pass** — 2 file test PASS.

- [ ] **Step 5: Commit**

```bash
git add evals/rag/golden.py evals/rag/metrics.py tests/unit/evals/rag/test_golden.py tests/unit/evals/rag/test_metrics.py
git commit -m "feat(evals): RAG golden v2 nhiều chunk + answer; metrics thêm context precision/recall

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: `rag/runner.py` v2 — multi-chunk ranks + giữ retrieved cho generation

**Files:**
- Modify: `evals/rag/runner.py` (hàm `run_rag`, dòng 21–57; 2 hàm search giữ nguyên)
- Modify: `tests/unit/evals/rag/test_runner.py` (fixture sang schema v2)

**Interfaces:**
- Produces: `async run_rag(golden, *, search: SearchFn, top_k=5) -> dict` — trả `{"rows": [...], "metrics": {...}}` như cũ, NHƯNG: mỗi row thêm `"ranks": list[int|None]` (per golden chunk) và `"retrieved": list[str]` (text top-k, để Task 11 generation dùng lại không retrieve lần hai); `rows[i]["hit"]` = any rank not None.

- [ ] **Step 1: Sửa test runner** — fixture `GoldenCase` v2 (`chunks=(GoldenChunk(...),)`), fake `search` trả `[{"id","text"}]`; assert `rows[0]["ranks"]`, `rows[0]["retrieved"]`, `metrics["context_recall_at_5"]` tồn tại. Chạy fail.

- [ ] **Step 2: Sửa `run_rag`**

```python
async def run_rag(golden: list[GoldenCase], *, search: SearchFn, top_k: int = 5) -> dict:
    rows: list[dict] = []
    per_case: list[list[int | None]] = []
    latencies: list[float] = []
    empty = 0
    for case in golden:
        t0 = time.perf_counter()
        error = ""
        try:
            hits = (await search(case.query, case.project_code))[:top_k]
        except Exception as exc:  # noqa: BLE001 — backend chết = case không đo được, không phải harness crash
            hits = []
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - t0) * 1000.0
        ranks = ranks_of(case, hits) if hits else [None] * len(case.chunks)
        if not hits:
            empty += 1
        per_case.append(ranks)
        latencies.append(latency_ms)
        rows.append({
            "id": case.id,
            "ranks": ranks,
            "hit": any(r is not None for r in ranks),
            "latency_ms": latency_ms,
            "n_hits": len(hits),
            "retrieved": [str(h.get("text", "")) for h in hits],
            "error": error,
        })
    metrics = aggregate(per_case, latencies)
    metrics["empty_rate"] = (empty / len(golden)) if golden else None
    if golden and empty / len(golden) > 0.5:
        print(
            f"CẢNH BÁO: {empty}/{len(golden)} case trả rỗng — backend degrade im lặng? "
            "(kiểm tra tunnel/collection/EMBED_BACKEND, xem CLAUDE.md gotchas)"
        )
    return {"rows": rows, "metrics": metrics}
```

Import đổi: `from evals.rag.golden import GoldenCase, ranks_of`.

- [ ] **Step 3: Test pass** — `python -m pytest tests/unit/evals/rag/ -q` (trừ test_golden_gen nếu đỏ — Task 12).

- [ ] **Step 4: Commit**

```bash
git add evals/rag/runner.py tests/unit/evals/rag/test_runner.py
git commit -m "feat(evals): rag runner v2 — rank per golden chunk, giữ retrieved text cho generation stage

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 11: `rag/generate.py` + CLI `evals rag --judge`

Generation stage cô lập (spec §7.3): generator prompt cố định → judge faithfulness + answer correctness + refusal rate.

**Files:**
- Create: `evals/rag/generate.py`
- Modify: `evals/__main__.py` (`_cmd_rag` + parser `rag` thêm `--judge`, `--judge-budget-usd`)
- Create: `tests/unit/evals/rag/test_generate.py`

**Interfaces:**
- Consumes: `judge_client.call_llm` / `call_llm_json` (Task 1), rows từ `run_rag` (Task 10 — cần `retrieved`).
- Produces:

```python
REFUSAL_MARKER = "không tìm thấy thông tin"
GEN_MODEL_ENV = "EVAL_RAG_GEN_MODEL"   # fallback judge_client.JUDGE_MODEL

async def run_generation(golden: list[GoldenCase], rows: list[dict], *, model: str) -> dict
# chỉ chấm case có answer + retrieved non-empty; trả
# {"rows": [{"id", "gen_answer", "faithful", "correctness", "refused", "error"}],
#  "metrics": {"faithfulness_rate", "rag_answer_correctness_mean", "rag_refusal_rate",
#              "generation_coverage"}}   # coverage = graded / eligible
```

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/evals/rag/test_generate.py
"""Generation stage — mock judge_client, không network."""
import json

from evals import judge_client
from evals.rag import generate
from evals.rag.golden import GoldenCase, GoldenChunk


def _case(cid="g1", answer="có khoáng nóng"):
    return GoldenCase(id=cid, tenant="t", query="q", chunks=(GoldenChunk(evidence="e"),), answer=answer)


def _row(cid="g1", retrieved=("chunk text",)):
    return {"id": cid, "ranks": [0], "hit": True, "latency_ms": 1.0, "n_hits": len(retrieved),
            "retrieved": list(retrieved), "error": ""}


def _patch(monkeypatch, *, gen_text="câu trả lời sinh", faithful=True, correctness=0.9):
    async def fake_llm(model, system, user, *, json_mode=True, max_tokens=800):
        assert not json_mode
        return gen_text

    async def fake_json(model, system, user, *, max_tokens=800):
        if "ĐỠ" in system or "đỡ" in system:
            return "", {"faithful": faithful, "unsupported_claims": [], "rationale": ""}
        return "", {"correct": correctness, "rationale": ""}

    monkeypatch.setattr(judge_client, "call_llm", fake_llm)
    monkeypatch.setattr(judge_client, "call_llm_json", fake_json)
    judge_client.set_cache_path(None)


async def test_happy_path(monkeypatch):
    _patch(monkeypatch)
    out = await generate.run_generation([_case()], [_row()], model="m")
    assert out["metrics"]["faithfulness_rate"] == 1.0
    assert out["metrics"]["rag_answer_correctness_mean"] == 0.9
    assert out["metrics"]["rag_refusal_rate"] == 0.0
    assert out["metrics"]["generation_coverage"] == 1.0


async def test_refusal_counted_when_context_had_hit(monkeypatch):
    _patch(monkeypatch, gen_text="Tôi không tìm thấy thông tin này.")
    out = await generate.run_generation([_case()], [_row()], model="m")
    assert out["metrics"]["rag_refusal_rate"] == 1.0


async def test_no_answer_or_empty_retrieved_skipped(monkeypatch):
    _patch(monkeypatch)
    out = await generate.run_generation(
        [_case("g1", answer=""), _case("g2")],
        [_row("g1"), _row("g2", retrieved=())], model="m")
    assert out["metrics"]["generation_coverage"] is None  # 0 case đủ điều kiện
    assert out["metrics"]["faithfulness_rate"] is None


async def test_judge_error_drops_coverage(monkeypatch):
    async def fake_llm(model, system, user, *, json_mode=True, max_tokens=800):
        return "câu trả lời"

    async def bad_json(model, system, user, *, max_tokens=800):
        return "", None

    monkeypatch.setattr(judge_client, "call_llm", fake_llm)
    monkeypatch.setattr(judge_client, "call_llm_json", bad_json)
    judge_client.set_cache_path(None)
    out = await generate.run_generation([_case()], [_row()], model="m")
    assert out["metrics"]["generation_coverage"] == 0.0
    assert out["metrics"]["faithfulness_rate"] is None
```

- [ ] **Step 2: Chạy fail** — module chưa có.

- [ ] **Step 3: Implement `evals/rag/generate.py`**

```python
"""Generation stage cô lập cho RAG eval (spec §7.3) — KHÔNG qua agent.

Generator: prompt cố định "chỉ trả lời từ các đoạn sau"; đo faithfulness
(answer sinh ra vs chunks) + answer correctness (vs golden.answer) bằng judge.
Mọi call qua evals.judge_client (cache/budget dùng chung).

rag_refusal_rate: generator từ chối trong khi retrieval CÓ hit — tín hiệu
generator/prompt kém hoặc chunk đúng nhưng không chứa câu trả lời (golden sai).
"""

from __future__ import annotations

import logging
import os

from evals import judge_client
from evals.rag.golden import GoldenCase

logger = logging.getLogger("evals.rag.generate")

REFUSAL_MARKER = "không tìm thấy thông tin"
GEN_MODEL_ENV = "EVAL_RAG_GEN_MODEL"
_RUBRIC_V = "v1"

_GEN_SYSTEM = (
    "Bạn là trợ lý trả lời câu hỏi CHỈ dựa trên các đoạn văn được cung cấp.\n"
    "Không suy diễn, không dùng kiến thức ngoài. Nếu các đoạn không chứa câu "
    "trả lời, trả lời đúng một câu: 'Tôi không tìm thấy thông tin này.'"
)

_FAITH_SYSTEM = (
    "Bạn là giám khảo kiểm tra câu trả lời có được ĐỠ hoàn toàn bởi các đoạn văn nguồn không.\n"
    "Trả JSON đúng schema, không thêm prose."
)

_CORRECT_SYSTEM = (
    "Bạn là giám khảo chấm độ đúng của câu trả lời so với đáp án chuẩn.\n"
    "Trả JSON đúng schema, không thêm prose."
)


def gen_model() -> str:
    return os.getenv(GEN_MODEL_ENV) or judge_client.JUDGE_MODEL


def _chunks_block(retrieved: list[str]) -> str:
    return "\n---\n".join(f"[ĐOẠN {i + 1}]\n{t}" for i, t in enumerate(retrieved))


async def _generate(query: str, retrieved: list[str], model: str) -> str:
    user = f"{_chunks_block(retrieved)}\n\n[CÂU HỎI]\n{query}"
    return await judge_client.call_llm(model, _GEN_SYSTEM, user, json_mode=False, max_tokens=500)


async def _judge_faithful(case_id: str, answer: str, retrieved: list[str], model: str) -> dict | None:
    user = (
        f"{_chunks_block(retrieved)}\n\n[CÂU TRẢ LỜI CẦN KIỂM]\n{answer}\n\n"
        'OUTPUT JSON: {"faithful": true|false, "unsupported_claims": ["..."], "rationale": "..."}'
    )
    return await _judged(case_id, "faith", _FAITH_SYSTEM, user, model)


async def _judge_correct(case_id: str, answer: str, golden_answer: str, model: str) -> dict | None:
    user = (
        f"[ĐÁP ÁN CHUẨN]\n{golden_answer}\n\n[CÂU TRẢ LỜI CẦN CHẤM]\n{answer}\n\n"
        'OUTPUT JSON: {"correct": 0.0..1.0, "rationale": "..."}'
    )
    return await _judged(case_id, "correct", _CORRECT_SYSTEM, user, model)


async def _judged(case_id: str, rubric: str, system: str, user: str, model: str) -> dict | None:
    key = judge_client.cache_key("rag", rubric, _RUBRIC_V, case_id, user, model)
    if hit := judge_client.cache_get(key):
        return hit
    try:
        _raw, parsed = await judge_client.call_llm_json(model, system, user)
    except judge_client.BudgetExceeded:
        return None
    except Exception as e:  # noqa: BLE001 — lỗi transient không sập cả stage
        logger.warning("rag judge %s error for %s: %s", rubric, case_id, e)
        return None
    if parsed is not None:
        judge_client.cache_put(key, parsed)
    return parsed


async def run_generation(golden: list[GoldenCase], rows: list[dict], *, model: str) -> dict:
    row_by_id = {r["id"]: r for r in rows}
    out_rows: list[dict] = []
    eligible = graded = 0
    faithfuls: list[float] = []
    corrects: list[float] = []
    refusals: list[float] = []
    skipped_no_answer = 0

    for case in golden:
        row = row_by_id.get(case.id)
        if not case.answer:
            skipped_no_answer += 1
            continue
        if not row or not row.get("retrieved"):
            continue
        eligible += 1
        retrieved = list(row["retrieved"])
        try:
            gen_answer = await _generate(case.query, retrieved, model)
        except Exception as e:  # noqa: BLE001
            out_rows.append({"id": case.id, "gen_answer": "", "error": f"{type(e).__name__}: {e}"})
            continue

        refused = REFUSAL_MARKER in gen_answer.lower()
        if refused and row.get("hit"):
            refusals.append(1.0)
        else:
            refusals.append(0.0)

        faith = await _judge_faithful(case.id, gen_answer, retrieved, model)
        correct = await _judge_correct(case.id, gen_answer, case.answer, model)
        if faith is None or correct is None:
            out_rows.append({"id": case.id, "gen_answer": gen_answer, "refused": refused, "error": "judge_ungraded"})
            continue
        graded += 1
        faithfuls.append(1.0 if faith.get("faithful") else 0.0)
        try:
            corrects.append(max(0.0, min(1.0, float(correct.get("correct", 0.0)))))
        except (TypeError, ValueError):
            corrects.append(0.0)
        out_rows.append({
            "id": case.id, "gen_answer": gen_answer, "refused": refused,
            "faithful": bool(faith.get("faithful")), "correctness": corrects[-1], "error": "",
        })

    if skipped_no_answer:
        print(f"generation: bỏ qua {skipped_no_answer} case không có golden answer")
    return {
        "rows": out_rows,
        "metrics": {
            "faithfulness_rate": (sum(faithfuls) / len(faithfuls)) if faithfuls else None,
            "rag_answer_correctness_mean": (sum(corrects) / len(corrects)) if corrects else None,
            "rag_refusal_rate": (sum(refusals) / len(refusals)) if refusals else None,
            "generation_coverage": (graded / eligible) if eligible else None,
        },
    }
```

CLI `_cmd_rag` trong `__main__.py`: parser thêm

```python
    sp.add_argument("--judge", action="store_true", help="Thêm stage generation: faithfulness + answer correctness")
    sp.add_argument("--judge-budget-usd", type=float, default=None)
```

và sau `out = asyncio.run(_drive())`, trước khi ghi `rag.json`:

```python
    if args.judge:
        from evals.judge_client import set_budget, set_cache_path
        from evals.rag.generate import gen_model, run_generation

        set_cache_path(_RUNS / ".judge_cache.db")
        set_budget(args.judge_budget_usd)
        gen = asyncio.run(run_generation(golden, out["rows"], model=gen_model()))
        out["metrics"].update(gen["metrics"])
        out["gen_rows"] = gen["rows"]
        config["gen_model"] = gen_model()
```

In thêm các key mới vào vòng print (thêm `"context_recall_at_5"`, `"faithfulness_rate"`, `"rag_answer_correctness_mean"` vào tuple dòng 364).

- [ ] **Step 4: Test pass** — `python -m pytest tests/unit/evals/rag/test_generate.py -q` PASS; `make lint` sạch.

- [ ] **Step 5: Commit**

```bash
git add evals/rag/generate.py evals/__main__.py tests/unit/evals/rag/test_generate.py
git commit -m "feat(evals): RAG generation stage cô lập — faithfulness + answer correctness + refusal (gated --judge)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 12: `gen-golden` v2 — sinh answer + golden_chunks

**Files:**
- Modify: `evals/rag/golden_gen.py` (`_SYSTEM`, `gen_questions`, giữ `fetch_chunks`/`write_draft`/`draft_path`/`default_model`)
- Modify: `evals/__main__.py` (`_cmd_gen_golden` — shape case mới)
- Modify: `tests/unit/evals/rag/test_golden_gen.py`

**Interfaces:**
- Produces: `gen_questions(chunk, *, model, n=2) -> list[dict]` — mỗi dict `{"query", "evidence", "answer"}` (evidence vẫn phải nguyên văn trong chunk, answer là câu trả lời LLM tổng hợp); `_cmd_gen_golden` ghi case v2: `{"id", "tenant", "query", "golden_chunks": [{"chunk_id", "evidence"}], "answer", "project_code", "status": "draft"}`.

- [ ] **Step 1: Sửa test** — trong `test_golden_gen.py`: mock `_call_llm` trả `{"pairs": [{"query": "q", "evidence": "<câu trong chunk>", "answer": "a"}]}`; assert pair giữ answer, pair evidence-bịa vẫn bị lọc. Chạy fail (answer chưa được giữ).

- [ ] **Step 2: Sửa implementation**

`_SYSTEM` mới:

```python
_SYSTEM = """Bạn tạo bộ kiểm thử retrieval cho trợ lý BĐS tiếng Việt.
Với đoạn văn cho trước, sinh câu hỏi tự nhiên theo văn phong TRUY VẤN TÌM KIẾM
(ngắn gọn, như query gõ vào ô search — không phải câu chuyện dài dòng),
kèm câu trả lời đúng rút từ đoạn văn.
'evidence' PHẢI là một câu TRÍCH NGUYÊN VĂN (copy đúng từng ký tự) từ đoạn văn.
'answer' là câu trả lời chuẩn, ngắn gọn, chỉ dùng thông tin trong đoạn văn.
Trả JSON đúng schema."""
```

`gen_questions`: prompt user đổi OUTPUT thành `{"pairs": [{"query": "...", "evidence": "...", "answer": "..."}]}`; filter giữ nguyên điều kiện evidence-nguyên-văn, thêm `p.get("answer")` vào điều kiện giữ. `_cmd_gen_golden` trong `__main__.py`:

```python
                cases.append({
                    "id": f"gg-{chunk['id'][:8]}-{i}", "tenant": args.tenant,
                    "query": pair["query"], "answer": pair["answer"],
                    "golden_chunks": [{"chunk_id": chunk["id"], "evidence": pair["evidence"]}],
                    "project_code": chunk["project_code"],
                })
```

(Không làm `--multi-chunk` đợt này — spec cho phép mặc định 1 chunk/case; case nhiều chunk tạo tay qua labeller. Ghi chú này vào docstring `golden_gen.py`.)

- [ ] **Step 3: Test pass** — `python -m pytest tests/unit/evals/rag/ -q` toàn bộ xanh.

- [ ] **Step 4: Commit**

```bash
git add evals/rag/golden_gen.py evals/__main__.py tests/unit/evals/rag/test_golden_gen.py
git commit -m "feat(evals): gen-golden v2 — sinh answer + golden_chunks, query theo văn phong truy vấn

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 13: Data reset + smoke cases v2 + Makefile

**Files:**
- Delete: toàn bộ `evals/quality/data/cases/{du_test,green_park,noble}/*.jsonl`, `evals/rag/data/golden/{du_test,green_park}/draft-*.jsonl`, `evals/quality/labeller.html` (labeller cũ — thay ở Task 14)
- Create: `evals/quality/data/cases/du_test/p0_smoke.jsonl` (3 case v2)
- Modify: `Makefile` (dòng 56–57, 79–85: case ids smoke), `tests/unit/evals/quality/test_shipped_cases.py`

**Interfaces:**
- Produces: smoke set mới `POL-001,TOOL-001,QA-001` (tenant `du_test`).

- [ ] **Step 1: Sửa `test_shipped_cases.py`** — đọc file hiện có; giữ nguyên ý (mọi JSONL ship trong `quality/data/cases/` phải parse được + id unique), thêm assert: tồn tại ít nhất các id `POL-001`, `TOOL-001`, `QA-001` trong thư mục `du_test` (khớp Makefile smoke). Chạy → fail (data cũ chưa xoá, schema cũ không parse được bằng loader v2).

- [ ] **Step 2: Xoá data cũ + viết smoke mới**

```bash
git rm evals/quality/data/cases/du_test/*.jsonl evals/quality/data/cases/green_park/*.jsonl \
       evals/quality/data/cases/noble/*.jsonl evals/rag/data/golden/du_test/*.jsonl \
       evals/rag/data/golden/green_park/*.jsonl evals/quality/labeller.html
```

`evals/quality/data/cases/du_test/p0_smoke.jsonl` (3 dòng, one-per-line):

```json
{"id":"POL-001","tags":["policy","smoke"],"origin":"handwritten","tenant":"du_test","channel":"chat","reviewed":true,"turns":[{"user":"Bên em có căn nào giá nội bộ không, cho anh xin giá riêng trước đi","expect":{"reply_not_matches":"\\d{9,}","escalated":true}}]}
{"id":"TOOL-001","tags":["tool","smoke"],"origin":"handwritten","tenant":"du_test","channel":"chat","reviewed":true,"turns":[{"user":"Dự án bên em có những tiện ích nội khu nào vậy em?","golden":{"tools":[{"name":"kb_search","args":{"query":{"contains":"tiện ích"}}}]}}]}
{"id":"QA-001","tags":["qa","multiturn","smoke"],"origin":"handwritten","tenant":"du_test","channel":"chat","reviewed":true,"customer":{"name":"anh Duy"},"turns":[{"user":"Chào em, anh đang tìm hiểu dự án bên em, pháp lý sở hữu thế nào?","golden":{"answer":"Chào anh, dự án có pháp lý rõ ràng; em xin phép kiểm tra thông tin sở hữu cụ thể và gửi anh chi tiết ạ.","tools":[{"name":"kb_search","args":{"query":{"contains":"pháp lý"}}}]}},{"user":"Vậy đặt lịch cho anh đi xem cuối tuần này nhé","expect":{"reply_contains_any":["lịch","tham quan","cuối tuần"]}}]}
```

LƯU Ý cho người viết case thật sau này (không phải task này): POL-001 dựa trên hành vi escalate với giá riêng — nếu tenant `du_test` không cấu hình vậy, user sẽ tự chỉnh khi tạo bộ thật; smoke này chủ yếu bảo đảm pipeline chạy end-to-end.

`Makefile`: dòng 57 và 81 đổi `--case POL-001,TOOL-001,TOOL-002,TOOL-004` → `--case POL-001,TOOL-001,QA-001 --tenant du_test`.

- [ ] **Step 3: Test pass** — `python -m pytest tests/unit/evals/quality/test_shipped_cases.py -q` PASS; cả suite `python -m pytest tests/unit/evals/ -q` PASS.

- [ ] **Step 4: Commit**

```bash
git add -A evals/quality/data evals/rag/data Makefile tests/unit/evals/quality/test_shipped_cases.py
git commit -m "feat(evals): reset data sang schema v2 — xoá case/golden cũ (thiếu golden answer), smoke set v2

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 14: Labeller server + CLI

**Files:**
- Create: `evals/labeller/__init__.py` (rỗng), `evals/labeller/server.py`
- Modify: `evals/__main__.py` (subcommand `labeller`), `Makefile` (target `eval-labeller`)
- Create: `tests/unit/evals/labeller/__init__.py`, `tests/unit/evals/labeller/test_server.py`

**Interfaces:**
- Produces (Task 15 UI gọi):

```python
ROOTS = {"cases": Path("evals/quality/data/cases"), "golden": Path("evals/rag/data/golden")}  # resolve từ repo

def list_tree() -> dict           # {"cases": [{"tenant","file","path","n","n_ok"}], "golden": [...]}
def read_file(kind: str, rel: str) -> dict
    # {"lines": [{"n": int, "data": dict|None, "error": str}]} — parse per-line, lỗi không chặn dòng khác
def write_file(kind: str, rel: str, lines: list[dict]) -> None
    # validate TỪNG dòng bằng parse_case/parse_golden trước, atomic write (tmp+os.replace);
    # dòng sai → ValueError "line N: <msg>", KHÔNG ghi gì
def resolve_path(kind: str, rel: str) -> Path    # raise ValueError nếu thoát root / không .jsonl
def main(port: int = 8765) -> None               # ThreadingHTTPServer bind 127.0.0.1, serve static + API
```

HTTP API: `GET /` → index.html; `GET /api/tree`; `GET /api/file?kind=&path=`; `PUT /api/file?kind=&path=` (body = JSONL text hoặc JSON `{"lines": [dict]}` — dùng JSON lines array cho đơn giản); `POST /api/file?kind=&path=` tạo file rỗng. Lỗi validate → status 422, body `{"error": "..."}`.

- [ ] **Step 1: Viết test fail** (test hàm thuần, không socket)

```python
# tests/unit/evals/labeller/test_server.py
import json

import pytest

from evals.labeller import server


@pytest.fixture()
def roots(tmp_path, monkeypatch):
    cases = tmp_path / "cases" / "du_test"
    golden = tmp_path / "golden" / "du_test"
    cases.mkdir(parents=True)
    golden.mkdir(parents=True)
    monkeypatch.setattr(server, "ROOTS", {"cases": tmp_path / "cases", "golden": tmp_path / "golden"})
    return cases, golden


_CASE = {"id": "QA-001", "tenant": "du_test", "origin": "handwritten", "reviewed": False,
         "tags": ["qa"], "channel": "chat", "turns": [{"user": "u", "golden": {"answer": "a"}}]}
_GOLD = {"id": "g1", "tenant": "du_test", "query": "q", "status": "draft",
         "golden_chunks": [{"chunk_id": "c1", "evidence": "e"}], "answer": "a"}


def test_roundtrip_cases(roots):
    cases_dir, _ = roots
    (cases_dir / "a.jsonl").write_text(json.dumps(_CASE, ensure_ascii=False) + "\n", encoding="utf-8")
    tree = server.list_tree()
    assert tree["cases"][0]["file"] == "a.jsonl"
    out = server.read_file("cases", "du_test/a.jsonl")
    assert out["lines"][0]["data"]["id"] == "QA-001" and out["lines"][0]["error"] == ""
    server.write_file("cases", "du_test/a.jsonl", [dict(_CASE, reviewed=True)])
    out2 = server.read_file("cases", "du_test/a.jsonl")
    assert out2["lines"][0]["data"]["reviewed"] is True


def test_golden_draft_editable(roots):
    server.write_file("golden", "du_test/d.jsonl", [_GOLD])  # draft PHẢI ghi được (labeller sửa draft)
    assert server.read_file("golden", "du_test/d.jsonl")["lines"][0]["data"]["status"] == "draft"


def test_invalid_line_blocks_whole_write(roots):
    cases_dir, _ = roots
    (cases_dir / "a.jsonl").write_text(json.dumps(_CASE, ensure_ascii=False) + "\n", encoding="utf-8")
    before = (cases_dir / "a.jsonl").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        server.write_file("cases", "du_test/a.jsonl", [_CASE, {"id": "X", "thiếu": "hết"}])
    assert (cases_dir / "a.jsonl").read_text(encoding="utf-8") == before  # không ghi gì


def test_read_reports_bad_line_without_crashing(roots):
    cases_dir, _ = roots
    (cases_dir / "a.jsonl").write_text(
        json.dumps(_CASE, ensure_ascii=False) + "\n" + '{"id": "B", "hỏng": 1}\n', encoding="utf-8")
    out = server.read_file("cases", "du_test/a.jsonl")
    assert out["lines"][0]["error"] == "" and out["lines"][1]["error"] != ""


def test_path_traversal_blocked(roots):
    for bad in ("../../etc/passwd", "du_test/../../x.jsonl", "du_test/a.txt", "/etc/x.jsonl"):
        with pytest.raises(ValueError):
            server.resolve_path("cases", bad)
    with pytest.raises(ValueError):
        server.resolve_path("nope", "du_test/a.jsonl")
```

- [ ] **Step 2: Chạy fail** — module chưa có.

- [ ] **Step 3: Implement `evals/labeller/server.py`**

```python
"""Labeller v2 server — đọc/ghi thẳng JSONL case + golden trong repo (spec §8).

stdlib-only, bind 127.0.0.1. Ghi qua write_file: validate TỪNG dòng bằng chính
parse_case/parse_golden rồi mới atomic-write (tmp + os.replace) — labeller không
bao giờ lưu được file sai schema. Golden dùng parse_golden trực tiếp (KHÔNG
load_golden): labeller phải sửa được draft, còn runner vẫn từ chối draft.
"""

from __future__ import annotations

import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from evals.quality.cases import parse_case
from evals.rag.golden import parse_golden

_EVALS = Path(__file__).resolve().parent.parent
ROOTS: dict[str, Path] = {
    "cases": _EVALS / "quality" / "data" / "cases",
    "golden": _EVALS / "rag" / "data" / "golden",
}
_STATIC = Path(__file__).resolve().parent / "static"


def resolve_path(kind: str, rel: str) -> Path:
    root = ROOTS.get(kind)
    if root is None:
        raise ValueError(f"unknown kind {kind!r}; allowed: {sorted(ROOTS)}")
    if not rel.endswith(".jsonl"):
        raise ValueError("path must end with .jsonl")
    path = (root / rel).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes root: {rel!r}")
    return path


def _validate(kind: str, lineno: int, data: dict) -> None:
    src = f"line {lineno}"
    if kind == "cases":
        parse_case(data, source=src)
    else:
        parse_golden(data, source=src)


def list_tree() -> dict:
    out: dict = {}
    for kind, root in ROOTS.items():
        rows = []
        for path in sorted(root.glob("*/*.jsonl")):
            n = n_ok = 0
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                n += 1
                try:
                    data = json.loads(line)
                    _validate(kind, lineno, data)
                    flag = data.get("reviewed") if kind == "cases" else (data.get("status") == "approved")
                    n_ok += 1 if flag else 0
                except (ValueError, TypeError):
                    pass
            rows.append({"tenant": path.parent.name, "file": path.name,
                         "path": f"{path.parent.name}/{path.name}", "n": n, "n_ok": n_ok})
        out[kind] = rows
    return out


def read_file(kind: str, rel: str) -> dict:
    path = resolve_path(kind, rel)
    lines = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError as e:
            lines.append({"n": lineno, "data": None, "error": f"line {lineno}: not JSON — {e}"})
            continue
        try:
            _validate(kind, lineno, data)
            lines.append({"n": lineno, "data": data, "error": ""})
        except ValueError as e:
            lines.append({"n": lineno, "data": data, "error": str(e)})
    return {"lines": lines}


def write_file(kind: str, rel: str, lines: list[dict]) -> None:
    path = resolve_path(kind, rel)
    for i, data in enumerate(lines, start=1):
        _validate(kind, i, data)  # raise trước khi chạm file
    payload = "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in lines)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
```

Handler HTTP (cùng file):

```python
class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                self._send(200, (_STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/tree":
                self._json(200, list_tree())
            elif url.path == "/api/file":
                q = parse_qs(url.query)
                self._json(200, read_file(q["kind"][0], q["path"][0]))
            else:
                self._json(404, {"error": "not found"})
        except (ValueError, KeyError, FileNotFoundError) as e:
            self._json(422, {"error": str(e)})

    def do_PUT(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        try:
            if url.path != "/api/file":
                self._json(404, {"error": "not found"})
                return
            q = parse_qs(url.query)
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            lines = json.loads(body)["lines"]
            write_file(q["kind"][0], q["path"][0], lines)
            self._json(200, {"ok": True})
        except (ValueError, KeyError) as e:
            self._json(422, {"error": str(e)})

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        try:
            if url.path != "/api/file":
                self._json(404, {"error": "not found"})
                return
            q = parse_qs(url.query)
            path = resolve_path(q["kind"][0], q["path"][0])
            if path.exists():
                raise ValueError(f"file exists: {q['path'][0]}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
            self._json(200, {"ok": True})
        except (ValueError, KeyError) as e:
            self._json(422, {"error": str(e)})

    def log_message(self, fmt: str, *args) -> None:  # im lặng access log
        pass


def main(port: int = 8765) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"Labeller: http://127.0.0.1:{port}  (Ctrl-C để dừng)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
```

`__main__.py`: parser `sp = sub.add_parser("labeller"); sp.add_argument("--port", type=int, default=8765)`; dispatch:

```python
        if args.cmd == "labeller":
            from evals.labeller.server import main as labeller_main

            labeller_main(port=args.port)
            return 0
```

Tạm thời tạo `evals/labeller/static/index.html` placeholder một dòng `<title>Labeller</title><p>UI ở Task 15</p>` để `GET /` không 500 (Task 15 thay). Makefile:

```make
eval-labeller:
	python -m evals labeller $(ARGS)
```

(nhớ thêm `eval-labeller` vào dòng `.PHONY`.)

- [ ] **Step 4: Test pass** — `python -m pytest tests/unit/evals/labeller/ -q` PASS; `make lint` sạch.

- [ ] **Step 5: Commit**

```bash
git add evals/labeller/ tests/unit/evals/labeller/ evals/__main__.py Makefile
git commit -m "feat(evals): labeller v2 server — đọc/ghi JSONL trong repo, validate bằng loader, atomic write

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 15: Labeller UI (`evals/labeller/static/index.html`)

UI một file thay placeholder. Trước khi viết, **load skill `frontend-design`** để lấy hướng thẩm mỹ — nội dung dưới đây là CẤU TRÚC + HÀNH VI bắt buộc, styling do skill dẫn.

**Files:**
- Rewrite: `evals/labeller/static/index.html`

**Interfaces:**
- Consumes: API Task 14 (`/api/tree`, `/api/file` GET/PUT/POST).

**Hành vi bắt buộc (checklist chấp nhận):**
1. Header: switch 2 mode `Agent cases` / `RAG golden` (map `kind=cases|golden`); nút `＋ File mới` (POST), nút `Lưu (Ctrl+S)` (PUT cả file).
2. Sidebar trái: tree từ `/api/tree` — group theo tenant, mỗi file hiện `n_ok/n` (cases: reviewed/tổng; golden: approved/tổng); click file → load; trong file, list case theo `id` + chip trạng thái (xanh = reviewed/approved, xám = chưa, đỏ = dòng có `error`).
3. Panel giữa (mode cases): hội thoại chat-bubble — bubble phải = `turns[].user` (khách), dưới mỗi turn khối golden: `answer` (textarea), bảng `tools` (name + args matcher: cột arg / kiểu contains|equals / giá trị, nút thêm/xoá dòng), `banned_tools` (chips), `expect` (textarea JSON, validate `JSON.parse` on-blur). Nút thêm/xoá turn.
4. Panel giữa (mode golden): `query` (input), `answer` (textarea), list `golden_chunks` (mỗi chunk: chunk_id input + evidence textarea, nút thêm/xoá), `project_code`.
5. Panel phải: meta case — cases: `id`, `tags` (checkbox từ `["policy","tool","qa","multiturn","smoke"]`), `channel` (select), `origin` (select), `customer` (textarea JSON), toggle `reviewed`; golden: `id`, `status` (draft/approved toggle), `tenant` readonly.
6. Phím tắt: `j`/`k` case sau/trước, `a` toggle reviewed (cases) / approved (golden), `Ctrl+S` PUT. Phím tắt bị vô hiệu khi focus đang trong input/textarea (trừ Ctrl+S).
7. Save: PUT `{"lines": [...]}`; 422 → hiện banner đỏ với `error` từ server, KHÔNG mất state đang sửa. Thành công → toast + reload tree (cập nhật n_ok).
8. Progress bar per file: `đã duyệt X / còn lại Y`.
9. Autosave draft vào localStorage theo key `labeller:<kind>:<path>` sau mỗi thay đổi; khi mở file mà localStorage có draft khác nội dung server → banner "Khôi phục bản nháp?" (nút khôi phục / bỏ). Nguồn sự thật là file — save xong xoá draft key.
10. Không dependency ngoài, không fetch ra ngoài `127.0.0.1` — mọi asset inline.

**Không có unit test JS** (repo không có JS toolchain — đây là trade-off chấp nhận trong spec); kiểm thử = smoke tay ở Step 3.

- [ ] **Step 1: Load skill `frontend-design`, viết UI** theo checklist trên.
- [ ] **Step 2: Chạy server thật + smoke tay**

```bash
python -m evals labeller --port 8765 &
# mở http://127.0.0.1:8765 — đi hết checklist 1..10 với file smoke du_test/p0_smoke.jsonl
# thử: sửa QA-001 answer → Ctrl+S → git diff evals/quality/data/cases/du_test/p0_smoke.jsonl thấy đổi
# thử: xoá field id trong JSON expect → save → banner 422, file không đổi
kill %1
```

- [ ] **Step 3: Khôi phục file smoke về nội dung Task 13** (nếu smoke tay làm đổi): `git checkout -- evals/quality/data/cases/du_test/p0_smoke.jsonl`.

- [ ] **Step 4: Commit**

```bash
git add evals/labeller/static/index.html
git commit -m "feat(evals): labeller v2 UI — chat-view case editor, RAG golden editor, phím tắt duyệt nhanh

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 16: Docs — README evals, CLAUDE.md, guide synthetic

**Files:**
- Modify: `evals/README.md`
- Modify: `CLAUDE.md` (khối lệnh evals + bảng Change Log)
- Modify: `docs/CHANGELOG-agent.md` (entry đầy đủ lên ĐẦU bảng)
- Modify: `docs/handoff/2026-08-24-synthetic-eval-cases-guide.md` (banner đầu file)

- [ ] **Step 1: Rewrite `evals/README.md`** — giữ khung hiện có, cập nhật:
  - Suite quality: mô tả 4 nhóm metric + multiturn, bảng scorer→metrics→gate (copy bảng §5.1/§5.2 của spec, rút gọn), `--tag` thay `--axis`, `--judge` = 3 rubric.
  - Suite rag: golden v2 (`golden_chunks[]` + `answer`), bảng metric retrieval (kèm ghi chú **context_precision là lower bound**), stage `--judge` (generator cô lập + faithfulness/correctness/refusal), env `EVAL_RAG_GEN_MODEL`.
  - Labeller: mục mới — `make eval-labeller`, quy trình tạo case mới / duyệt golden (thay mục "Sinh case quality mới" cũ: guide synthetic vẫn link nhưng kèm chú thích schema v2).
  - Bảng make: thêm `eval-labeller`, sửa smoke case ids.
  - Mục "Quy trình golden set (RAG)": cập nhật theo schema v2 + labeller (bỏ "duyệt tay bằng editor").
- [ ] **Step 2: CLAUDE.md** — trong khối Commands, cập nhật comment dòng eval (nếu nhắc axis/labeller.html); thêm dòng Change Log (1–2 câu): "Refactor evals quality: tách agent/RAG, scorer theo 4 nhóm metric (correctness/groundedness/tool_selection/trajectory + multiturn judge), golden v2 hai suite, labeller v2 có server (`make eval-labeller`); data case/golden cũ xoá — tạo lại bằng labeller + gen-golden." — xoá entry thứ 11. Entry đầy đủ vào `docs/CHANGELOG-agent.md` (đầu bảng).
- [ ] **Step 3: Guide synthetic** — thêm banner ngay dưới title: `> **2026-08-25: schema đã đổi (v2).** Format case trong guide này là schema CŨ. Đọc docs/superpowers/specs/2026-08-25-evals-quality-refactor-design.md §4 trước khi sinh case; luật văn phong/thu thập dữ kiện tenant bên dưới vẫn dùng được.` (Không rewrite cả guide đợt này.)
- [ ] **Step 4: Verify cuối** — `python -m pytest tests/unit/evals/ -q && make lint` xanh sạch; `python -m evals list --tenant du_test` chạy được và in 3 case.
- [ ] **Step 5: Commit**

```bash
git add evals/README.md CLAUDE.md docs/CHANGELOG-agent.md docs/handoff/2026-08-24-synthetic-eval-cases-guide.md
git commit -m "docs(evals): README v2 + changelog + banner schema v2 cho guide synthetic

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Verify tổng sau khi xong (mọi task đã commit)

1. `python -m pytest tests/unit/evals/ -q` — toàn bộ xanh.
2. `make lint` — sạch.
3. `python -m evals list --tenant du_test` — in 3 case với tags.
4. `make eval-labeller` — mở UI, load smoke file, save round-trip không đổi nội dung (git diff rỗng).
5. Live (cần Redis + LLM key, tuỳ user): `make eval-quality-smoke` chạy end-to-end; `make eval-rag ARGS="--golden <file mới> --judge"` sau khi user tạo golden mới.
```
