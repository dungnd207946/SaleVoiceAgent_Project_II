# Plan 3 — Noisy-Neighbor Guards (§4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Independent of Plans 1–2 (no contextvar dependency), but ships last. Can be done in parallel with Plan 2 if worktrees isolate them.

**Goal:** Make one shared async process safe to host many tenants' chat sessions: (1) move the only CPU-on-loop RAG path (HippoRAG PPR) off the event loop, (2) enforce an in-process chat admission cap read from env — reject / go not-ready at the ceiling and expose the reject-rate + active-session signal the phase-sau KEDA autoscaler reuses.

**Architecture:** HippoRAG `expander.expand` (numpy power-iteration PPR) currently runs inline on the event loop (`adapter.py:145`), blocking every other session mid-turn — wrap it in `run_in_executor`. Add a process-level `ChatAdmission` counter (async-safe) gated by `CHAT_MAX_CONCURRENT_SESSIONS`; the chat session boundary admits or rejects (WS close) and readiness flips false at the ceiling. Both are env-driven and in-process now, so KEDA later just scales replicas on the same signal without new code (memo §0.4).

**Tech Stack:** asyncio, numpy (existing), websockets, pytest.

## Global Constraints

- Branch `feat/agent`. **NO commit/push/PR** without explicit instruction. **Never `develop`.** (memo §10)
- **Admission cap read from config (env), enforced in-process THIS phase** — set it wide (chat is I/O-bound) but wire the enforcement + the reject/active signal now so KEDA is a config change later. (memo §0.4, §4)
- **Do NOT change voice.** LiveKit already forks a subprocess per job (per-call isolation) — only note the "set a jobs/worker ceiling" as infra, don't implement pool tuning here. (memo §4, §0)
- **HippoRAG stays default-off** (`NOBLE_RAG_BACKEND=flat_store`); the PPR offload makes it *safe* to enable under a shared process but does not enable it. (memo §4)
- Surgical; keep the qdrant-fallback + project-scoping behavior of the hipporag adapter byte-identical — only the execution seam (inline → executor) changes.
- `make test-unit` baseline, 0 new; `make lint` clean on touched files. New env var → document in `.env.example` + CLAUDE.md config table + Change Log (same commit). (memo §9, §10)

---

## File Structure

**New files:**
- `src/noble_agent/server/admission.py` — `ChatAdmission` (async-safe counter, `try_admit`/`release`/`stats`).
- `tests/unit/unified/test_admission.py`, `tests/unit/unified/rag/test_hipporag_offload.py`.

**Modified files:**
- `src/noble_agent/agent/rag/hipporag/adapter.py:145` — `expander.expand(...)` → `await loop.run_in_executor(None, lambda: expander.expand(...))`.
- `src/noble_agent/server/text_chat.py` — admit at session start, release on exit.
- `src/noble_agent/config.py` — `chat_max_concurrent_sessions: int` (env `CHAT_MAX_CONCURRENT_SESSIONS`).
- `src/noble_agent/server/http.py` — readiness endpoint reflects admission at-capacity + active count.

---

### Task 1: Offload HippoRAG PPR to a thread (`adapter.py`)

**Files:**
- Modify: `src/noble_agent/agent/rag/hipporag/adapter.py:145-154` (`query_hipporag_for_noble_kb`)
- Test: `tests/unit/unified/rag/test_hipporag_offload.py` (create)

**Interfaces:**
- `expander.expand(...)` stays synchronous; the adapter awaits it via the loop's default executor.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/rag/test_hipporag_offload.py
"""PPR expansion must run off the event loop (run_in_executor), else one
tenant's PPR blocks every other session mid-turn (memo §4)."""
import ast
import pathlib


