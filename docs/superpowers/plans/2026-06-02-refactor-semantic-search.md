# Noble Agent Refactor — Semantic Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current grep-only `noble_search` backend in `noble_agent_refactor` with a real semantic search pipeline: FlatStore (e5-large dense + BM25 RRF) + SemanticCache + SlowThinker background prefetch, fully self-contained inside `src/noble_agent_refactor/rag/`.

**Architecture:** Port the legacy RAG stack module-by-module into the refactor package so the refactor stays standalone (no runtime imports from `noble_agent.*`). Compose a `MemoryRouter` singleton in `facade._build_runner()` when `NOBLE_SEARCH_BACKEND=rag`, wrap it in the existing `RagAdapter` duck-typed interface (`fast_talker.get_context` / `slow_thinker.predict`), and route the orchestrator's per-turn prefetch through a USER_UTTERANCE event published on `MemoryRouter.stream`. FAQ semantic inject (V10) is **out of scope** for this plan.

**Tech Stack:** Python 3.11+, numpy, faiss-cpu, fastembed (or sentence-transformers fallback), bm25s, pyvi, openai-AsyncOpenAI for the SlowThinker LLM predictor. All already pinned in `pyproject.toml`.

---

## Scope & non-goals

**In scope**
- Port `MetricsCollector`/`Timer`, `ConversationStream`, `SemanticCache`, `FlatStore` (+ embedder, hybrid search), `FlatStoreEmbeddingAdapter`/`FlatStoreVectorStoreAdapter`, `FastTalker`, `SlowThinker`, `MemoryRouter` from `noble_agent.agent.rag.*` → `noble_agent_refactor.rag.*`.
- Add RAG settings to `RefactorSettings`.
- Wire the runner so that `NOBLE_SEARCH_BACKEND=rag` (currently a no-op that logs a warning) returns real hits.
- Per-turn prefetch flow: `TurnRunner.handle_turn` already calls `self._rag.prefetch(sid, user_text, customer)`. The new `RagAdapter` publishes `USER_UTTERANCE` to the `MemoryRouter`'s stream there; `SlowThinker`'s background subscriber drives prediction + retrieval into the cache.

**Out of scope (explicitly)**
- FAQ V10 semantic inject (`faq_searcher.py`). User chose "no FAQ inject — only tool noble_search".
- Pre-built embedding cache regeneration. We reuse the existing `data/flat_store/` artifacts produced by the legacy build script.
- Voice-side wiring. Refactor is currently only used by `/chat` when `USE_REFACTOR_CORE=true`.

---

## File structure

**New files** (all under `src/noble_agent_refactor/rag/`):

| File | Responsibility | Source |
|---|---|---|
| `metrics.py` | `MetricsCollector` + `Timer` context manager. Stdlib-only. | port of `src/noble_agent/metrics/collector.py` |
| `conversation_stream.py` | `EventType`, `StreamEvent`, `ConversationStream` pub/sub. | port of `src/noble_agent/agent/rag/conversation_stream.py` |
| `semantic_cache.py` | `CachedContext`, `SemanticCache` (FAISS IP). | port of `src/noble_agent/agent/rag/semantic_cache.py` |
| `flat_store.py` | `Chunk`, `SearchHit`, `_Embedder`, `FlatStore` (dense + BM25 RRF), `format_hits`, `get_flat_store()` singleton. | port of `src/noble_agent/agent/rag/flat_store.py` |
| `flat_store_adapter.py` | `SearchResult` dataclass, `FlatStoreEmbeddingAdapter`, `FlatStoreVectorStoreAdapter`, `get_flat_store_adapters`, `query_flat_store_for_noble_kb`. | port of `src/noble_agent/agent/rag/flat_store_adapter.py` + inline copy of the legacy `SearchResult` dataclass (avoid pulling `noble_agent.agent.rag.vector_store`). |
| `fast_talker.py` | `FastTalker` cache-aware retrieval wrapper. | port of `src/noble_agent/agent/rag/fast_talker.py` |
| `slow_thinker.py` | `SlowThinker` event-driven prefetch + predictor prompts. | port of `src/noble_agent/agent/rag/slow_thinker.py` |
| `memory_router.py` | `MemoryRouter` composes everything + `_OpenAIPredictor` for SlowThinker LLM. | port of `src/noble_agent/agent/rag/memory_router.py`, adapted to `RefactorSettings`. |

**Modified files**

| File | Change |
|---|---|
| `src/noble_agent_refactor/config.py` | Add 11 RAG-related fields (model, threads, cache size/TTL/thresholds, fast/slow talker params, slow-thinker LLM model). |
| `src/noble_agent_refactor/rag/adapter.py` | Wrap `MemoryRouter` so the existing duck-typed contract (`fast_talker.get_context` / `slow_thinker.predict`) works. `prefetch()` publishes `USER_UTTERANCE` on the router's stream — SlowThinker's background loop picks it up. |
| `src/noble_agent_refactor/rag/grep_search.py` | Unchanged — kept as `NOBLE_SEARCH_BACKEND=grep` fallback. |
| `src/noble_agent_refactor/tools/noble_search.py` | Unchanged. Already routes `backend=="rag"` through `rag.search(...)`. |
| `src/noble_agent_refactor/facade.py:_build_runner` | When `settings.search_backend == "rag"`: build `MemoryRouter`, await `router.start()`, wrap in `RagAdapter`. Otherwise keep `rag = None`. |
| `src/noble_agent_refactor/orchestrator.py` | No code change required. Existing `asyncio.create_task(self._rag.prefetch(sid, user_text, customer))` already fires per turn. |

**New tests** (all `tests/unit/refactor/`):

| File | Coverage |
|---|---|
| `test_rag_metrics.py` | counters, latency percentile, Timer context manager |
| `test_rag_conversation_stream.py` | publish/subscribe, history window, get_conversation_text |
| `test_rag_semantic_cache.py` | put/get, dedup, TTL eviction, LRU eviction |
| `test_rag_fast_talker.py` | cache hit path, cache miss → vector store path, empty-result path |
| `test_rag_slow_thinker.py` | event handling (USER_UTTERANCE → predict → retrieve_and_cache), rate-limit gating |
| `test_rag_flat_store_adapter.py` | dense-only `async_search`, format_hits shape (with fake FlatStore) |
| `test_rag_memory_router.py` | start/stop lifecycle, query_context publishes USER_UTTERANCE (router with fake adapters) |

**Modified tests**

| File | Change |
|---|---|
| `tests/unit/refactor/test_rag_adapter.py` | Existing tests for `fast_talker.get_context` duck-typing still pass. Add 2 tests for the new `prefetch` flow (USER_UTTERANCE publish path). |
| `tests/unit/refactor/test_facade.py` | Add a smoke test: when `NOBLE_SEARCH_BACKEND=rag`, `_build_runner` builds a non-None `rag` (with `MemoryRouter.start` mocked). |

---

## Background context an engineer needs

### How the refactor's current grep path works

1. LLM emits `noble_search` tool call with `{query, project_filter}`.
2. `tools/dispatcher.py` routes to `tools/noble_search.run(rag, dispatcher, args)`.
3. `noble_search.run` reads `get_settings().search_backend`:
   - `grep` → `rag/grep_search.search()` → substring match on `data/faq/<CODE>.md`.
   - `empty` → `""`.
   - `rag` → calls `await rag.search(query, project_filter)` if `rag is not None`. Currently `facade._build_runner` hard-codes `rag = None`, so this branch logs a warning and returns `""`.
4. Tool result string goes back into the LLM message stream verbatim.

### How the legacy semantic search works (model to copy)

Per `CLAUDE.md` and `src/noble_agent/agent/rag/`:

