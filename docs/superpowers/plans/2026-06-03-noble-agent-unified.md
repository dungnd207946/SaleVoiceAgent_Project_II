# Noble Agent Unified Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 3-agent (MA/CA/SA) architecture with one unified Luna agent in a new self-contained package `src/noble_agent/`, gated by feature flag `USE_UNIFIED_AGENT`. Agent core is written fresh; service layer (voice/transport/telephony/server/services/storage/metrics) is copied 1-1 from `noble_agent/` with import rewrites only.

**Architecture:** A single agent loads operational-protocol prompt + 12 union tools (CA+SA minus `switch_agent`), drives 1 LLM stream loop with parallel tool dispatch, persists state in 3 Redis keys (`meta`/`customer`/`state`), async summarizes when history grows past K turns. Drop-in `NobleAgent` facade keeps transport call sites unchanged. Dev workflow only — no production rollout in this plan.

**Tech Stack:** Python 3.11–3.13, asyncio, pydantic v2, Jinja2, OpenAI SDK (used as multi-provider client incl. Gemini), Anthropic SDK, Redis + fakeredis, MongoDB, pytest (asyncio_mode=auto), ruff (line 120, target py311).

**Spec:** [`docs/superpowers/specs/2026-06-03-noble-agent-unified-design.md`](../specs/2026-06-03-noble-agent-unified-design.md)

---

## Conventions

- **Branch:** stay on `refactor/unify-agent` (current branch). Do not push, do not merge. Commit after every task with the message shown in the task's commit step.
- **Working dir for paths:** `/home/dutn/Documents/Hotline-Agent/santa-hotline-agent`. All paths in this plan are relative to that root.
- **Lint/format:** after every edit, run `make lint` (ruff check) and `make format` (ruff format) before committing. If a step does not call it out, it still applies.
- **Test runner:** `pytest` (configured `asyncio_mode=auto`).
- **Imports:** when copying a file from `noble_agent.*` to `noble_agent.*`, rewrite every `from noble_agent.` or `import noble_agent.` occurrence inside that file to `noble_agent.`. Do not change anything else.
- **TDD style:** for new code (agent core), write the failing test first, then the implementation. For mechanical 1-1 copies of legacy files, no TDD — just copy, rewrite imports, verify imports parse.
- **Commit messages:** start with one of `feat(unified):`, `chore(unified):`, `test(unified):`, `refactor(unified):` per task.

---

## File Structure

The plan produces this structure under `src/noble_agent/` (and a parallel `tests/{unit,integration}/unified/`). Files marked **NEW** are written from scratch; **COPY** = copied 1-1 from a legacy/refactor source with imports rewritten; **MOVE+ADAPT** = file relocated and lightly modified.

```
src/noble_agent/
├── __init__.py                         NEW (1 line: package marker)
├── __main__.py                         NEW
├── _runner.py                          NEW (trivial entry)
├── config.py                           NEW — UnifiedSettings merging legacy + refactor settings
├── agent/
│   ├── __init__.py                     NEW
│   ├── base.py                         NEW — AgentDef dataclass
│   ├── facade.py                       NEW — NobleAgent (drop-in for transport)
│   ├── orchestrator.py                 NEW — TurnRunner
│   ├── runner.py                       NEW — run_turn (LLM + tool loop)
│   ├── catalog.py                      COPY from noble_agent_refactor/catalog.py
│   ├── qwen_transcript.py              COPY from noble_agent_refactor/qwen_transcript.py
│   ├── definitions/
│   │   ├── SOUL.md                     NEW
│   │   ├── RULES.md                    NEW (Operational Protocol + Tool Catalog + Style + Guardrails)
│   │   ├── PROMPT_TEMPLATE.md          NEW
│   │   ├── CUSTOMER_PROFILE.md         COPY from noble_agent_refactor/definitions/shared/CUSTOMER_PROFILE.md
│   │   └── config.json                 NEW (12 tools, model, temp, max_tokens)
│   ├── prompts/
│   │   ├── __init__.py
│   │   └── builder.py                  NEW — build_system_prompt (single-agent)
│   ├── tools/                          COPY from noble_agent_refactor/tools/ EXCEPT switch_agent.py
│   │   ├── __init__.py
│   │   ├── schemas.py                  COPY + drop switch_agent schema, touch up escalate desc
│   │   ├── dispatcher.py               COPY + simplify (no switch_agent special case)
│   │   ├── update_customer.py          COPY
│   │   ├── noble_search.py             COPY
│   │   ├── projects_info.py            COPY
│   │   ├── project_financial.py        COPY
│   │   ├── search_units.py             COPY (verify exists; else from projects_info.py)
│   │   ├── match_projects.py           COPY (verify exists; else from projects_info.py)
│   │   ├── booking.py                  COPY
│   │   ├── booking_state.py            COPY
│   │   ├── availability.py             COPY
│   │   ├── schedule_viewing.py         COPY
│   │   ├── support_ops.py              COPY (crm_lookup/verify_identity/support_ticket/escalate)
│   │   └── send_via_app.py             COPY (verify exists in refactor; if not, COPY from legacy)
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py                   COPY from noble_agent_refactor/llm/client.py
│   │   └── anthropic_provider.py       COPY from noble_agent_refactor/llm/anthropic_provider.py
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── flat_store.py               COPY from noble_agent/agent/rag/flat_store.py
│   │   ├── flat_store_adapter.py       COPY from noble_agent/agent/rag/flat_store_adapter.py
│   │   ├── faq_searcher.py             COPY from noble_agent/agent/rag/faq_searcher.py
│   │   ├── noble_kb.py                 COPY from noble_agent/agent/rag/noble_kb.py
│   │   └── grep_search.py              COPY from noble_agent_refactor/rag/grep_search.py
│   └── summary/
│       ├── __init__.py
│       └── summarizer.py               NEW — summarize_and_persist (single-thread)
├── storage/
│   ├── __init__.py
│   ├── connection.py                   COPY from noble_agent/storage/connection.py
│   ├── session_store.py                COPY from noble_agent/storage/session_store.py
│   ├── bookings_flat.py                COPY
│   ├── call_events.py                  COPY
│   ├── call_summaries.py               COPY
│   ├── noble_profiles.py               COPY
│   ├── outbound_briefs.py              COPY
│   ├── outbound_calls.py               COPY
│   ├── resilience.py                   COPY
│   ├── redis_client.py                 COPY from noble_agent_refactor/storage/redis_client.py
│   ├── mongo_client.py                 COPY from noble_agent_refactor/storage/mongo_client.py
│   ├── models.py                       NEW — Meta/Customer/State/ThreadMessage/ThreadSummary
│   └── repo.py                         NEW — StateRepo (load/save_all/update_summary)
├── server/                             COPY from noble_agent/server/ EXCEPT ws_handler/session/text_chat (those get edits)
│   ├── __init__.py                     COPY
│   ├── http.py                         COPY (import rewrite only)
│   ├── ws_handler.py                   COPY + edit (routes to unified text_chat/session)
│   ├── session.py                      COPY + edit (use NobleAgent from unified facade)
│   ├── text_chat.py                    COPY + edit (use NobleAgent from unified facade)
│   ├── base_session.py                 COPY
│   ├── outbound_endpoints.py           COPY
│   ├── rate_limit.py                   COPY
│   ├── csv_export.py                   COPY
│   ├── logging_config.py               COPY
│   └── _websockets_post_patch.py       COPY
├── voice/                              COPY from noble_agent/voice/
│   ├── stt/                            COPY (all 4 backends)
│   ├── tts/                            COPY (all 2 backends)
│   ├── vad/                            COPY
│   ├── turn_detection/                 COPY
│   ├── audio/                          COPY
│   ├── audio_guard.py                  COPY
│   ├── gender_detector.py              COPY
│   ├── sentence_buffer.py              MOVE+ADAPT from noble_agent/agent/sentence_buffer.py
│   └── voice_agent.py                  MOVE+ADAPT from noble_agent/agent/voice.py (+ relevant bits of app.py)
├── telephony/                          COPY from noble_agent/telephony/
├── transport/                          COPY from noble_agent/transport/ (incl. livekit/ subdir)
├── services/                           COPY from noble_agent/services/
└── metrics/                            COPY from noble_agent/metrics/

tests/unit/unified/
├── __init__.py
├── conftest.py                         fixtures: fake_llm, fake_redis, unified_runner, fake_dispatcher
├── test_state_models.py
├── test_repo.py
├── test_prompt_builder.py
├── test_runner.py
├── test_dispatcher.py
├── test_summarizer.py
└── test_facade.py

tests/integration/unified/
├── __init__.py
├── conftest.py
├── test_text_chat_e2e.py
├── test_text_chat_tool_flow.py
├── test_text_chat_booking_flow.py
└── test_session_resume.py
```

Each file has one responsibility; service-layer copies preserve their legacy responsibility unchanged.

---

# Phase 0 — Package scaffold + settings

## Task 0.1: Create package scaffold

**Files:**
- Create: `src/noble_agent/__init__.py`
- Create: `src/noble_agent/__main__.py`
- Create: `src/noble_agent/_runner.py`
- Create: `src/noble_agent/agent/__init__.py`
- Create: `src/noble_agent/agent/prompts/__init__.py`
- Create: `src/noble_agent/agent/tools/__init__.py`
- Create: `src/noble_agent/agent/llm/__init__.py`
- Create: `src/noble_agent/agent/rag/__init__.py`
- Create: `src/noble_agent/agent/summary/__init__.py`
- Create: `src/noble_agent/storage/__init__.py`
- Create: `tests/unit/unified/__init__.py`
- Create: `tests/integration/unified/__init__.py`

- [ ] **Step 1: Create `src/noble_agent/__init__.py`**

```python
"""Noble Voice Agent — unified single-agent package.

See docs/superpowers/specs/2026-06-03-noble-agent-unified-design.md.
"""
```

- [ ] **Step 2: Create empty `__init__.py` for each subpackage**

For each of the paths listed above ending in `__init__.py` except the top-level one, write an empty file (zero bytes).

- [ ] **Step 3: Create `src/noble_agent/__main__.py`**

```python
"""CLI entry: dispatches to unified server when USE_UNIFIED_AGENT=true,
otherwise falls back to the legacy noble_agent.__main__."""

from __future__ import annotations


def main() -> None:
    from noble_agent.config import get_settings

    if get_settings().use_unified_agent:
        from noble_agent.server.http import run_server

        run_server()
    else:
        from noble_agent.__main__ import main as legacy_main

        legacy_main()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create trivial `_runner.py`**

```python
"""Compat shim — some scripts import `noble_agent._runner.main`."""

from noble_agent.__main__ import main

__all__ = ["main"]
```

- [ ] **Step 5: Verify package imports**

```bash
python -c "import noble_agent; print(noble_agent.__doc__)"
```
Expected: prints docstring, no `ImportError`.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent tests/unit/unified tests/integration/unified
git commit -m "chore(unified): scaffold package directory tree"
```

## Task 0.2: Write `UnifiedSettings`

**Files:**
- Create: `src/noble_agent/config.py`
- Test: `tests/unit/unified/test_config.py`

**Context (read first, do not skip):**
1. Open `src/noble_agent/config.py` and read the full `Settings` class.
2. Open `src/noble_agent_refactor/config.py` and read `RefactorSettings`.
3. The new `UnifiedSettings` must contain every field from both, **with their exact env var aliases preserved**, plus:
   - `use_unified_agent: bool` (alias `USE_UNIFIED_AGENT`, default `False`)
   - `summary_keep_tail: int` (alias `NOBLE_SUMMARY_KEEP_TAIL`, default `4`)
4. Remove these refactor fields (no longer meaningful): `default_agent`, `max_handoff_chain`, `auto_briefing_lookback`, `briefing_model`.
5. Keep all `semcache_*` fields but set `semcache_enabled` default to `False`.

- [ ] **Step 1: Write failing test for the new flag**

`tests/unit/unified/test_config.py`:

```python
import os

import pytest

from noble_agent.config import UnifiedSettings, get_settings, reset_settings_for_tests


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_settings_for_tests()
    yield
    reset_settings_for_tests()


def test_use_unified_agent_flag_default_false(monkeypatch):
    monkeypatch.delenv("USE_UNIFIED_AGENT", raising=False)
    assert UnifiedSettings().use_unified_agent is False


def test_use_unified_agent_flag_reads_env(monkeypatch):
    monkeypatch.setenv("USE_UNIFIED_AGENT", "true")
    assert UnifiedSettings().use_unified_agent is True


def test_summary_keep_tail_default(monkeypatch):
    monkeypatch.delenv("NOBLE_SUMMARY_KEEP_TAIL", raising=False)
    assert UnifiedSettings().summary_keep_tail == 4


def test_summary_threshold_default(monkeypatch):
    monkeypatch.delenv("NOBLE_SUMMARY_K", raising=False)
    assert UnifiedSettings().summary_threshold_K == 8


def test_semcache_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NOBLE_SEMCACHE_ENABLED", raising=False)
    assert UnifiedSettings().semcache_enabled is False


def test_removed_fields_are_absent():
    s = UnifiedSettings()
    for name in ("default_agent", "max_handoff_chain", "auto_briefing_lookback", "briefing_model"):
        assert not hasattr(s, name), f"{name} should be removed from UnifiedSettings"


def test_get_settings_returns_singleton(monkeypatch):
    monkeypatch.setenv("USE_UNIFIED_AGENT", "false")
    a = get_settings()
    b = get_settings()
    assert a is b
```

Run: `pytest tests/unit/unified/test_config.py -v`
Expected: FAIL (no `UnifiedSettings`).

- [ ] **Step 2: Implement `UnifiedSettings`**

`src/noble_agent/config.py`:

Open both legacy and refactor config files. Copy every field from `noble_agent/config.py::Settings` and every field from `noble_agent_refactor/config.py::RefactorSettings` (minus the 4 removed fields) into a new `UnifiedSettings(BaseSettings)` class. Keep field names, types, defaults, and `Field(alias=...)` env-var aliases identical to the source. Append:

```python
    use_unified_agent: bool = Field(False, alias="USE_UNIFIED_AGENT")
    summary_keep_tail: int = Field(4, alias="NOBLE_SUMMARY_KEEP_TAIL")
```

Set `semcache_enabled` default to `False` regardless of the refactor default.

Top of file:

