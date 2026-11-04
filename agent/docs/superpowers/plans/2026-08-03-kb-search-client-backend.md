# Agent-side `kb_search` client backend (`kb_service`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new flag-gated RAG backend `kb_service` that calls the external `kb_search` retrieval service over HTTP per the agreed contract, so `kb_search` can be pointed at that service by config once the RAG team ships it.

**Architecture:** A config-free async HTTP client (`data/kb_service.py`) speaks the contract; an adapter (`agent/rag/kb_service_adapter.py`) supplies `tenant_id`/config, maps `project_filter → project_codes`, and formats `hits → string`; `noble_kb.query_noble_kb` gains a `backend == "kb_service"` dispatch branch that wraps errors → `""`. Off by default → zero behavior change. All tests are offline (mock `httpx`).

**Tech Stack:** Python 3.11+, `httpx` (already a dep), `pydantic-settings` (`UnifiedSettings`), pytest (`asyncio_mode=auto` — async tests are plain `async def test_...`, no decorator).

## Global Constraints

- **Off by default:** `noble_rag_backend` default stays `"flat_store"`; the new code path runs ONLY when `NOBLE_RAG_BACKEND=kb_service`. No existing behavior changes.
- **Tool schema LLM unchanged:** do NOT touch `kb_search`'s tool schema (stays flat `kb_search(query, project_filter)` — PA1). No prompt change.
- **Do NOT touch:** `send_media` / `data/media_data.py`, the other RAG backends (`flat_store`/`qdrant`/`hipporag`/`grep_faq`), or `noble_kb`'s existing branches. Additive only.
- **Config-free client:** `data/kb_service.py` reads NO `settings`; all params passed by caller (mirror `data/media_data.py`) → mock-test without the service.
- **Degrade rule (contract §5):** every transport error / non-2xx / timeout / empty `kb_search_url` → return `""` (no context), never raise out of `noble_kb`. `hits: []` → `""`.
- **Contract of record:** `docs/superpowers/specs/2026-08-03-kb-search-service-api-contract.md`. Spec of record: `docs/superpowers/specs/2026-08-03-kb-search-client-backend-design.md`.
- **Style:** ruff line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Match surrounding code idiom.
- **Tests offline:** mock `httpx.AsyncClient` via the `_FakeClient`/`_FakeResp` pattern already in `tests/unit/unified/test_send_media.py`. No network, no live service.

---

### Task 1: Config keys `kb_search_*`

**Files:**
- Modify: `src/noble_agent/config.py` (after the `media_search_*` block, ends `src/noble_agent/config.py:413`)
- Modify: `.env.example` (add a documented block near the existing media-search / RAG settings)
- Test: `tests/unit/unified/rag/test_kb_service_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `UnifiedSettings.kb_search_url: str = ""`, `kb_search_token: str = ""`, `kb_search_top_k: int = 5`, `kb_search_min_score: float = 0.0`, `kb_search_timeout: float = 10.0`. Env vars (uppercase): `KB_SEARCH_URL`, `KB_SEARCH_TOKEN`, `KB_SEARCH_TOP_K`, `KB_SEARCH_MIN_SCORE`, `KB_SEARCH_TIMEOUT`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/rag/test_kb_service_config.py
from noble_agent.config import UnifiedSettings


def test_kb_search_settings_defaults(monkeypatch):
    for var in (
        "KB_SEARCH_URL",
        "KB_SEARCH_TOKEN",
        "KB_SEARCH_TOP_K",
        "KB_SEARCH_MIN_SCORE",
        "KB_SEARCH_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)
    s = UnifiedSettings(_env_file=None)
    assert s.kb_search_url == ""
    assert s.kb_search_token == ""
    assert s.kb_search_top_k == 5
    assert s.kb_search_min_score == 0.0
    assert s.kb_search_timeout == 10.0


def test_kb_search_url_from_env(monkeypatch):
    monkeypatch.setenv("KB_SEARCH_URL", "http://svc:9000/v1/kb_search")
    s = UnifiedSettings(_env_file=None)
    assert s.kb_search_url == "http://svc:9000/v1/kb_search"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/rag/test_kb_service_config.py -v`
Expected: FAIL with `AttributeError: 'UnifiedSettings' object has no attribute 'kb_search_url'`

- [ ] **Step 3: Add the config block**

Insert into `src/noble_agent/config.py` immediately after line 413 (`media_search_timeout: float = 10.0`):