- **FlatStore** (`flat_store.py`): loads ~3.7k chunks from `data/rag/lightrag_s02_<key>/` (symlinks to santa-chat-agent corpus), encodes with `intfloat/multilingual-e5-large` (1024-d), caches embeddings to `data/flat_store/embeddings_intfloat__multilingual-e5-large.npy`. Hybrid search = dense top-k (numpy matmul) + BM25 top-k (bm25s with pyvi tokenization) fused via Reciprocal Rank Fusion (`rrf_k=60`). Warm latency <50ms.
- **SemanticCache** (`semantic_cache.py`): FAISS `IndexFlatIP` over query embeddings, max_size=2000, TTL=300s, similarity threshold 0.40, dedup threshold 0.95.
- **FastTalker** (`fast_talker.py`): on `get_context(query, project_filter)` → embed query → check cache (hit returns formatted) → on miss call `vector_store.async_search` → write results to cache for next turn → publish `PRIORITY_RETRIEVAL` event.
- **SlowThinker** (`slow_thinker.py`): background asyncio task subscribed to the stream. On `USER_UTTERANCE`: rate-limit gate (0.5s) → call gpt-4o-mini with `PREDICTION_PROMPT` → parse 5 numbered topics → for each, embed + search FlatStore + put into cache. ~$0.0003/turn.
- **MemoryRouter** (`memory_router.py`): singleton composing cache + stream + fast/slow talkers; lazy `start()` triggers the heavy FlatStore load (3–5s ONNX init) and the SlowThinker background task.

### How the orchestrator already calls prefetch

`src/noble_agent_refactor/orchestrator.py:51-52`:
```python
if self._settings.enable_slow_thinker and self._rag is not None:
    asyncio.create_task(self._rag.prefetch(sid, user_text, customer))
```

`RagAdapter.prefetch` (current) calls `slow_thinker.predict(user_text=..., session_id=..., project_filter=...)` if a `slow_thinker` was injected. **For the new MemoryRouter flow, the right action is to publish `USER_UTTERANCE` to the router's stream — the legacy `SlowThinker._run` subscriber does prediction + retrieval automatically.** So `RagAdapter.prefetch` will be rewritten to call `router.stream.publish(...)` instead of an explicit `predict()`.

### Path/import differences vs. legacy

| Legacy | Refactor |
|---|---|
| `src/noble_agent/agent/rag/flat_store.py` → `parents[4]` is repo root | `src/noble_agent_refactor/rag/flat_store.py` → **`parents[3]`** is repo root |
| `from noble_agent.config import settings` | `from noble_agent_refactor.config import get_settings`; `settings = get_settings()` |
| `from noble_agent.metrics.collector import MetricsCollector, Timer` | `from noble_agent_refactor.rag.metrics import MetricsCollector, Timer` |
| `from noble_agent.agent.rag.conversation_stream import ...` | `from noble_agent_refactor.rag.conversation_stream import ...` |
| `from noble_agent.agent.rag.semantic_cache import ...` | `from noble_agent_refactor.rag.semantic_cache import ...` |
| `from noble_agent.agent.rag.vector_store import SearchResult` (in adapter) | inline-define `SearchResult` dataclass in `flat_store_adapter.py` |
| `from noble_agent.agent import project_catalog as _catalog` | refactor doesn't use catalog in this pipeline (FAQ V10 is out of scope) |

### Settings names (refactor flavor)

All new fields are aliased to env vars prefixed with `NOBLE_RAG_*` so they don't collide with the legacy `noble_agent.config.settings` namespace used by the old code path.

---

## Task 1: Port MetricsCollector + Timer

**Files:**
- Create: `src/noble_agent_refactor/rag/metrics.py`
- Test: `tests/unit/refactor/test_rag_metrics.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/refactor/test_rag_metrics.py`:
```python
import time

from noble_agent_refactor.rag.metrics import MetricsCollector, Timer


def test_counter_increments():
    m = MetricsCollector()
    m.increment("hits")
    m.increment("hits", 3)
    assert m.get_counter("hits") == 4
    assert m.get_counter("missing") == 0


def test_cache_hit_rate():
    m = MetricsCollector()
    m.increment("cache_hit", 7)
    m.increment("cache_miss", 3)
    assert m.cache_hit_rate == 0.7


def test_record_latency_and_percentiles():
    m = MetricsCollector()
    for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
        m.record_latency("comp", "op", v)
    assert m.get_avg_latency("comp", "op") == 30.0
    assert m.get_p50_latency("comp", "op") == 30.0
    assert m.get_p95_latency("comp", "op") == 48.0


def test_timer_records_latency():
    m = MetricsCollector()
    with Timer(m, "comp", "op"):
        time.sleep(0.01)
    assert m.get_counter("comp_op") == 0  # Timer records latency, not counters
    durations = [r for r in m._records if r.component == "comp"]
    assert len(durations) == 1
    assert durations[0].duration_ms >= 10.0


def test_summary_shape():
    m = MetricsCollector()
    m.increment("cache_hit", 2)
    m.increment("cache_miss", 1)
    m.record_latency("c", "o", 5.0)
    out = m.summary()
    assert out["counters"] == {"cache_hit": 2, "cache_miss": 1}
    assert "latency" in out and "c" in out["latency"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/refactor/test_rag_metrics.py -v
```
Expected: `ModuleNotFoundError: noble_agent_refactor.rag.metrics`.

- [ ] **Step 3: Create `src/noble_agent_refactor/rag/metrics.py`**

Copy `src/noble_agent/metrics/collector.py` verbatim (file is stdlib-only). No edits needed beyond the leading docstring.

```python
"""MetricsCollector — in-memory latency + counter tracking with percentile calculations.

Ported from src/noble_agent/metrics/collector.py for refactor standalone-ness.
Pure stdlib; no external deps.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass
class LatencyRecord:
    component: str
    operation: str
    duration_ms: float
    timestamp: float


class MetricsCollector:
    def __init__(self) -> None:
        self._records: list[LatencyRecord] = []
        self._counters: dict[str, int] = defaultdict(int)

    def record_latency(self, component: str, operation: str, duration_ms: float) -> None:
        self._records.append(LatencyRecord(
            component=component, operation=operation,
            duration_ms=duration_ms, timestamp=time.time(),
        ))

    def increment(self, counter_name: str, amount: int = 1) -> None:
        self._counters[counter_name] += amount

    def get_counter(self, counter_name: str) -> int:
        return self._counters.get(counter_name, 0)

    @property
    def cache_hit_rate(self) -> float:
        hits = self._counters.get("cache_hit", 0)
        misses = self._counters.get("cache_miss", 0)
        total = hits + misses
        return hits / total if total > 0 else 0.0

    def _percentile(self, values: list[float], p: int) -> float:
        if not values:
            return 0.0
        sorted_v = sorted(values)
        k = (len(sorted_v) - 1) * (p / 100)
        f = int(k)
        c = min(f + 1, len(sorted_v) - 1)
        return sorted_v[f] + (k - f) * (sorted_v[c] - sorted_v[f])

    def _get_durations(self, component: str, operation: str | None = None) -> list[float]:
        return [
            r.duration_ms for r in self._records
            if r.component == component
            and (operation is None or r.operation == operation)
        ]

    def get_avg_latency(self, component: str, operation: str | None = None) -> float:
        d = self._get_durations(component, operation)
        return sum(d) / len(d) if d else 0.0

    def get_p50_latency(self, component: str, operation: str | None = None) -> float:
        return self._percentile(self._get_durations(component, operation), 50)

    def get_p95_latency(self, component: str, operation: str | None = None) -> float:
        return self._percentile(self._get_durations(component, operation), 95)

    def get_p99_latency(self, component: str, operation: str | None = None) -> float:
        return self._percentile(self._get_durations(component, operation), 99)

    def summary(self) -> dict[str, Any]:
        components = {r.component for r in self._records}
        result: dict[str, Any] = {
            "counters": dict(self._counters),
            "cache_hit_rate": f"{self.cache_hit_rate:.1%}",
            "latency": {},
        }
        for comp in sorted(components):
            operations = {r.operation for r in self._records if r.component == comp}
            result["latency"][comp] = {}
            for op in sorted(operations):
                durations = self._get_durations(comp, op)
                result["latency"][comp][op] = {
                    "count": len(durations),
                    "avg_ms": round(self.get_avg_latency(comp, op), 1),
                    "p50_ms": round(self._percentile(durations, 50), 1),
                    "p95_ms": round(self._percentile(durations, 95), 1),
                    "p99_ms": round(self._percentile(durations, 99), 1),
                    "min_ms": round(min(durations), 1) if durations else 0,
                    "max_ms": round(max(durations), 1) if durations else 0,
                }
        return result

    def reset(self) -> None:
        self._records.clear()
        self._counters.clear()


class Timer:
    """Context manager that auto-records latency on exit."""

    def __init__(self, metrics: MetricsCollector, component: str, operation: str) -> None:
        self._metrics = metrics
        self._component = component
        self._operation = operation
        self._start: float = 0
        self.elapsed_ms: float = 0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
        self._metrics.record_latency(self._component, self._operation, self.elapsed_ms)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/refactor/test_rag_metrics.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/rag/metrics.py tests/unit/refactor/test_rag_metrics.py
git commit -m "feat(refactor/rag): port MetricsCollector + Timer"
```