```python
from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class UnifiedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── flags ─────────────────────────────────────────────────────────────
    use_unified_agent: bool = Field(False, alias="USE_UNIFIED_AGENT")

    # ── agent core (from refactor, minus handoff fields) ──────────────────
    summary_threshold_K: int = Field(8, alias="NOBLE_SUMMARY_K")
    summary_keep_tail: int = Field(4, alias="NOBLE_SUMMARY_KEEP_TAIL")
    summary_model: str = Field("qwen3.6-plus", alias="NOBLE_SUMMARY_MODEL")
    enable_slow_thinker: bool = Field(True, alias="NOBLE_ENABLE_SLOW_THINKER")
    session_ttl_seconds: int = Field(86400, alias="NOBLE_SESSION_TTL")
    search_backend: Literal["rag", "grep", "empty"] = Field("rag", alias="NOBLE_SEARCH_BACKEND")
    transcript_log_enabled: bool = Field(False, alias="NOBLE_TRANSCRIPT_LOG_ENABLED")
    transcript_log_dir: str = Field("data/training_logs", alias="NOBLE_TRANSCRIPT_LOG_DIR")

    # ── semantic cache (deferred; disabled by default in unified) ─────────
    semcache_enabled: bool = Field(False, alias="NOBLE_SEMCACHE_ENABLED")
    semcache_num_predictions: int = Field(5, alias="NOBLE_SEMCACHE_NUM_PREDICTIONS")
    semcache_threshold: float = Field(0.85, alias="NOBLE_SEMCACHE_THRESHOLD")
    semcache_embed_model: str = Field("intfloat/multilingual-e5-small", alias="NOBLE_SEMCACHE_EMBED_MODEL")
    semcache_predictor_temperature: float = Field(0.8, alias="NOBLE_SEMCACHE_PREDICTOR_TEMPERATURE")
    semcache_history_lookback: int = Field(8, alias="NOBLE_SEMCACHE_HISTORY_LOOKBACK")

    # ── legacy settings (copy ALL from noble_agent.config.Settings here) ──
    # Add every remaining field from src/noble_agent/config.py::Settings verbatim,
    # preserving Field(alias=...) and defaults. Do not rename. Group with
    # `# ── <topic> ──` dividers matching the topic structure of the legacy
    # file (audio, voice, stt, tts, llm, redis, mongo, metrics, telephony,
    # transport, etc.).


_settings: UnifiedSettings | None = None


def get_settings() -> UnifiedSettings:
    global _settings
    if _settings is None:
        _settings = UnifiedSettings()
    return _settings


def reset_settings_for_tests() -> None:
    global _settings
    _settings = None
```

When inlining legacy fields, group them with `# ── <topic> ──` comment dividers (audio, voice, stt, tts, llm, redis, mongo, metrics, telephony, transport, etc.) matching how the legacy file is organized. Keep `Literal[...]` types where the legacy uses them.

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/unified/test_config.py -v
```
Expected: all 6 tests PASS.

- [ ] **Step 4: Verify a sample legacy env var still resolves**

```bash
USE_UNIFIED_AGENT=true STT_BACKEND=qwen3asr python -c "from noble_agent.config import UnifiedSettings; s = UnifiedSettings(); print(s.use_unified_agent, s.stt_backend)"
```
Expected: `True qwen3asr` (substitute `stt_backend` with whatever legacy field actually exists; the point is to confirm a legacy alias still loads from env).

- [ ] **Step 5: Lint + format + commit**

```bash
make lint && make format
git add src/noble_agent/config.py tests/unit/unified/test_config.py
git commit -m "feat(unified): UnifiedSettings merging legacy + refactor config"
```

---

# Phase 1 — State models + StateRepo

## Task 1.1: Pydantic state models

**Files:**
- Create: `src/noble_agent/storage/models.py`
- Test: `tests/unit/unified/test_state_models.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/unified/test_state_models.py`:

```python
from datetime import UTC, datetime

import pytest

from noble_agent.storage.models import (
    Customer,
    Meta,
    State,
    ThreadMessage,
    ThreadSummary,
)


def test_meta_has_no_active_agent():
    m = Meta(
        session_id="s1",
        started_at=datetime.now(UTC),
        last_active=datetime.now(UTC),
    )
    assert not hasattr(m, "active_agent")


def test_customer_defaults_all_optional():
    c = Customer()
    assert c.name is None
    assert c.phone is None
    assert c.project_interest is None


def test_state_defaults_empty():
    s = State()
    assert s.history == []
    assert s.summary is None
    assert s.scratchpad == ""


def test_thread_message_to_openai_user():
    m = ThreadMessage(role="user", content="hi")
    assert m.to_openai() == {"role": "user", "content": "hi"}


def test_thread_message_to_openai_assistant_with_tool_calls():
    tc = [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]
    m = ThreadMessage(role="assistant", content="ok", tool_calls=tc)
    out = m.to_openai()
    assert out["role"] == "assistant"
    assert out["content"] == "ok"
    assert out["tool_calls"] == tc


def test_thread_message_to_openai_tool():
    m = ThreadMessage(role="tool", tool_call_id="c1", name="f", content="result")
    out = m.to_openai()
    assert out == {"role": "tool", "tool_call_id": "c1", "name": "f", "content": "result"}


def test_state_round_trip_json():
    s = State(
        history=[
            ThreadMessage(role="user", content="hello"),
            ThreadMessage(role="assistant", content="hi"),
        ],
        summary=ThreadSummary(text="prev calls", covers_turns=4, updated_at=datetime.now(UTC)),
        scratchpad="note",
    )
    blob = s.model_dump_json()
    s2 = State.model_validate_json(blob)
    assert len(s2.history) == 2
    assert s2.summary.covers_turns == 4
    assert s2.scratchpad == "note"
```

Run: `pytest tests/unit/unified/test_state_models.py -v`
Expected: FAIL (no `models` module).

- [ ] **Step 2: Implement models**

`src/noble_agent/storage/models.py`:

```python
"""Unified single-agent state models.

3 Redis keys per session: meta / customer / state. State holds a single flat
history thread and an optional async-generated summary covering older turns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Meta(BaseModel):
    session_id: str
    started_at: datetime
    last_active: datetime
    phone: str | None = None


class Customer(BaseModel):
    name: str | None = None
    full_name: str | None = None
    gender: Literal["M", "F"] | None = None
    phone: str | None = None
    project_interest: str | None = None
    purpose: str | None = None
    budget: str | None = None
    preferred_area: str | None = None
    bedroom_count: str | None = None
    is_buyer: bool | None = None
    is_noble_customer: bool | None = None
    noble_info: str | None = None


class ThreadMessage(BaseModel):
    role: Literal["user", "assistant", "tool", "system"]
    content: str = ""
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_openai(self) -> dict:
        """Render as an OpenAI Chat Completions message dict."""
        if self.role == "tool":
            return {
                "role": "tool",
                "tool_call_id": self.tool_call_id or "",
                "name": self.name or "",
                "content": self.content,
            }
        if self.role == "assistant" and self.tool_calls:
            return {"role": "assistant", "content": self.content, "tool_calls": self.tool_calls}
        return {"role": self.role, "content": self.content}


class ThreadSummary(BaseModel):
    text: str
    covers_turns: int
    updated_at: datetime


class State(BaseModel):
    history: list[ThreadMessage] = Field(default_factory=list)
    summary: ThreadSummary | None = None
    scratchpad: str = ""
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/unified/test_state_models.py -v
```
Expected: all PASS.

- [ ] **Step 4: Lint + format + commit**

```bash
make lint && make format
git add src/noble_agent/storage/models.py tests/unit/unified/test_state_models.py
git commit -m "feat(unified): state models — single-thread history + summary"
```

## Task 1.2: Copy Redis + Mongo clients

**Files:**
- Create: `src/noble_agent/storage/redis_client.py` (from `src/noble_agent_refactor/storage/redis_client.py`)
- Create: `src/noble_agent/storage/mongo_client.py` (from `src/noble_agent_refactor/storage/mongo_client.py`)

- [ ] **Step 1: Copy `redis_client.py` and `mongo_client.py`**

```bash
cp src/noble_agent_refactor/storage/redis_client.py src/noble_agent/storage/redis_client.py
cp src/noble_agent_refactor/storage/mongo_client.py src/noble_agent/storage/mongo_client.py
```

- [ ] **Step 2: Rewrite imports in both files**

Replace every `from noble_agent_refactor.` with `from noble_agent.` and every `import noble_agent_refactor.` with `import noble_agent.` inside those two files.

```bash
sed -i 's/from noble_agent_refactor\./from noble_agent./g; s/import noble_agent_refactor\./import noble_agent./g' src/noble_agent/storage/redis_client.py src/noble_agent/storage/mongo_client.py
```

If they import `noble_agent_refactor.config.get_settings`, change to `noble_agent.config.get_settings`.

- [ ] **Step 3: Verify import**

```bash
python -c "from noble_agent.storage import redis_client, mongo_client; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
make lint && make format
git add src/noble_agent/storage/redis_client.py src/noble_agent/storage/mongo_client.py
git commit -m "chore(unified): copy redis/mongo clients from refactor"
```

## Task 1.3: StateRepo (load / save_all / update_summary)

**Files:**
- Create: `src/noble_agent/storage/repo.py`
- Test: `tests/unit/unified/test_repo.py`

- [ ] **Step 1: Add `fakeredis` to dev deps if absent**

Check `pyproject.toml` `[project.optional-dependencies].dev` for `fakeredis`. If missing, append `"fakeredis[lua]>=2.20"` to the list.

Run: `pip install -e ".[dev]"` to install.

- [ ] **Step 2: Write failing tests**

`tests/unit/unified/test_repo.py`:

```python
from datetime import UTC, datetime

import fakeredis.aioredis
import pytest

from noble_agent.storage.models import (
    Customer,
    Meta,
    State,
    ThreadMessage,
    ThreadSummary,
)
from noble_agent.storage.repo import StateRepo


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


@pytest.fixture
def repo(redis):
    return StateRepo(redis_client=redis, ttl_seconds=3600)


async def test_load_fresh_session(repo):
    meta, customer, state = await repo.load("sid1")
    assert meta.session_id == "sid1"
    assert customer.name is None
    assert state.history == []
    assert state.summary is None


async def test_save_then_load_round_trip(repo):
    now = datetime.now(UTC)
    meta = Meta(session_id="sid2", started_at=now, last_active=now, phone="0901234567")
    customer = Customer(name="Hùng", project_interest="NCLB")
    state = State(history=[ThreadMessage(role="user", content="hi")])

    await repo.save_all("sid2", meta, customer, state)
    m2, c2, s2 = await repo.load("sid2")

    assert m2.phone == "0901234567"
    assert c2.name == "Hùng"
    assert c2.project_interest == "NCLB"
    assert len(s2.history) == 1
    assert s2.history[0].content == "hi"


async def test_ttl_is_set(repo, redis):
    now = datetime.now(UTC)
    meta = Meta(session_id="sid3", started_at=now, last_active=now)
    await repo.save_all("sid3", meta, Customer(), State())
    ttl = await redis.ttl("session:sid3:meta")
    # fakeredis returns the seconds remaining; should be > 0 and ≤ 3600
    assert 0 < ttl <= 3600


async def test_update_summary_writes_only_summary(repo):
    now = datetime.now(UTC)
    meta = Meta(session_id="sid4", started_at=now, last_active=now)
    customer = Customer(name="Lan")
    state = State(history=[ThreadMessage(role="user", content="m1")])
    await repo.save_all("sid4", meta, customer, state)

    new_summary = ThreadSummary(text="abc", covers_turns=1, updated_at=now)
    await repo.update_summary("sid4", new_summary)

    _, c2, s2 = await repo.load("sid4")
    assert c2.name == "Lan"           # untouched
    assert len(s2.history) == 1       # untouched
    assert s2.summary is not None
    assert s2.summary.text == "abc"
    assert s2.summary.covers_turns == 1


async def test_update_summary_on_missing_session_is_noop(repo):
    new_summary = ThreadSummary(
        text="x", covers_turns=0, updated_at=datetime.now(UTC)
    )
    # Should not raise even if the state key doesn't exist yet.
    await repo.update_summary("never-existed", new_summary)
    _, _, s = await repo.load("never-existed")
    # No summary was persisted because no state existed to attach it to.
    assert s.summary is None
```

Run: `pytest tests/unit/unified/test_repo.py -v`
Expected: FAIL (no `repo` module).

- [ ] **Step 3: Implement `StateRepo`**

`src/noble_agent/storage/repo.py`:

```python
"""StateRepo — 3-key Redis session state for the unified single agent.

Keys per session:
  - session:{sid}:meta      — Meta JSON
  - session:{sid}:customer  — Customer JSON
  - session:{sid}:state     — State JSON (history + summary + scratchpad)

`update_summary` is a narrow read-modify-write on the state key only, so the
background summary task doesn't clobber concurrent history writes from the
live turn. Uses WATCH for optimistic concurrency.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from noble_agent.storage.models import (
    Customer,
    Meta,
    State,
    ThreadSummary,
)

logger = logging.getLogger("noble_agent.repo")


class StateRepo:
    def __init__(self, *, redis_client, ttl_seconds: int = 86400):
        self._redis = redis_client
        self._ttl = ttl_seconds

    def _keys(self, sid: str) -> tuple[str, str, str]:
        return (
            f"session:{sid}:meta",
            f"session:{sid}:customer",
            f"session:{sid}:state",
        )

    async def load(self, sid: str) -> tuple[Meta, Customer, State]:
        k_meta, k_cust, k_state = self._keys(sid)
        meta_raw, cust_raw, state_raw = await self._redis.mget(k_meta, k_cust, k_state)

        if meta_raw is None:
            now = datetime.now(UTC)
            meta = Meta(session_id=sid, started_at=now, last_active=now)
        else:
            meta = Meta.model_validate_json(_to_str(meta_raw))

        customer = (
            Customer.model_validate_json(_to_str(cust_raw))
            if cust_raw is not None
            else Customer()
        )
        state = (
            State.model_validate_json(_to_str(state_raw))
            if state_raw is not None
            else State()
        )
        return meta, customer, state

    async def save_all(
        self, sid: str, meta: Meta, customer: Customer, state: State
    ) -> None:
        k_meta, k_cust, k_state = self._keys(sid)
        pipe = self._redis.pipeline()
        pipe.set(k_meta, meta.model_dump_json(), ex=self._ttl)
        pipe.set(k_cust, customer.model_dump_json(), ex=self._ttl)
        pipe.set(k_state, state.model_dump_json(), ex=self._ttl)
        await pipe.execute()

    async def update_summary(self, sid: str, summary: ThreadSummary) -> None:
        """WATCH-based atomic summary update on the state key only.

        No-op if the state key does not exist (session never had a turn).
        Retries once on WATCH conflict; if it still conflicts, the summary is
        dropped — the next overflow check will retry.
        """
        _, _, k_state = self._keys(sid)
        for attempt in range(2):
            async with self._redis.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(k_state)
                    raw = await pipe.get(k_state)
                    if raw is None:
                        await pipe.unwatch()
                        return
                    state = State.model_validate_json(_to_str(raw))
                    state.summary = summary
                    pipe.multi()
                    pipe.set(k_state, state.model_dump_json(), ex=self._ttl)
                    await pipe.execute()
                    return
                except Exception as exc:  # WatchError or generic
                    if attempt == 0 and _is_watch_error(exc):
                        logger.info("repo.update_summary: retry on watch conflict")
                        continue
                    logger.warning("repo.update_summary failed: %s", exc)
                    return