```python
    # ── kb_search retrieval service (RAG-team owned, contract-driven) ─────────
    # POSTs {query, tenant_id, project_codes, top_k, min_score?} → {"hits":[...]}.
    # Active only when NOBLE_RAG_BACKEND=kb_service. Empty URL → backend degrades
    # to no-context. Contract: docs/superpowers/specs/2026-08-03-kb-search-service-api-contract.md
    kb_search_url: str = ""
    kb_search_token: str = ""
    kb_search_top_k: int = 5
    kb_search_min_score: float = 0.0
    kb_search_timeout: float = 10.0
```

- [ ] **Step 4: Document in `.env.example`**

Add near the RAG/media-search settings in `.env.example`:

```bash
# kb_search retrieval service (RAG-team owned). Set NOBLE_RAG_BACKEND=kb_service to use.
KB_SEARCH_URL=
KB_SEARCH_TOKEN=
KB_SEARCH_TOP_K=5
KB_SEARCH_MIN_SCORE=0.0
KB_SEARCH_TIMEOUT=10.0
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/unified/rag/test_kb_service_config.py -v`
Expected: PASS (both tests)

- [ ] **Step 6: Lint + commit**

```bash
ruff check src/noble_agent/config.py tests/unit/unified/rag/test_kb_service_config.py
git add src/noble_agent/config.py .env.example tests/unit/unified/rag/test_kb_service_config.py
git commit -m "feat(rag): add kb_search_* config for the kb_service backend"
```

---

### Task 2: HTTP client `data/kb_service.py`

**Files:**
- Create: `src/noble_agent/data/kb_service.py`
- Test: `tests/unit/unified/test_kb_service_client.py`

**Interfaces:**
- Consumes: nothing (config-free).
- Produces: `async def search_kb(query: str, tenant_id: str, project_codes: list[str], *, base_url: str, token: str = "", top_k: int = 5, min_score: float = 0.0, timeout: float = 10.0) -> list[dict]`. POSTs `{query, tenant_id, project_codes, top_k}` (+ `min_score` only when `> 0.0`); Bearer header when `token`; `raise_for_status()`; returns `resp.json().get("hits", []) or []`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_kb_service_client.py
"""kb_search HTTP client — data/kb_service.search_kb.

Exercises the contract request/response shape with a fake httpx.AsyncClient (no
network), mirroring tests/unit/unified/test_send_media.py.
"""
from __future__ import annotations

import httpx
import pytest

from noble_agent.data import kb_service as kb


class _FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


class _FakeClient:
    def __init__(self, resp, capture):
        self._resp = resp
        self._capture = capture

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self._capture["url"] = url
        self._capture["json"] = json
        self._capture["headers"] = headers
        return self._resp


def _patch(monkeypatch, resp, capture):
    monkeypatch.setattr(kb.httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp, capture))


async def test_posts_contract_payload_and_returns_hits(monkeypatch):
    capture: dict = {}
    resp = _FakeResp({"hits": [{"text": "t", "project_code": "NCLB", "project_name": "N"}]})
    _patch(monkeypatch, resp, capture)
    hits = await kb.search_kb(
        "tiện ích", "noble", ["NCLB"], base_url="http://svc/v1/kb_search", token="tok", top_k=5
    )
    assert capture["url"] == "http://svc/v1/kb_search"
    assert capture["json"] == {
        "query": "tiện ích",
        "tenant_id": "noble",
        "project_codes": ["NCLB"],
        "top_k": 5,
    }
    assert capture["headers"] == {"Authorization": "Bearer tok"}
    assert hits == [{"text": "t", "project_code": "NCLB", "project_name": "N"}]


async def test_min_score_included_only_when_positive(monkeypatch):
    capture: dict = {}
    _patch(monkeypatch, _FakeResp({"hits": []}), capture)
    await kb.search_kb("q", "noble", [], base_url="http://svc", min_score=0.3)
    assert capture["json"]["min_score"] == 0.3

    capture2: dict = {}
    _patch(monkeypatch, _FakeResp({"hits": []}), capture2)
    await kb.search_kb("q", "noble", [], base_url="http://svc", min_score=0.0)
    assert "min_score" not in capture2["json"]


async def test_no_token_omits_auth_header(monkeypatch):
    capture: dict = {}
    _patch(monkeypatch, _FakeResp({"hits": []}), capture)
    await kb.search_kb("q", "noble", [], base_url="http://svc")
    assert capture["headers"] == {}


async def test_missing_hits_key_returns_empty(monkeypatch):
    _patch(monkeypatch, _FakeResp({}), {})
    assert await kb.search_kb("q", "noble", [], base_url="http://svc") == []


