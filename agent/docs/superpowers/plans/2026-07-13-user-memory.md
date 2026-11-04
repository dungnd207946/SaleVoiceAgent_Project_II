# User Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Luna per-caller memory keyed by phone — short-term (latest call summary + last K turns injected at bootstrap) and long-term (an agent-invoked `recall_memory` tool over a phone-filtered Qdrant collection of QA-pair points), behind a pluggable `MemoryBackend` interface.

**Architecture:** A new `agent/memory/` subpackage hides all memory behind a `MemoryBackend` interface resolved by `get_memory_backend(settings)`. The v1 impl (`qa_vector`) embeds each user↔assistant exchange as one Qdrant point (dense e5-large, phone in payload), de-duplicates cross-session near-identical points at write time, and reads short-term context from the existing Mongo collections. Two thin async helpers (`record_call_memory`, `short_term_block`) are the only entry points `base_session` and `orchestrator` touch. Everything is gated off by default.

**Tech Stack:** Python 3.11+, pydantic-settings, Qdrant (`qdrant-client`, async), e5-large embeddings (`_Embedder`, remote-capable), MongoDB (motor), pytest (`asyncio_mode=auto`), ruff.

## Global Constraints

- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Run `make lint` + `make format`.
- Tests: `pytest asyncio_mode=auto` — async tests need no `@pytest.mark.asyncio`. New tests must not require Docker/Mongo/Redis/Qdrant (use fakes/monkeypatch).
- Branch: work on the current branch `feat/refactor2`. NEVER touch `develop`. Local commits only; no push/PR/merge without explicit instruction.
- `qdrant-client` is an optional extra (`rag-qdrant`) and MUST stay import-lazy (import inside functions) so `make test-unit` collects without it.
- Heavy imports (`_Embedder`, qdrant, motor) stay function-local.
- Every memory op is best-effort: log-and-continue, never raise into a call. Memory failure must never break a turn or a call.
- Feature is OFF unless `NOBLE_USER_MEMORY_ENABLED=true`. With it off, behavior is byte-identical to today (no new calls, no new imports on the hot path).
- Phone is code-supplied, never an LLM parameter. The `recall_memory` schema exposes only `query`.
- Embedded/dedup template is fixed (do not change the wording — a caller edited it):
  ```
  Khách hỏi: {query}
  Sale trả lời: {answer}
  ```
- Update the CLAUDE.md Change Log in the same commit as the code change that alters a workflow rule / adds the tool (per repo self-maintenance rules) — done in Task 8.

Spec: `docs/superpowers/specs/2026-07-13-user-memory-design.md`.

---

## File Structure

Create:
- `src/noble_agent/agent/memory/__init__.py` — factory `get_memory_backend` + entry helpers `record_call_memory`, `short_term_block`.
- `src/noble_agent/agent/memory/base.py` — `MemoryBackend` Protocol + `MemoryHit` dataclass.
- `src/noble_agent/agent/memory/vector_store.py` — low-level Qdrant `user_memory` ops.
- `src/noble_agent/agent/memory/qa_vector.py` — v1 `QAVectorMemory` + pure `build_qa_pairs`.
- `src/noble_agent/agent/tools/recall_memory.py` — the tool executor.
- Tests: `tests/unit/unified/test_memory_config.py`, `test_memory_factory.py`, `test_memory_vector_store.py`, `test_memory_qa_vector.py`, `test_recall_memory.py`, `test_memory_entry_helpers.py`.

Modify:
- `src/noble_agent/config.py` — 8 settings.
- `src/noble_agent/agent/tools/schemas.py` — add `recall_memory` schema.
- `src/noble_agent/agent/tools/dispatcher.py` — dispatch branch.
- `src/noble_agent/agent/definitions/config.json` — offered tools.
- `src/noble_agent/agent/definitions/RULES.md` — tool-catalog row.
- `src/noble_agent/server/base_session.py` — write path (call end).
- `src/noble_agent/agent/orchestrator.py` — short-term block at bootstrap.
- `tests/unit/unified/test_agent_def.py` — tool count 10 → 11.

---

## Task 1: Config settings

**Files:**
- Modify: `src/noble_agent/config.py` (add a block after the Qdrant settings, ~L455)
- Test: `tests/unit/unified/test_memory_config.py`

**Interfaces:**
- Produces: `settings.user_memory_enabled: bool`, `settings.user_memory_backend: str`, `settings.user_memory_qdrant_collection: str`, `settings.user_memory_short_term_turns: int`, `settings.user_memory_recall_top_k: int`, `settings.user_memory_since_days: int`, `settings.user_memory_dedup_enabled: bool`, `settings.user_memory_dedup_threshold: float`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_memory_config.py`:

```python
import importlib

import noble_agent.config as config_mod