def _to_str(raw) -> str:
    return raw.decode("utf-8") if isinstance(raw, bytes) else raw


def _is_watch_error(exc: Exception) -> bool:
    return exc.__class__.__name__ == "WatchError"
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/unified/test_repo.py -v
```
Expected: all 5 tests PASS.

- [ ] **Step 5: Lint + format + commit**

```bash
make lint && make format
git add src/noble_agent/storage/repo.py tests/unit/unified/test_repo.py pyproject.toml
git commit -m "feat(unified): StateRepo with 3-key load/save_all and WATCH-based update_summary"
```

---

# Phase 2 — Agent definitions + AgentDef + prompt builder

## Task 2.1: Write Luna definition files

**Files:**
- Create: `src/noble_agent/agent/definitions/SOUL.md`
- Create: `src/noble_agent/agent/definitions/RULES.md`
- Create: `src/noble_agent/agent/definitions/PROMPT_TEMPLATE.md`
- Create: `src/noble_agent/agent/definitions/config.json`
- Copy: `src/noble_agent/agent/definitions/CUSTOMER_PROFILE.md` from `src/noble_agent_refactor/definitions/shared/CUSTOMER_PROFILE.md`

- [ ] **Step 1: Write `SOUL.md`**

```
Bạn là Luna — chuyên viên Noble Real Estate. Em phụ trách toàn bộ cuộc gọi:
chào khách, tư vấn dự án và căn hộ, đặt lịch tham quan, hỗ trợ khách đã mua
(hợp đồng / thanh toán / sổ hồng / bảo hành), và chuyển khách sang chuyên
viên phụ trách khi cần.
```

- [ ] **Step 2: Write `RULES.md`** — verbatim content from spec section 7.3 + 7.4 + 7.5

Copy the full content of spec sections 7.3 (Operational Protocol), 7.4 (Tool catalog), and 7.5 (Style + Guardrails) into a single `RULES.md` file. Headings are `## Operational Protocol`, `## Tool catalog`, `## Style`, `## Guardrails` — in that order, separated by a blank line.

- [ ] **Step 3: Write `PROMPT_TEMPLATE.md`**

```jinja
{{ soul }}

Hôm nay là {{ today }}.

{{ rules }}

{{ customer_block }}

{% if prior_summary %}
## Tóm tắt các turn trước (đã được summary)
{{ prior_summary.text }}
{% endif %}
```

- [ ] **Step 4: Copy `CUSTOMER_PROFILE.md`**

```bash
cp src/noble_agent_refactor/definitions/shared/CUSTOMER_PROFILE.md src/noble_agent/agent/definitions/CUSTOMER_PROFILE.md
```

- [ ] **Step 5: Write `config.json`**

```json
{
  "name": "luna",
  "model": "gemini-2.5-flash",
  "temperature": 0.7,
  "max_tokens": 800,
  "tools": [
    "update_customer",
    "noble_search",
    "list_projects",
    "get_project_overview",
    "get_project_financial",
    "search_units",
    "match_projects",
    "booking",
    "crm_lookup",
    "verify_identity",
    "support_ticket",
    "escalate",
    "send_via_app"
  ]
}
```

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/agent/definitions
git commit -m "feat(unified): Luna definitions — SOUL, RULES, prompt template, config"
```

## Task 2.2: `AgentDef` dataclass + loader

**Files:**
- Create: `src/noble_agent/agent/base.py`
- Test: `tests/unit/unified/test_agent_def.py`

- [ ] **Step 1: Write failing test**

`tests/unit/unified/test_agent_def.py`:

```python
from pathlib import Path

from noble_agent.agent.base import AgentDef, load_agent_def

DEFINITIONS = Path("src/noble_agent/agent/definitions")


def test_load_agent_def_returns_populated_object():
    agent = load_agent_def(DEFINITIONS)
    assert isinstance(agent, AgentDef)
    assert agent.name == "luna"
    assert agent.temperature == 0.7
    assert agent.max_tokens == 800
    assert "update_customer" in agent.tool_names
    assert "switch_agent" not in agent.tool_names
    assert len(agent.tool_names) == 13


def test_load_agent_def_has_sections():
    agent = load_agent_def(DEFINITIONS)
    assert "Luna" in agent.sections["soul"]
    assert "Operational Protocol" in agent.sections["rules"]
    assert "customer.name" in agent.sections["customer_format"]
    assert agent.prompt_template is not None


def test_load_agent_def_has_tool_schemas():
    agent = load_agent_def(DEFINITIONS)
    # 13 tool names in config → schemas should match.
    assert len(agent.tool_schemas) == 13
    names = {s["function"]["name"] for s in agent.tool_schemas}
    assert "switch_agent" not in names
    assert "escalate" in names
```

Note: 13 tools — the 12 listed in spec § 6 plus `escalate`. The spec table in §6 lists 12 user-facing tools but the implementation count is 13 (escalate is listed but I count carefully: update_customer, noble_search, list_projects, get_project_overview, get_project_financial, search_units, match_projects, booking, crm_lookup, verify_identity, support_ticket, escalate, send_via_app = 13). The config.json above has all 13.

Run: `pytest tests/unit/unified/test_agent_def.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement `AgentDef` + `load_agent_def`**

`src/noble_agent/agent/base.py`:

```python
"""AgentDef — frozen single-agent definition loaded from `definitions/`."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import jinja2


@dataclass(frozen=True)
class AgentDef:
    name: str
    model: str
    temperature: float
    max_tokens: int
    prompt_template: jinja2.Template
    sections: dict[str, str]      # keys: soul, rules, customer_format
    tool_names: list[str]
    tool_schemas: list[dict]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_agent_def(definitions_dir: Path | str) -> AgentDef:
    from noble_agent.agent.tools.schemas import schemas_for

    d = Path(definitions_dir)
    config = json.loads(_read(d / "config.json"))

    env = jinja2.Environment(
        loader=jinja2.BaseLoader(),
        autoescape=False,
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    template_src = _read(d / "PROMPT_TEMPLATE.md")
    tmpl = env.from_string(template_src)

    sections = {
        "soul": _read(d / "SOUL.md"),
        "rules": _read(d / "RULES.md"),
        "customer_format": _read(d / "CUSTOMER_PROFILE.md"),
    }

    tool_names = list(config["tools"])
    tool_schemas = schemas_for(tool_names)

    return AgentDef(
        name=config["name"],
        model=config["model"],
        temperature=float(config["temperature"]),
        max_tokens=int(config["max_tokens"]),
        prompt_template=tmpl,
        sections=sections,
        tool_names=tool_names,
        tool_schemas=tool_schemas,
    )
```

This test cannot pass until `tools/schemas.py` exists (Task 3.1). Mark test as `@pytest.mark.skip(reason="depends on tools/schemas")` or write a fixture stub for now; remove the skip in Task 3.1.

Recommended: skip the schema assertion test (`test_load_agent_def_has_tool_schemas`) with `@pytest.mark.skip(reason="enable after tools/schemas.py exists")`. Leave the first two passing tests un-skipped — they will pass once Task 3.1 adds `tools/schemas.py` because the import is inside the function body.

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/unified/test_agent_def.py -v
```

Expected for now: 2 PASS, 1 SKIPPED.

- [ ] **Step 4: Lint + format + commit**

```bash
make lint && make format
git add src/noble_agent/agent/base.py tests/unit/unified/test_agent_def.py
git commit -m "feat(unified): AgentDef dataclass + load_agent_def"
```

## Task 2.3: Prompt builder

**Files:**
- Create: `src/noble_agent/agent/prompts/builder.py`
- Test: `tests/unit/unified/test_prompt_builder.py`

- [ ] **Step 1: Write failing test**

`tests/unit/unified/test_prompt_builder.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

import pytest

from noble_agent.agent.base import load_agent_def
from noble_agent.agent.prompts.builder import build_system_prompt
from noble_agent.storage.models import Customer, ThreadSummary

DEFINITIONS = Path("src/noble_agent/agent/definitions")


@pytest.fixture
def agent():
    return load_agent_def(DEFINITIONS)


def test_prompt_with_empty_customer_no_summary(agent):
    prompt = build_system_prompt(agent, Customer(), None)
    assert "Luna" in prompt
    assert "Operational Protocol" in prompt
    assert "Hôm nay là" in prompt
    # Customer block should not list any field when customer is empty.
    assert "Tên:" not in prompt
    assert "Tóm tắt các turn trước" not in prompt


def test_prompt_with_customer_data(agent):
    prompt = build_system_prompt(
        agent,
        Customer(name="Hùng", phone="0901234567", project_interest="NCLB"),
        None,
    )
    assert "Hùng" in prompt
    assert "0901234567" in prompt
    assert "NCLB" in prompt


def test_prompt_with_summary(agent):
    summary = ThreadSummary(
        text="Khách Hùng đã hỏi giá NCLB và đặt lịch tham quan thứ Bảy.",
        covers_turns=6,
        updated_at=datetime.now(UTC),
    )
    prompt = build_system_prompt(agent, Customer(name="Hùng"), summary)
    assert "Tóm tắt các turn trước" in prompt
    assert "đặt lịch tham quan thứ Bảy" in prompt