async def test_raises_on_http_error(monkeypatch):
    _patch(monkeypatch, _FakeResp({"hits": []}, status=500), {})
    with pytest.raises(httpx.HTTPError):
        await kb.search_kb("q", "noble", [], base_url="http://svc")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_kb_service_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'noble_agent.data.kb_service'`

- [ ] **Step 3: Write the client**

```python
# src/noble_agent/data/kb_service.py
"""kb_search retrieval service HTTP client (RAG-team owned service).

Config-free by design: base_url / token / top_k / min_score / timeout are passed
in by the caller (agent/rag/kb_service_adapter), so this module never reads
settings and stays trivially testable by mocking httpx. Speaks the contract in
docs/superpowers/specs/2026-08-03-kb-search-service-api-contract.md.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("noble_agent.data.kb_service")


async def search_kb(
    query: str,
    tenant_id: str,
    project_codes: list[str],
    *,
    base_url: str,
    token: str = "",
    top_k: int = 5,
    min_score: float = 0.0,
    timeout: float = 10.0,
) -> list[dict]:
    """POST the kb_search service and return its raw ``hits`` list.

    Raises ``httpx.HTTPError`` on transport failure / non-2xx — the caller
    (kb_service_adapter via noble_kb) owns the 'never raise' degrade guarantee.
    """
    payload: dict = {
        "query": query,
        "tenant_id": tenant_id,
        "project_codes": project_codes,
        "top_k": top_k,
    }
    if min_score > 0.0:
        payload["min_score"] = min_score
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(base_url, json=payload, headers=headers)
        resp.raise_for_status()
        hits = resp.json().get("hits", []) or []
    return hits
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_kb_service_client.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/noble_agent/data/kb_service.py tests/unit/unified/test_kb_service_client.py
git add src/noble_agent/data/kb_service.py tests/unit/unified/test_kb_service_client.py
git commit -m "feat(rag): kb_search service HTTP client (config-free)"
```

---

### Task 3: Adapter `agent/rag/kb_service_adapter.py`

**Files:**
- Create: `src/noble_agent/agent/rag/kb_service_adapter.py`
- Test: `tests/unit/unified/rag/test_kb_service_adapter.py`

**Interfaces:**
- Consumes: `noble_agent.data.kb_service.search_kb(...)` (Task 2); `settings.kb_search_url/token/min_score/timeout` (Task 1); `noble_agent.tenant.current.current_tenant() -> str`.
- Produces: `async def query_kb_service_for_noble_kb(query: str, project_filter: str, top_k: int = 5) -> str` (formatted context string, `""` when nothing). Module-level `_format_kb_hits(hits: list[dict]) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/rag/test_kb_service_adapter.py
import pytest

from noble_agent.agent.rag import kb_service_adapter as ad


def test_format_includes_name_section_and_updated():
    out = ad._format_kb_hits(
        [
            {
                "text": "Bể bơi vô cực tầng 5.",
                "project_name": "Noble Crystal Long Biên",
                "section": "Noble Crystal › tiện ích",
                "updated_at": "2026-07-29T08:00:00Z",
            }
        ]
    )
    assert "Noble Crystal Long Biên › Noble Crystal › tiện ích" in out
    assert "Bể bơi vô cực tầng 5." in out
    assert "cập nhật: 2026-07-29T08:00:00Z" in out


def test_format_omits_missing_optional_fields():
    out = ad._format_kb_hits([{"text": "chỉ có text", "project_name": "Dự án X"}])
    assert "[Dự án X]" in out  # no ' › ' when section absent
    assert "›" not in out
    assert "cập nhật" not in out


def test_format_skips_empty_text_and_empty_hits():
    assert ad._format_kb_hits([]) == ""
    assert ad._format_kb_hits([{"text": "  ", "project_name": "X"}]) == ""


async def test_query_maps_filter_and_tenant(monkeypatch):
    captured: dict = {}

    async def fake_search_kb(query, tenant_id, project_codes, **kw):
        captured["args"] = (query, tenant_id, project_codes)
        captured["kw"] = kw
        return [{"text": "hit", "project_name": "N"}]

    monkeypatch.setattr(ad.kb_service, "search_kb", fake_search_kb)
    monkeypatch.setattr(ad, "current_tenant", lambda: "noble")
    monkeypatch.setattr(ad.settings, "kb_search_url", "http://svc")
    monkeypatch.setattr(ad.settings, "kb_search_token", "tok")

    out = await ad.query_kb_service_for_noble_kb("tiện ích", "NCLB", top_k=7)
    assert captured["args"] == ("tiện ích", "noble", ["NCLB"])
    assert captured["kw"]["base_url"] == "http://svc"
    assert captured["kw"]["token"] == "tok"
    assert captured["kw"]["top_k"] == 7
    assert "hit" in out


async def test_empty_filter_maps_to_empty_list(monkeypatch):
    captured: dict = {}

    async def fake_search_kb(query, tenant_id, project_codes, **kw):
        captured["codes"] = project_codes
        return []

    monkeypatch.setattr(ad.kb_service, "search_kb", fake_search_kb)
    monkeypatch.setattr(ad, "current_tenant", lambda: "noble")
    monkeypatch.setattr(ad.settings, "kb_search_url", "http://svc")

    out = await ad.query_kb_service_for_noble_kb("q", "")
    assert captured["codes"] == []
    assert out == ""  # empty hits → ""


async def test_empty_query_returns_empty():
    assert await ad.query_kb_service_for_noble_kb("  ", "NCLB") == ""


async def test_empty_url_returns_empty(monkeypatch):
    monkeypatch.setattr(ad.settings, "kb_search_url", "")
    assert await ad.query_kb_service_for_noble_kb("tiện ích", "NCLB") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/rag/test_kb_service_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'noble_agent.agent.rag.kb_service_adapter'`

- [ ] **Step 3: Write the adapter**

```python
# src/noble_agent/agent/rag/kb_service_adapter.py
"""Adapter: kb_search retrieval service → noble_kb context string.