def test_expand_is_offloaded_to_executor():
    src = pathlib.Path("src/noble_agent/agent/rag/hipporag/adapter.py").read_text()
    tree = ast.parse(src)
    # Find the assignment target `ppr_rows` and assert its value is an `await`
    # of run_in_executor (not a bare expander.expand(...) call).
    found_inline = False
    found_offloaded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ppr_rows" for t in node.targets
        ):
            v = node.value
            if isinstance(v, ast.Await):
                found_offloaded = True
            elif isinstance(v, ast.Call) and "expand" in ast.dump(v):
                found_inline = True
    assert found_offloaded and not found_inline
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/rag/test_hipporag_offload.py -v`
Expected: FAIL — `ppr_rows = expander.expand(...)` is an inline call.

- [ ] **Step 3: Implement**

In `query_hipporag_for_noble_kb`, ensure a loop handle exists (add near the top of the function if not already present: `loop = asyncio.get_event_loop()`), then replace the inline `ppr_rows = expander.expand(graph, hybrid_rows, ...)` (line 145) with:

```python
    ppr_rows = await loop.run_in_executor(
        None,
        lambda: expander.expand(
            graph,
            hybrid_rows,
            alpha=settings.hipporag_ppr_alpha,
            iters=settings.hipporag_ppr_iters,
            seed_k=settings.hipporag_seed_k,
            top_k=max(top_k * 2, top_k),
            project_filter=project_filter,
            extra_seeds=phrase_seeds,
            sparse_weight=settings.hipporag_sparse_seed_weight if sparse_on else 0.0,
        ),
    )
```

(Keep every argument identical to the current call — only the invocation is wrapped. `expander.expand` and `graph.personalized_pagerank` stay synchronous.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/rag/test_hipporag_offload.py tests/unit/unified/rag/test_hippo*.py -v`
Expected: PASS — offload test green + existing hipporag adapter tests unchanged (qdrant fallback + project-scoping behavior intact).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/rag/hipporag/adapter.py tests/unit/unified/rag/test_hipporag_offload.py
git commit -m "perf(rag): offload HippoRAG PPR expansion to a thread (loop-safe under shared process)"
```

---

### Task 2: Chat admission cap (`server/admission.py` + config + enforcement)

**Files:**
- Create: `src/noble_agent/server/admission.py`
- Modify: `src/noble_agent/config.py` (add `chat_max_concurrent_sessions`), `src/noble_agent/server/text_chat.py` (admit/release around the session)
- Test: `tests/unit/unified/test_admission.py`

**Interfaces:**
- Produces: a process singleton `chat_admission` with `async try_admit() -> bool`, `async release() -> None`, `stats() -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_admission.py
import pytest
from noble_agent.server.admission import ChatAdmission


@pytest.mark.asyncio
async def test_admits_up_to_cap_then_rejects():
    a = ChatAdmission(max_sessions=2)
    assert await a.try_admit() is True
    assert await a.try_admit() is True
    assert await a.try_admit() is False          # at cap → reject
    assert a.stats()["active"] == 2
    assert a.stats()["rejected"] == 1
    await a.release()
    assert await a.try_admit() is True            # slot freed