```

Run: `pytest tests/unit/unified/test_prompt_builder.py -v`
Expected: FAIL (no `builder` module).

- [ ] **Step 2: Implement `build_system_prompt`**

`src/noble_agent/agent/prompts/builder.py`:

```python
"""Compose the unified agent's system prompt from AgentDef + runtime state."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import jinja2

from noble_agent.agent.base import AgentDef
from noble_agent.storage.models import Customer, ThreadSummary

_customer_env = jinja2.Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True)
_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
_VN_WEEKDAYS = ("Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật")


def _today_vn() -> str:
    now = datetime.now(tz=_VN_TZ)
    return f"{now.strftime('%d/%m/%Y')} ({_VN_WEEKDAYS[now.weekday()]})"


def _render_customer(template_src: str, customer: Customer) -> str:
    return _customer_env.from_string(template_src).render(customer=customer)


def build_system_prompt(
    agent: AgentDef,
    customer: Customer,
    prior_summary: ThreadSummary | None,
) -> str:
    customer_block = _render_customer(agent.sections["customer_format"], customer)
    return agent.prompt_template.render(
        soul=agent.sections["soul"],
        rules=agent.sections["rules"],
        customer_block=customer_block,
        prior_summary=prior_summary.model_dump() if prior_summary else None,
        today=_today_vn(),
    )
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/unified/test_prompt_builder.py -v
```
Expected: all PASS (this test depends on `load_agent_def` returning real sections; if Task 3.1 hasn't run yet, the schemas import inside `load_agent_def` will fail — temporarily stub `schemas_for` by adding a `src/noble_agent/agent/tools/schemas.py` returning `[]` if a tools file doesn't exist yet. Cleaner: run Task 3.1 before Task 2.3 if doing strictly serial).

- [ ] **Step 4: Lint + format + commit**

```bash
make lint && make format
git add src/noble_agent/agent/prompts/builder.py tests/unit/unified/test_prompt_builder.py
git commit -m "feat(unified): system prompt builder (Jinja, single-agent)"
```

---

# Phase 3 — Tool layer

## Task 3.1: Copy tool schemas + drop `switch_agent`

**Files:**
- Create: `src/noble_agent/agent/tools/schemas.py` (from `src/noble_agent_refactor/tools/schemas.py`)
- Test: `tests/unit/unified/test_tool_schemas.py`

- [ ] **Step 1: Copy file**

```bash
cp src/noble_agent_refactor/tools/schemas.py src/noble_agent/agent/tools/schemas.py
```

- [ ] **Step 2: Remove `switch_agent` schema**

Open `src/noble_agent/agent/tools/schemas.py`. Delete the entire `"switch_agent": { ... },` entry from the `SCHEMAS` dict (it spans from `"switch_agent": {` through its matching closing `},`).

- [ ] **Step 3: Update `escalate` description**

Find the `"escalate"` entry. Replace its `"description"` value with:

```
"Bàn giao khách sang chuyên viên người thật (CVTV / CSKH / Kỹ thuật / Pháp lý / Quản lý KD / Kế toán / Bàn giao / Thủ tục) khi vượt khả năng tự xử lý. Đây là cách duy nhất để chuyển cuộc gọi ra khỏi luồng tự động — KHÔNG có agent khác để bàn giao trong hệ thống."
```

- [ ] **Step 4: Update import inside file**

If any `from noble_agent_refactor` remains, rewrite to `noble_agent`:

```bash
sed -i 's/from noble_agent_refactor\./from noble_agent./g; s/import noble_agent_refactor\./import noble_agent./g' src/noble_agent/agent/tools/schemas.py
```

- [ ] **Step 5: Write tests**

`tests/unit/unified/test_tool_schemas.py`:

```python
from noble_agent.agent.tools.schemas import SCHEMAS, schemas_for


def test_switch_agent_is_absent():
    assert "switch_agent" not in SCHEMAS


def test_escalate_description_mentions_no_agent_handoff():
    desc = SCHEMAS["escalate"]["function"]["description"]
    assert "chuyên viên người thật" in desc or "agent khác" in desc.lower()


def test_schemas_for_returns_in_order():
    out = schemas_for(["update_customer", "noble_search"])
    assert len(out) == 2
    assert out[0]["function"]["name"] == "update_customer"
    assert out[1]["function"]["name"] == "noble_search"


def test_schemas_for_skips_unknown():
    assert schemas_for(["nonexistent_tool", "noble_search"]) == [SCHEMAS["noble_search"]]


def test_thirteen_tools_present():
    expected = {
        "update_customer", "noble_search", "list_projects", "get_project_overview",
        "get_project_financial", "search_units", "match_projects", "booking",
        "crm_lookup", "verify_identity", "support_ticket", "escalate", "send_via_app",
    }
    assert expected.issubset(SCHEMAS.keys())
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/unit/unified/test_tool_schemas.py -v
```
Expected: all PASS.

- [ ] **Step 7: Unskip the agent_def tools test (from Task 2.2)**

Remove the `@pytest.mark.skip` from `test_load_agent_def_has_tool_schemas` in `tests/unit/unified/test_agent_def.py`. Re-run:

```bash
pytest tests/unit/unified/test_agent_def.py -v
```
Expected: all 3 PASS.

- [ ] **Step 8: Commit**

```bash
make lint && make format
git add src/noble_agent/agent/tools/schemas.py tests/unit/unified/test_tool_schemas.py tests/unit/unified/test_agent_def.py
git commit -m "feat(unified): tool schemas — drop switch_agent, refresh escalate desc"
```

## Task 3.2: Copy tool implementations

**Files:**
- Create: `src/noble_agent/agent/tools/{update_customer,noble_search,projects_info,project_financial,booking,booking_state,availability,schedule_viewing,support_ops}.py` (from `src/noble_agent_refactor/tools/`)
- Optional copy from refactor or legacy: `search_units.py`, `match_projects.py`, `send_via_app.py`

- [ ] **Step 1: Inspect refactor tools dir**

```bash
ls src/noble_agent_refactor/tools/
```

For every `.py` file EXCEPT `schemas.py`, `dispatcher.py`, and `switch_agent.py`, copy to the unified tools dir:

```bash
for f in update_customer noble_search projects_info project_financial booking booking_state availability schedule_viewing support_ops; do
  cp "src/noble_agent_refactor/tools/${f}.py" "src/noble_agent/agent/tools/${f}.py"
done
```

For any of `search_units.py`, `match_projects.py`, `send_via_app.py` that exists in refactor, also copy. If a file does not exist in refactor, copy it from `src/noble_agent/agent/tools/<name>.py` instead (legacy implementation).

- [ ] **Step 2: Rewrite imports in every copied file**

```bash
find src/noble_agent/agent/tools -name '*.py' -exec sed -i 's/from noble_agent_refactor\./from noble_agent./g; s/import noble_agent_refactor\./import noble_agent./g; s/from noble_agent\.agent/from noble_agent.agent/g; s/from noble_agent\.services/from noble_agent.services/g; s/from noble_agent\.storage/from noble_agent.storage/g; s/from noble_agent\.config/from noble_agent.config/g' {} +
```

- [ ] **Step 3: Verify every tool module imports**

```bash
python -c "
from noble_agent.agent.tools import (
    update_customer, noble_search, projects_info, project_financial,
    booking, booking_state, availability, schedule_viewing, support_ops,
)
print('ok')
"
```

Expected: `ok`. If any `ImportError` references `noble_agent.<something>`, run the sed step again with the additional source module name, or open the file and rewrite manually.

- [ ] **Step 4: Verify `schemas_for(all 13 tool names)` returns 13 entries**

```bash
python -c "
from noble_agent.agent.tools.schemas import schemas_for
names = ['update_customer','noble_search','list_projects','get_project_overview','get_project_financial','search_units','match_projects','booking','crm_lookup','verify_identity','support_ticket','escalate','send_via_app']
print(len(schemas_for(names)))
"
```

Expected: `13`.

- [ ] **Step 5: Commit**

```bash
make lint && make format
git add src/noble_agent/agent/tools
git commit -m "chore(unified): copy 12 tool implementations from refactor (no switch_agent)"
```

## Task 3.3: Simplified `ToolDispatcher`

**Files:**
- Create: `src/noble_agent/agent/tools/dispatcher.py`
- Test: `tests/unit/unified/test_dispatcher.py`

**Context:** open `src/noble_agent_refactor/tools/dispatcher.py` and read it. The unified dispatcher is similar but does not need to detect `switch_agent` (the tool no longer exists) and does not need `session_id` propagation for handoff. Keep:

- `customer_dirty` flag set by tools that mutate Customer fields (e.g. `noble_search` setting `project_interest`).
- `consume_customer_dirty()` to read-and-reset the flag.
- A `dispatch(tool_call)` async method that returns the tool result string.

Drop:

- Any `if tc["function"]["name"] == "switch_agent": raise HandoffRequest(...)` special case.

- [ ] **Step 1: Copy file and remove handoff branch**

```bash
cp src/noble_agent_refactor/tools/dispatcher.py src/noble_agent/agent/tools/dispatcher.py
sed -i 's/from noble_agent_refactor\./from noble_agent./g; s/import noble_agent_refactor\./import noble_agent./g' src/noble_agent/agent/tools/dispatcher.py
```

Open `src/noble_agent/agent/tools/dispatcher.py` in an editor. Find and delete any code branch related to `switch_agent` (typically a 3-10 line block). The rest of the dispatch logic — routing by tool name to its implementation module — stays.

- [ ] **Step 2: Write tests**

`tests/unit/unified/test_dispatcher.py`:

```python
import json
from datetime import UTC, datetime

import pytest

from noble_agent.agent.tools.dispatcher import ToolDispatcher
from noble_agent.storage.models import Customer, State


class _StubCallbacks:
    async def on_token(self, token): ...
    async def on_tool_start(self, name, args): ...
    async def on_tool_done(self, name, result): ...
    async def on_agent_switch(self, **kw): ...
    async def on_done(self): ...


def _tc(name: str, args: dict, tc_id: str = "c1") -> dict:
    return {
        "id": tc_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


@pytest.fixture
def dispatcher_ctx():
    customer = Customer()
    state = State()
    cb = _StubCallbacks()
    d = ToolDispatcher(
        state=state, customer=customer, rag=None, callbacks=cb, session_id="sid"
    )
    return d, customer, state


async def test_update_customer_sets_field_and_marks_dirty(dispatcher_ctx):
    d, customer, _ = dispatcher_ctx
    out = await d.dispatch(_tc("update_customer", {"name": "Hùng"}))
    assert "ok" in out.lower() or "success" in out.lower() or out  # tool returns SOMETHING
    assert customer.name == "Hùng"
    assert d.consume_customer_dirty() is True
    # Subsequent consume returns False.
    assert d.consume_customer_dirty() is False


async def test_unknown_tool_returns_error_string(dispatcher_ctx):
    d, _, _ = dispatcher_ctx
    out = await d.dispatch(_tc("totally_nonexistent_tool", {}))
    assert "error" in out.lower() or "unknown" in out.lower()


async def test_switch_agent_no_longer_raises(dispatcher_ctx):
    d, _, _ = dispatcher_ctx
    # switch_agent doesn't exist as a tool in unified — must NOT raise HandoffRequest.
    # It should be treated as an unknown tool.
    out = await d.dispatch(_tc("switch_agent", {"target": "CA", "reason": "x"}))
    assert "error" in out.lower() or "unknown" in out.lower()
```

Run: `pytest tests/unit/unified/test_dispatcher.py -v`
Expected initially: the third test (`switch_agent` returns error) PASSES only if the refactor dispatcher's `switch_agent` branch has been removed in Step 1. Verify by failing first then succeeding.

- [ ] **Step 3: Adjust dispatcher if test 3 fails**

If `test_switch_agent_no_longer_raises` fails, open the dispatcher and remove the remaining `switch_agent` branch. Run tests again.

- [ ] **Step 4: Run full unified test suite to check no regressions**

```bash
pytest tests/unit/unified -v
```
Expected: all PASS so far.

- [ ] **Step 5: Commit**

```bash
make lint && make format
git add src/noble_agent/agent/tools/dispatcher.py tests/unit/unified/test_dispatcher.py
git commit -m "feat(unified): ToolDispatcher without switch_agent special case"
```

---

# Phase 4 — LLM client + RAG + catalog

## Task 4.1: Copy LLM client + Anthropic provider + catalog + qwen_transcript

**Files:**
- Create: `src/noble_agent/agent/llm/client.py` (from `src/noble_agent_refactor/llm/client.py`)
- Create: `src/noble_agent/agent/llm/anthropic_provider.py` (from `src/noble_agent_refactor/llm/anthropic_provider.py`)
- Create: `src/noble_agent/agent/catalog.py` (from `src/noble_agent_refactor/catalog.py`)
- Create: `src/noble_agent/agent/qwen_transcript.py` (from `src/noble_agent_refactor/qwen_transcript.py`)

- [ ] **Step 1: Copy files**

```bash
cp src/noble_agent_refactor/llm/client.py src/noble_agent/agent/llm/client.py
cp src/noble_agent_refactor/llm/anthropic_provider.py src/noble_agent/agent/llm/anthropic_provider.py
cp src/noble_agent_refactor/catalog.py src/noble_agent/agent/catalog.py
cp src/noble_agent_refactor/qwen_transcript.py src/noble_agent/agent/qwen_transcript.py
```

- [ ] **Step 2: Rewrite imports**

```bash
sed -i 's/from noble_agent_refactor\./from noble_agent./g; s/import noble_agent_refactor\./import noble_agent./g' \
  src/noble_agent/agent/llm/client.py \
  src/noble_agent/agent/llm/anthropic_provider.py \
  src/noble_agent/agent/catalog.py \
  src/noble_agent/agent/qwen_transcript.py
```

If `qwen_transcript.py` imports `AgentRegistry` (refactor multi-agent), change the type to `AgentDef` and adjust the call site to read sections from a single agent. Inspect the file and adapt the constructor signature accordingly:

```python
# Before (refactor):
#   def __init__(self, dir: str, registry: AgentRegistry): ...
# After (unified):
#   def __init__(self, dir: str, agent: AgentDef): ...
```

Use `agent.sections["soul"]` etc. where the registry previously selected `registry.get(code).sections`.

- [ ] **Step 3: Verify imports**

```bash
python -c "from noble_agent.agent.llm import client, anthropic_provider; from noble_agent.agent import catalog, qwen_transcript; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
make lint && make format
git add src/noble_agent/agent/llm src/noble_agent/agent/catalog.py src/noble_agent/agent/qwen_transcript.py
git commit -m "chore(unified): copy LLM client, anthropic provider, catalog, qwen_transcript"
```

## Task 4.2: Copy RAG modules

**Files:**
- Create: `src/noble_agent/agent/rag/{flat_store,flat_store_adapter,faq_searcher,noble_kb}.py` (from `src/noble_agent/agent/rag/`)
- Create: `src/noble_agent/agent/rag/grep_search.py` (from `src/noble_agent_refactor/rag/grep_search.py`)
- Skip: `embeddings.py`, `faq_lookup.py`, `vector_store.py` (deprecated stubs), `fast_talker.py`, `slow_thinker.py`, `semantic_cache.py`, `conversation_stream.py`, `memory_router.py` (semcache deferred).

- [ ] **Step 1: Copy files**

```bash
for f in flat_store flat_store_adapter faq_searcher noble_kb; do
  cp "src/noble_agent/agent/rag/${f}.py" "src/noble_agent/agent/rag/${f}.py"
done
cp src/noble_agent_refactor/rag/grep_search.py src/noble_agent/agent/rag/grep_search.py
```

- [ ] **Step 2: Rewrite imports in all 5 files**

```bash
find src/noble_agent/agent/rag -name '*.py' -exec sed -i \
  's/from noble_agent_refactor\./from noble_agent./g; s/import noble_agent_refactor\./import noble_agent./g; s/from noble_agent\.agent/from noble_agent.agent/g; s/from noble_agent\.config/from noble_agent.config/g; s/from noble_agent\.services/from noble_agent.services/g' {} +
```

- [ ] **Step 3: Strip semcache/slow_thinker references**

Search `flat_store_adapter.py` and `noble_kb.py` for any imports of `SemanticCache`, `FastTalker`, `SlowThinker`, `MemoryRouter`. If present, remove the imports and any code paths that reference those classes. The unified phase 1 has no semcache.

- [ ] **Step 4: Verify imports**

```bash
python -c "from noble_agent.agent.rag import flat_store, flat_store_adapter, faq_searcher, noble_kb, grep_search; print('ok')"
```
Expected: `ok`. If `ImportError`, address case-by-case.

- [ ] **Step 5: Commit**

```bash
make lint && make format
git add src/noble_agent/agent/rag
git commit -m "chore(unified): copy RAG modules (flat_store, faq_searcher, noble_kb, grep_search)"
```

---

# Phase 5 — Summarizer

## Task 5.1: `summarize_and_persist`

**Files:**
- Create: `src/noble_agent/agent/summary/summarizer.py`
- Test: `tests/unit/unified/test_summarizer.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/unified/test_summarizer.py`:

```python
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from noble_agent.agent.summary.summarizer import summarize_and_persist
from noble_agent.storage.models import State, ThreadMessage, ThreadSummary
from noble_agent.storage.repo import StateRepo


@pytest.fixture
async def repo():
    r = fakeredis.aioredis.FakeRedis()
    yield StateRepo(redis_client=r, ttl_seconds=3600)
    await r.aclose()


def _msg(i: int) -> ThreadMessage:
    return ThreadMessage(role="user", content=f"m{i}")


async def test_below_keep_tail_does_nothing(repo):
    # 3 messages, keep_tail=4 → nothing to summarize.
    history = [_msg(i) for i in range(3)]
    llm = AsyncMock()
    llm.simple_completion = AsyncMock(return_value="should not be called")

    await summarize_and_persist(
        sid="s1", history=history, prior_summary=None,
        llm=llm, repo=repo, model="m", keep_tail=4,
    )
    llm.simple_completion.assert_not_called()
    _, _, state = await repo.load("s1")
    assert state.summary is None


async def test_summarizes_overflow_only(repo):
    from noble_agent.storage.models import Customer, Meta
    now = datetime.now(UTC)
    # Pre-populate state so update_summary has something to attach to.
    await repo.save_all(
        "s2",
        Meta(session_id="s2", started_at=now, last_active=now),
        Customer(),
        State(history=[_msg(i) for i in range(10)]),
    )

    history = [_msg(i) for i in range(10)]  # 10 msgs
    llm = AsyncMock()
    llm.simple_completion = AsyncMock(return_value="summary text")

    await summarize_and_persist(
        sid="s2", history=history, prior_summary=None,
        llm=llm, repo=repo, model="m", keep_tail=4,
    )
    # Should have summarized the first 6 (10 - keep_tail=4).
    llm.simple_completion.assert_awaited_once()
    _, _, state = await repo.load("s2")
    assert state.summary is not None
    assert state.summary.text == "summary text"
    assert state.summary.covers_turns == 6


async def test_incremental_summary_extends_prior_coverage(repo):
    from noble_agent.storage.models import Customer, Meta
    now = datetime.now(UTC)
    prior = ThreadSummary(text="old", covers_turns=4, updated_at=now)
    history = [_msg(i) for i in range(12)]  # 12 msgs; prior covers 4
    await repo.save_all(
        "s3",
        Meta(session_id="s3", started_at=now, last_active=now),
        Customer(),
        State(history=history, summary=prior),
    )

    llm = AsyncMock()
    llm.simple_completion = AsyncMock(return_value="new summary")

    await summarize_and_persist(
        sid="s3", history=history, prior_summary=prior,
        llm=llm, repo=repo, model="m", keep_tail=4,
    )

    _, _, state = await repo.load("s3")
    # Coverage moves: prior.covers_turns(4) + new_msgs_to_summarize(12-4-4=4) = 8.
    assert state.summary.covers_turns == 8
    assert state.summary.text == "new summary"
```

Run: `pytest tests/unit/unified/test_summarizer.py -v`
Expected: FAIL (no module).

- [ ] **Step 2: Implement summarizer**

`src/noble_agent/agent/summary/summarizer.py`:

```python
"""Async summary helper for the unified single-thread agent.