---

## Task 2: Port ConversationStream

**Files:**
- Create: `src/noble_agent_refactor/rag/conversation_stream.py`
- Test: `tests/unit/refactor/test_rag_conversation_stream.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio

import pytest

from noble_agent_refactor.rag.conversation_stream import (
    ConversationStream, EventType, StreamEvent,
)


async def test_publish_appends_to_history():
    s = ConversationStream(window_size=3)
    await s.publish(StreamEvent(EventType.USER_UTTERANCE, text="hi"))
    await s.publish(StreamEvent(EventType.AGENT_RESPONSE, text="hello"))
    h = s.history
    assert len(h) == 2
    assert h[0].text == "hi"
    assert h[1].event_type == EventType.AGENT_RESPONSE


async def test_history_window_caps_oldest():
    s = ConversationStream(window_size=2)
    for i in range(5):
        await s.publish(StreamEvent(EventType.USER_UTTERANCE, text=str(i)))
    assert [e.text for e in s.history] == ["3", "4"]


async def test_subscribe_yields_published_events():
    s = ConversationStream(window_size=10)
    sub = s.subscribe()

    async def reader():
        async for e in sub:
            return e

    task = asyncio.create_task(reader())
    await asyncio.sleep(0)  # let reader start
    await s.publish(StreamEvent(EventType.USER_UTTERANCE, text="hey"))
    got = await asyncio.wait_for(task, timeout=1.0)
    assert got.text == "hey"
    await sub.unsubscribe()


async def test_get_conversation_text_skips_other_types():
    s = ConversationStream(window_size=10)
    await s.publish(StreamEvent(EventType.USER_UTTERANCE, text="u1"))
    await s.publish(StreamEvent(EventType.SILENCE_DETECTED, text="(silence)"))
    await s.publish(StreamEvent(EventType.AGENT_RESPONSE, text="a1"))
    assert s.get_conversation_text() == "User: u1\nAssistant: a1"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/refactor/test_rag_conversation_stream.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/noble_agent_refactor/rag/conversation_stream.py`**

Verbatim port — stdlib + asyncio only:

```python
"""ConversationStream — pub/sub event bus + sliding history window.

Ported from src/noble_agent/agent/rag/conversation_stream.py.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class EventType(Enum):
    USER_UTTERANCE = "user_utterance"
    AGENT_RESPONSE = "agent_response"
    SILENCE_DETECTED = "silence_detected"
    TOPIC_SHIFT = "topic_shift"
    PRIORITY_RETRIEVAL = "priority_retrieval"


@dataclass
class StreamEvent:
    event_type: EventType
    text: str = ""
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class ConversationStream:
    def __init__(self, window_size: int = 10) -> None:
        self._subscribers: list[asyncio.Queue[StreamEvent]] = []
        self._history: deque[StreamEvent] = deque(maxlen=window_size)
        self._window_size = window_size

    async def publish(self, event: StreamEvent) -> None:
        self._history.append(event)
        for queue in self._subscribers:
            await queue.put(event)

    def subscribe(self) -> _SubscriptionIterator:
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        self._subscribers.append(queue)
        return _SubscriptionIterator(queue, self._subscribers)

    @property
    def history(self) -> list[StreamEvent]:
        return list(self._history)

    def get_conversation_text(self, max_turns: int | None = None) -> str:
        events = list(self._history)
        if max_turns:
            events = events[-max_turns:]
        lines: list[str] = []
        for event in events:
            if event.event_type == EventType.USER_UTTERANCE:
                lines.append(f"User: {event.text}")
            elif event.event_type == EventType.AGENT_RESPONSE:
                lines.append(f"Assistant: {event.text}")
        return "\n".join(lines)

    def clear(self) -> None:
        self._history.clear()


class _SubscriptionIterator:
    def __init__(self, queue, subscribers):
        self._queue = queue
        self._subscribers = subscribers

    def __aiter__(self):
        return self

    async def __anext__(self) -> StreamEvent:
        try:
            return await self._queue.get()
        except asyncio.CancelledError:
            if self._queue in self._subscribers:
                self._subscribers.remove(self._queue)
            raise

    async def unsubscribe(self) -> None:
        if self._queue in self._subscribers:
            self._subscribers.remove(self._queue)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/refactor/test_rag_conversation_stream.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/rag/conversation_stream.py tests/unit/refactor/test_rag_conversation_stream.py
git commit -m "feat(refactor/rag): port ConversationStream pub/sub"
```

---

## Task 3: Port SemanticCache

**Files:**
- Create: `src/noble_agent_refactor/rag/semantic_cache.py`
- Test: `tests/unit/refactor/test_rag_semantic_cache.py`

- [ ] **Step 1: Write the failing test**

```python
import time

import numpy as np
import pytest

from noble_agent_refactor.rag.semantic_cache import CachedContext, SemanticCache


def _vec(seed: int, dim: int = 8) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-12)


async def test_put_then_get_returns_entry():
    cache = SemanticCache(dimension=8, similarity_threshold=0.5)
    v = _vec(1)
    await cache.put(v, text="hello", metadata={"p": "NCLB"}, relevance_score=0.9)
    out = await cache.get(v, top_k=1)
    assert len(out) == 1
    assert out[0].text == "hello"


async def test_dedup_overwrites_when_above_threshold():
    cache = SemanticCache(dimension=8, dedup_threshold=0.9, similarity_threshold=0.5)
    v = _vec(2)
    await cache.put(v, text="v1", relevance_score=0.5)
    await cache.put(v, text="v2", relevance_score=0.9)
    assert cache.size == 1
    out = await cache.get(v)
    assert out[0].text == "v2"


async def test_get_returns_empty_when_below_threshold():
    cache = SemanticCache(dimension=8, similarity_threshold=0.99)
    v1, v2 = _vec(1), _vec(2)
    await cache.put(v1, text="a")
    out = await cache.get(v2, top_k=1)
    assert out == []


async def test_expired_entries_skipped():
    cache = SemanticCache(dimension=8, default_ttl=0.05, similarity_threshold=0.5)
    v = _vec(3)
    await cache.put(v, text="x")
    time.sleep(0.06)
    out = await cache.get(v)
    assert out == []


async def test_lru_eviction_when_over_capacity():
    cache = SemanticCache(dimension=8, max_size=2, similarity_threshold=0.0)
    await cache.put(_vec(10), text="a")
    await cache.put(_vec(11), text="b")
    await cache.put(_vec(12), text="c")
    assert cache.size == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/refactor/test_rag_semantic_cache.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/noble_agent_refactor/rag/semantic_cache.py`**

Verbatim port of `src/noble_agent/agent/rag/semantic_cache.py` with only the metrics import line changed:

Replace
```python
from noble_agent.metrics.collector import MetricsCollector
```
with
```python
from noble_agent_refactor.rag.metrics import MetricsCollector
```

Everything else (CachedContext dataclass, FAISS index logic, put/get/clear/_evict_*) is copied verbatim.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/refactor/test_rag_semantic_cache.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/rag/semantic_cache.py tests/unit/refactor/test_rag_semantic_cache.py
git commit -m "feat(refactor/rag): port SemanticCache (FAISS IP)"
```

---

## Task 4: Port FlatStore + embedder

**Files:**
- Create: `src/noble_agent_refactor/rag/flat_store.py`
- Test: `tests/unit/refactor/test_rag_flat_store.py`

- [ ] **Step 1: Write the failing test**

The test uses a tiny fake corpus to avoid the 3-5s e5-large load. The real-data check is deferred to the integration test in Task 12.

```python
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from noble_agent_refactor.rag.flat_store import Chunk, FlatStore, SearchHit, format_hits