@pytest.mark.asyncio
async def test_zero_or_negative_cap_means_unbounded():
    a = ChatAdmission(max_sessions=0)
    for _ in range(50):
        assert await a.try_admit() is True
    assert a.stats()["at_capacity"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_admission.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

```python
# src/noble_agent/server/admission.py
"""In-process chat admission cap (memo §0.4, §4).

Enforced now so a shared multi-tenant chat process rejects rather than
degrading all sessions at overload; the active/rejected counts are the signal
the phase-sau KEDA autoscaler reuses (scale on active-sessions, not CPU%)."""

from __future__ import annotations

import asyncio


class ChatAdmission:
    def __init__(self, max_sessions: int):
        self._max = max_sessions            # <= 0 → unbounded
        self._active = 0
        self._rejected = 0
        self._admitted = 0
        self._lock = asyncio.Lock()

    async def try_admit(self) -> bool:
        async with self._lock:
            if self._max > 0 and self._active >= self._max:
                self._rejected += 1
                return False
            self._active += 1
            self._admitted += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            if self._active > 0:
                self._active -= 1

    def stats(self) -> dict:
        return {
            "active": self._active,
            "max": self._max,
            "admitted": self._admitted,
            "rejected": self._rejected,
            "at_capacity": self._max > 0 and self._active >= self._max,
        }


_admission: ChatAdmission | None = None


def get_chat_admission() -> ChatAdmission:
    global _admission
    if _admission is None:
        from noble_agent.config import get_settings

        _admission = ChatAdmission(get_settings().chat_max_concurrent_sessions)
    return _admission


def reset_admission_for_tests() -> None:
    global _admission
    _admission = None
```

Add to `config.py`:
```python
    chat_max_concurrent_sessions: int = Field(200, alias="CHAT_MAX_CONCURRENT_SESSIONS")
```
(Default wide — chat is I/O-bound; the point is the *seam*, not a tight limit.)

In `text_chat.handle_text_session`, right after the `session_id` event / before building the LLM, admit; release in a `finally`:

```python
    from noble_agent.server.admission import get_chat_admission

    admission = get_chat_admission()
    if not await admission.try_admit():
        await send({"type": "error", "message": "Hệ thống đang quá tải, vui lòng thử lại."})
        try:
            await ws.close(code=4029, reason="chat_at_capacity")
        except Exception:
            pass
        return
    try:
        ... existing session body ...
    finally:
        await admission.release()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_admission.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/server/admission.py src/noble_agent/config.py src/noble_agent/server/text_chat.py tests/unit/unified/test_admission.py
git commit -m "feat(chat): in-process admission cap (CHAT_MAX_CONCURRENT_SESSIONS) + reject/active signal"
```

---

### Task 3: Surface admission in readiness + docs

**Files:**
- Modify: `src/noble_agent/server/http.py` — the readiness/health probe reports `at_capacity` + active count (so a load balancer / KEDA can read it).
- Modify: `.env.example`, `CLAUDE.md` (config table + Change Log).

- [ ] **Step 1: Add the readiness signal**

Locate the existing health/readiness handler in `http.py` (the `/api/config` or readiness route). Fold in the admission stats and flip readiness to not-ready when at capacity:

```python
    from noble_agent.server.admission import get_chat_admission

    adm = get_chat_admission().stats()
    # ... in the readiness JSON:
    payload["chat_admission"] = adm
    ready = ready and not adm["at_capacity"]
```

(Match the actual variable/response shape in `http.py`; the deliverable is: readiness reflects `at_capacity`, and the JSON exposes `active`/`rejected` for the autoscaler.)

- [ ] **Step 2: Document + CLAUDE.md self-maintenance**

`.env.example`: add `CHAT_MAX_CONCURRENT_SESSIONS=200` with a one-line note. `CLAUDE.md`: add a config-table row and append a Change Log row (HippoRAG PPR now offloaded → loop-safe; chat admission cap added; note voice stays LiveKit-fork-per-job and the jobs/worker ceiling is infra-phase).

- [ ] **Step 3: Full gate + lint**

Run: `make test-unit && make lint`
Expected: baseline pass, 0 new; ruff clean on touched files.

- [ ] **Step 4: Commit**

```bash
git add src/noble_agent/server/http.py .env.example CLAUDE.md
git commit -m "feat(chat): readiness reflects admission at-capacity; docs + CLAUDE.md sync"
```

---

## Self-Review

**Spec coverage (memo §4):**
- HippoRAG PPR off the loop (`run_in_executor`): Task 1. ✅ (the one true CPU-on-loop exception the audit confirmed at `adapter.py:145`)
- Chat admission cap from env, enforced in-process, reject + active/reject signal for KEDA: Tasks 2, 3. ✅
- Voice unchanged (LiveKit fork-per-job), jobs/worker ceiling = infra note only: stated in Global Constraints + Task 3 Change Log. ✅
- Thread-pool sizing (memo §4 point 2, "cân nhắc dedicated RAG executor"): **deliberately deferred** — the audit shows flat_store (the default backend) already offloads to the shared default executor and is I/O-bound-adjacent; a dedicated CPU-sized executor is a tuning optimization worth doing only if load tests (memo §9 noisy-neighbor, "có thể để nhẹ ở phase này") show default-pool starvation. Recorded here as a follow-up, not built, to stay surgical.

**Placeholder scan:** real code for the admission counter + the offload wrap; Task 3 Step 1 references "match the actual readiness shape in http.py" — the implementer must read that handler, but the required behavior (expose stats + gate readiness on `at_capacity`) and the exact stats keys are fully specified. ✅

**Type consistency:** `ChatAdmission(max_sessions)`, `try_admit() -> bool`, `release()`, `stats() -> dict` (keys `active`/`max`/`admitted`/`rejected`/`at_capacity`) consistent across Tasks 2/3. ✅