Runs in a background task at the end of a user turn when history exceeds K.
Only summarizes the overflow head; the trailing keep_tail messages stay
verbatim in history so the next LLM call sees fresh recent context.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from noble_agent.storage.models import ThreadMessage, ThreadSummary

logger = logging.getLogger("noble_agent.summary")

_SUMMARY_PROMPT = """\
Bạn là helper tóm tắt cuộc gọi tư vấn bất động sản. Đầu vào là:
- (tuỳ chọn) tóm tắt phiên trước.
- Danh sách các tin nhắn user/assistant/tool cần được nén lại.

Yêu cầu:
- Viết bằng tiếng Việt, một đoạn duy nhất, dưới 200 từ.
- Tập trung vào: hồ sơ khách (tên, SĐT, ngân sách, dự án quan tâm), yêu cầu khách
  đã đưa ra, tool đã được gọi và kết quả chính, quyết định đã chốt (lịch hẹn,
  ticket).
- KHÔNG viết lại nguyên văn tin nhắn, KHÔNG dùng bullet, KHÔNG dùng markdown.

{prior_block}

Tin nhắn cần tóm tắt:
{messages_block}
"""


def _format_message(m: ThreadMessage) -> str:
    if m.role == "user":
        return f"User: {m.content}"
    if m.role == "assistant":
        body = m.content or ""
        if m.tool_calls:
            calls = ", ".join(tc.get("function", {}).get("name", "?") for tc in m.tool_calls)
            body = f"{body} [tool_calls: {calls}]".strip()
        return f"Assistant: {body}"
    if m.role == "tool":
        return f"Tool[{m.name}]: {m.content}"
    return f"{m.role}: {m.content}"


def build_summary_prompt(
    prior: ThreadSummary | None, messages: list[ThreadMessage]
) -> str:
    prior_block = (
        f"Tóm tắt phiên trước:\n{prior.text}\n" if prior else "(Chưa có tóm tắt phiên trước.)"
    )
    messages_block = "\n".join(_format_message(m) for m in messages)
    return _SUMMARY_PROMPT.format(prior_block=prior_block, messages_block=messages_block)


async def summarize_and_persist(
    *,
    sid: str,
    history: list[ThreadMessage],
    prior_summary: ThreadSummary | None,
    llm,
    repo,
    model: str,
    keep_tail: int,
) -> None:
    covered = prior_summary.covers_turns if prior_summary else 0
    pending = history[covered:]
    if len(pending) <= keep_tail:
        return

    to_summarize = pending[:-keep_tail]
    prompt = build_summary_prompt(prior_summary, to_summarize)

    try:
        text = await llm.simple_completion(prompt, model=model, max_tokens=400)
    except Exception as exc:
        logger.warning("summarizer: llm call failed (%s) — skipping summary update", exc)
        return

    new_summary = ThreadSummary(
        text=(text or "").strip(),
        covers_turns=covered + len(to_summarize),
        updated_at=datetime.now(UTC),
    )
    await repo.update_summary(sid, new_summary)
```

- [ ] **Step 3: Verify `llm.simple_completion` exists in the copied client**

```bash
grep -n "simple_completion" src/noble_agent/agent/llm/client.py
```
Expected: at least one line. If absent (the refactor client may not have it), add a minimal `simple_completion` method to `client.py`:

```python
    async def simple_completion(
        self, prompt: str, *, model: str, max_tokens: int = 400, temperature: float = 0.3
    ) -> str:
        messages = [{"role": "user", "content": prompt}]
        text, _ = await self.stream_completion(
            messages=messages, tools=[], model=model,
            temperature=temperature, max_tokens=max_tokens, on_token=None,
        )
        return text or ""
```

Verify the existing `stream_completion` signature matches; adjust the call if needed.

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/unified/test_summarizer.py -v
```
Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
make lint && make format
git add src/noble_agent/agent/summary tests/unit/unified/test_summarizer.py src/noble_agent/agent/llm/client.py
git commit -m "feat(unified): async summarize_and_persist (single-thread, keep_tail)"
```

---

# Phase 6 — Orchestrator, runner, facade

## Task 6.1: `run_turn` (single-agent LLM + tool loop)

**Files:**
- Create: `src/noble_agent/agent/runner.py`
- Test: `tests/unit/unified/test_runner.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/unified/test_runner.py`:

```python
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from noble_agent.agent.base import load_agent_def
from noble_agent.agent.runner import run_turn
from noble_agent.storage.models import Customer, State, ThreadMessage

DEFINITIONS = Path("src/noble_agent/agent/definitions")


@pytest.fixture
def agent():
    return load_agent_def(DEFINITIONS)


class _Sink:
    def __init__(self):
        self.tokens: list[str] = []
        self.tool_starts: list[tuple[str, dict]] = []
        self.tool_dones: list[tuple[str, str]] = []

    async def on_token(self, t):
        self.tokens.append(t)

    async def on_tool_start(self, name, args):
        self.tool_starts.append((name, args))

    async def on_tool_done(self, name, result):
        self.tool_dones.append((name, result))

    async def on_agent_switch(self, **kw): ...
    async def on_done(self): ...


async def test_no_tool_calls_appends_assistant_and_returns(agent):
    state = State(history=[ThreadMessage(role="user", content="hi")])
    customer = Customer()
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("hello!", []))
    dispatcher = MagicMock()
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)
    sink = _Sink()

    await run_turn(
        agent=agent, state=state, customer=customer,
        llm=llm, dispatcher=dispatcher, callbacks=sink,
    )

    assert state.history[-1].role == "assistant"
    assert state.history[-1].content == "hello!"
    dispatcher.dispatch.assert_not_called()


async def test_tool_call_dispatched_then_loop_continues(agent):
    state = State(history=[ThreadMessage(role="user", content="cho em xin danh sách dự án")])
    customer = Customer()

    tc = {
        "id": "c1", "type": "function",
        "function": {"name": "list_projects", "arguments": "{}"},
    }
    llm = AsyncMock()
    # First call: tool. Second call: plain content.
    llm.stream_completion = AsyncMock(side_effect=[
        ("", [tc]),
        ("Bên em có Noble Crystal Long Biên...", []),
    ])
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value='{"projects":["NCLB"]}')
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)
    sink = _Sink()

    await run_turn(
        agent=agent, state=state, customer=customer,
        llm=llm, dispatcher=dispatcher, callbacks=sink,
    )

    assert llm.stream_completion.await_count == 2
    dispatcher.dispatch.assert_awaited_once_with(tc)
    # State has: user, assistant(tc), tool, assistant(reply) = 4 messages.
    assert len(state.history) == 4
    assert state.history[-1].content.startswith("Bên em có")


async def test_customer_dirty_triggers_prompt_rebuild(agent, monkeypatch):
    state = State(history=[ThreadMessage(role="user", content="hỏi noble crystal")])
    customer = Customer()

    tc = {
        "id": "c1", "type": "function",
        "function": {"name": "noble_search", "arguments": '{"query":"NCLB","project_filter":"NCLB"}'},
    }
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(side_effect=[
        ("", [tc]),
        ("ok", []),
    ])
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value="{}")
    dispatcher.consume_customer_dirty = MagicMock(side_effect=[True, False])

    builder_calls = []
    real = pytest.importorskip("noble_agent.agent.prompts.builder")
    original = real.build_system_prompt

    def _spy(*a, **kw):
        builder_calls.append((a, kw))
        return original(*a, **kw)

    monkeypatch.setattr(real, "build_system_prompt", _spy)
    # Also re-import runner so its symbol is patched if it was bound by from-import.
    import noble_agent.agent.runner as runner_mod
    monkeypatch.setattr(runner_mod, "build_system_prompt", _spy)

    await run_turn(
        agent=agent, state=state, customer=customer,
        llm=llm, dispatcher=dispatcher, callbacks=_Sink(),
    )
    # First call before LLM, second call after dispatcher.consume_customer_dirty()==True.
    assert len(builder_calls) >= 2


async def test_max_tool_iterations_breaks(agent, caplog):
    state = State(history=[ThreadMessage(role="user", content="loop")])
    customer = Customer()

    tc = {"id": "c1", "type": "function", "function": {"name": "list_projects", "arguments": "{}"}}
    llm = AsyncMock()
    # Always return a tool call → trigger MAX iteration cap.
    llm.stream_completion = AsyncMock(return_value=("", [tc]))
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value="{}")
    dispatcher.consume_customer_dirty = MagicMock(return_value=False)

    import logging
    with caplog.at_level(logging.WARNING, logger="noble_agent.runner"):
        await run_turn(
            agent=agent, state=state, customer=customer,
            llm=llm, dispatcher=dispatcher, callbacks=_Sink(),
        )
    assert any("MAX_TOOL_ITERATIONS" in r.message for r in caplog.records)
```

Run: `pytest tests/unit/unified/test_runner.py -v`
Expected: FAIL (no `runner` module).

- [ ] **Step 2: Implement `run_turn`**

`src/noble_agent/agent/runner.py`:

```python
"""Single-turn LLM + tool loop. No handoffs, no per-agent threads."""

from __future__ import annotations

import logging

from noble_agent.agent.base import AgentDef
from noble_agent.agent.prompts.builder import build_system_prompt
from noble_agent.storage.models import Customer, State, ThreadMessage

logger = logging.getLogger("noble_agent.runner")

MAX_TOOL_ITERATIONS = 5


async def run_turn(
    *,
    agent: AgentDef,
    state: State,
    customer: Customer,
    llm,
    dispatcher,
    callbacks,
) -> None:
    """Drive one user turn against the live state. Mutates state.history."""
    system = build_system_prompt(agent, customer, state.summary)
    messages: list[dict] = [{"role": "system", "content": system}]

    start = state.summary.covers_turns if state.summary else 0
    messages.extend(m.to_openai() for m in state.history[start:])

    for _ in range(MAX_TOOL_ITERATIONS):
        content, tool_calls = await llm.stream_completion(
            messages=messages,
            tools=agent.tool_schemas,
            model=agent.model,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
            on_token=callbacks.on_token,
        )

        assistant_msg = ThreadMessage(
            role="assistant", content=content or "", tool_calls=tool_calls
        )
        state.history.append(assistant_msg)
        messages.append(assistant_msg.to_openai())

        if not tool_calls:
            return

        for tc in tool_calls:
            result = await dispatcher.dispatch(tc)
            tool_msg = ThreadMessage(
                role="tool",
                tool_call_id=tc["id"],
                name=tc["function"]["name"],
                content=result,
            )
            state.history.append(tool_msg)
            messages.append(tool_msg.to_openai())

        if dispatcher.consume_customer_dirty():
            messages[0] = {
                "role": "system",
                "content": build_system_prompt(agent, customer, state.summary),
            }

    logger.warning("runner: hit MAX_TOOL_ITERATIONS without natural termination")
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/unified/test_runner.py -v
```
Expected: all 4 PASS.

- [ ] **Step 4: Lint + format + commit**

```bash
make lint && make format
git add src/noble_agent/agent/runner.py tests/unit/unified/test_runner.py
git commit -m "feat(unified): run_turn — single-agent LLM/tool loop, no handoffs"
```

## Task 6.2: `TurnRunner` orchestrator

**Files:**
- Create: `src/noble_agent/agent/orchestrator.py`
- Test: extend `tests/unit/unified/test_runner.py` with orchestrator-level cases

- [ ] **Step 1: Write failing tests** (append to `test_runner.py`)

```python
import asyncio
from datetime import UTC, datetime

import fakeredis.aioredis

from noble_agent.agent.orchestrator import TurnRunner
from noble_agent.config import UnifiedSettings
from noble_agent.storage.models import Meta
from noble_agent.storage.repo import StateRepo


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def repo(redis):
    return StateRepo(redis_client=redis, ttl_seconds=3600)


@pytest.fixture
def settings():
    return UnifiedSettings(USE_UNIFIED_AGENT=True, NOBLE_SUMMARY_K=4, NOBLE_SUMMARY_KEEP_TAIL=2)


async def test_handle_turn_persists_history(agent, repo, settings):
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("hi!", []))
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=settings)

    await runner.handle_turn("sid-A", "xin chào", _Sink())

    _, _, state = await repo.load("sid-A")
    assert len(state.history) >= 2
    assert state.history[0].role == "user"
    assert state.history[-1].role == "assistant"