class _FakeEmbedder:
    def __init__(self, *a, **kw):
        pass

    def load(self):
        pass

    def encode_batch(self, texts, batch_size=32, show_progress=False):
        rng = np.random.default_rng(0)
        vecs = rng.standard_normal((len(texts), 8)).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12
        return vecs / norms

    def encode_query(self, text):
        rng = np.random.default_rng(abs(hash(text)) % (2**32))
        v = rng.standard_normal(8).astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-12)

    @property
    def backend(self):
        return "fake"


def _patched_store(tmp_path: Path) -> FlatStore:
    s = FlatStore(
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        model_name="fake",
    )
    s.embedder = _FakeEmbedder()
    s.chunks = [
        Chunk(id="c1", project="NCLB", text="noble crystal long biên giá"),
        Chunk(id="c2", project="NCLB", text="tiện ích sky villa"),
        Chunk(id="c3", project="NCTH", text="crystal tây hồ"),
    ]
    s.embeddings = s.embedder.encode_batch([c.text for c in s.chunks])
    arr = np.array([c.project for c in s.chunks])
    for p in ("NCLB", "NCTH"):
        s.project_idx[p] = np.where(arr == p)[0]
    return s


def test_search_filters_by_project(tmp_path):
    s = _patched_store(tmp_path)
    hits = s.search("giá", project_filter="NCLB", top_k=5)
    assert all(h.chunk.project == "NCLB" for h in hits)
    assert len(hits) == 2


def test_search_cache_hit_increments_counter(tmp_path):
    s = _patched_store(tmp_path)
    s.search("giá", top_k=1)
    s.search("giá", top_k=1)
    assert s.stats["cache_hit"] == 1
    assert s.stats["cache_miss"] == 1


def test_format_hits_empty_returns_default_message():
    assert format_hits([]) == "Không tìm thấy thông tin liên quan."


def test_format_hits_truncates_long_text(tmp_path):
    s = _patched_store(tmp_path)
    long_chunk = Chunk(id="x", project="NCLB", text="a" * 2000)
    hits = [SearchHit(chunk=long_chunk, score=0.9)]
    out = format_hits(hits, max_chars=100)
    assert "…" in out
    assert "Dự án: NCLB" in out


def test_search_returns_empty_when_assertion_fires(tmp_path):
    s = FlatStore(
        data_dir=tmp_path / "d",
        cache_dir=tmp_path / "c",
        model_name="fake",
    )
    s.embedder = _FakeEmbedder()
    with pytest.raises(AssertionError):
        s.search("anything")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/refactor/test_rag_flat_store.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/noble_agent_refactor/rag/flat_store.py`**

Copy `src/noble_agent/agent/rag/flat_store.py` verbatim, then apply these edits:

1. **Update docstring header**:
```python
"""In-process flat vector store for ~4k chunks.

Ported from src/noble_agent/agent/rag/flat_store.py. Only differences:
- Path resolution: parents[3] (refactor) vs parents[4] (legacy).
- Settings lookup: tries noble_agent_refactor.config.get_settings() for
  embed_remote_url; falls back to env if unavailable.
- No imports from noble_agent.*
"""
```

2. **Adjust `DEFAULT_SANTA_DATA` and `DEFAULT_CACHE_DIR`** — both use `parents[3]` instead of `parents[4]` because `src/noble_agent_refactor/rag/flat_store.py` has one less package level than the legacy file:
```python
DEFAULT_SANTA_DATA = Path(
    os.environ.get(
        "SANTA_CHAT_DATA_DIR",
        str(Path(__file__).resolve().parents[3] / "data" / "rag"),
    )
)
DEFAULT_CACHE_DIR = Path(
    os.environ.get(
        "FLAT_STORE_CACHE_DIR",
        str(Path(__file__).resolve().parents[3] / "data" / "flat_store"),
    )
)
```

3. **Replace the `noble_agent.config` lookup** inside `_Embedder.load()` with a tolerant lookup against the refactor settings (and gracefully skip if absent):
```python
        remote_url = os.environ.get("EMBED_REMOTE_URL", "").strip()
        if not remote_url:
            try:
                from noble_agent_refactor.config import get_settings as _gs
                _s = _gs()
                remote_url = getattr(_s, "noble_rag_embed_remote_url", "") or ""
                self._remote_timeout = float(
                    getattr(_s, "noble_rag_embed_remote_timeout", 10.0)
                )
            except Exception:
                pass
```

4. **Leave everything else** (`_load_project_dotenv`, `PROJECT_MAP`, `Chunk`, `SearchHit`, `_Embedder.encode_batch/encode_query/_encode_remote`, `FlatStore.__init__/load/search/search_hybrid/_dense_topk/_bm25_topk/build_bm25/load_bm25/clear_cache`, `get_flat_store`, `format_hits`) **untouched**.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/refactor/test_rag_flat_store.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/rag/flat_store.py tests/unit/refactor/test_rag_flat_store.py
git commit -m "feat(refactor/rag): port FlatStore (e5-large + BM25 RRF)"
```

---

## Task 5: Port FlatStore adapters

**Files:**
- Create: `src/noble_agent_refactor/rag/flat_store_adapter.py`
- Test: `tests/unit/refactor/test_rag_flat_store_adapter.py`

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
import pytest

from noble_agent_refactor.rag.flat_store import Chunk
from noble_agent_refactor.rag.flat_store_adapter import (
    FlatStoreEmbeddingAdapter,
    FlatStoreVectorStoreAdapter,
    SearchResult,
)


class _FakeStore:
    def __init__(self):
        rng = np.random.default_rng(0)
        emb = rng.standard_normal((3, 8)).astype(np.float32)
        emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-12
        self.embeddings = emb
        self.chunks = [
            Chunk(id=f"c{i}", project="NCLB", text=f"chunk {i}")
            for i in range(3)
        ]
        arr = np.array([c.project for c in self.chunks])
        self.project_idx = {"NCLB": np.where(arr == "NCLB")[0]}

        class _E:
            def encode_query(self, t):
                return emb[0]
            def encode_batch(self, t, show_progress=False):
                return emb[: len(t)]

        self.embedder = _E()

    def _dense_topk(self, q, pf, k):
        scores = self.embeddings @ q
        idx = np.argsort(-scores)[:k]
        return [(int(i), float(scores[i])) for i in idx]


async def test_embedding_adapter_dim_default():
    a = FlatStoreEmbeddingAdapter(_FakeStore())
    assert a.dimension == 8


async def test_vector_store_async_search_returns_results():
    s = _FakeStore()
    a = FlatStoreVectorStoreAdapter(s)
    q = s.embeddings[0]
    results = await a.async_search(q, top_k=2, include_embeddings=True)
    assert len(results) == 2
    assert all(isinstance(r, SearchResult) for r in results)
    assert results[0].text == "chunk 0"
    assert results[0].embedding is not None


async def test_vector_store_handles_empty_embeddings():
    s = _FakeStore()
    s.embeddings = None
    a = FlatStoreVectorStoreAdapter(s)
    assert await a.async_search(np.zeros(8, dtype=np.float32)) == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/refactor/test_rag_flat_store_adapter.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/noble_agent_refactor/rag/flat_store_adapter.py`**

Copy `src/noble_agent/agent/rag/flat_store_adapter.py` with these edits:

1. **Inline define `SearchResult`** at the top — the legacy version imports it from `noble_agent.agent.rag.vector_store` (which is a dead stub). Drop the legacy import line and put this dataclass right after the module imports:

```python
from dataclasses import dataclass, field

@dataclass
class SearchResult:
    text: str
    metadata: dict
    score: float
    index: int = 0
    embedding: np.ndarray | None = None
```

2. **Adjust all `noble_agent.agent.rag.flat_store` imports** → `noble_agent_refactor.rag.flat_store`.

3. **Remove the legacy `from noble_agent.agent.rag.vector_store import SearchResult`** line inside `FlatStoreVectorStoreAdapter.async_search` (now top-level).

4. Keep `_ensure_flat_store`, `_format_hits`, `query_flat_store_for_noble_kb`, `FlatStoreEmbeddingAdapter`, `FlatStoreVectorStoreAdapter`, `get_flat_store_adapters` untouched apart from those import swaps.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/refactor/test_rag_flat_store_adapter.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/rag/flat_store_adapter.py tests/unit/refactor/test_rag_flat_store_adapter.py
git commit -m "feat(refactor/rag): port FlatStore adapters"
```