Supplies tenant_id + config to the config-free client, maps the flat tool arg
``project_filter`` → the contract's ``project_codes`` list, and formats the
returned ``hits`` into the one-block-per-hit context string noble_kb expects.
Errors are NOT caught here — noble_kb._query_via_kb_service wraps them → "".
"""

from __future__ import annotations

import logging

from noble_agent.config import settings
from noble_agent.data import kb_service
from noble_agent.tenant.current import current_tenant

logger = logging.getLogger("rag.kb_service_adapter")


def _format_kb_hits(hits: list[dict]) -> str:
    """One block per hit, separated by '\\n---\\n'. Only ``text`` is required;
    optional fields (project_name/section/updated_at) are omitted when absent."""
    blocks: list[str] = []
    for h in hits:
        text = (h.get("text") or "").strip()
        if not text:
            continue
        name = (h.get("project_name") or "").strip()
        section = (h.get("section") or "").strip()
        updated = (h.get("updated_at") or "").strip()
        parts: list[str] = []
        if name and section:
            parts.append(f"[{name} › {section}]")
        elif name:
            parts.append(f"[{name}]")
        elif section:
            parts.append(f"[{section}]")
        parts.append(text)
        if updated:
            parts.append(f"(cập nhật: {updated})")
        blocks.append("\n".join(parts))
    return "\n---\n".join(blocks)


async def query_kb_service_for_noble_kb(query: str, project_filter: str, top_k: int = 5) -> str:
    query = (query or "").strip()
    project_filter = (project_filter or "").strip()
    if not query:
        return ""
    base_url = settings.kb_search_url
    if not base_url:
        logger.warning("[kb_service_adapter] kb_search_url empty — returning no context")
        return ""
    tenant_id = current_tenant()
    project_codes = [project_filter] if project_filter else []
    hits = await kb_service.search_kb(
        query,
        tenant_id,
        project_codes,
        base_url=base_url,
        token=settings.kb_search_token,
        top_k=top_k,
        min_score=settings.kb_search_min_score,
        timeout=settings.kb_search_timeout,
    )
    return _format_kb_hits(hits)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/rag/test_kb_service_adapter.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/noble_agent/agent/rag/kb_service_adapter.py tests/unit/unified/rag/test_kb_service_adapter.py
git add src/noble_agent/agent/rag/kb_service_adapter.py tests/unit/unified/rag/test_kb_service_adapter.py
git commit -m "feat(rag): kb_service adapter (tenant + project_codes mapping + hit formatting)"
```

---

### Task 4: Dispatch branch in `noble_kb` + full gate

**Files:**
- Modify: `src/noble_agent/agent/rag/noble_kb.py` (add branch in `query_noble_kb`, ~line 68-72; add `_query_via_kb_service` near `_query_via_qdrant`, ~line 100)
- Test: `tests/unit/unified/rag/test_kb_service_dispatch.py`

**Interfaces:**
- Consumes: `noble_agent.agent.rag.kb_service_adapter.query_kb_service_for_noble_kb(query, project_filter, top_k)` (Task 3); `settings.kb_search_top_k` (Task 1); `settings.noble_rag_backend`.
- Produces: `query_noble_kb` routes `backend == "kb_service"` → `_query_via_kb_service`; the latter wraps all errors → `""`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/rag/test_kb_service_dispatch.py
from noble_agent.agent.rag import noble_kb


async def test_dispatch_routes_to_kb_service(monkeypatch):
    called: dict = {}

    async def fake_query(query, project_filter, top_k=5):
        called["args"] = (query, project_filter, top_k)
        return "CTX"

    # noble_kb imports the adapter lazily inside _query_via_kb_service; patch the
    # module attribute the branch calls.
    import noble_agent.agent.rag.kb_service_adapter as ad

    monkeypatch.setattr(ad, "query_kb_service_for_noble_kb", fake_query)
    monkeypatch.setattr(noble_kb.settings, "noble_rag_backend", "kb_service")
    monkeypatch.setattr(noble_kb.settings, "kb_search_top_k", 9)

    out = await noble_kb.query_noble_kb("tiện ích", "NCLB")
    assert out == "CTX"
    assert called["args"] == ("tiện ích", "NCLB", 9)


async def test_dispatch_kb_service_degrades_on_error(monkeypatch):
    async def boom(query, project_filter, top_k=5):
        raise RuntimeError("service down")

    import noble_agent.agent.rag.kb_service_adapter as ad

    monkeypatch.setattr(ad, "query_kb_service_for_noble_kb", boom)
    monkeypatch.setattr(noble_kb.settings, "noble_rag_backend", "kb_service")

    out = await noble_kb.query_noble_kb("tiện ích", "NCLB")
    assert out == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/rag/test_kb_service_dispatch.py -v`
Expected: FAIL (backend `kb_service` falls through to flat_store, so `called` is never set / `out != "CTX"`)

- [ ] **Step 3: Add the dispatch branch**

In `src/noble_agent/agent/rag/noble_kb.py`, inside `query_noble_kb`, add after the `qdrant` branch (before the `hipporag` branch, around line 68):

```python
    if backend == "kb_service":
        return await _query_via_kb_service(query, project)
```

Then add this function next to `_query_via_qdrant` (mirror its shape):

```python
async def _query_via_kb_service(query: str, project_filter: str) -> str:
    """External kb_search retrieval service (RAG-team owned). Wraps all errors →
    "" so a service failure never breaks the turn (contract §5 degrade rule)."""
    try:
        from noble_agent.agent.rag.kb_service_adapter import query_kb_service_for_noble_kb

        result = await query_kb_service_for_noble_kb(
            query,
            project_filter,
            top_k=settings.kb_search_top_k if settings.kb_search_top_k > 0 else 5,
        )
        if result:
            logger.info(
                "[noble_kb] kb_service returned %d chars (project=%s)", len(result), project_filter or "ALL"
            )
        return result or ""
    except Exception as exc:
        logger.warning("[noble_kb] kb_service error: %s — returning empty", exc)
        return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/rag/test_kb_service_dispatch.py -v`
Expected: PASS (2 tests)

Note: the dispatch test patches `kb_service_adapter.query_kb_service_for_noble_kb`; because `_query_via_kb_service` imports it lazily from that module each call, patching the module attribute takes effect.

- [ ] **Step 5: Full unit gate + lint**

Run: `make test-unit`
Expected: the documented baseline failures only (SP2 ledger records ~10 baseline-red, e.g. 2 USD-normalize, `test_tool_ack` flaky, qdrant_adapter×2, qdrant_store, prompt 'Tên:', send_media local-.env, project_financial_mongo) + **ZERO new failures**; the 4 new test files all green.

Run: `ruff check src/noble_agent/agent/rag/noble_kb.py tests/unit/unified/rag/test_kb_service_dispatch.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/agent/rag/noble_kb.py tests/unit/unified/rag/test_kb_service_dispatch.py
git commit -m "feat(rag): wire kb_service backend into noble_kb dispatch (degrade-safe)"
```

---

## Notes for the implementer

- **Async tests need no decorator** — `pytest.ini`/`pyproject` sets `asyncio_mode=auto`, so `async def test_...` runs directly (see existing `tests/unit/unified/rag/test_qdrant_adapter.py`).
- **Do not add a try/except inside the adapter** (Task 3) — the single catch point is `_query_via_kb_service` in `noble_kb` (Task 4), mirroring how `_query_via_qdrant` is the wrapper. The adapter only short-circuits on empty query / empty URL.
- **`pytest` import** is only needed where `pytest.raises` is used (Task 2). Don't import it elsewhere — ruff `F401` flags unused imports.
- Keep every diff additive; if `make test-unit` shows a NEW failure, it is from this change — fix before committing Task 4.
```