async def test_handle_turn_schedules_summary_when_history_exceeds_K(agent, repo, settings, monkeypatch):
    # Pre-seed history so the first new turn pushes past K.
    now = datetime.now(UTC)
    big_state = State(history=[ThreadMessage(role="user", content=f"old{i}") for i in range(6)])
    await repo.save_all(
        "sid-B",
        Meta(session_id="sid-B", started_at=now, last_active=now),
        Customer(), big_state,
    )

    summarize_called = asyncio.Event()

    async def fake_summarize(**kwargs):
        summarize_called.set()

    monkeypatch.setattr(
        "noble_agent.agent.orchestrator.summarize_and_persist",
        fake_summarize,
    )

    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("ok", []))
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=settings)

    await runner.handle_turn("sid-B", "câu mới", _Sink())
    # Background task should have been scheduled and run.
    await asyncio.wait_for(summarize_called.wait(), timeout=1.0)
```

Run: `pytest tests/unit/unified/test_runner.py -v`
Expected: FAIL (no `orchestrator` module).

- [ ] **Step 2: Implement `TurnRunner`**

`src/noble_agent/agent/orchestrator.py`:

```python
"""TurnRunner — entry per user turn. Single-agent, no handoff chain."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Protocol

from noble_agent.agent.runner import run_turn
from noble_agent.agent.summary.summarizer import summarize_and_persist
from noble_agent.agent.tools.dispatcher import ToolDispatcher
from noble_agent.storage.models import ThreadMessage

logger = logging.getLogger("noble_agent.orchestrator")


class TurnCallbacks(Protocol):
    async def on_token(self, token: str) -> None: ...
    async def on_tool_start(self, name: str, args: dict) -> None: ...
    async def on_tool_done(self, name: str, result: str) -> None: ...
    async def on_agent_switch(self, *, from_: str, to: str, reason: str) -> None: ...
    async def on_done(self) -> None: ...


class TurnRunner:
    def __init__(
        self, *, repo, agent_def, llm, rag, settings, transcript_writer=None
    ):
        self._repo = repo
        self._agent = agent_def
        self._llm = llm
        self._rag = rag
        self._settings = settings
        self._transcript = transcript_writer

    async def handle_turn(
        self, sid: str, user_text: str, callbacks: TurnCallbacks
    ) -> None:
        meta, customer, state = await self._repo.load(sid)
        state.history.append(ThreadMessage(role="user", content=user_text))

        dispatcher = ToolDispatcher(
            state=state, customer=customer, rag=self._rag,
            callbacks=callbacks, session_id=sid,
        )

        try:
            await run_turn(
                agent=self._agent, state=state, customer=customer,
                llm=self._llm, dispatcher=dispatcher, callbacks=callbacks,
            )
        finally:
            meta.last_active = datetime.now(UTC)
            await self._repo.save_all(sid, meta, customer, state)

        pending = len(state.history) - (
            state.summary.covers_turns if state.summary else 0
        )
        if pending > self._settings.summary_threshold_K:
            asyncio.create_task(
                summarize_and_persist(
                    sid=sid,
                    history=list(state.history),
                    prior_summary=state.summary,
                    llm=self._llm,
                    repo=self._repo,
                    model=self._settings.summary_model,
                    keep_tail=self._settings.summary_keep_tail,
                )
            )

        if self._transcript is not None:
            try:
                await self._transcript.write_session_async(
                    session_id=sid, customer=customer, state=state
                )
            except Exception:
                logger.exception("orchestrator: transcript writer failed")

        await callbacks.on_done()
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/unified/test_runner.py -v
```
Expected: all PASS (orchestrator tests pass; existing run_turn tests still pass).

- [ ] **Step 4: Lint + format + commit**

```bash
make lint && make format
git add src/noble_agent/agent/orchestrator.py tests/unit/unified/test_runner.py
git commit -m "feat(unified): TurnRunner — single-turn orchestrator with async summary"
```

## Task 6.3: `NobleAgent` facade

**Files:**
- Create: `src/noble_agent/agent/facade.py`
- Test: `tests/unit/unified/test_facade.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/unified/test_facade.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from noble_agent.agent.facade import NobleAgent


@pytest.fixture
def runner():
    r = MagicMock()
    r.handle_turn = AsyncMock()
    r._settings = MagicMock()
    r._repo = MagicMock()
    r._repo._redis = AsyncMock()
    return r


async def test_stream_response_collects_tokens(runner):
    async def fake_handle_turn(sid, text, cb):
        await cb.on_token("hello ")
        await cb.on_token("world")
        await cb.on_done()

    runner.handle_turn = AsyncMock(side_effect=fake_handle_turn)
    agent = NobleAgent(session_id="s1", runner=runner)
    out = await agent.stream_response("hi")
    assert out == "hello world"


async def test_stream_response_invokes_legacy_sync_callbacks(runner):
    received = []

    async def fake_handle_turn(sid, text, cb):
        await cb.on_token("ab")
        await cb.on_tool_start("noble_search", {"query": "x"})
        await cb.on_tool_done("noble_search", "{}")

    runner.handle_turn = AsyncMock(side_effect=fake_handle_turn)
    agent = NobleAgent(session_id="s1", runner=runner)

    def on_token(t): received.append(("tok", t))
    def on_tool_start(name, args): received.append(("start", name))
    def on_tool_done(name, res): received.append(("done", name))

    await agent.stream_response(
        "hi", on_token=on_token, on_tool_start=on_tool_start, on_tool_done=on_tool_done
    )
    assert ("tok", "ab") in received
    assert ("start", "noble_search") in received
    assert ("done", "noble_search") in received


async def test_on_agent_switch_kwarg_is_accepted_but_inert(runner):
    runner.handle_turn = AsyncMock()
    agent = NobleAgent(session_id="s1", runner=runner)
    # Passing on_agent_switch must not raise.
    await agent.stream_response("hi", on_agent_switch=lambda **kw: None)


async def test_current_agent_attribute_is_constant(runner):
    agent = NobleAgent(session_id="s1", runner=runner)
    assert agent._current_agent == "unified"


async def test_reset_deletes_session_keys(runner):
    agent = NobleAgent(session_id="abc", runner=runner)
    await agent.reset()
    runner._repo._redis.delete.assert_awaited_once()
    args = runner._repo._redis.delete.call_args.args
    assert "session:abc:meta" in args
    assert "session:abc:customer" in args
    assert "session:abc:state" in args


async def test_refresh_system_prompt_is_noop(runner):
    agent = NobleAgent(session_id="s1", runner=runner)
    assert await agent.refresh_system_prompt() is None


def test_set_interrupt_context_is_noop(runner):
    agent = NobleAgent(session_id="s1", runner=runner)
    assert agent.set_interrupt_context(anything=1) is None
```

Run: `pytest tests/unit/unified/test_facade.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement facade**

`src/noble_agent/agent/facade.py`:

```python
"""Drop-in NobleAgent facade for transport (text_chat, voice loop).

Mirrors the legacy StreamingLLM / refactor NobleAgent callable surface so
transport code passes sync callbacks unchanged.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from noble_agent.agent.base import load_agent_def
from noble_agent.agent.llm.client import StreamingClient
from noble_agent.agent.orchestrator import TurnRunner
from noble_agent.agent.qwen_transcript import TranscriptWriter
from noble_agent.config import get_settings
from noble_agent.storage.redis_client import get_redis
from noble_agent.storage.repo import StateRepo

logger = logging.getLogger("noble_agent.facade")

_runner_singleton: TurnRunner | None = None
_runner_lock = asyncio.Lock()


def _model_override() -> str | None:
    return os.getenv("OPENAI_MODEL") or None


async def _build_runner() -> TurnRunner:
    settings = get_settings()
    defs_dir = Path(__file__).resolve().parent / "definitions"
    agent_def = load_agent_def(defs_dir)

    if (override := _model_override()):
        from dataclasses import replace
        agent_def = replace(agent_def, model=override)
        logger.info("facade: OPENAI_MODEL override → %s", override)

    providers: list[tuple[str, object]] = []

    if (anthropic_key := os.getenv("ANTHROPIC_API_KEY")):
        try:
            from noble_agent.agent.llm.anthropic_provider import AnthropicProvider
            providers.append((
                "anthropic",
                AnthropicProvider(
                    api_key=anthropic_key,
                    model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
                    base_url=os.getenv("ANTHROPIC_BASE_URL") or None,
                ),
            ))
        except ImportError:
            logger.error("anthropic SDK not installed — skipping")

    try:
        import openai
        if (openai_key := os.getenv("OPENAI_API_KEY")):
            kwargs: dict[str, Any] = {"api_key": openai_key}
            if (base := os.getenv("OPENAI_BASE_URL")):
                kwargs["base_url"] = base
            providers.append(("openai", openai.AsyncOpenAI(**kwargs)))
        if os.getenv("GEMINI_API_KEY"):
            providers.append((
                "gemini",
                openai.AsyncOpenAI(
                    api_key=os.getenv("GEMINI_API_KEY"),
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                ),
            ))
    except ImportError:
        logger.error("openai SDK not installed")

    if not providers:
        raise RuntimeError(
            "No LLM providers configured (ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY)"
        )
    logger.info("facade: LLM provider order = %s", " → ".join(n for n, _ in providers))

    llm = StreamingClient(providers=providers)
    redis_client = await get_redis()
    repo = StateRepo(
        redis_client=redis_client, ttl_seconds=settings.session_ttl_seconds
    )

    transcript_writer: TranscriptWriter | None = None
    if settings.transcript_log_enabled:
        transcript_writer = TranscriptWriter(settings.transcript_log_dir, agent_def)
        logger.info("facade: transcript logging → %s", settings.transcript_log_dir)

    return TurnRunner(
        repo=repo, agent_def=agent_def, llm=llm,
        rag=None,  # RAG wired by noble_search tool itself, no adapter needed for phase 1
        settings=settings, transcript_writer=transcript_writer,
    )


async def _get_runner() -> TurnRunner:
    global _runner_singleton
    if _runner_singleton is not None:
        return _runner_singleton
    async with _runner_lock:
        if _runner_singleton is None:
            _runner_singleton = await _build_runner()
    return _runner_singleton


async def _maybe_await(fn: Callable | None, *args, **kwargs):
    if fn is None:
        return
    try:
        result = fn(*args, **kwargs)
    except TypeError:
        try:
            result = fn()
        except Exception:
            logger.exception("facade: callback raised")
            return
    if inspect.isawaitable(result):
        await result


class _Callbacks:
    def __init__(self, *, on_token, on_tool_start, on_tool_done, sink):
        self._on_token = on_token
        self._on_tool_start = on_tool_start
        self._on_tool_done = on_tool_done
        self._sink = sink

    async def on_token(self, token: str):
        self._sink.append(token)
        await _maybe_await(self._on_token, token)

    async def on_tool_start(self, name: str, args: dict):
        await _maybe_await(self._on_tool_start, name, args)

    async def on_tool_done(self, name: str, result: str):
        await _maybe_await(self._on_tool_done, name, result)

    async def on_agent_switch(self, *, from_, to, reason):  # never fired
        pass

    async def on_done(self):
        pass


class NobleAgent:
    def __init__(self, session_id: str, runner: TurnRunner):
        self.session_id = session_id
        self._runner = runner
        self._current_agent: str = "unified"

    @classmethod
    async def create(cls, session_id: str, customer: dict | None = None) -> NobleAgent:
        runner = await _get_runner()
        return cls(session_id=session_id, runner=runner)

    async def stream_response(
        self,
        user_text: str,
        on_token: Callable | None = None,
        on_tool_start: Callable | None = None,
        on_tool_done: Callable | None = None,
        interrupt_check: Callable[[], bool] | None = None,  # not honored in phase 1
        on_agent_switch: Callable | None = None,            # never fired
        **_legacy_ignored,
    ) -> str:
        sink: list[str] = []
        cb = _Callbacks(
            on_token=on_token, on_tool_start=on_tool_start,
            on_tool_done=on_tool_done, sink=sink,
        )
        await self._runner.handle_turn(self.session_id, user_text, cb)
        return "".join(sink)

    async def reset(self) -> None:
        try:
            redis = self._runner._repo._redis
            sid = self.session_id
            await redis.delete(
                f"session:{sid}:meta",
                f"session:{sid}:customer",
                f"session:{sid}:state",
            )
        except Exception:
            logger.exception("facade.reset: failed to delete session keys")

    async def refresh_system_prompt(self) -> None:
        return None

    def set_interrupt_context(self, **_kwargs) -> None:
        return None


def reset_runner_for_tests() -> None:
    global _runner_singleton
    _runner_singleton = None
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/unified/test_facade.py -v
```
Expected: all PASS.

- [ ] **Step 4: Run full unified unit suite**

```bash
pytest tests/unit/unified -v
```
Expected: all PASS.

- [ ] **Step 5: Lint + format + commit**

```bash
make lint && make format
git add src/noble_agent/agent/facade.py tests/unit/unified/test_facade.py
git commit -m "feat(unified): NobleAgent facade — drop-in for transport, no agent switching"
```

---

# Phase 7 — Service layer migration (mechanical copies)

## Task 7.1: Copy `voice/`, `telephony/`, `transport/`, `services/`, `metrics/`

**Files:**
- Copy `src/noble_agent/{voice,telephony,transport,services,metrics}/` to `src/noble_agent/<same>/`

- [ ] **Step 1: Copy directories**

```bash
cp -r src/noble_agent/voice/ src/noble_agent/voice/
cp -r src/noble_agent/telephony/ src/noble_agent/telephony/
cp -r src/noble_agent/transport/ src/noble_agent/transport/
cp -r src/noble_agent/services/ src/noble_agent/services/
cp -r src/noble_agent/metrics/ src/noble_agent/metrics/
```

- [ ] **Step 2: Drop legacy `__pycache__` directories**

```bash
find src/noble_agent -type d -name __pycache__ -exec rm -rf {} +
```

- [ ] **Step 3: Rewrite imports across copied dirs**

```bash
find src/noble_agent/voice src/noble_agent/telephony src/noble_agent/transport src/noble_agent/services src/noble_agent/metrics -name '*.py' -exec sed -i \
  's/from noble_agent\.\([a-zA-Z_][a-zA-Z0-9_.]*\)/from noble_agent.\1/g; s/import noble_agent\.\([a-zA-Z_][a-zA-Z0-9_.]*\)/import noble_agent.\1/g' {} +