---

## Task 6: Port FastTalker

**Files:**
- Create: `src/noble_agent_refactor/rag/fast_talker.py`
- Test: `tests/unit/refactor/test_rag_fast_talker.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from noble_agent_refactor.rag.conversation_stream import ConversationStream
from noble_agent_refactor.rag.fast_talker import FastTalker
from noble_agent_refactor.rag.metrics import MetricsCollector
from noble_agent_refactor.rag.semantic_cache import CachedContext, SemanticCache


def _vec(seed: int, dim: int = 8) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-12)


async def _make_ft(vector_results=None):
    cache = SemanticCache(dimension=8, similarity_threshold=0.3)
    stream = ConversationStream()
    metrics = MetricsCollector()
    emb = MagicMock()
    emb.embed_single = AsyncMock(return_value=_vec(1))
    vs = MagicMock()
    vs.async_search = AsyncMock(return_value=vector_results or [])
    ft = FastTalker(embeddings=emb, vector_store=vs, cache=cache,
                    stream=stream, metrics=metrics, max_context_chunks=3)
    return ft, cache, vs


async def test_cache_hit_skips_vector_search():
    ft, cache, vs = await _make_ft()
    v = _vec(1)
    await cache.put(v, text="cached-text", metadata={"project": "NCLB"})
    out = await ft.get_context("giá", project_filter="NCLB")
    assert "cached-text" in out
    vs.async_search.assert_not_called()


async def test_cache_miss_calls_vector_store_and_caches_results():
    class _Hit:
        def __init__(self, t):
            self.text = t
            self.metadata = {"project": "NCLB"}
            self.score = 0.8
            self.embedding = _vec(99)
    ft, cache, vs = await _make_ft(vector_results=[_Hit("a"), _Hit("b")])
    out = await ft.get_context("giá", project_filter="NCLB")
    assert "a" in out and "b" in out
    vs.async_search.assert_awaited_once()
    assert cache.size == 2


async def test_no_results_returns_empty_string():
    ft, cache, vs = await _make_ft(vector_results=[])
    out = await ft.get_context("nothing matches", project_filter="")
    assert out == ""
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/refactor/test_rag_fast_talker.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/noble_agent_refactor/rag/fast_talker.py`**

Copy `src/noble_agent/agent/rag/fast_talker.py` verbatim. Only edits:

1. Update imports:
```python
from noble_agent_refactor.rag.conversation_stream import ConversationStream, EventType, StreamEvent
from noble_agent_refactor.rag.semantic_cache import CachedContext, SemanticCache
from noble_agent_refactor.rag.metrics import MetricsCollector, Timer
```

2. Update logger name:
```python
logger = logging.getLogger("noble_agent_refactor.rag.fast_talker")
```

Everything else (`FastTalker.__init__`, `get_context`, `_get_context`, `_format_context_from_cache`, `_format_context_from_results`) stays identical.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/refactor/test_rag_fast_talker.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/rag/fast_talker.py tests/unit/refactor/test_rag_fast_talker.py
git commit -m "feat(refactor/rag): port FastTalker (cache-aware retrieval)"
```

---

## Task 7: Port SlowThinker

**Files:**
- Create: `src/noble_agent_refactor/rag/slow_thinker.py`
- Test: `tests/unit/refactor/test_rag_slow_thinker.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from noble_agent_refactor.rag.conversation_stream import (
    ConversationStream, EventType, StreamEvent,
)
from noble_agent_refactor.rag.metrics import MetricsCollector
from noble_agent_refactor.rag.semantic_cache import SemanticCache
from noble_agent_refactor.rag.slow_thinker import SlowThinker


def _vec(seed: int):
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(8).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-12)


async def _make_thinker(predictions: list[str]):
    cache = SemanticCache(dimension=8, similarity_threshold=0.0)
    stream = ConversationStream()
    metrics = MetricsCollector()
    emb = MagicMock()
    emb.embed_single = AsyncMock(side_effect=lambda t: _vec(hash(t) & 0xFF))

    class _Hit:
        def __init__(self, t):
            self.text = t
            self.metadata = {"project": "NCLB"}
            self.score = 0.7
            self.embedding = _vec(123)

    vs = MagicMock()
    vs.async_search = AsyncMock(return_value=[_Hit("a"), _Hit("b")])
    llm = MagicMock()
    numbered = "\n".join(f"{i+1}. {p}" for i, p in enumerate(predictions))
    llm.generate = AsyncMock(return_value=numbered)

    st = SlowThinker(llm=llm, embeddings=emb, vector_store=vs, cache=cache,
                    stream=stream, metrics=metrics, prediction_strategy="llm",
                    max_predictions=len(predictions), prefetch_top_k=2,
                    rate_limit=0.0)
    return st, cache, llm, vs


async def test_user_utterance_triggers_predict_and_cache():
    st, cache, llm, vs = await _make_thinker(["topic-a", "topic-b"])
    await st.start()
    try:
        await st._stream.publish(StreamEvent(EventType.USER_UTTERANCE, text="hi"))
        # let event-loop process the queue + downstream calls
        for _ in range(10):
            await asyncio.sleep(0.01)
            if cache.size >= 2:
                break
    finally:
        await st.stop()
    llm.generate.assert_called()
    assert vs.async_search.await_count >= 1
    assert cache.size > 0


async def test_rate_limit_skips_close_events():
    st, cache, llm, vs = await _make_thinker(["x"])
    st._rate_limit = 5.0
    await st._on_user_utterance(StreamEvent(EventType.USER_UTTERANCE, text="a"))
    await st._on_user_utterance(StreamEvent(EventType.USER_UTTERANCE, text="b"))
    assert llm.generate.await_count == 1  # second call gated by rate-limit
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/refactor/test_rag_slow_thinker.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/noble_agent_refactor/rag/slow_thinker.py`**

Copy `src/noble_agent/agent/rag/slow_thinker.py` verbatim. Edits:

1. Update imports:
```python
from noble_agent_refactor.rag.conversation_stream import (
    ConversationStream, EventType, StreamEvent,
)
from noble_agent_refactor.rag.semantic_cache import SemanticCache
from noble_agent_refactor.rag.metrics import MetricsCollector, Timer
```

2. Update logger:
```python
logger = logging.getLogger("noble_agent_refactor.rag.slow_thinker")
```

Preserve `PREDICTION_PROMPT` and `KEYWORD_EXTRACTION_PROMPT` strings verbatim — they're tuned for Noble's project taxonomy.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/refactor/test_rag_slow_thinker.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/rag/slow_thinker.py tests/unit/refactor/test_rag_slow_thinker.py
git commit -m "feat(refactor/rag): port SlowThinker (event-driven prefetch)"
```

---

## Task 8: Add RAG settings to RefactorSettings

**Files:**
- Modify: `src/noble_agent_refactor/config.py`
- Test: `tests/unit/refactor/test_config.py` (extend)

- [ ] **Step 1: Write the failing test** — append to `tests/unit/refactor/test_config.py`:

```python
def test_rag_settings_defaults(monkeypatch):
    from noble_agent_refactor import config

    config.reset_settings_for_tests()
    s = config.get_settings()
    assert s.noble_rag_embedding_model == "intfloat/multilingual-e5-large"
    assert s.noble_rag_embed_threads == 4
    assert s.noble_rag_cache_max_size == 2000
    assert s.noble_rag_cache_ttl == 300.0
    assert s.noble_rag_cache_similarity_threshold == 0.40
    assert s.noble_rag_cache_dedup_threshold == 0.95
    assert s.noble_rag_fast_max_context_chunks == 10
    assert s.noble_rag_fast_fallback_to_retrieval is True
    assert s.noble_rag_slow_model == "gpt-4o-mini"
    assert s.noble_rag_slow_max_predictions == 5
    assert s.noble_rag_slow_prefetch_top_k == 10
    assert s.noble_rag_slow_rate_limit == 0.5
    assert s.noble_rag_slow_prediction_strategy == "llm"
    config.reset_settings_for_tests()


def test_rag_settings_env_overrides(monkeypatch):
    from noble_agent_refactor import config

    monkeypatch.setenv("NOBLE_RAG_EMBEDDING_MODEL", "intfloat/multilingual-e5-base")
    monkeypatch.setenv("NOBLE_RAG_SLOW_MAX_PREDICTIONS", "3")
    config.reset_settings_for_tests()
    s = config.get_settings()
    assert s.noble_rag_embedding_model == "intfloat/multilingual-e5-base"
    assert s.noble_rag_slow_max_predictions == 3
    config.reset_settings_for_tests()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/refactor/test_config.py -v
```
Expected: `AttributeError: ... has no attribute 'noble_rag_embedding_model'`.