def _fresh_settings(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    importlib.reload(config_mod)
    return config_mod.UnifiedSettings()


def test_user_memory_defaults(monkeypatch):
    for k in (
        "NOBLE_USER_MEMORY_ENABLED",
        "USER_MEMORY_BACKEND",
        "USER_MEMORY_QDRANT_COLLECTION",
        "USER_MEMORY_DEDUP_THRESHOLD",
    ):
        monkeypatch.delenv(k, raising=False)
    s = _fresh_settings(monkeypatch)
    assert s.user_memory_enabled is False
    assert s.user_memory_backend == "qa_vector"
    assert s.user_memory_qdrant_collection == "user_memory"
    assert s.user_memory_short_term_turns == 6
    assert s.user_memory_recall_top_k == 3
    assert s.user_memory_since_days == 30
    assert s.user_memory_dedup_enabled is True
    assert s.user_memory_dedup_threshold == 0.95


def test_user_memory_env_override(monkeypatch):
    s = _fresh_settings(
        monkeypatch,
        NOBLE_USER_MEMORY_ENABLED="true",
        USER_MEMORY_BACKEND="qa_vector",
        USER_MEMORY_SHORT_TERM_TURNS="8",
        USER_MEMORY_DEDUP_THRESHOLD="0.9",
    )
    assert s.user_memory_enabled is True
    assert s.user_memory_short_term_turns == 8
    assert s.user_memory_dedup_threshold == 0.9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_memory_config.py -v`
Expected: FAIL (`AttributeError: 'UnifiedSettings' object has no attribute 'user_memory_enabled'`).

- [ ] **Step 3: Add the settings**

In `src/noble_agent/config.py`, immediately after the Qdrant block (after `tei_url: str = "http://localhost:8080"`, ~L454), add. Note `Field(..., alias=...)` is already imported/used in this file (see `project_registry_refresh_sec`):

```python
    # ── User Memory (per-caller short-term + long-term, keyed by phone) ───────
    # Off by default. Short-term = latest call summary + last K turns injected at
    # bootstrap; long-term = the recall_memory tool over a phone-filtered Qdrant
    # collection of QA-pair points. See docs/.../2026-07-13-user-memory-design.md.
    user_memory_enabled: bool = Field(False, alias="NOBLE_USER_MEMORY_ENABLED")
    user_memory_backend: str = "qa_vector"  # env USER_MEMORY_BACKEND; future: "graph"
    user_memory_qdrant_collection: str = "user_memory"
    user_memory_short_term_turns: int = 6
    user_memory_recall_top_k: int = 3
    user_memory_since_days: int = 30
    user_memory_dedup_enabled: bool = True
    user_memory_dedup_threshold: float = 0.95
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_memory_config.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/config.py tests/unit/unified/test_memory_config.py
git commit -m "feat(memory): user_memory config settings (gated off)"
```

---

## Task 2: MemoryBackend interface + factory

**Files:**
- Create: `src/noble_agent/agent/memory/__init__.py`
- Create: `src/noble_agent/agent/memory/base.py`
- Test: `tests/unit/unified/test_memory_factory.py`

**Interfaces:**
- Consumes: `settings.user_memory_backend` (Task 1).
- Produces:
  - `MemoryHit` dataclass: `query: str`, `answer: str`, `score: float`, `ended_at: int`.
  - `class MemoryBackend(Protocol)` with `async write_call(self, phone, session_id, history, ended_at) -> None`, `async build_short_term_context(self, phone, current_session_id) -> str`, `async recall(self, phone, query, top_k) -> list[MemoryHit]`.
  - `get_memory_backend(settings) -> MemoryBackend` (cached per backend name; unknown → warn + `qa_vector`).
  - `async record_call_memory(settings, *, phone, session_id, history, ended_at) -> None` (guards enabled+phone, swallows errors).
  - `async short_term_block(settings, *, phone, session_id) -> str` (guards enabled+phone, returns "" on skip/error).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_memory_factory.py`:

```python
from types import SimpleNamespace

import noble_agent.agent.memory as memory
from noble_agent.agent.memory.base import MemoryHit


def _settings(**kw):
    base = dict(user_memory_enabled=True, user_memory_backend="qa_vector")
    base.update(kw)
    return SimpleNamespace(**base)


def test_memory_hit_fields():
    h = MemoryHit(query="q", answer="a", score=0.9, ended_at=123)
    assert (h.query, h.answer, h.score, h.ended_at) == ("q", "a", 0.9, 123)


def test_factory_returns_qa_vector_and_caches(monkeypatch):
    memory._backend_cache.clear()
    b1 = memory.get_memory_backend(_settings())
    b2 = memory.get_memory_backend(_settings())
    assert type(b1).__name__ == "QAVectorMemory"
    assert b1 is b2  # cached singleton per backend name


def test_factory_unknown_falls_back(monkeypatch):
    memory._backend_cache.clear()
    b = memory.get_memory_backend(_settings(user_memory_backend="graph"))
    assert type(b).__name__ == "QAVectorMemory"


async def test_record_call_memory_skips_when_disabled(monkeypatch):
    called = False

    def _boom(_s):
        nonlocal called
        called = True
        raise AssertionError("should not be called")

    monkeypatch.setattr(memory, "get_memory_backend", _boom)
    await memory.record_call_memory(_settings(user_memory_enabled=False), phone="0900", session_id="s", history=[], ended_at=None)
    await memory.record_call_memory(_settings(), phone="", session_id="s", history=[], ended_at=None)
    assert called is False


async def test_short_term_block_returns_empty_on_error(monkeypatch):
    class _BE:
        async def build_short_term_context(self, phone, sid):
            raise RuntimeError("qdrant down")

    monkeypatch.setattr(memory, "get_memory_backend", lambda _s: _BE())
    out = await memory.short_term_block(_settings(), phone="0900", session_id="s")
    assert out == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_memory_factory.py -v`
Expected: FAIL (`ModuleNotFoundError: noble_agent.agent.memory`).

- [ ] **Step 3: Create `base.py`**

Create `src/noble_agent/agent/memory/base.py`:

```python
"""MemoryBackend interface + hit type.

All consumers (base_session write, orchestrator short-term, recall_memory tool)
depend ONLY on this Protocol, resolved via get_memory_backend(). A future
version (e.g. LLM-extracted graph memory) implements the same three methods and
is selected by USER_MEMORY_BACKEND — no consumer changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class MemoryHit:
    query: str
    answer: str
    score: float
    ended_at: int  # epoch seconds


class MemoryBackend(Protocol):
    async def write_call(
        self, phone: str, session_id: str, history: list[dict], ended_at: datetime
    ) -> None:
        """Distill + persist memory from a finished call. Best-effort."""
        ...

    async def build_short_term_context(self, phone: str, current_session_id: str) -> str:
        """Return the short-term block injected at bootstrap ("" when nothing)."""
        ...

    async def recall(self, phone: str, query: str, top_k: int) -> list[MemoryHit]:
        """Long-term retrieval scoped to this phone."""
        ...
```

- [ ] **Step 4: Create `__init__.py`**

Create `src/noble_agent/agent/memory/__init__.py`:

```python
"""User-memory subpackage: pluggable per-caller memory keyed by phone.

Entry points used by the rest of the app:
  - get_memory_backend(settings) → the configured MemoryBackend (cached).
  - record_call_memory(...)       → write memory at call end (guarded, safe).
  - short_term_block(...)         → short-term context at bootstrap (guarded, safe).
"""

from __future__ import annotations

import logging
from datetime import datetime

from noble_agent.agent.memory.base import MemoryBackend, MemoryHit

logger = logging.getLogger("noble_agent.agent.memory")

_backend_cache: dict[str, MemoryBackend] = {}


def get_memory_backend(settings) -> MemoryBackend:
    name = (getattr(settings, "user_memory_backend", "") or "qa_vector").strip()
    cached = _backend_cache.get(name)
    if cached is not None:
        return cached
    if name != "qa_vector":
        logger.warning("user_memory: unknown backend %r — falling back to qa_vector", name)
    from noble_agent.agent.memory.qa_vector import QAVectorMemory

    backend = QAVectorMemory(settings)
    _backend_cache[name] = backend
    return backend


async def record_call_memory(
    settings, *, phone: str, session_id: str, history: list[dict], ended_at: datetime
) -> None:
    """Write memory from a finished call. No-op unless enabled + real phone.
    Swallows all errors — memory must never break a call."""
    if not getattr(settings, "user_memory_enabled", False) or not phone:
        return
    try:
        await get_memory_backend(settings).write_call(phone, session_id, history, ended_at)
    except Exception:
        logger.exception("user_memory: record_call_memory failed session=%s", session_id)


async def short_term_block(settings, *, phone: str, session_id: str) -> str:
    """Short-term context block for bootstrap. "" unless enabled + real phone."""
    if not getattr(settings, "user_memory_enabled", False) or not phone:
        return ""
    try:
        return await get_memory_backend(settings).build_short_term_context(phone, session_id)
    except Exception:
        logger.exception("user_memory: short_term_block failed session=%s", session_id)
        return ""


__all__ = ["MemoryBackend", "MemoryHit", "get_memory_backend", "record_call_memory", "short_term_block"]
```

Note: `get_memory_backend` imports `qa_vector` (Task 4). The factory test monkeypatches around the real backend for the guard tests, but `test_factory_returns_qa_vector_and_caches` needs `qa_vector.py` to exist. Implement Task 4 before running the full factory test, OR run only the guard tests now:

- [ ] **Step 5: Run the guard tests (qa_vector not yet present)**

Run: `pytest tests/unit/unified/test_memory_factory.py -v -k "hit or skips or error"`
Expected: PASS (3 passed). The two factory tests will pass after Task 4.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/agent/memory/__init__.py src/noble_agent/agent/memory/base.py tests/unit/unified/test_memory_factory.py
git commit -m "feat(memory): MemoryBackend interface + factory + entry helpers"
```

---

## Task 3: Qdrant vector store

**Files:**
- Create: `src/noble_agent/agent/memory/vector_store.py`
- Test: `tests/unit/unified/test_memory_vector_store.py`

**Interfaces:**
- Consumes: `settings.user_memory_qdrant_collection`; reuses `qdrant_store._get_client()`.
- Produces (all async, module-level functions):
  - `ensure_collection(dim: int = 1024) -> None`
  - `upsert_points(points: list) -> None` — `points` are `qdrant_client.models.PointStruct`.
  - `find_similar(phone: str, vector: list[float], top_k: int = 1) -> list[tuple[str, float]]` — `[(point_id, score)]`.
  - `search(phone: str, vector: list[float], top_k: int) -> list[tuple[str, str, str, float, int]]` — `[(point_id, query, answer, score, ended_at)]`.
  - `phone_filter(phone) -> models.Filter`
  - `make_point(point_id, vector, payload) -> models.PointStruct` helper.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_memory_vector_store.py`:

```python
import pytest

from noble_agent.agent.memory import vector_store as vs


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # vector_store reuses qdrant_store's client singleton; reset it.
    from noble_agent.agent.rag import qdrant_store as qs

    qs._client = None
    yield
    qs._client = None


async def test_search_filters_by_phone_and_maps(monkeypatch):
    class _Pt:
        def __init__(self, pid, payload, score):
            self.id, self.payload, self.score = pid, payload, score

    class _Resp:
        points = [
            _Pt("p1", {"query": "giá NCLB?", "answer": "3 tỷ", "ended_at": 111}, 0.92),
            _Pt("p2", {"query": "vị trí?", "answer": "quận 9", "ended_at": 222}, 0.81),
        ]

    captured = {}

    class _FakeClient:
        async def query_points(self, **kwargs):
            captured.update(kwargs)
            return _Resp()

    monkeypatch.setattr(vs, "_get_client", lambda: _FakeClient())
    out = await vs.search("0900000001", [0.0] * 4, top_k=5)
    assert out == [
        ("p1", "giá NCLB?", "3 tỷ", 0.92, 111),
        ("p2", "vị trí?", "quận 9", 0.81, 222),
    ]
    assert captured["query_filter"] is not None  # phone pre-filter applied


async def test_find_similar_returns_id_score(monkeypatch):
    class _Pt:
        def __init__(self, pid, score):
            self.id, self.score, self.payload = pid, score, {}

    class _Resp:
        points = [_Pt("dup1", 0.97)]

    class _FakeClient:
        async def query_points(self, **kwargs):
            return _Resp()

    monkeypatch.setattr(vs, "_get_client", lambda: _FakeClient())
    out = await vs.find_similar("0900000001", [0.0] * 4, top_k=1)
    assert out == [("dup1", 0.97)]


async def test_search_swallows_errors(monkeypatch):
    class _FakeClient:
        async def query_points(self, **kwargs):
            raise RuntimeError("qdrant down")

    monkeypatch.setattr(vs, "_get_client", lambda: _FakeClient())
    assert await vs.search("0900", [0.0] * 4, top_k=3) == []
    assert await vs.find_similar("0900", [0.0] * 4, top_k=1) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_memory_vector_store.py -v`
Expected: FAIL (`ModuleNotFoundError: ...memory.vector_store`).

- [ ] **Step 3: Create `vector_store.py`**

Create `src/noble_agent/agent/memory/vector_store.py`:

```python
"""Low-level Qdrant store for the app-owned `user_memory` collection.

Dense-only (e5-large 1024d, cosine). One point per QA exchange; `phone` is a
KEYWORD payload field, always used as a pre-filter so a search can only ever see
one caller's points. Reuses the AsyncQdrantClient singleton from qdrant_store.

qdrant-client is imported lazily (optional extra `rag-qdrant`).
"""

from __future__ import annotations

import contextlib
import logging

from noble_agent.config import get_settings

logger = logging.getLogger("noble_agent.agent.memory.vector_store")


def _get_client():
    # Reuse the shared qdrant_store client singleton (same URL/API key).
    from noble_agent.agent.rag import qdrant_store

    return qdrant_store._get_client()


def _collection() -> str:
    return get_settings().user_memory_qdrant_collection


def phone_filter(phone: str):
    from qdrant_client import models

    return models.Filter(must=[models.FieldCondition(key="phone", match=models.MatchValue(value=phone))])


def make_point(point_id: str, vector: list[float], payload: dict):
    from qdrant_client import models

    return models.PointStruct(id=point_id, vector=vector, payload=payload)


async def ensure_collection(dim: int = 1024) -> None:
    """Create the collection + `phone` payload index if absent. Best-effort."""
    from qdrant_client import models

    client = _get_client()
    coll = _collection()
    try:
        if await client.collection_exists(coll):
            return
        await client.create_collection(
            collection_name=coll,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )
        await client.create_payload_index(coll, field_name="phone", field_schema=models.PayloadSchemaType.KEYWORD)
        logger.info("[user_memory] created collection %s (dim=%d)", coll, dim)
    except Exception as exc:
        logger.warning("[user_memory] ensure_collection failed: %s", exc)


async def upsert_points(points: list) -> None:
    """Upsert prepared PointStructs. Best-effort."""
    if not points:
        return
    try:
        await _get_client().upsert(collection_name=_collection(), points=points)
    except Exception as exc:
        logger.warning("[user_memory] upsert failed: %s", exc)


async def find_similar(phone: str, vector: list[float], top_k: int = 1) -> list[tuple[str, float]]:
    """Search BY VECTOR (dedup path), phone pre-filtered → [(point_id, score)]."""
    try:
        resp = await _get_client().query_points(
            collection_name=_collection(),
            query=vector,
            query_filter=phone_filter(phone),
            limit=top_k,
            with_payload=False,
        )
        return [(str(p.id), float(p.score)) for p in resp.points]
    except Exception as exc:
        logger.warning("[user_memory] find_similar failed: %s", exc)
        return []


async def search(phone: str, vector: list[float], top_k: int) -> list[tuple[str, str, str, float, int]]:
    """Semantic search within a phone → [(point_id, query, answer, score, ended_at)]."""
    try:
        resp = await _get_client().query_points(
            collection_name=_collection(),
            query=vector,
            query_filter=phone_filter(phone),
            limit=top_k,
            with_payload=True,
        )
        out: list[tuple[str, str, str, float, int]] = []
        for p in resp.points:
            pl = p.payload or {}
            out.append(
                (str(p.id), pl.get("query", ""), pl.get("answer", ""), float(p.score), int(pl.get("ended_at", 0)))
            )
        return out
    except Exception as exc:
        logger.warning("[user_memory] search failed: %s", exc)
        return []


async def close() -> None:
    from noble_agent.agent.rag import qdrant_store

    with contextlib.suppress(Exception):
        await qdrant_store.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_memory_vector_store.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/memory/vector_store.py tests/unit/unified/test_memory_vector_store.py
git commit -m "feat(memory): Qdrant user_memory vector store (dense + phone pre-filter)"
```

---

## Task 4: QAVectorMemory (v1 backend)

**Files:**
- Create: `src/noble_agent/agent/memory/qa_vector.py`
- Test: `tests/unit/unified/test_memory_qa_vector.py`

**Interfaces:**
- Consumes: `vector_store` (Task 3); `MemoryHit` (Task 2); settings from Task 1; existing DAOs `call_summaries.load_last_summary_by_phone`, `call_summaries.list_summaries`, `agent_messages.get_session_messages`; `flat_store._Embedder`.
- Produces:
  - `build_qa_pairs(history: list[dict]) -> list[tuple[str, str]]` — pure; `[(query, answer)]`.
  - `PAIR_TEMPLATE = "Khách hỏi: {query}\nSale trả lời: {answer}"`.
  - `class QAVectorMemory` implementing `MemoryBackend` (`__init__(self, settings)`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_memory_qa_vector.py`:

```python
from types import SimpleNamespace

import pytest

from noble_agent.agent.memory import qa_vector
from noble_agent.agent.memory.qa_vector import QAVectorMemory, build_qa_pairs


def _settings(**kw):
    base = dict(
        user_memory_enabled=True,
        user_memory_backend="qa_vector",
        user_memory_qdrant_collection="user_memory",
        user_memory_short_term_turns=4,
        user_memory_recall_top_k=3,
        user_memory_since_days=30,
        user_memory_dedup_enabled=True,
        user_memory_dedup_threshold=0.95,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_build_qa_pairs_pairs_user_then_assistant():
    history = [
        {"role": "user", "content": "giá NCLB?"},
        {"role": "assistant", "content": "khoảng 3 tỷ"},
        {"role": "user", "content": "vị trí?"},
        {"role": "tool", "content": "{}"},
        {"role": "assistant", "content": "ở quận 9"},
    ]
    assert build_qa_pairs(history) == [("giá NCLB?", "khoảng 3 tỷ"), ("vị trí?", "ở quận 9")]


def test_build_qa_pairs_skips_empty_and_unpaired():
    history = [
        {"role": "user", "content": ""},
        {"role": "assistant", "content": "xin chào"},   # no preceding non-empty user
        {"role": "user", "content": "còn suất không?"},  # no following assistant
    ]
    assert build_qa_pairs(history) == []


async def test_write_call_dedup_reuses_existing_id(monkeypatch):
    upserted: list = []

    async def _find_similar(phone, vec, top_k=1):
        return [("existing-id", 0.99)]  # above threshold → dedup

    async def _upsert(points):
        upserted.extend(points)

    async def _ensure(dim=1024):
        return None

    monkeypatch.setattr(qa_vector.vector_store, "find_similar", _find_similar)
    monkeypatch.setattr(qa_vector.vector_store, "upsert_points", _upsert)
    monkeypatch.setattr(qa_vector.vector_store, "ensure_collection", _ensure)
    monkeypatch.setattr(qa_vector.vector_store, "make_point", lambda pid, vec, pl: {"id": pid, "payload": pl})

    mem = QAVectorMemory(_settings())
    monkeypatch.setattr(mem, "_embed_docs", lambda texts: [[0.0, 1.0] for _ in texts])

    from datetime import datetime, UTC

    await mem.write_call("0900", "sess-1", [
        {"role": "user", "content": "giá?"},
        {"role": "assistant", "content": "3 tỷ"},
    ], datetime(2026, 7, 13, tzinfo=UTC))

    assert len(upserted) == 1
    assert upserted[0]["id"] == "existing-id"  # reused, not a new blake2b id
    assert upserted[0]["payload"]["phone"] == "0900"


async def test_write_call_new_id_when_below_threshold(monkeypatch):
    upserted: list = []
    monkeypatch.setattr(qa_vector.vector_store, "find_similar", lambda p, v, top_k=1: _async([]))
    monkeypatch.setattr(qa_vector.vector_store, "upsert_points", lambda points: _async(upserted.extend(points)))
    monkeypatch.setattr(qa_vector.vector_store, "ensure_collection", lambda dim=1024: _async(None))
    monkeypatch.setattr(qa_vector.vector_store, "make_point", lambda pid, vec, pl: {"id": pid, "payload": pl})

    mem = QAVectorMemory(_settings())
    monkeypatch.setattr(mem, "_embed_docs", lambda texts: [[1.0, 0.0] for _ in texts])

    from datetime import datetime, UTC

    await mem.write_call("0900", "sess-9", [
        {"role": "user", "content": "vị trí?"},
        {"role": "assistant", "content": "quận 9"},
    ], datetime(2026, 7, 13, tzinfo=UTC))
    assert upserted[0]["id"] != "existing-id"  # deterministic blake2b(sess-9:0)


async def test_recall_maps_hits(monkeypatch):
    async def _search(phone, vec, top_k):
        return [("p1", "giá?", "3 tỷ", 0.9, 111)]

    monkeypatch.setattr(qa_vector.vector_store, "search", _search)
    mem = QAVectorMemory(_settings())
    monkeypatch.setattr(mem, "_embed_query", lambda q: [0.1, 0.2])
    hits = await mem.recall("0900", "giá bao nhiêu", top_k=3)
    assert hits[0].query == "giá?" and hits[0].answer == "3 tỷ" and hits[0].ended_at == 111


async def test_build_short_term_empty_when_no_history(monkeypatch):
    monkeypatch.setattr(qa_vector, "load_last_summary_by_phone", lambda phone, since_days=30: _async(None))
    monkeypatch.setattr(qa_vector, "list_summaries", lambda phone, limit=5: _async([]))
    mem = QAVectorMemory(_settings())
    assert await mem.build_short_term_context("0900", "sess-cur") == ""


async def test_build_short_term_renders_block(monkeypatch):
    async def _summary(phone, since_days=30):
        return {"summary": "KH hỏi giá NCLB, đã tư vấn.", "open_actions": [{"action": "gửi bảng giá"}]}

    async def _list(phone, limit=5):
        return [{"session_id": "sess-prev", "ended_at": 1}, {"session_id": "sess-cur", "ended_at": 2}]

    async def _msgs(sid):
        return [{"role": "caller", "content": "giá NCLB?"}, {"role": "agent", "content": "3 tỷ"}]

    monkeypatch.setattr(qa_vector, "load_last_summary_by_phone", _summary)
    monkeypatch.setattr(qa_vector, "list_summaries", _list)
    monkeypatch.setattr(qa_vector, "get_session_messages", _msgs)

    mem = QAVectorMemory(_settings())
    block = await mem.build_short_term_context("0900", "sess-cur")
    assert "lần gọi trước" in block.lower()
    assert "NCLB" in block


def _async(value):
    async def _coro():
        return value
    return _coro()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_memory_qa_vector.py -v`
Expected: FAIL (`ModuleNotFoundError: ...memory.qa_vector`).

- [ ] **Step 3: Create `qa_vector.py`**

Create `src/noble_agent/agent/memory/qa_vector.py`:

```python
"""v1 memory backend: QA-pair vectors on Qdrant + short-term from Mongo.

- write_call: history → QA pairs → embed → dedup (refresh existing near-dup
  point) → upsert to Qdrant `user_memory`.
- build_short_term_context: latest call summary (call_summaries) + last K turns
  of the most recent PRIOR session (agent_messages, 2-hop via call_summaries).
- recall: embed query → phone-filtered dense search → MemoryHit list.

Heavy imports (embedder) are function-local. All Qdrant ops are best-effort in
vector_store; this layer additionally guards embedding.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime

from noble_agent.agent.memory import vector_store
from noble_agent.agent.memory.base import MemoryHit
from noble_agent.storage.agent_messages import get_session_messages
from noble_agent.storage.call_summaries import list_summaries, load_last_summary_by_phone

logger = logging.getLogger("noble_agent.agent.memory.qa_vector")

PAIR_TEMPLATE = "Khách hỏi: {query}\nSale trả lời: {answer}"

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from noble_agent.agent.rag.flat_store import _Embedder

        _embedder = _Embedder()
    return _embedder


def build_qa_pairs(history: list[dict]) -> list[tuple[str, str]]:
    """Pair each non-empty user message with the NEXT non-empty assistant text.
    Skips system/tool and empty content. Pure function."""
    pairs: list[tuple[str, str]] = []
    pending_q: str | None = None
    for m in history:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            pending_q = content
        elif role == "assistant" and pending_q is not None:
            pairs.append((pending_q, content))
            pending_q = None
        # system/tool ignored
    return pairs


class QAVectorMemory:
    def __init__(self, settings) -> None:
        self._s = settings

    # ── embedding (run off the event loop) ────────────────────────────────
    def _embed_docs(self, texts: list[str]) -> list[list[float]]:
        return _get_embedder().encode_batch(texts, show_progress=False, is_query=False).tolist()

    def _embed_query(self, query: str) -> list[float]:
        return _get_embedder().encode_query(query).tolist()

    # ── write ─────────────────────────────────────────────────────────────
    async def write_call(self, phone: str, session_id: str, history: list[dict], ended_at: datetime) -> None:
        pairs = build_qa_pairs(history)
        if not pairs:
            return
        texts = [PAIR_TEMPLATE.format(query=q, answer=a) for q, a in pairs]
        vectors = await asyncio.to_thread(self._embed_docs, texts)
        await vector_store.ensure_collection(dim=len(vectors[0]) if vectors else 1024)
        ended_ts = int(ended_at.timestamp())
        dedup = bool(getattr(self._s, "user_memory_dedup_enabled", True))
        threshold = float(getattr(self._s, "user_memory_dedup_threshold", 0.95))
        for idx, ((q, a), vec) in enumerate(zip(pairs, vectors)):
            point_id = hashlib.blake2b(f"{session_id}:{idx}".encode(), digest_size=16).hexdigest()
            if dedup:
                similar = await vector_store.find_similar(phone, vec, top_k=1)
                if similar and similar[0][1] >= threshold:
                    point_id = similar[0][0]  # refresh existing point (latest wins)
            payload = {
                "phone": phone,
                "session_id": session_id,
                "ended_at": ended_ts,
                "query": q,
                "answer": a,
            }
            await vector_store.upsert_points([vector_store.make_point(point_id, vec, payload)])

    # ── recall ────────────────────────────────────────────────────────────
    async def recall(self, phone: str, query: str, top_k: int) -> list[MemoryHit]:
        vec = await asyncio.to_thread(self._embed_query, query)
        rows = await vector_store.search(phone, vec, top_k)
        return [MemoryHit(query=q, answer=a, score=score, ended_at=ended) for (_id, q, a, score, ended) in rows]

    # ── short-term ─────────────────────────────────────────────────────────
    async def build_short_term_context(self, phone: str, current_session_id: str) -> str:
        since_days = int(getattr(self._s, "user_memory_since_days", 30))
        k = int(getattr(self._s, "user_memory_short_term_turns", 6))
        summary = await load_last_summary_by_phone(phone, since_days)

        prior_sid = await self._latest_prior_session(phone, current_session_id)
        turns: list[dict] = []
        if prior_sid:
            all_msgs = await get_session_messages(prior_sid)
            turns = all_msgs[-k:] if len(all_msgs) > k else all_msgs

        return self._render(summary, turns)

    async def _latest_prior_session(self, phone: str, current_session_id: str) -> str | None:
        try:
            rows = await list_summaries(phone, limit=5)  # newest first (sorted by ended_at desc)
        except Exception:
            return None
        for row in rows:
            sid = row.get("session_id", "")
            if sid and sid != current_session_id:
                return sid
        return None

    @staticmethod
    def _render(summary: dict | None, turns: list[dict]) -> str:
        if not summary and not turns:
            return ""
        lines = ["## Bối cảnh lần gọi trước"]
        if summary:
            text = (summary.get("summary") or "").strip()
            if text:
                lines.append(f"Tóm tắt: {text}")
            actions = summary.get("open_actions") or []
            action_texts = [a.get("action", "") if isinstance(a, dict) else str(a) for a in actions]
            action_texts = [t for t in action_texts if t]
            if action_texts:
                lines.append("Việc còn dang dở: " + "; ".join(action_texts))
        if turns:
            lines.append("Vài lượt gần nhất:")
            for m in turns:
                role = m.get("role", "")
                who = "Khách" if role == "caller" else "Luna" if role == "agent" else role
                content = (m.get("content") or "").strip()
                if content:
                    lines.append(f"- {who}: {content[:200]}")
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests (this task + the deferred factory tests)**

Run: `pytest tests/unit/unified/test_memory_qa_vector.py tests/unit/unified/test_memory_factory.py -v`
Expected: PASS (all — the two `test_factory_*` cases now pass since `qa_vector` exists).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/memory/qa_vector.py tests/unit/unified/test_memory_qa_vector.py
git commit -m "feat(memory): QAVectorMemory v1 (QA pairs, dedup, short-term, recall)"
```

---

## Task 5: `recall_memory` tool (5 seams)

**Files:**
- Create: `src/noble_agent/agent/tools/recall_memory.py`
- Modify: `src/noble_agent/agent/tools/schemas.py` (add schema to `SCHEMAS`)
- Modify: `src/noble_agent/agent/tools/dispatcher.py` (import + branch)
- Modify: `src/noble_agent/agent/definitions/config.json` (add to `tools`)
- Modify: `src/noble_agent/agent/definitions/RULES.md` (tool-catalog row)
- Modify: `tests/unit/unified/test_agent_def.py` (10 → 11)
- Test: `tests/unit/unified/test_recall_memory.py`

**Interfaces:**
- Consumes: `get_memory_backend` / `MemoryHit` (Task 2), `settings` (Task 1).
- Produces: `recall_memory.run(customer, args) -> str`; dispatcher branch `name == "recall_memory"`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_recall_memory.py`:

```python
import json
from types import SimpleNamespace

import pytest

from noble_agent.agent.tools import recall_memory
from noble_agent.agent.memory.base import MemoryHit


async def test_run_returns_no_data_without_phone(monkeypatch):
    customer = SimpleNamespace(phone="")
    out = await recall_memory.run(customer, {"query": "giá NCLB"})
    assert "lịch sử" in out.lower()


async def test_run_injects_phone_from_customer_not_args(monkeypatch):
    seen = {}

    class _BE:
        async def recall(self, phone, query, top_k):
            seen["phone"] = phone
            seen["query"] = query
            return [MemoryHit("giá?", "3 tỷ", 0.9, 111)]

    monkeypatch.setattr(recall_memory, "get_memory_backend", lambda _s: _BE())
    monkeypatch.setattr(recall_memory, "get_settings", lambda: SimpleNamespace(user_memory_recall_top_k=3))
    customer = SimpleNamespace(phone="0900000001")
    # Even if the model tries to pass a phone, it is ignored.
    out = await recall_memory.run(customer, {"query": "giá bao nhiêu", "phone": "0000000000"})
    assert seen["phone"] == "0900000001"
    assert seen["query"] == "giá bao nhiêu"
    assert "3 tỷ" in out


async def test_run_empty_hits(monkeypatch):
    class _BE:
        async def recall(self, phone, query, top_k):
            return []

    monkeypatch.setattr(recall_memory, "get_memory_backend", lambda _s: _BE())
    monkeypatch.setattr(recall_memory, "get_settings", lambda: SimpleNamespace(user_memory_recall_top_k=3))
    out = await recall_memory.run(SimpleNamespace(phone="0900"), {"query": "abc"})
    assert "không tìm thấy" in out.lower()


def test_schema_exposes_only_query():
    from noble_agent.agent.tools.schemas import SCHEMAS

    props = SCHEMAS["recall_memory"]["function"]["parameters"]["properties"]
    assert set(props.keys()) == {"query"}
    assert SCHEMAS["recall_memory"]["function"]["parameters"]["required"] == ["query"]


async def test_dispatcher_routes_recall_memory(monkeypatch):
    from noble_agent.agent.tools.dispatcher import ToolDispatcher

    async def _run(customer, args):
        return "MEM"

    monkeypatch.setattr(recall_memory, "run", _run)

    class _CB:
        async def on_tool_start(self, *a, **k):
            pass

        async def on_tool_done(self, *a, **k):
            pass

    d = ToolDispatcher(state=None, customer=SimpleNamespace(phone="0900"), rag=None, callbacks=_CB(), session_id="s")
    result = await d.dispatch({"function": {"name": "recall_memory", "arguments": json.dumps({"query": "x"})}})
    assert result == "MEM"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_recall_memory.py -v`
Expected: FAIL (`ModuleNotFoundError: ...tools.recall_memory`).

- [ ] **Step 3: Create the executor**

Create `src/noble_agent/agent/tools/recall_memory.py`:

```python
"""Tool: recall_memory — long-term semantic search of THIS caller's past calls.

The phone is code-supplied from `customer` (never an LLM parameter), so a caller
can never read another caller's memory. The tool exposes only `query`.
"""

from __future__ import annotations

import logging

from noble_agent.agent.memory import get_memory_backend
from noble_agent.config import get_settings

logger = logging.getLogger("noble_agent.agent.tools.recall_memory")

_NO_PHONE = "Chưa có dữ liệu lịch sử của khách này."
_NO_HITS = "Không tìm thấy thông tin liên quan trong các cuộc gọi trước."


async def run(customer, args: dict) -> str:
    phone = getattr(customer, "phone", "") or ""
    if not phone:
        return _NO_PHONE
    query = (args.get("query") or "").strip()
    if not query:
        return _NO_HITS
    settings = get_settings()
    top_k = int(getattr(settings, "user_memory_recall_top_k", 3))
    try:
        hits = await get_memory_backend(settings).recall(phone, query, top_k)
    except Exception:
        logger.exception("recall_memory failed phone=%s", phone)
        return _NO_HITS
    if not hits:
        return _NO_HITS
    lines = ["Thông tin từ các cuộc gọi trước của khách:"]
    for h in hits:
        lines.append(f"- Khách hỏi: {h.query} → Luna trả lời: {h.answer}")
    return "\n".join(lines)
```

- [ ] **Step 4: Add the schema**

In `src/noble_agent/agent/tools/schemas.py`, add a new entry inside the `SCHEMAS` dict (e.g. after `"send_media"`, before the closing `}` of the dict):

```python
    "recall_memory": {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": (
                "Tra cứu lại điều khách đã trao đổi ở CÁC CUỘC GỌI TRƯỚC (không phải cuộc hiện tại). "
                "Gọi khi khách nhắc 'lần trước em có hỏi...', 'anh gọi hôm nọ...', hoặc cần thông tin "
                "khách từng nói mà không có trong bối cảnh hiện tại. Ví dụ khách nói 'lần trước tôi hỏi "
                "gì về NCLB nhỉ' → recall_memory(query='NCLB')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Nội dung cần tìm trong lịch sử trò chuyện của khách.",
                    },
                },
                "required": ["query"],
            },
        },
    },
```

Do NOT add `recall_memory` to `_ENUM_TOOLS` or `_PROJECT_CODE_TOOLS` — it has no project-code param.

- [ ] **Step 5: Add the dispatcher branch**

In `src/noble_agent/agent/tools/dispatcher.py`:
- Add `recall_memory` to the tools import block (top):
```python
from noble_agent.agent.tools import (
    booking,
    noble_search,
    project_financial,
    projects_info,
    recall_memory,
    support_ops,
    update_customer,
)
```
- Add the branch in `_exec` (e.g. right after the `send_media` branch):
```python
        if name == "recall_memory":
            return await recall_memory.run(self.customer, args)
```

- [ ] **Step 6: Offer the tool + update agent-def test**

In `src/noble_agent/agent/definitions/config.json`, add `"recall_memory"` to the `tools` array (after `"send_media"`):
```json
    "send_media",
    "recall_memory"
```

In `tests/unit/unified/test_agent_def.py`, update the two count assertions:
- `assert len(agent.tool_names) == 10` → `== 11`
- `assert len(agent.tool_schemas) == 10` → `== 11`
- Add: `assert "recall_memory" in agent.tool_names`

- [ ] **Step 7: Document the tool in RULES.md**

In `src/noble_agent/agent/definitions/RULES.md`, add one row to the tool-catalog table (match the existing table's columns/format), stating: call `recall_memory(query)` only for something discussed in a PREVIOUS call and absent from the current context; do NOT use it for within-current-call recall (that history is already present). Keep it to one row; do not restructure the file.

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_recall_memory.py tests/unit/unified/test_agent_def.py -v`
Expected: PASS (all).

- [ ] **Step 9: Commit**

```bash
git add src/noble_agent/agent/tools/recall_memory.py src/noble_agent/agent/tools/schemas.py src/noble_agent/agent/tools/dispatcher.py src/noble_agent/agent/definitions/config.json src/noble_agent/agent/definitions/RULES.md tests/unit/unified/test_recall_memory.py tests/unit/unified/test_agent_def.py
git commit -m "feat(memory): recall_memory tool (phone code-supplied, query-only schema)"
```

---

## Task 6: Write path at call end (`base_session`)

**Files:**
- Modify: `src/noble_agent/server/base_session.py` (~L381, right after `save_call_summary`)
- Test: `tests/unit/unified/test_memory_entry_helpers.py` (covers `record_call_memory`)

**Interfaces:**
- Consumes: `record_call_memory` (Task 2), `fire_and_forget` (`storage.persist`).
- Produces: nothing new; wires the write into the existing stop() summary block.

- [ ] **Step 1: Write the failing test (entry helper, real fire path)**

Create `tests/unit/unified/test_memory_entry_helpers.py`:

```python
from types import SimpleNamespace
from datetime import datetime, UTC

import noble_agent.agent.memory as memory


def _settings(enabled=True):
    return SimpleNamespace(user_memory_enabled=enabled, user_memory_backend="qa_vector")


async def test_record_call_memory_invokes_backend_when_enabled(monkeypatch):
    seen = {}

    class _BE:
        async def write_call(self, phone, session_id, history, ended_at):
            seen["phone"] = phone
            seen["session_id"] = session_id

    monkeypatch.setattr(memory, "get_memory_backend", lambda _s: _BE())
    await memory.record_call_memory(
        _settings(), phone="0900", session_id="s1", history=[{"role": "user", "content": "hi"}], ended_at=datetime.now(UTC)
    )
    assert seen == {"phone": "0900", "session_id": "s1"}


async def test_record_call_memory_swallows_backend_error(monkeypatch):
    class _BE:
        async def write_call(self, *a, **k):
            raise RuntimeError("boom")

    monkeypatch.setattr(memory, "get_memory_backend", lambda _s: _BE())
    # Must not raise:
    await memory.record_call_memory(_settings(), phone="0900", session_id="s1", history=[], ended_at=datetime.now(UTC))


async def test_short_term_block_invokes_backend(monkeypatch):
    class _BE:
        async def build_short_term_context(self, phone, sid):
            return "## Bối cảnh lần gọi trước\nTóm tắt: x"

    monkeypatch.setattr(memory, "get_memory_backend", lambda _s: _BE())
    out = await memory.short_term_block(_settings(), phone="0900", session_id="s1")
    assert "Bối cảnh" in out
```

- [ ] **Step 2: Run test to verify it fails/passes**

Run: `pytest tests/unit/unified/test_memory_entry_helpers.py -v`
Expected: PASS (these helpers were created in Task 2 — this test locks their behavior. If Task 2 is complete, they pass; run to confirm no regression).

- [ ] **Step 3: Wire the write into `base_session.stop()`**

In `src/noble_agent/server/base_session.py`, inside the `if phone:` block, immediately after the `save_call_summary(...)` try/except (the block ending ~L385), add a new guarded fire-and-forget call. `history`, `phone`, `ended_at` are already in scope from the summary block above:

```python
                # User memory (long-term): embed this call's QA pairs into Qdrant.
                # Off unless NOBLE_USER_MEMORY_ENABLED. Fire-and-forget so stop()
                # stays fast; the helper guards enabled+phone and swallows errors.
                try:
                    from noble_agent.agent.memory import record_call_memory
                    from noble_agent.config import get_settings
                    from noble_agent.storage.persist import fire_and_forget

                    fire_and_forget(
                        record_call_memory(
                            get_settings(),
                            phone=phone,
                            session_id=self.session_id,
                            history=history,
                            ended_at=ended_at,
                        )
                    )
                except Exception as mem_exc:  # noqa: BLE001
                    logger.warning("[MEMORY] write scheduling failed: %s", mem_exc)
```

- [ ] **Step 4: Verify existing base_session tests still pass**

Run: `pytest tests/unit/unified/test_memory_entry_helpers.py -v && pytest tests/ -k base_session -v`
Expected: PASS (no regression; memory write is gated off by default so existing tests are unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/server/base_session.py tests/unit/unified/test_memory_entry_helpers.py
git commit -m "feat(memory): write user memory at call end (fire-and-forget, gated)"
```

---

## Task 7: Short-term injection at bootstrap (`orchestrator`)

**Files:**
- Modify: `src/noble_agent/agent/orchestrator.py` (first-turn bootstrap block, ~L140-142)
- Test: `tests/unit/unified/test_memory_entry_helpers.py` already covers `short_term_block`; add a focused orchestrator-level assertion here.

**Interfaces:**
- Consumes: `short_term_block` (Task 2).
- Produces: appends the memory block into the frozen `state.scratchpad["customer_block"]` (no template/runner/build_system_prompt signature change — the block flows through the existing `customer_block` path).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/unified/test_memory_entry_helpers.py`:

```python
async def test_short_term_block_appended_to_customer_block(monkeypatch):
    # Simulate the orchestrator bootstrap append logic in isolation.
    import noble_agent.agent.memory as memory

    class _BE:
        async def build_short_term_context(self, phone, sid):
            return "## Bối cảnh lần gọi trước\nTóm tắt: KH hỏi giá NCLB"

    monkeypatch.setattr(memory, "get_memory_backend", lambda _s: _BE())
    settings = _settings(enabled=True)
    customer_block = "## Hồ sơ khách\n- Tên: Hùng"

    mem = await memory.short_term_block(settings, phone="0900", session_id="cur")
    if mem:
        customer_block += "\n\n" + mem
    assert "Hồ sơ khách" in customer_block
    assert "Bối cảnh lần gọi trước" in customer_block
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_memory_entry_helpers.py::test_short_term_block_appended_to_customer_block -v`
Expected: PASS.

- [ ] **Step 3: Wire into the orchestrator bootstrap**

In `src/noble_agent/agent/orchestrator.py`, inside the `if not state.scratchpad.get("_profile_loaded"):` block, right after:
```python
                state.scratchpad["customer_block"] = render_customer_block(self._agent, customer)
```
add (before `state.scratchpad["_profile_loaded"] = True`):
```python
                # Short-term user memory: prepend prior-call context into the
                # frozen customer_block (no prompt-template change needed). Gated
                # off + safe: short_term_block returns "" unless enabled + phone.
                if self._settings.user_memory_enabled and customer.phone:
                    from noble_agent.agent.memory import short_term_block

                    mem_block = await short_term_block(
                        self._settings, phone=customer.phone, session_id=sid
                    )
                    if mem_block:
                        state.scratchpad["customer_block"] += "\n\n" + mem_block
```

- [ ] **Step 4: Run the runner/orchestrator tests**

Run: `pytest tests/unit/unified/test_runner.py tests/unit/unified/test_customer_bootstrap.py tests/unit/unified/test_memory_entry_helpers.py -v`
Expected: PASS (memory off by default → bootstrap unchanged; helper tests green).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/orchestrator.py tests/unit/unified/test_memory_entry_helpers.py
git commit -m "feat(memory): inject short-term prior-call context at bootstrap (gated)"
```

---

## Task 8: Full-suite gate, lint, docs

**Files:**
- Modify: `CLAUDE.md` (Change Log row + tool count / layout notes)
- Modify: `.env.example` (document the new env vars)

- [ ] **Step 1: Run the full unit suite + lint**

Run:
```bash
make test-unit
make lint
```
Expected: all pass; ruff clean. Fix any issues inline (e.g. import ordering — `ruff check --fix`).

- [ ] **Step 2: Document env vars in `.env.example`**

Add a block:
```bash
# ── User Memory (per-caller, keyed by phone) — off by default ────────────────
NOBLE_USER_MEMORY_ENABLED=false
USER_MEMORY_BACKEND=qa_vector
USER_MEMORY_QDRANT_COLLECTION=user_memory
USER_MEMORY_SHORT_TERM_TURNS=6
USER_MEMORY_RECALL_TOP_K=3
USER_MEMORY_SINCE_DAYS=30
USER_MEMORY_DEDUP_ENABLED=true
USER_MEMORY_DEDUP_THRESHOLD=0.95
```

- [ ] **Step 3: Update CLAUDE.md**

- In the layout table / tool-catalog summary, note the new `agent/memory/` subpackage and that Luna now offers **11 tools** when `NOBLE_USER_MEMORY_ENABLED=true` (adds `recall_memory`); 10 when off.
- Append a Change Log row (top of the `## Change Log` table) dated `2026-07-13` summarizing: user memory feature (short-term prompt inject + long-term Qdrant `user_memory` recall tool), phone-scoped + code-supplied, pluggable `MemoryBackend`, semantic write-dedup, gated off by default, branch `feat/refactor2`. Reference the spec + this plan.

- [ ] **Step 4: Manual smoke checklist reminder**

Per `src/noble_agent/SMOKE.md`, this change touches the turn loop (bootstrap) + prompt + tool catalog. With `NOBLE_USER_MEMORY_ENABLED=false`, confirm a `/chat` turn behaves exactly as before (no new block, 10 tools). With it `true` + a real phone that has a prior summary, confirm the "Bối cảnh lần gọi trước" block appears and `recall_memory` is offered. (Requires live Qdrant + Mongo — do this in a dev environment, not in unit CI.)

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md .env.example
git commit -m "docs(memory): CLAUDE.md change log + .env.example for user memory"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** Component 0 (backend abstraction) → Task 2. Component 1 (vector store) → Task 3. Component 2 (write + dedup) → Tasks 4, 6. Component 3 (short-term) → Tasks 4, 7. Component 4 (tool) → Task 5. Config → Task 1. Identity/edge cases (gating, phone pre-filter, log-and-continue) → Tasks 2, 3, 5, 6, 7. Testing section → per-task tests. Out-of-scope items are not implemented (graph memory left as a future backend enum value).
- **Placeholder scan:** No TBD/TODO; every code step has full code. RULES.md row (Task 5 Step 7) is described precisely (one row, stated content) rather than pasted because the table format must match the live file — acceptable, it is one concrete row with exact semantics.
- **Type consistency:** `MemoryHit(query, answer, score, ended_at)` consistent across base.py, qa_vector.recall, recall_memory tool. `vector_store.search` returns 5-tuples `(id, query, answer, score, ended_at)`; qa_vector maps them to MemoryHit dropping id — consistent. `build_qa_pairs -> list[tuple[str,str]]`, `make_point(id, vector, payload)`, `find_similar -> list[tuple[str,float]]` all match their call sites. `get_memory_backend(settings)`, `record_call_memory(settings, *, phone, session_id, history, ended_at)`, `short_term_block(settings, *, phone, session_id)` signatures match every consumer.
- **Decision noted:** short-term is folded into the frozen `customer_block` (Task 7) instead of a new `{{ user_memory_block }}` template var — fewer seams, no change to `build_system_prompt`/runner/warm path; spec explicitly allowed "or extend the customer block".