```

- [ ] **Step 4: Verify no stray `noble_agent.` import remains**

```bash
grep -rn 'noble_agent\.' src/noble_agent/voice src/noble_agent/telephony src/noble_agent/transport src/noble_agent/services src/noble_agent/metrics | grep -v '^Binary' | grep -v 'noble_agent' | head
```
Expected: no output. If lines appear, open the files and fix the leftover imports.

- [ ] **Step 5: Verify imports**

```bash
python -c "from noble_agent import voice, telephony, transport, services, metrics; print('ok')"
```
Expected: `ok`. If `ImportError`, the most common cause is a downstream import inside one of these subpackages that points at `noble_agent.agent.<something>` or `noble_agent.config`. Address each one — most should resolve once Phase 8 is done. For now, comment out broken imports with `# TODO(unified-phase-8): rewire` and proceed. Track them in `git diff`.

- [ ] **Step 6: Commit**

```bash
make lint && make format || true   # lint may complain about unused imports temporarily — proceed
git add src/noble_agent/voice src/noble_agent/telephony src/noble_agent/transport src/noble_agent/services src/noble_agent/metrics
git commit -m "chore(unified): copy voice/telephony/transport/services/metrics from legacy"
```

## Task 7.2: Move + adapt `sentence_buffer.py` and `voice_agent.py`

**Files:**
- Create: `src/noble_agent/voice/sentence_buffer.py` (from `src/noble_agent/agent/sentence_buffer.py`)
- Create: `src/noble_agent/voice/voice_agent.py` (from `src/noble_agent/agent/voice.py` + relevant parts of `src/noble_agent/agent/app.py`)

- [ ] **Step 1: Copy `sentence_buffer.py`**

```bash
cp src/noble_agent/agent/sentence_buffer.py src/noble_agent/voice/sentence_buffer.py
sed -i 's/from noble_agent\./from noble_agent./g; s/import noble_agent\./import noble_agent./g' src/noble_agent/voice/sentence_buffer.py
```

If `noble_agent.agent.sentence_buffer` is imported anywhere else (e.g. in a copied voice file), update those callers to import from `noble_agent.voice.sentence_buffer`:

```bash
grep -rln 'noble_agent\.agent\.sentence_buffer\|from noble_agent\.agent import sentence_buffer' src/noble_agent | while read f; do
  sed -i 's|noble_agent\.agent\.sentence_buffer|noble_agent.voice.sentence_buffer|g; s|from noble_agent\.agent import sentence_buffer|from noble_agent.voice import sentence_buffer|g' "$f"
done
```

- [ ] **Step 2: Copy `voice.py` → `voice_agent.py`**

```bash
cp src/noble_agent/agent/voice.py src/noble_agent/voice/voice_agent.py
sed -i 's/from noble_agent\./from noble_agent./g; s/import noble_agent\./import noble_agent./g' src/noble_agent/voice/voice_agent.py
```

Open `src/noble_agent/voice/voice_agent.py`. Anywhere it imports `StreamingLLM` from a legacy LLM module, replace with `NobleAgent` from `noble_agent.agent.facade`. Specifically:

- Replace `from noble_agent.agent.llm.streaming import StreamingLLM` (or similar) with `from noble_agent.agent.facade import NobleAgent`.
- Replace any `await StreamingLLM.create(session_id, customer)` with `await NobleAgent.create(session_id, customer)`.
- The `stream_response` signature is the same — no other call-site changes should be needed.

If `voice.py` references multi-agent constructs (e.g. `registry`, `MA/CA/SA`, `switch_agent`), remove that code — unified has none of it.

- [ ] **Step 3: Pull entry-point bits from `app.py` if needed**

Open `src/noble_agent/agent/app.py`. Anything that defines the voice-loop entry function (typically `run_voice_session` or similar) but is **not** present in `voice.py` should be appended to `voice_agent.py`. The goal: `voice_agent.py` is a self-contained module the server can import to drive a voice session.

If everything `app.py` does is already covered elsewhere, skip this step.

- [ ] **Step 4: Verify imports**

```bash
python -c "from noble_agent.voice import voice_agent, sentence_buffer; print('ok')"
```
Expected: `ok`. Fix any remaining `ImportError` by tracing the failed module.

- [ ] **Step 5: Commit**

```bash
make lint && make format || true
git add src/noble_agent/voice/sentence_buffer.py src/noble_agent/voice/voice_agent.py src/noble_agent
git commit -m "refactor(unified): move sentence_buffer + voice_agent into voice/"
```

## Task 7.3: Copy `storage/` legacy helpers

**Files:**
- Copy: `src/noble_agent/storage/{connection,session_store,bookings_flat,call_events,call_summaries,noble_profiles,outbound_briefs,outbound_calls,resilience}.py` to `src/noble_agent/storage/`

- [ ] **Step 1: Copy files**

```bash
for f in connection session_store bookings_flat call_events call_summaries noble_profiles outbound_briefs outbound_calls resilience; do
  cp "src/noble_agent/storage/${f}.py" "src/noble_agent/storage/${f}.py"
done
```

- [ ] **Step 2: Rewrite imports**

```bash
find src/noble_agent/storage -name '*.py' ! -name 'models.py' ! -name 'repo.py' ! -name 'redis_client.py' ! -name 'mongo_client.py' -exec sed -i \
  's/from noble_agent\./from noble_agent./g; s/import noble_agent\./import noble_agent./g' {} +
```

- [ ] **Step 3: Verify imports**

```bash
python -c "
from noble_agent.storage import (
    connection, session_store, bookings_flat, call_events,
    call_summaries, noble_profiles, outbound_briefs, outbound_calls, resilience,
)
print('ok')
"
```
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
make lint && make format || true
git add src/noble_agent/storage
git commit -m "chore(unified): copy storage helpers from legacy"
```

---

# Phase 8 — Server wiring + CLI dispatch

## Task 8.1: Copy server files (non-wire-up)

**Files:**
- Copy: `src/noble_agent/server/{__init__,http,base_session,outbound_endpoints,rate_limit,csv_export,logging_config,_websockets_post_patch}.py` to `src/noble_agent/server/`

- [ ] **Step 1: Copy files**

```bash
for f in __init__ http base_session outbound_endpoints rate_limit csv_export logging_config _websockets_post_patch; do
  cp "src/noble_agent/server/${f}.py" "src/noble_agent/server/${f}.py"
done
```

- [ ] **Step 2: Rewrite imports**

```bash
find src/noble_agent/server -maxdepth 1 -name '*.py' -exec sed -i \
  's/from noble_agent\./from noble_agent./g; s/import noble_agent\./import noble_agent./g' {} +
```

- [ ] **Step 3: Verify imports**

```bash
python -c "from noble_agent.server import http, base_session, outbound_endpoints, rate_limit, csv_export, logging_config; print('ok')"
```
Expected: `ok`. Investigate any failures (likely a stale `noble_agent.agent.<something>` reference).

- [ ] **Step 4: Commit**

```bash
make lint && make format || true
git add src/noble_agent/server
git commit -m "chore(unified): copy non-wire-up server files"
```

## Task 8.2: Adapt `server/text_chat.py`

**Files:**
- Create: `src/noble_agent/server/text_chat.py` (from `src/noble_agent/server/text_chat.py`)
- Test: `tests/unit/unified/test_text_chat.py` (light unit test mirroring legacy `tests/unit/test_text_chat.py`)

- [ ] **Step 1: Copy file**

```bash
cp src/noble_agent/server/text_chat.py src/noble_agent/server/text_chat.py
sed -i 's/from noble_agent\./from noble_agent./g; s/import noble_agent\./import noble_agent./g' src/noble_agent/server/text_chat.py
```

- [ ] **Step 2: Switch the agent factory**

Open `src/noble_agent/server/text_chat.py`. Find where the agent is instantiated. In legacy that's something like:

```python
from noble_agent.agent.llm.streaming import StreamingLLM
llm = await StreamingLLM.create(session_id)
```

Replace with:

```python
from noble_agent.agent.facade import NobleAgent
llm = await NobleAgent.create(session_id)
```

The downstream call `llm.stream_response(text, on_token=..., on_tool_start=..., on_tool_done=..., on_agent_switch=...)` works as-is because `NobleAgent.stream_response` has the same signature (with `on_agent_switch` accepted but inert).

- [ ] **Step 3: Write a smoke unit test**

`tests/unit/unified/test_text_chat.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from noble_agent.server.text_chat import is_chat_path, run_text_turn


def test_is_chat_path_true():
    assert is_chat_path("/chat") is True
    assert is_chat_path("/chat/ws") is True


def test_is_chat_path_false():
    assert is_chat_path("/ws/voice") is False
    assert is_chat_path("/health") is False


async def test_run_text_turn_emits_events_in_order():
    agent = MagicMock()

    async def fake_stream_response(text, **callbacks):
        # Simulate the agent calling its callbacks in order.
        if callbacks.get("on_tool_start"):
            callbacks["on_tool_start"]("list_projects", {})
        if callbacks.get("on_token"):
            callbacks["on_token"]("hi")
        if callbacks.get("on_tool_done"):
            callbacks["on_tool_done"]("list_projects", "{}")
        return "hi"

    agent.stream_response = AsyncMock(side_effect=fake_stream_response)

    events = []
    async def send(payload): events.append(payload)

    await run_text_turn(agent=agent, user_text="x", send=send)

    # We at least see a token event and a done event in the sequence.
    types = [e.get("type") for e in events]
    assert "done" in types
```

If `is_chat_path` / `run_text_turn` symbols don't exist in the unified `text_chat.py` (they may be named differently), inspect the file and adjust the test to its actual public API. Keep the principle: assert the path-routing function answers truthfully and assert at least one happy-path turn yields a `done` event.

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/unified/test_text_chat.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
make lint && make format
git add src/noble_agent/server/text_chat.py tests/unit/unified/test_text_chat.py
git commit -m "feat(unified): server/text_chat using NobleAgent facade"
```

## Task 8.3: Adapt `server/session.py` (voice session)

**Files:**
- Create: `src/noble_agent/server/session.py` (from `src/noble_agent/server/session.py`)

- [ ] **Step 1: Copy file**

```bash
cp src/noble_agent/server/session.py src/noble_agent/server/session.py
sed -i 's/from noble_agent\./from noble_agent./g; s/import noble_agent\./import noble_agent./g' src/noble_agent/server/session.py
```

- [ ] **Step 2: Switch the LLM instantiation**