- [ ] **Step 3: Extend `src/noble_agent_refactor/config.py`** — insert these fields into `RefactorSettings` (after the existing `transcript_log_dir`):

```python
    # ── RAG (semantic search) ────────────────────────────────────────────
    noble_rag_embedding_model: str = Field(
        "intfloat/multilingual-e5-large", alias="NOBLE_RAG_EMBEDDING_MODEL"
    )
    noble_rag_embed_threads: int = Field(4, alias="NOBLE_RAG_EMBED_THREADS")
    noble_rag_embed_remote_url: str = Field("", alias="NOBLE_RAG_EMBED_REMOTE_URL")
    noble_rag_embed_remote_timeout: float = Field(10.0, alias="NOBLE_RAG_EMBED_REMOTE_TIMEOUT")
    noble_rag_cache_max_size: int = Field(2000, alias="NOBLE_RAG_CACHE_MAX_SIZE")
    noble_rag_cache_ttl: float = Field(300.0, alias="NOBLE_RAG_CACHE_TTL")
    noble_rag_cache_similarity_threshold: float = Field(0.40, alias="NOBLE_RAG_CACHE_SIMILARITY")
    noble_rag_cache_dedup_threshold: float = Field(0.95, alias="NOBLE_RAG_CACHE_DEDUP")
    noble_rag_conversation_window: int = Field(10, alias="NOBLE_RAG_CONVERSATION_WINDOW")
    noble_rag_fast_max_context_chunks: int = Field(10, alias="NOBLE_RAG_FAST_MAX_CHUNKS")
    noble_rag_fast_fallback_to_retrieval: bool = Field(True, alias="NOBLE_RAG_FAST_FALLBACK")
    noble_rag_slow_model: str = Field("gpt-4o-mini", alias="NOBLE_RAG_SLOW_MODEL")
    noble_rag_slow_max_predictions: int = Field(5, alias="NOBLE_RAG_SLOW_MAX_PRED")
    noble_rag_slow_prefetch_top_k: int = Field(10, alias="NOBLE_RAG_SLOW_PREFETCH_K")
    noble_rag_slow_rate_limit: float = Field(0.5, alias="NOBLE_RAG_SLOW_RATE_LIMIT")
    noble_rag_slow_prediction_strategy: Literal["llm", "keyword"] = Field(
        "llm", alias="NOBLE_RAG_SLOW_STRATEGY"
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/refactor/test_config.py -v
```
Expected: all green (including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/config.py tests/unit/refactor/test_config.py
git commit -m "feat(refactor/config): add RAG semantic-search settings"
```

---

## Task 9: Build MemoryRouter (compose layer)

**Files:**
- Create: `src/noble_agent_refactor/rag/memory_router.py`
- Test: `tests/unit/refactor/test_rag_memory_router.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from noble_agent_refactor.rag.conversation_stream import EventType
from noble_agent_refactor.rag.memory_router import MemoryRouter


async def test_start_initialises_fast_and_slow_talker():
    router = MemoryRouter()

    fake_emb = MagicMock()
    fake_emb.embed_single = AsyncMock(return_value=np.zeros(8, dtype=np.float32))
    fake_vs = MagicMock()
    fake_vs.async_search = AsyncMock(return_value=[])

    with patch(
        "noble_agent_refactor.rag.memory_router.get_flat_store_adapters",
        AsyncMock(return_value=(fake_emb, fake_vs)),
    ), patch.object(MemoryRouter, "_build_llm", return_value=MagicMock(generate=AsyncMock(return_value=""))):
        await router.start()
        assert router._fast_talker is not None
        assert router._slow_thinker is not None
        await router.stop()


async def test_query_context_publishes_user_utterance():
    router = MemoryRouter()
    router._fast_talker = MagicMock()
    router._fast_talker.get_context = AsyncMock(return_value="ctx")

    out = await router.query_context("giá NCLB", "NCLB")
    assert out == "ctx"
    assert any(
        e.event_type == EventType.USER_UTTERANCE and e.text == "giá NCLB"
        for e in router.stream.history
    )


async def test_query_context_raises_when_not_started():
    router = MemoryRouter()
    with pytest.raises(RuntimeError):
        await router.query_context("x", "")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/refactor/test_rag_memory_router.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/noble_agent_refactor/rag/memory_router.py`**

```python
"""MemoryRouter — refactor's standalone composition of FlatStore + cache + talkers.

Adapted from src/noble_agent/agent/rag/memory_router.py. Differences:
- Reads RefactorSettings instead of noble_agent.config.
- Builds its own LLM predictor from OPENAI_API_KEY (+ optional GEMINI fallback)
  rather than reusing the (non-existent) noble_agent.config provider chain.
- All cross-module imports point at noble_agent_refactor.rag.*.
"""
from __future__ import annotations

import asyncio
import logging
import os

from openai import AsyncOpenAI

from noble_agent_refactor.config import get_settings
from noble_agent_refactor.rag.conversation_stream import (
    ConversationStream, EventType, StreamEvent,
)
from noble_agent_refactor.rag.fast_talker import FastTalker
from noble_agent_refactor.rag.flat_store_adapter import get_flat_store_adapters
from noble_agent_refactor.rag.metrics import MetricsCollector
from noble_agent_refactor.rag.semantic_cache import SemanticCache
from noble_agent_refactor.rag.slow_thinker import SlowThinker

logger = logging.getLogger("noble_agent_refactor.rag.memory_router")


class _OpenAIPredictor:
    """Minimal non-streaming chat completion adapter for SlowThinker.

    Reads OPENAI_API_KEY/OPENAI_BASE_URL from env. Optional GEMINI_API_KEY
    is wired as a fallback provider so a degraded primary doesn't silently
    disable prefetch.
    """

    def __init__(self, model: str, max_retries: int = 1) -> None:
        self._model = model
        self._max_retries = max_retries
        self._providers: list[tuple[str, AsyncOpenAI, str]] = []

        api_key = os.getenv("OPENAI_API_KEY", "")
        if api_key:
            kwargs: dict = {"api_key": api_key, "timeout": 15.0}
            base_url = os.getenv("OPENAI_BASE_URL", "").strip()
            if base_url:
                kwargs["base_url"] = base_url
            self._providers.append(("openai", AsyncOpenAI(**kwargs), model))

        gemini_key = os.getenv("GEMINI_API_KEY", "")
        if gemini_key:
            self._providers.append((
                "gemini",
                AsyncOpenAI(
                    api_key=gemini_key,
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    timeout=15.0,
                ),
                "gemini-1.5-flash",
            ))

        if not self._providers:
            logger.warning("_OpenAIPredictor: no provider configured — generate() will return ''")

    async def generate(self, prompt: str) -> str:
        last_error = None
        for name, client, model in self._providers:
            for attempt in range(self._max_retries + 1):
                try:
                    resp = await client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.3,
                        max_tokens=512,
                    )
                    return resp.choices[0].message.content or ""
                except Exception as e:
                    last_error = e
                    if attempt < self._max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
            logger.warning("predictor %s exhausted retries: %s", name, last_error)
        return ""