Open `src/noble_agent/server/session.py`. Find the section that creates the per-session LLM/agent (this is the voice session's brain). Replace `StreamingLLM.create(...)` with `NobleAgent.create(...)`:

```python
from noble_agent.agent.facade import NobleAgent
# ...
self.llm = await NobleAgent.create(session_id=self.session_id)
```

Keep the rest of the voice pipeline wiring (STT factory, TTS factory, VAD, turn detection, sentence buffer) unchanged. The sentence buffer import already moved to `voice/sentence_buffer.py` via Task 7.2; verify the import path matches.

- [ ] **Step 3: Verify import**

```bash
python -c "from noble_agent.server import session; print('ok')"
```
Expected: `ok`. If `ImportError`, fix the stale path then retry.

- [ ] **Step 4: Commit**

```bash
make lint && make format
git add src/noble_agent/server/session.py
git commit -m "feat(unified): server/session uses NobleAgent facade for voice loop"
```

## Task 8.4: Adapt `server/ws_handler.py`

**Files:**
- Create: `src/noble_agent/server/ws_handler.py` (from `src/noble_agent/server/ws_handler.py`)

- [ ] **Step 1: Copy file**

```bash
cp src/noble_agent/server/ws_handler.py src/noble_agent/server/ws_handler.py
sed -i 's/from noble_agent\./from noble_agent./g; s/import noble_agent\./import noble_agent./g' src/noble_agent/server/ws_handler.py
```

- [ ] **Step 2: Confirm routing**

Open `src/noble_agent/server/ws_handler.py`. Confirm the `_handle_session` (or equivalent) function:

1. Calls `is_chat_path(path)` (imported from `noble_agent.server.text_chat`) and dispatches `/chat*` to `handle_text_session`.
2. Other paths go through the voice `Session(...)` constructor from `noble_agent.server.session`.

If the file uses different function names, mirror the legacy logic faithfully — change only the import paths.

- [ ] **Step 3: Verify import**

```bash
python -c "from noble_agent.server import ws_handler; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Boot test (no requests yet)**

```bash
USE_UNIFIED_AGENT=true OPENAI_API_KEY=sk-fake python -c "
from noble_agent.server.http import build_app
app = build_app()
print('built:', app)
"
```
Adjust the function name if `build_app` doesn't exist — the goal is to confirm `http.py` can construct the ASGI/HTTP app without exceptions. Iterate on missing imports until success.

- [ ] **Step 5: Commit**

```bash
make lint && make format
git add src/noble_agent/server/ws_handler.py
git commit -m "feat(unified): ws_handler routes /chat and voice paths to unified handlers"
```

## Task 8.5: Wire `pyproject.toml` entry + `.env.example`

**Files:**
- Modify: `pyproject.toml` (change `[project.scripts] noble-agent` target)
- Modify: `.env.example` (add `USE_UNIFIED_AGENT=false` + `NOBLE_SUMMARY_KEEP_TAIL=4`)
- Verify: `scripts/run.sh` (no changes if it just shells `noble-agent`)

- [ ] **Step 1: Locate the legacy entry in `pyproject.toml`**

```bash
grep -n 'noble-agent' pyproject.toml
```

Replace the value (typically `"noble_agent.__main__:main"` or similar) with:

```toml
noble-agent = "noble_agent.__main__:main"
```

- [ ] **Step 2: Append to `.env.example`**

Open `.env.example` and append at the bottom:

```bash
# ── Unified agent (single-agent rewrite) ──────────────────────────────────
# false  → behave as before (legacy or refactor depending on USE_REFACTOR_CORE)
# true   → use src/noble_agent/ — single-agent prompt + 12 tools
USE_UNIFIED_AGENT=false

# Number of recent messages kept verbatim in history after async summary fires.
NOBLE_SUMMARY_KEEP_TAIL=4
```

- [ ] **Step 3: Reinstall package**

```bash
pip install -e ".[dev]"
```

- [ ] **Step 4: Verify CLI dispatches correctly**

```bash
USE_UNIFIED_AGENT=false noble-agent --help 2>&1 | head -5
```
Expected: legacy help text or similar. If the CLI hangs (boot), Ctrl-C and inspect.

```bash
USE_UNIFIED_AGENT=true noble-agent --help 2>&1 | head -5
```
Expected: same legacy help OR unified-specific help — point is, no `ImportError`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .env.example
git commit -m "feat(unified): wire CLI entry + USE_UNIFIED_AGENT env to dispatch through __main__"
```

---

# Phase 9 — Integration tests + manual smoke

## Task 9.1: `conftest.py` for integration

**Files:**
- Create: `tests/integration/unified/conftest.py`

- [ ] **Step 1: Write fixtures**

```python
"""Integration fixtures for unified agent path.

Boots a minimal ASGI app, points it at fakeredis, and stubs LLM responses
deterministically. Tests connect over WebSocket using `httpx` or `websockets`.
"""

from __future__ import annotations

import asyncio
import json
import os

import fakeredis.aioredis
import pytest


@pytest.fixture(autouse=True)
def _force_unified_env(monkeypatch):
    monkeypatch.setenv("USE_UNIFIED_AGENT", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    # Reset cached settings + runner singletons between tests.
    from noble_agent.config import reset_settings_for_tests
    from noble_agent.agent.facade import reset_runner_for_tests
    reset_settings_for_tests()
    reset_runner_for_tests()


@pytest.fixture
async def fake_redis(monkeypatch):
    r = fakeredis.aioredis.FakeRedis()
    async def _get_redis():
        return r
    monkeypatch.setattr("noble_agent.storage.redis_client.get_redis", _get_redis)
    yield r
    await r.aclose()


@pytest.fixture
def stub_llm_responses():
    """Return a list[(content, tool_calls)] that the fake LLM serves in order."""
    return []


@pytest.fixture
def fake_llm(monkeypatch, stub_llm_responses):
    """Replace StreamingClient with a fake that returns prepared responses."""
    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def stream_completion(
            self, *, messages, tools, model, temperature, max_tokens, on_token=None
        ):
            if not stub_llm_responses:
                return ("(no stubbed response)", [])
            content, tool_calls = stub_llm_responses.pop(0)
            if on_token and content:
                for ch in content.split(" "):
                    await on_token(ch + " ")
            return (content, tool_calls)

        async def simple_completion(self, prompt, *, model, max_tokens=400, temperature=0.3):
            return "(stub summary)"

    monkeypatch.setattr("noble_agent.agent.llm.client.StreamingClient", _FakeClient)
    return _FakeClient
```

- [ ] **Step 2: Verify imports**

```bash
python -c "from tests.integration.unified.conftest import _force_unified_env; print('ok')"
```
Expected: `ok` (or at least no import error from the conftest module).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/unified/conftest.py
git commit -m "test(unified): integration fixtures (fake_redis, fake_llm, env override)"
```

## Task 9.2: E2E text chat — single turn

**Files:**
- Create: `tests/integration/unified/test_text_chat_e2e.py`

- [ ] **Step 1: Write test**

```python
"""End-to-end /chat WebSocket: connect, send one message, assert token + done."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from noble_agent.server.http import build_app  # adjust if name differs


@pytest.fixture
def stub_llm_responses():
    return [("Dạ em chào anh, em là Luna ạ", [])]


async def test_one_text_turn_streams_tokens(fake_redis, fake_llm, stub_llm_responses):
    app = build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.websocket_connect("/chat/ws?session=test-1") as ws:
            await ws.send_json({"type": "user_text", "text": "xin chào"})
            received_types = []
            for _ in range(20):
                msg = await ws.receive_json()
                received_types.append(msg.get("type"))
                if msg.get("type") == "done":
                    break
    assert "token" in received_types or any(t.startswith("token") for t in received_types)
    assert "done" in received_types
```

If `httpx`'s `websocket_connect` is not available (depends on version), use the `websockets` lib + spin the ASGI app in a `uvicorn`-style test server. The legacy test suite at `tests/unit/test_text_chat.py` should show the pattern used in this repo — mirror it.

- [ ] **Step 2: Run test**

```bash
pytest tests/integration/unified/test_text_chat_e2e.py -v
```
Expected: PASS. Iterate on import paths, app builder name, and WS message shape until green.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/unified/test_text_chat_e2e.py
git commit -m "test(unified): integration — /chat single turn streams tokens + done"
```

## Task 9.3: Tool-flow integration

**Files:**
- Create: `tests/integration/unified/test_text_chat_tool_flow.py`

- [ ] **Step 1: Write test**

```python
"""Multi-tool turn: agent calls update_customer + list_projects, then replies."""

import json
from unittest.mock import AsyncMock, patch

import pytest


def _tc(name, args, tc_id="c1"):
    return {"id": tc_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


@pytest.fixture
def stub_llm_responses():
    return [
        ("", [
            _tc("update_customer", {"name": "Hùng"}, tc_id="c1"),
            _tc("list_projects", {}, tc_id="c2"),
        ]),
        ("Bên em có Noble Crystal Long Biên và Noble Palace.", []),
    ]


@pytest.fixture
def patch_list_projects():
    # Pretend list_projects always returns 2 projects.
    async def fake_list(args, customer, state, rag, callbacks, session_id):
        return json.dumps({"projects": ["NCLB", "NPLB"]})

    with patch(
        "noble_agent.agent.tools.projects_info.list_projects",
        side_effect=fake_list,
    ):
        yield


async def test_two_tools_then_reply(fake_redis, fake_llm, stub_llm_responses, patch_list_projects):
    # Mirror Task 9.2's setup. Connect, send "Anh tên Hùng, dự án nào?", drain events.
    from httpx import ASGITransport, AsyncClient
    from noble_agent.server.http import build_app
    app = build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with client.websocket_connect("/chat/ws?session=tool-1") as ws:
            await ws.send_json({
                "type": "user_text",
                "text": "Anh tên Hùng, bên em có dự án nào?",
            })
            events = []
            while True:
                msg = await ws.receive_json()
                events.append(msg)
                if msg.get("type") == "done":
                    break

    tool_names = [e.get("name") for e in events if "tool" in (e.get("type") or "")]
    assert "update_customer" in tool_names
    assert "list_projects" in tool_names
```

The `patch_list_projects` path may need adjustment — match it to the exact symbol your unified `projects_info.py` exports. Inspect the file and update.

- [ ] **Step 2: Run test**

```bash
pytest tests/integration/unified/test_text_chat_tool_flow.py -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/unified/test_text_chat_tool_flow.py
git commit -m "test(unified): integration — parallel tool calls then assistant reply"
```

## Task 9.4: Booking-flow integration

**Files:**
- Create: `tests/integration/unified/test_text_chat_booking_flow.py`

- [ ] **Step 1: Write test**

Mirror Task 9.3's structure. The stubbed LLM responses drive the conversation through:

1. User: "Em muốn đặt lịch tham quan Noble Crystal" → LLM emits `booking(action="get_state")`.
2. User: "Thứ Bảy tuần này, 10h sáng" → LLM emits `booking(action="update_info", preferred_date=..., preferred_slot=...)` then `booking(action="check_availability", ...)`.
3. User: "Xác nhận em ơi" → LLM emits `booking(action="schedule", confirmed=true, ...)` then assistant confirmation text.

Each booking call's implementation may need stubbing (`patch` on `noble_agent.agent.tools.booking.booking`) to return canned state transitions. Keep test deterministic and focused on the **dispatch sequence**, not on Mongo writes.

```python
import json
import pytest
from unittest.mock import patch
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def stub_llm_responses():
    def tc(name, args, tc_id):
        return {"id": tc_id, "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)}}
    return [
        # Turn 1
        ("", [tc("booking", {"action": "get_state"}, "c1")]),
        ("Anh/chị muốn xem dự án nào và vào ngày giờ nào ạ?", []),
        # Turn 2
        ("", [
            tc("booking", {"action": "update_info", "preferred_date": "07/06/2026", "preferred_slot": "10:00 - 11:00"}, "c2"),
            tc("booking", {"action": "check_availability", "project_code": "NCLB"}, "c3"),
        ]),
        ("Em còn slot 10:00 ngày 07/06 ạ. Anh/chị xác nhận giúp em nhé.", []),
        # Turn 3
        ("", [tc("booking", {"action": "schedule", "preferred_date": "07/06/2026", "preferred_time": "10:00", "confirmed": True}, "c4")]),
        ("Em đã đặt lịch thứ Bảy 07/06 lúc 10h ạ.", []),
    ]


@pytest.fixture
def stub_booking_tool():
    async def fake_booking(args, customer, state, rag, callbacks, session_id):
        action = args.get("action")
        if action == "get_state":
            return json.dumps({"state": "INIT"})
        if action == "update_info":
            return json.dumps({"state": "PENDING_AVAILABILITY"})
        if action == "check_availability":
            return json.dumps({"slots": ["10:00 - 11:00"]})
        if action == "schedule":
            return json.dumps({"booking_id": "APT001", "status": "CONFIRMED"})
        return json.dumps({})

    with patch("noble_agent.agent.tools.booking.booking", side_effect=fake_booking):
        yield


async def test_three_turn_booking_flow(fake_redis, fake_llm, stub_llm_responses, stub_booking_tool):
    from noble_agent.server.http import build_app
    app = build_app()
    actions = []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with client.websocket_connect("/chat/ws?session=book-1") as ws:
            for text in [
                "Em muốn đặt lịch tham quan Noble Crystal",
                "Thứ Bảy tuần này, 10h sáng",
                "Xác nhận em ơi",
            ]:
                await ws.send_json({"type": "user_text", "text": text})
                while True:
                    msg = await ws.receive_json()
                    if msg.get("type", "").startswith("tool_start"):
                        actions.append(msg.get("args", {}).get("action"))
                    if msg.get("type") == "done":
                        break

    assert actions[0] == "get_state"
    assert "update_info" in actions
    assert "check_availability" in actions
    assert actions[-1] == "schedule"
```

Adjust `actions` extraction to whatever event shape your `text_chat.py` emits for tool calls.

- [ ] **Step 2: Run**

```bash
pytest tests/integration/unified/test_text_chat_booking_flow.py -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/unified/test_text_chat_booking_flow.py
git commit -m "test(unified): integration — 3-turn booking happy path"
```

## Task 9.5: Session resume integration

**Files:**
- Create: `tests/integration/unified/test_session_resume.py`

- [ ] **Step 1: Write test**

```python
"""Reconnect with the same session id — second turn sees first turn's history."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def stub_llm_responses():
    return [
        ("Dạ em chào anh", []),    # first turn response
        ("Dạ anh vừa hỏi gì ạ?", []),  # second turn — assert LLM input contained first turn
    ]


async def test_history_persists_across_reconnect(fake_redis, fake_llm, stub_llm_responses):
    from noble_agent.server.http import build_app
    from noble_agent.storage.redis_client import get_redis
    from noble_agent.storage.repo import StateRepo

    app = build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with client.websocket_connect("/chat/ws?session=resume-1") as ws:
            await ws.send_json({"type": "user_text", "text": "xin chào"})
            while (msg := await ws.receive_json()).get("type") != "done":
                pass

        # New connection, same session id.
        async with client.websocket_connect("/chat/ws?session=resume-1") as ws:
            await ws.send_json({"type": "user_text", "text": "anh hỏi gì rồi nhỉ?"})
            while (msg := await ws.receive_json()).get("type") != "done":
                pass

    r = await get_redis()
    repo = StateRepo(redis_client=r, ttl_seconds=3600)
    _, _, state = await repo.load("resume-1")
    user_texts = [m.content for m in state.history if m.role == "user"]
    assert "xin chào" in user_texts
    assert "anh hỏi gì rồi nhỉ?" in user_texts
```

- [ ] **Step 2: Run**

```bash
pytest tests/integration/unified/test_session_resume.py -v
```
Expected: PASS.

- [ ] **Step 3: Run full unified test suite**

```bash
pytest tests/unit/unified tests/integration/unified -v
```
Expected: all PASS.

- [ ] **Step 4: Add Makefile target**

Open `Makefile`. Append:

```makefile
test-unified:
	pytest tests/unit/unified tests/integration/unified -v
```

- [ ] **Step 5: Commit**

```bash
git add tests/integration/unified/test_session_resume.py Makefile
git commit -m "test(unified): session resume across reconnects + add test-unified make target"
```

## Task 9.6: Manual smoke checklist

Not a code task — a checklist for the user to run after the plan completes. Document it in the README of the unified package.

**Files:**
- Modify: `src/noble_agent/__init__.py` (append a smoke-test docstring at end)

OR create `src/noble_agent/SMOKE.md` (the user can choose; recommend `SMOKE.md` for clarity).

- [ ] **Step 1: Create `src/noble_agent/SMOKE.md`**

```markdown
# Unified agent — manual smoke checklist

Run after setting `USE_UNIFIED_AGENT=true` in `.env`.

- [ ] `scripts/run.sh` boots cleanly (no Python import errors, port 8766 listening).
- [ ] Open `http://localhost:8766/chat`, send a message — assistant streams a response.
- [ ] Send "Anh tên Hùng, muốn tìm hiểu Noble Crystal" — verify `update_customer`
      and a project info tool appear in the trace pane on the left.
- [ ] Reload the chat tab with the same `?session=` URL — history is preserved.
- [ ] Place a voice call via the frontend voice client — Luna answers, speaks,
      tools called over voice still work.
- [ ] Toggle `USE_UNIFIED_AGENT=false`, restart — legacy/refactor path still
      boots and serves both `/chat` and voice.

If anything fails, note it in `docs/refactor/unified-issues.md` for follow-up.
```

- [ ] **Step 2: Commit**

```bash
git add src/noble_agent/SMOKE.md
git commit -m "docs(unified): manual smoke checklist for dev evaluation"
```

---

# Plan complete

After Task 9.6:

```bash
pytest tests/unit/unified tests/integration/unified -v
```

Expected: full green.

```bash
make lint && make format
git status
```

Expected: clean tree.

The unified agent is ready for the user to flip `USE_UNIFIED_AGENT=true` locally and evaluate.

---

## Tasks omitted on purpose

- **Semantic cache port.** The refactor's semcache (`semcache/`) depends on per-agent thread + briefing constructs that the unified path has removed. Re-porting it is a separate spec.
- **Production rollout / canary / metrics.** Spec § 2.2 keeps this out of scope — dev evaluation only.
- **Legacy cleanup.** `noble_agent/` and `noble_agent_refactor/` stay. Removal is a separate spec after the user accepts the unified path.
- **Session migration between paths.** Sessions don't transfer between legacy/refactor and unified schemas. Acceptable for dev.