class MemoryRouter:
    def __init__(self, metrics: MetricsCollector | None = None) -> None:
        settings = get_settings()
        self._settings = settings
        self._metrics = metrics or MetricsCollector()
        self._cache = SemanticCache(
            dimension=1024,  # e5-large
            max_size=settings.noble_rag_cache_max_size,
            default_ttl=settings.noble_rag_cache_ttl,
            similarity_threshold=settings.noble_rag_cache_similarity_threshold,
            dedup_threshold=settings.noble_rag_cache_dedup_threshold,
            metrics=self._metrics,
        )
        self._stream = ConversationStream(
            window_size=settings.noble_rag_conversation_window,
        )
        self._fast_talker: FastTalker | None = None
        self._slow_thinker: SlowThinker | None = None
        self._running = False

    @property
    def stream(self) -> ConversationStream:
        return self._stream

    @property
    def cache(self) -> SemanticCache:
        return self._cache

    @property
    def metrics(self) -> MetricsCollector:
        return self._metrics

    def _build_llm(self):
        """Hook for tests to patch LLM construction."""
        return _OpenAIPredictor(model=self._settings.noble_rag_slow_model)

    async def start(self) -> None:
        if self._running:
            return
        emb_adapter, vs_adapter = await get_flat_store_adapters()

        self._slow_thinker = SlowThinker(
            llm=self._build_llm(),
            embeddings=emb_adapter,
            vector_store=vs_adapter,
            cache=self._cache,
            stream=self._stream,
            metrics=self._metrics,
            prediction_strategy=self._settings.noble_rag_slow_prediction_strategy,
            max_predictions=self._settings.noble_rag_slow_max_predictions,
            prefetch_top_k=self._settings.noble_rag_slow_prefetch_top_k,
            rate_limit=self._settings.noble_rag_slow_rate_limit,
            cache_ttl_seconds=self._settings.noble_rag_cache_ttl,
        )

        self._fast_talker = FastTalker(
            embeddings=emb_adapter,
            vector_store=vs_adapter,
            cache=self._cache,
            stream=self._stream,
            metrics=self._metrics,
            max_context_chunks=self._settings.noble_rag_fast_max_context_chunks,
            fallback_to_retrieval=self._settings.noble_rag_fast_fallback_to_retrieval,
        )

        await self._slow_thinker.start()
        self._running = True
        logger.info("MemoryRouter started (refactor)")

    async def stop(self) -> None:
        self._running = False
        if self._slow_thinker is not None:
            await self._slow_thinker.stop()
        logger.info("MemoryRouter stopped (refactor)")

    async def query_context(self, text: str, project_filter: str = "") -> str:
        if self._fast_talker is None:
            raise RuntimeError("MemoryRouter not started — call await router.start() first")
        await self._stream.publish(StreamEvent(
            event_type=EventType.USER_UTTERANCE, text=text,
        ))
        return await self._fast_talker.get_context(text, project_filter)

    async def publish_user_utterance(self, text: str) -> None:
        """Triggers SlowThinker prefetch path without calling FastTalker."""
        await self._stream.publish(StreamEvent(
            event_type=EventType.USER_UTTERANCE, text=text,
        ))


_router_singleton: MemoryRouter | None = None
_router_lock = asyncio.Lock()


async def get_memory_router() -> MemoryRouter:
    global _router_singleton
    if _router_singleton is not None:
        return _router_singleton
    async with _router_lock:
        if _router_singleton is None:
            r = MemoryRouter()
            await r.start()
            _router_singleton = r
    return _router_singleton


def reset_router_for_tests() -> None:
    global _router_singleton
    _router_singleton = None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/refactor/test_rag_memory_router.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/rag/memory_router.py tests/unit/refactor/test_rag_memory_router.py
git commit -m "feat(refactor/rag): build MemoryRouter (compose FlatStore + cache + talkers)"
```

---

## Task 10: Rewrite RagAdapter to wrap MemoryRouter

**Files:**
- Modify: `src/noble_agent_refactor/rag/adapter.py`
- Modify: `tests/unit/refactor/test_rag_adapter.py`

The legacy `RagAdapter` already implements the `search` + `prefetch` interface the orchestrator + `noble_search.run` use. We **keep those method signatures** so no caller has to change. Internally we either:
- Wrap a `MemoryRouter` (preferred new path), or
- Stay duck-typed for unit tests (still accept generic fast_talker/slow_thinker objects).

The two construction paths are differentiated by which kwarg is set.

- [ ] **Step 1: Update `tests/unit/refactor/test_rag_adapter.py`** — keep the existing duck-typed tests (they still pass) and append:

```python
from unittest.mock import AsyncMock, MagicMock


async def test_search_via_memory_router_calls_query_context():
    router = MagicMock()
    router.query_context = AsyncMock(return_value="ctx-block")
    from noble_agent_refactor.rag.adapter import RagAdapter
    adapter = RagAdapter(router=router)
    out = await adapter.search(query="giá", project_filter="NCLB")
    assert out == "ctx-block"
    router.query_context.assert_awaited_once_with("giá", "NCLB")


async def test_prefetch_via_memory_router_publishes_user_utterance():
    router = MagicMock()
    router.publish_user_utterance = AsyncMock()
    from noble_agent_refactor.rag.adapter import RagAdapter
    from noble_agent_refactor.storage.models import Customer

    adapter = RagAdapter(router=router)
    await adapter.prefetch("sid", "hi", Customer(project_interest="NCLB"))
    router.publish_user_utterance.assert_awaited_once_with("hi")


async def test_router_path_swallows_publish_errors():
    router = MagicMock()
    router.publish_user_utterance = AsyncMock(side_effect=RuntimeError("boom"))
    from noble_agent_refactor.rag.adapter import RagAdapter
    from noble_agent_refactor.storage.models import Customer
    adapter = RagAdapter(router=router)
    await adapter.prefetch("sid", "x", Customer())  # must NOT raise
```

- [ ] **Step 2: Run tests to verify the new ones fail**

```bash
pytest tests/unit/refactor/test_rag_adapter.py -v
```
Expected: 4 existing pass, 3 new ones fail with `TypeError: RagAdapter() got an unexpected keyword argument 'router'`.

- [ ] **Step 3: Update `src/noble_agent_refactor/rag/adapter.py`**

```python
"""RAG adapter — the bridge `noble_search` + orchestrator call into.

Two construction paths:
  • RagAdapter(router=...)               — production: wraps MemoryRouter.
  • RagAdapter(fast_talker=, slow_thinker=) — unit tests / DI.

`search()` returns a formatted context string; `prefetch()` is fire-and-forget.
"""
from __future__ import annotations

import logging
from typing import Any

from noble_agent_refactor.storage.models import Customer

logger = logging.getLogger("noble_agent_refactor.rag.adapter")


class RagAdapter:
    def __init__(
        self,
        fast_talker: Any | None = None,
        slow_thinker: Any | None = None,
        router: Any | None = None,
    ):
        if router is None and fast_talker is None:
            raise ValueError("RagAdapter needs either router= or fast_talker=")
        self._router = router
        self._fast = fast_talker
        self._slow = slow_thinker

    async def search(self, query: str, project_filter: str | None) -> str:
        pf = project_filter or ""
        try:
            if self._router is not None:
                return await self._router.query_context(query, pf)
            return await self._fast.get_context(query=query, project_filter=pf)
        except Exception:
            logger.exception("rag.search failed")
            return ""

    async def prefetch(self, sid: str, user_text: str, customer: Customer) -> None:
        try:
            if self._router is not None:
                await self._router.publish_user_utterance(user_text)
                return
            if self._slow is None:
                return
            predict = getattr(self._slow, "predict", None)
            if predict is None:
                return
            await predict(
                user_text=user_text,
                session_id=sid,
                project_filter=customer.project_interest or "",
            )
        except Exception:
            logger.exception("rag.prefetch failed")
```

- [ ] **Step 4: Run tests to verify they all pass**

```bash
pytest tests/unit/refactor/test_rag_adapter.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/rag/adapter.py tests/unit/refactor/test_rag_adapter.py
git commit -m "feat(refactor/rag): wrap MemoryRouter in RagAdapter (router= path)"
```

---

## Task 11: Wire facade to construct MemoryRouter when backend=rag

**Files:**
- Modify: `src/noble_agent_refactor/facade.py` (around line 92–98)
- Modify: `tests/unit/refactor/test_facade.py`

- [ ] **Step 1: Write the failing test** — append to `tests/unit/refactor/test_facade.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest

from noble_agent_refactor import config, facade


@pytest.mark.asyncio
async def test_build_runner_constructs_rag_adapter_when_backend_rag(monkeypatch):
    monkeypatch.setenv("NOBLE_SEARCH_BACKEND", "rag")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    config.reset_settings_for_tests()
    facade.reset_runner_for_tests()

    fake_router = AsyncMock()
    with patch(
        "noble_agent_refactor.facade.MemoryRouter", autospec=True
    ) as MR, patch(
        "noble_agent_refactor.facade.get_redis", AsyncMock(return_value=AsyncMock())
    ):
        instance = MR.return_value
        instance.start = AsyncMock()
        runner = await facade._build_runner()
        assert runner._rag is not None
        MR.assert_called_once()
        instance.start.assert_awaited_once()

    facade.reset_runner_for_tests()
    config.reset_settings_for_tests()


@pytest.mark.asyncio
async def test_build_runner_keeps_rag_none_when_backend_grep(monkeypatch):
    monkeypatch.setenv("NOBLE_SEARCH_BACKEND", "grep")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    config.reset_settings_for_tests()
    facade.reset_runner_for_tests()
    with patch("noble_agent_refactor.facade.get_redis", AsyncMock(return_value=AsyncMock())):
        runner = await facade._build_runner()
        assert runner._rag is None
    facade.reset_runner_for_tests()
    config.reset_settings_for_tests()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/refactor/test_facade.py::test_build_runner_constructs_rag_adapter_when_backend_rag -v
```
Expected: `AttributeError` (MemoryRouter not imported in facade).

- [ ] **Step 3: Edit `src/noble_agent_refactor/facade.py`** — replace the existing `rag = None` block (lines 92–98) with conditional construction. Add the import at the top of the file (with the other rag imports):

```python
from noble_agent_refactor.rag.adapter import RagAdapter
from noble_agent_refactor.rag.memory_router import MemoryRouter
```

And replace lines 92–98 with:

```python
    # RAG: noble_search routes by NOBLE_SEARCH_BACKEND (grep | rag | empty).
    # backend=grep / empty → no adapter needed (tool reads data/faq/<CODE>.md or
    # returns ""). backend=rag → build a MemoryRouter (FlatStore + SemanticCache
    # + SlowThinker prefetch) and wrap it in RagAdapter so the orchestrator's
    # existing rag.search(...) / rag.prefetch(...) contract still holds.
    rag = None
    if settings.search_backend == "rag":
        try:
            router = MemoryRouter()
            await router.start()
            rag = RagAdapter(router=router)
            logger.info("facade: RAG backend=rag, MemoryRouter started")
        except Exception:
            logger.exception("facade: failed to start MemoryRouter — falling back to rag=None")
            rag = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/refactor/test_facade.py -v
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/facade.py tests/unit/refactor/test_facade.py
git commit -m "feat(refactor/facade): wire MemoryRouter when NOBLE_SEARCH_BACKEND=rag"
```

---

## Task 12: Integration test against real FlatStore (smoke)

**Files:**
- Create: `tests/integration/refactor/test_rag_end_to_end.py`

This test is gated on the existence of the prebuilt cache files. It will be skipped on CI machines that don't have them.

- [ ] **Step 1: Write the failing test**

```python
"""End-to-end smoke test: real e5-large + FlatStore against data/flat_store cache.

Skipped if the prebuilt cache is missing — the legacy data/flat_store/
artifacts are gitignored. To enable locally, run the build script from
the legacy CLAUDE.md once.
"""
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[3] / "data" / "flat_store"
_HAS_CACHE = (DATA / "embeddings_intfloat__multilingual-e5-large.npy").is_file()

pytestmark = pytest.mark.skipif(not _HAS_CACHE, reason="data/flat_store cache missing")


@pytest.mark.asyncio
async def test_real_flat_store_returns_hits_for_known_query():
    from noble_agent_refactor.rag.flat_store_adapter import (
        query_flat_store_for_noble_kb,
    )
    out = await query_flat_store_for_noble_kb(
        "giá Noble Crystal Long Biên", "NCLB", top_k=3
    )
    assert "NCLB" in out
    assert "Diem:" in out
    assert len(out) > 50


@pytest.mark.asyncio
async def test_memory_router_query_context_returns_string():
    from noble_agent_refactor.rag.memory_router import (
        MemoryRouter, reset_router_for_tests,
    )
    reset_router_for_tests()
    router = MemoryRouter()
    await router.start()
    try:
        out = await router.query_context("tiện ích bể bơi", "NCLB")
        assert isinstance(out, str)
    finally:
        await router.stop()
        reset_router_for_tests()
```

- [ ] **Step 2: Run test**

```bash
pytest tests/integration/refactor/test_rag_end_to_end.py -v
```
Expected (local with cache): 2 passed (~5–10s first call, <100ms after). On CI without cache: skipped.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/refactor/test_rag_end_to_end.py
git commit -m "test(refactor/rag): end-to-end smoke against real FlatStore"
```

---

## Task 13: Manual verification via /chat

- [ ] **Step 1: Start the dev server with the refactor + rag backend**

```bash
USE_REFACTOR_CORE=true NOBLE_SEARCH_BACKEND=rag scripts/run.sh
```

Open `http://localhost:8766/chat`.

- [ ] **Step 2: First-turn cold-start expectation**

Send: `tiện ích Noble Crystal Long Biên`. First call should take 3–5s while FlatStore loads ONNX. Check server logs for:
- `flat_store_adapter loading FlatStore`
- `fastembed loaded intfloat/multilingual-e5-large`
- `MemoryRouter started (refactor)`

- [ ] **Step 3: Verify noble_search tool returns semantic hits**

In the trace pane on the left, click the `noble_search` tool result. It should be a non-empty text containing `[Nguon … | Du an: NCLB | Diem: …]` lines (the FlatStore adapter format), not the grep-style block.

- [ ] **Step 4: Verify SlowThinker prefetch fires**

Send a follow-up like `so sánh với Noble Palace Long Biên`. Check logs for:
- `[SlowThinker]` line or `slow_thinker.prediction` Timer entry.
- Subsequent turns hitting the same predicted topic should show `Cache HIT` in the `rag.fast_talker` logger.

- [ ] **Step 5: Run the full unit test suite**

```bash
make test-unit
```
Expected: green across the board, no regressions in legacy tests (they don't import `noble_agent_refactor.rag.*`).

- [ ] **Step 6: Commit any final tweaks**

```bash
git add -p
git commit -m "chore(refactor/rag): final tweaks from manual /chat verification"
```

---

## Risks & open questions

1. **FastEmbed first-load cost (~3–5s)**: the facade now blocks on `MemoryRouter.start()` during the first WS connect of the process. If TTFA on cold-start matters for voice, we may want to lazy-start the router on the first `noble_search` call instead of in `_build_runner`. Decision deferred — refactor is currently text-only via `/chat`, so the cold-start hit is acceptable.
2. **GEMINI fallback for `_OpenAIPredictor`**: hardcoded to `gemini-1.5-flash`. Legacy uses settings — we could surface a `NOBLE_RAG_SLOW_FALLBACK_MODEL` field if needed. Not added now to keep the settings surface small.
3. **Path resolution**: `parents[3]` only works if the package stays at `src/noble_agent_refactor/rag/`. If anyone moves the file, the data path breaks — a one-line `try: import noble_agent_refactor` self-check in module-load would catch it. Skipped for now; existing legacy file has the same fragility.
4. **No port of `faq_searcher.py` (V10)**: confirmed out-of-scope. If V10 is added later, it can reuse `flat_store.get_flat_store()`'s embedder singleton same way the legacy did — no new infrastructure required.

---

## Self-review notes

- **Spec coverage:** "Replace grep-only with real semantic search; full pipeline; ported into refactor; no FAQ inject" — all three points covered. FAQ explicitly skipped in Task list and Risks.
- **Type consistency:** `MemoryRouter`, `RagAdapter`, `SearchResult`, `Chunk`, `SearchHit` names match across tasks. `_OpenAIPredictor` signature consistent.
- **No placeholders:** every task ships full code or a "copy verbatim + apply N tiny edits" instruction. Tests are explicit.
- **One open ambiguity:** Task 11 calls `await router.start()` inside `_build_runner`. The 3–5s blocking init is documented as risk #1 but accepted.
