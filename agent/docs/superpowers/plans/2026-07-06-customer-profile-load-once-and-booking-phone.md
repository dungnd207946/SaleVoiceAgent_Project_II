# Customer profile load-once + booking phone flow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load the caller's profile once (by phone, from Mongo `customers` + `bookings_flat`) at the start of a call and freeze it in the system prompt; make the agent proactively collect the name and confirm the booking phone at booking time; drop the Noble-Profile ecosystem lookup.

**Architecture:** A one-time bootstrap guard in `TurnRunner.handle_turn` (first turn only) merges the DB profile into the live `Customer` and freezes the rendered profile block into `state.scratchpad["customer_block"]`. `build_system_prompt` gains an optional `customer_block` override so every turn reuses the frozen block instead of re-rendering the mutating `Customer`. The mid-turn `consume_customer_dirty` rebuild is removed. Booking gains a `phone` param written only to the `bookings_flat` row (never overwriting `customer.phone`).

**Tech Stack:** Python 3.11+, pydantic v2, jinja2, pytest (`asyncio_mode=auto`), fakeredis, MongoDB (motor), Redis.

## Global Constraints

- **Branch:** `feat/refactor2`. Never touch `develop`. Local commits on the feature branch only; no push/PR/merge without explicit instruction.
- **CMS is read-only over Mongo — no HTTP to `agent-cms.noble.vn`.** All CMS updates are Mongo writes to `customers` / `call_summaries` / `bookings_flat` via the existing persist layer (`storage/persist.py`, `storage/call_summaries.py`, `storage/bookings_flat.py`, `storage/session_store.py`). Do not add an HTTP client.
- **Mongo write field contracts are fixed** (`docs/cms-mongo-field-map.md`): `bookings_flat.phone` / `customer_name` / `project`; `call_summaries.customer_name` / `phone` / `project_code` top-level; `agent_messages.role ∈ {agent,caller}`. Do not change field names/types.
- **Ruff:** line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Run `make lint` before each commit.
- **Phone format:** VN mobile `^(0[35789])\d{8}$` (10 digits, prefix 03/05/07/08/09), stripped of spaces/dots/dashes — same rule as `update_customer`.
- **All Mongo helpers are best-effort:** return `{}`/`None` and log on `get_db() is None` or any exception; never raise into the turn path.
- **Spec:** `docs/superpowers/specs/2026-07-06-customer-profile-load-once-and-booking-phone-design.md`.

---

### Task 1: `load_latest_booking_hint_by_phone` helper (bookings_flat fallback source)

**Files:**
- Modify: `src/noble_agent/storage/session_store.py` (add function after `load_customer_by_phone`, ~line 277)
- Test: `tests/unit/unified/test_booking_hint.py` (create)

**Interfaces:**
- Produces: `async def load_latest_booking_hint_by_phone(phone: str) -> dict` returning `{"customer_name": str, "project": str}` for the most recent `bookings_flat` row for `phone`, or `{}` if none / Mongo down. Consumed by Task 2.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_booking_hint.py`:

```python
import pytest

from noble_agent.storage import session_store


class _FakeColl:
    def __init__(self, doc):
        self._doc = doc
        self.last_sort = None

    async def find_one(self, query, sort=None):
        self.last_sort = sort
        return self._doc


class _FakeDB:
    def __init__(self, doc):
        self.bookings_flat = _FakeColl(doc)


def _patch_db(monkeypatch, db):
    async def _get_db():
        return db

    monkeypatch.setattr("noble_agent.storage.mongo_client.get_db", _get_db)


async def test_hint_returns_name_and_project_from_latest_row(monkeypatch):
    db = _FakeDB({"customer_name": "Hùng", "project": "NCLB", "phone": "0901234567"})
    _patch_db(monkeypatch, db)
    hint = await session_store.load_latest_booking_hint_by_phone("0901234567")
    assert hint == {"customer_name": "Hùng", "project": "NCLB"}
    assert db.bookings_flat.last_sort == [("updated_at", -1)]


async def test_hint_empty_when_no_row(monkeypatch):
    _patch_db(monkeypatch, _FakeDB(None))
    assert await session_store.load_latest_booking_hint_by_phone("0901234567") == {}


async def test_hint_empty_when_no_phone(monkeypatch):
    _patch_db(monkeypatch, _FakeDB({"customer_name": "x"}))
    assert await session_store.load_latest_booking_hint_by_phone("") == {}


async def test_hint_empty_when_mongo_down(monkeypatch):
    async def _get_db():
        return None

    monkeypatch.setattr("noble_agent.storage.mongo_client.get_db", _get_db)
    assert await session_store.load_latest_booking_hint_by_phone("0901234567") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_booking_hint.py -v`
Expected: FAIL with `AttributeError: module 'noble_agent.storage.session_store' has no attribute 'load_latest_booking_hint_by_phone'`

- [ ] **Step 3: Write minimal implementation**

In `src/noble_agent/storage/session_store.py`, immediately after `load_customer_by_phone` (before `save_customer_persistent`):

```python
async def load_latest_booking_hint_by_phone(phone: str) -> dict:
    """Most-recent ``bookings_flat`` row for ``phone`` → ``{customer_name, project}``.

    Fallback profile source at call start when the ``customers`` collection lacks
    a name/project. Empty dict if none or MongoDB unavailable — callers tolerate.
    """
    from noble_agent.storage.mongo_client import get_db

    db = await get_db()
    if db is None or not phone:
        return {}
    try:
        doc = await db.bookings_flat.find_one({"phone": phone}, sort=[("updated_at", -1)])
    except Exception as exc:
        logger.warning("load_latest_booking_hint_by_phone failed: %s", exc)
        return {}
    if not doc:
        return {}
    return {"customer_name": doc.get("customer_name", ""), "project": doc.get("project", "")}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_booking_hint.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
make lint
git add src/noble_agent/storage/session_store.py tests/unit/unified/test_booking_hint.py
git commit -m "feat(storage): load_latest_booking_hint_by_phone (bookings_flat profile fallback)"
```

---

### Task 2: `bootstrap_customer_profile` — one-time DB merge into the live Customer

**Files:**
- Create: `src/noble_agent/agent/customer_bootstrap.py`
- Test: `tests/unit/unified/test_customer_bootstrap.py` (create)

**Interfaces:**
- Consumes: `session_store.load_customer_by_phone(phone) -> dict` (existing), `session_store.load_latest_booking_hint_by_phone(phone) -> dict` (Task 1), `catalog.normalize(str) -> str` (existing).
- Produces: `async def bootstrap_customer_profile(customer: Customer) -> None` — mutates `customer` in place; no-op when `customer.phone` empty. Consumed by Task 5.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_customer_bootstrap.py`:

```python
import pytest

from noble_agent.agent.customer_bootstrap import bootstrap_customer_profile
from noble_agent.storage import session_store
from noble_agent.storage.models import Customer


def _patch(monkeypatch, profile: dict, hint: dict):
    async def _prof(phone):
        return profile

    async def _hint(phone):
        return hint

    monkeypatch.setattr(session_store, "load_customer_by_phone", _prof)
    monkeypatch.setattr(session_store, "load_latest_booking_hint_by_phone", _hint)


async def test_no_phone_is_noop(monkeypatch):
    called = {"prof": False}

    async def _prof(phone):
        called["prof"] = True
        return {}

    monkeypatch.setattr(session_store, "load_customer_by_phone", _prof)
    c = Customer()
    await bootstrap_customer_profile(c)
    assert called["prof"] is False
    assert c.name is None


async def test_merges_customers_doc(monkeypatch):
    _patch(monkeypatch, {"name": "Hùng", "gender": "M", "project_interest": "NCLB"}, {})
    c = Customer(phone="0901234567")
    await bootstrap_customer_profile(c)
    assert c.name == "Hùng"
    assert c.gender == "M"
    assert c.project_interest == "NCLB"
    assert c.phone == "0901234567"  # untouched


async def test_booking_hint_fills_missing_name_and_project(monkeypatch):
    _patch(monkeypatch, {}, {"customer_name": "Lan", "project": "NCLB"})
    c = Customer(phone="0901234567")
    await bootstrap_customer_profile(c)
    assert c.name == "Lan"
    assert c.project_interest == "NCLB"


async def test_customers_doc_wins_over_booking_hint(monkeypatch):
    _patch(monkeypatch, {"name": "Hùng"}, {"customer_name": "Lan", "project": "SLC"})
    c = Customer(phone="0901234567")
    await bootstrap_customer_profile(c)
    assert c.name == "Hùng"  # customers doc wins
    assert c.project_interest == "SLC"  # project only in hint → used


async def test_unknown_project_dropped(monkeypatch):
    _patch(monkeypatch, {"project_interest": "not-a-code"}, {})
    c = Customer(phone="0901234567")
    await bootstrap_customer_profile(c)
    assert c.project_interest is None


async def test_empty_db_leaves_only_phone(monkeypatch):
    _patch(monkeypatch, {}, {})
    c = Customer(phone="0901234567")
    await bootstrap_customer_profile(c)
    assert c.name is None
    assert c.phone == "0901234567"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_customer_bootstrap.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'noble_agent.agent.customer_bootstrap'`

- [ ] **Step 3: Write minimal implementation**

Create `src/noble_agent/agent/customer_bootstrap.py`:

```python
"""One-time, per-session customer-profile bootstrap.

At the first turn of a call we look the caller up by phone in MongoDB and merge
what we find into the live ``Customer``. MongoDB is the source of truth for the
frozen profile snapshot: a DB value overwrites the current field; a missing/empty
DB value leaves the current field untouched. Falls back to the most recent
``bookings_flat`` row for name/project when ``customers`` lacks them. No-op (and
no I/O) when ``customer.phone`` is empty (blocked/withheld first-ever caller).
"""

from __future__ import annotations

import logging

from noble_agent.storage.models import Customer

logger = logging.getLogger("noble_agent.agent.customer_bootstrap")

# Fields accepted from the DB profile into the frozen snapshot. Mirrors the
# Customer model minus `phone` (the lookup key) and `is_buyer` (session-only).
_MERGE_FIELDS = (
    "name",
    "full_name",
    "gender",
    "project_interest",
    "purpose",
    "budget",
    "preferred_area",
    "bedroom_count",
    "is_noble_customer",
    "noble_info",
)


async def bootstrap_customer_profile(customer: Customer) -> None:
    """Merge the DB profile for ``customer.phone`` into ``customer`` in place."""
    phone = (customer.phone or "").strip()
    if not phone:
        logger.info("bootstrap: no phone on session — skipping profile lookup")
        return

    from noble_agent.agent import catalog
    from noble_agent.storage import session_store

    profile = await session_store.load_customer_by_phone(phone)
    hint = await session_store.load_latest_booking_hint_by_phone(phone)

    # bookings_flat fallback for the two fields it carries.
    if not profile.get("name") and not profile.get("full_name") and hint.get("customer_name"):
        profile["name"] = hint["customer_name"]
    if not profile.get("project_interest") and hint.get("project"):
        profile["project_interest"] = hint["project"]

    applied: list[str] = []
    for field in _MERGE_FIELDS:
        value = profile.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if field == "project_interest":
            value = catalog.normalize(value)
            if not value:
                continue
        setattr(customer, field, value)
        applied.append(field)
    logger.info("bootstrap: phone=%s applied=%s", phone, applied)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_customer_bootstrap.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
make lint
git add src/noble_agent/agent/customer_bootstrap.py tests/unit/unified/test_customer_bootstrap.py
git commit -m "feat(agent): bootstrap_customer_profile — one-time DB merge by phone"
```

---

### Task 3: `build_system_prompt` accepts a frozen `customer_block`; add `render_customer_block`

**Files:**
- Modify: `src/noble_agent/agent/prompts/builder.py:39-55`
- Test: `tests/unit/unified/test_prompt_builder.py` (add tests)

**Interfaces:**
- Produces: `render_customer_block(agent: AgentDef, customer: Customer) -> str` (renders the profile block once). `build_system_prompt(agent, customer, prior_summary, *, customer_block: str | None = None) -> str` — uses `customer_block` verbatim when given, else renders from `customer` (back-compat). Consumed by Tasks 4 & 5.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/unified/test_prompt_builder.py`:

```python
def test_render_customer_block_standalone(agent):
    from noble_agent.agent.prompts.builder import render_customer_block

    block = render_customer_block(agent, Customer(name="Hùng", phone="0901234567"))
    assert "Hùng" in block
    assert "0901234567" in block


def test_build_uses_frozen_customer_block_verbatim(agent):
    # A frozen block from a DIFFERENT customer must win over the live customer.
    frozen = render_customer_block(agent, Customer(name="Minh", phone="0912345678"))
    prompt = build_system_prompt(
        agent,
        Customer(name="Hùng", phone="0901234567"),
        None,
        customer_block=frozen,
    )
    assert "Minh" in prompt
    assert "0912345678" in prompt
    assert "Hùng" not in prompt  # live customer ignored when block is frozen
```

(Add `from noble_agent.agent.prompts.builder import render_customer_block` at the top of the file, next to the existing `build_system_prompt` import.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_prompt_builder.py -v`
Expected: FAIL with `ImportError: cannot import name 'render_customer_block'`

- [ ] **Step 3: Write minimal implementation**

In `src/noble_agent/agent/prompts/builder.py`, add `render_customer_block` after `_render_customer` (line 25) and change `build_system_prompt`:

```python
def render_customer_block(agent: AgentDef, customer: Customer) -> str:
    """Render the customer profile block once (used to freeze it per session)."""
    return _render_customer(agent.sections["customer_format"], customer)


def build_system_prompt(
    agent: AgentDef,
    customer: Customer,
    prior_summary: ThreadSummary | None,
    *,
    customer_block: str | None = None,
) -> str:
    block = customer_block if customer_block is not None else _render_customer(
        agent.sections["customer_format"], customer
    )
    # Pass the summary text directly (not model_dump()) so the template can't
    # accidentally render `updated_at: datetime(...)` into the system prompt.
    summary_text = (prior_summary.text or "").strip() if prior_summary else None
    return agent.prompt_template.render(
        soul=agent.sections["soul"],
        rules=agent.sections["rules"],
        project_table=_project_table(),
        customer_block=block,
        prior_summary=summary_text or None,
        today=_today_vn(),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_prompt_builder.py -v`
Expected: PASS (all — existing 5 + new 2; the 3-positional-arg existing calls still work because `customer_block` is keyword-only with a default)

- [ ] **Step 5: Commit**

```bash
make lint
git add src/noble_agent/agent/prompts/builder.py tests/unit/unified/test_prompt_builder.py
git commit -m "feat(prompt): build_system_prompt accepts frozen customer_block override"
```

---

### Task 4: Runner uses the frozen block; remove the mid-turn dirty rebuild

**Files:**
- Modify: `src/noble_agent/agent/runner.py:35` and `:105-109`
- Test: `tests/unit/unified/test_runner.py` (replace one test, add one)

**Interfaces:**
- Consumes: `build_system_prompt(..., customer_block=...)` (Task 3), `state.scratchpad["customer_block"]` (set by Task 5; may be absent in direct unit calls → falls back to live render).

- [ ] **Step 1: Write the failing test (replace the rebuild test)**

In `tests/unit/unified/test_runner.py`, DELETE `test_customer_dirty_triggers_prompt_rebuild` (lines 104-145) and replace with:

```python
async def test_no_prompt_rebuild_mid_turn(agent):
    """update_customer / booking(schedule) no longer rebuild the prompt mid-turn.
    build_system_prompt is called exactly once per turn (freeze semantics)."""
    from unittest.mock import patch

    state = State(history=[ThreadMessage(role="user", content="hỏi noble crystal")])
    customer = Customer()
    tc = {"id": "c1", "type": "function", "function": {"name": "update_customer", "arguments": '{"name":"Hùng"}'}}
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(side_effect=[("", [tc]), ("ok", [])])
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value="{}")

    with patch("noble_agent.agent.runner.build_system_prompt", wraps=None) as spy:
        spy.return_value = "SYS"
        await run_turn(agent=agent, state=state, customer=customer, llm=llm, dispatcher=dispatcher, callbacks=_Sink())

    assert spy.call_count == 1


async def test_run_turn_uses_frozen_customer_block(agent):
    state = State(history=[ThreadMessage(role="user", content="hi")])
    state.scratchpad["customer_block"] = "__FROZEN_BLOCK__"
    customer = Customer(name="Hùng")  # live customer differs from the frozen block
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("hello!", []))
    dispatcher = MagicMock()

    await run_turn(agent=agent, state=state, customer=customer, llm=llm, dispatcher=dispatcher, callbacks=_Sink())

    sent_messages = llm.stream_completion.call_args.kwargs["messages"]
    assert "__FROZEN_BLOCK__" in sent_messages[0]["content"]
    assert "Hùng" not in sent_messages[0]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_runner.py -v`
Expected: FAIL — `test_run_turn_uses_frozen_customer_block` fails because `run_turn` still renders from the live `customer` (frozen block ignored), and `test_no_prompt_rebuild_mid_turn` may fail because the runner still calls `build_system_prompt` twice when `consume_customer_dirty` is truthy.

- [ ] **Step 3: Write minimal implementation**

In `src/noble_agent/agent/runner.py`, change line 35:

```python
    system = build_system_prompt(
        agent, customer, state.summary, customer_block=state.scratchpad.get("customer_block")
    )
```

And DELETE the mid-turn rebuild block (current lines 105-109):

```python
        if dispatcher.consume_customer_dirty():
            messages[0] = {
                "role": "system",
                "content": build_system_prompt(agent, customer, state.summary),
            }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_runner.py -v`
Expected: PASS (all runner tests; the remaining `dispatcher.consume_customer_dirty = MagicMock(...)` lines in other tests are now unused but harmless)

- [ ] **Step 5: Commit**

```bash
make lint
git add src/noble_agent/agent/runner.py tests/unit/unified/test_runner.py
git commit -m "feat(runner): use frozen customer_block; drop mid-turn dirty rebuild"
```

---

### Task 5: Orchestrator bootstrap guard (first turn) + thread frozen block into cache-warm

**Files:**
- Modify: `src/noble_agent/agent/orchestrator.py` (imports ~line 12; guard after line 121; warm chain lines 197-204, 294-320, 322-336, 338-365)
- Test: `tests/unit/unified/test_runner.py` (add handle_turn test)

**Interfaces:**
- Consumes: `bootstrap_customer_profile` (Task 2), `render_customer_block` (Task 3).
- Produces: after the first `handle_turn`, `state.scratchpad["customer_block"]` (str) and `state.scratchpad["_profile_loaded"] = True` are persisted; the cache-warm renders the same frozen block.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/unified/test_runner.py`:

```python
async def test_handle_turn_bootstraps_profile_once(agent, repo, settings, monkeypatch):
    now = datetime.now(UTC)
    await repo.save_all(
        "sid-C",
        Meta(session_id="sid-C", started_at=now, last_active=now, phone="0901234567"),
        Customer(phone="0901234567"),
        State(),
    )

    calls = {"n": 0}

    async def fake_bootstrap(customer):
        calls["n"] += 1
        customer.name = "Hùng"

    monkeypatch.setattr("noble_agent.agent.orchestrator.bootstrap_customer_profile", fake_bootstrap)

    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("ok", []))
    runner = TurnRunner(repo=repo, agent_def=agent, llm=llm, rag=None, settings=settings)

    await runner.handle_turn("sid-C", "xin chào", _Sink())
    await runner.handle_turn("sid-C", "câu hai", _Sink())

    assert calls["n"] == 1  # bootstrap runs only on the first turn
    _, customer, state = await repo.load("sid-C")
    assert state.scratchpad.get("_profile_loaded") is True
    assert "Hùng" in state.scratchpad.get("customer_block", "")
    assert customer.name == "Hùng"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_runner.py::test_handle_turn_bootstraps_profile_once -v`
Expected: FAIL with `AttributeError: <module 'noble_agent.agent.orchestrator'> does not have the attribute 'bootstrap_customer_profile'`

- [ ] **Step 3: Write minimal implementation**

In `src/noble_agent/agent/orchestrator.py`:

(a) Update imports (line 12):

```python
from noble_agent.agent.customer_bootstrap import bootstrap_customer_profile
from noble_agent.agent.prompts.builder import build_system_prompt, render_customer_block
```

(b) Insert the guard immediately after `meta, customer, state = await self._repo.load(sid)` (line 121), before `history_anchor = len(state.history)`:

```python
            # One-time customer-profile bootstrap. On the first turn of a session,
            # look the caller up by phone (Mongo customers + latest bookings_flat)
            # and FREEZE the rendered profile block for the whole call. Later turns
            # reuse the frozen block — update_customer still mutates `customer`
            # (for summary/booking/persist) but never changes the displayed block.
            if not state.scratchpad.get("_profile_loaded"):
                await bootstrap_customer_profile(customer)
                state.scratchpad["customer_block"] = render_customer_block(self._agent, customer)
                state.scratchpad["_profile_loaded"] = True
```

(c) Thread the frozen block into the cache-warm so it warms the SAME prefix the next live turn builds. At the warm scheduling site (lines 197-204), add `customer_block=state.scratchpad.get("customer_block")`:

```python
                task = asyncio.create_task(
                    self._run_summary_then_warm(
                        sid=sid,
                        history=list(state.history),
                        prior_summary=state.summary,
                        customer=customer.model_copy(deep=True),
                        customer_block=state.scratchpad.get("customer_block"),
                    )
                )
```

Add `customer_block: str | None = None` to the signatures of `_run_summary_then_warm` (line 294), `_schedule_warm` (line 322), and `_warm` (line 338), forwarding it through each call (`self._schedule_warm(..., customer_block=customer_block)` and `self._warm(..., customer_block=customer_block)`), and use it at line 354:

```python
            system = build_system_prompt(self._agent, customer, new_summary, customer_block=customer_block)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_runner.py -v`
Expected: PASS (all, including `test_handle_turn_persists_history` and the summary test — `Customer()` has no phone in those, so `bootstrap_customer_profile` is a no-op and touches no Mongo)

- [ ] **Step 5: Commit**

```bash
make lint
git add src/noble_agent/agent/orchestrator.py tests/unit/unified/test_runner.py
git commit -m "feat(orchestrator): one-time profile bootstrap + freeze block; warm uses frozen block"
```

---

### Task 6: Booking `phone` param — written to the booking row only, never to customer.phone

**Files:**
- Modify: `src/noble_agent/agent/tools/schemas.py:206-252` (booking schema: add `phone` prop + description)
- Modify: `src/noble_agent/agent/tools/schedule_viewing.py` (imports + `schedule_viewing`)
- Test: `tests/unit/unified/test_booking_phone.py` (create)

**Interfaces:**
- Consumes: `schedule_viewing(state, customer, args: dict, session_id: str) -> str` (existing signature — unchanged); reads new `args["phone"]`.
- Produces: booking row `phone = args.get("phone") or customer.phone` (validated); `customer.phone` is NOT mutated.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_booking_phone.py`:

```python
import json

import pytest

from noble_agent.agent.tools import schedule_viewing as sv
from noble_agent.storage.models import Customer, State


@pytest.fixture(autouse=True)
def _no_mongo(monkeypatch):
    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(sv, "_persist_flat", _noop)
    monkeypatch.setattr("noble_agent.storage.persist.fire_and_forget", lambda coro: coro.close())


async def test_booking_defaults_to_caller_phone():
    state = State()
    customer = Customer(phone="0901234567")
    out = json.loads(
        await sv.schedule_viewing(
            state, customer,
            {"project": "NCLB", "preferred_date": "31/12/2030", "preferred_time": "09:00 - 10:00", "confirmed": True},
            "sid-1",
        )
    )
    assert out["success"] is True
    bookings = json.loads(state.scratchpad["bookings"])
    assert bookings[-1]["phone"] == "0901234567"
    assert customer.phone == "0901234567"


async def test_booking_uses_explicit_phone_without_touching_customer():
    state = State()
    customer = Customer(phone="0901234567")
    await sv.schedule_viewing(
        state, customer,
        {"project": "NCLB", "preferred_date": "31/12/2030", "preferred_time": "09:00 - 10:00",
         "confirmed": True, "phone": "0912 345 678"},
        "sid-2",
    )
    bookings = json.loads(state.scratchpad["bookings"])
    assert bookings[-1]["phone"] == "0912345678"  # cleaned
    assert customer.phone == "0901234567"  # caller-ID identity untouched


async def test_booking_rejects_invalid_phone():
    state = State()
    customer = Customer(phone="0901234567")
    out = json.loads(
        await sv.schedule_viewing(
            state, customer,
            {"project": "NCLB", "preferred_date": "31/12/2030", "preferred_time": "09:00 - 10:00",
             "confirmed": True, "phone": "123"},
            "sid-3",
        )
    )
    assert out["success"] is False
    assert "điện thoại" in out["error"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_booking_phone.py -v`
Expected: FAIL — `test_booking_uses_explicit_phone...` fails (booking ignores `phone`, uses `customer.phone`) and `test_booking_rejects_invalid_phone` fails (no validation → succeeds).

- [ ] **Step 3: Write minimal implementation**

In `src/noble_agent/agent/tools/schedule_viewing.py`, add near the top (after `import random`):

```python
import re

_PHONE_REGEX = re.compile(r"^(0[35789])\d{8}$")
```

In `schedule_viewing`, after the `norm_project, errors = _normalize_and_validate(...)` block and its `if errors:` return (currently line 87-92), add:

```python
    booking_phone = re.sub(r"[\s.\-]", "", str(args.get("phone") or customer.phone or ""))
    if booking_phone and not _PHONE_REGEX.match(booking_phone):
        return json.dumps(
            {
                "ok": False,
                "success": False,
                "error": "Số điện thoại không hợp lệ (cần 10 số, đầu 03/05/07/08/09). Hỏi lại khách số dùng để đặt lịch.",
            },
            ensure_ascii=False,
        )
```

Then in the `booking = {...}` dict (currently line 115-126) change the phone line from `"phone": customer.phone or "",` to:

```python
        "phone": booking_phone,
```

In `src/noble_agent/agent/tools/schemas.py`, in the `booking` schema (line 206), update the `description` and add the `phone` property:

- Replace the description trailing sentence `"...Chỉ cần dự án, ngày và giờ; không cần tên hay số điện thoại."` with:
  `"...schedule cần dự án, ngày, giờ và TÊN khách trong hồ sơ; xác nhận số điện thoại đặt lịch — bỏ trống param phone nếu khách dùng số đang gọi, hoặc truyền phone khi khách cho số khác."`
- Add to `properties` (e.g. after `preferred_time`):

```python
                    "phone": {
                        "type": "string",
                        "description": "SĐT liên hệ cho lịch hẹn (schedule). Bỏ trống = dùng số khách đang gọi.",
                    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_booking_phone.py tests/unit/test_booking_tools.py -v`
Expected: PASS (new file + existing booking tests still green)

- [ ] **Step 5: Commit**

```bash
make lint
git add src/noble_agent/agent/tools/schedule_viewing.py src/noble_agent/agent/tools/schemas.py tests/unit/unified/test_booking_phone.py
git commit -m "feat(booking): schedule phone param → booking row only, validated; keep customer.phone"
```

---

### Task 7: Prompt — proactive name + booking phone confirmation (RULES.md)

**Files:**
- Modify: `src/noble_agent/agent/definitions/RULES.md` (rule 6 lines 28-39; Tool catalog booking row line 78)
- Test: none (markdown prompt; validated by `test_agent_def` loading + manual/SMOKE)

**Interfaces:** none (prompt text only; `load_agent_def` must still parse the file).

- [ ] **Step 1: Rewrite rule 6**

Replace RULES.md rule 6 (lines 28-39) with:

```markdown
6. Đặt lịch tham quan (cần dự án + ngày + giờ + TÊN khách + xác nhận SĐT):
   - Gọi booking(action="check_availability") để lấy ngày và khung giờ còn
     trống, rồi báo khách chọn.
   - Nếu chưa có tên khách trong hồ sơ → hỏi tên và lưu bằng
     update_customer(name=...) TRƯỚC khi chốt lịch.
   - Xác nhận số điện thoại: hỏi "Anh/chị dùng số đang gọi này để đặt lịch
     không ạ?". Khách đồng ý → gọi schedule KHÔNG truyền param phone (mặc định
     dùng số đang gọi). Khách cho số khác → booking(action="schedule",
     phone="<số khách đọc>"). (Số booking chỉ dùng cho lịch hẹn, không đổi
     danh tính khách.)
   - Khi khách đã chọn ngày, giờ (và đã có tên + xác nhận số): booking(
     action="schedule", confirmed=true) để chốt.
   - Xem lịch đã đặt: booking(action="list"). Đổi ngày/giờ lịch đã đặt:
     booking(action="modify", booking_id=...).
   - Dự án lấy từ hồ sơ khách (project_interest); nếu chưa rõ thì hỏi khách
     muốn tham quan dự án nào trước khi schedule.
```

- [ ] **Step 2: Update the Tool catalog booking row**

Replace the booking row (line 78) with:

```markdown
| Đặt/đổi/xem lịch tham quan | booking(action=check_availability→schedule; list/modify) — cần dự án + ngày + giờ + tên khách (update_customer(name=...)) + xác nhận SĐT (bỏ trống phone nếu dùng số đang gọi, truyền phone nếu khách cho số khác) trước khi chốt |
```

- [ ] **Step 3: Verify the agent definition still loads**

Run: `pytest tests/unit/unified/test_agent_def.py -v`
Expected: PASS (RULES.md is loaded as the `rules` section; no structural assertion on rule 6 text)

- [ ] **Step 4: Spot-check the built prompt contains the new flow**

Run: `python -c "from pathlib import Path; from noble_agent.agent.base import load_agent_def; from noble_agent.agent.prompts.builder import build_system_prompt; from noble_agent.storage.models import Customer; p=build_system_prompt(load_agent_def(Path('src/noble_agent/agent/definitions')), Customer(), None); print('xác nhận số điện thoại' in p or 'dùng số đang gọi' in p)"`
Expected: `True`

- [ ] **Step 5: Commit**

```bash
make lint
git add src/noble_agent/agent/definitions/RULES.md
git commit -m "docs(prompt): booking flow asks name + confirms phone (reverses no-phone rule)"
```

---

### Task 8: Drop the Noble-Profile ecosystem lookup from telephony (keep caller-ID seed)

**Files:**
- Modify: `src/noble_agent/telephony/session.py:174-210` (seed block) and `:231-283` (Noble enrichment block)

**Interfaces:** none new. After: `session.run` seeds only `{"phone": caller_number}` into Redis; the orchestrator bootstrap (Task 5) does the DB lookup on the first turn.

- [ ] **Step 1: Replace the seed lookup block with a phone-only seed**

In `src/noble_agent/telephony/session.py`, replace the whole `if self.caller_number:` seed block (lines 174-210, the one starting `# Part 2: seed customer profile from MongoDB...`) with:

```python
            # Seed the caller-ID phone into Redis BEFORE agent.start() so the
            # first-turn profile bootstrap (orchestrator) can look the caller up
            # by phone. The DB lookup itself lives in the orchestrator now — this
            # only establishes the phone identity for this session.
            if self.caller_number:
                try:
                    await session_store.save_customer(self.session_id, {"phone": self.caller_number})
                except Exception as seed_exc:
                    logger.warning("[TEL] seed phone failed: %s", seed_exc)
```

- [ ] **Step 2: Delete the Noble Profile enrichment block**

Delete lines 231-283 (the whole `# Part 7: Noble Profile API enrichment...` block gated on `if settings.noble_profile_enabled and self.caller_number:`, ending at the `except Exception as enrich_exc:` clause, immediately before `# Start LLM (loads agent prompt from registry)`). Leave the outbound-callback-intent block (lines 212-229) and `await self.agent.start()` intact.

- [ ] **Step 3: Verify no residual Noble-profile references in the run path**

Run: `grep -n "noble_profile\|load_customer_by_phone\|enrich_customer" src/noble_agent/telephony/session.py`
Expected: no matches for `noble_profile` / `enrich_customer` / `load_customer_by_phone` in `session.py` (the `save_customer_persistent` call at cleanup stays and is unrelated).

- [ ] **Step 4: Verify the unit suite still passes**

Run: `make test-unit`
Expected: PASS (no unit test exercises `TelephonySession.run`; import of `telephony/session.py` still succeeds)

- [ ] **Step 5: Commit**

```bash
make lint
git add src/noble_agent/telephony/session.py
git commit -m "refactor(telephony): drop Noble-Profile lookup+enrich; seed caller-ID only (bootstrap owns lookup)"
```

---

### Task 9: Full-suite verification + smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the unified unit suite**

Run: `pytest tests/unit/unified -q`
Expected: PASS (all).

- [ ] **Step 2: Run the full unit suite + lint**

Run: `make test-unit && make lint`
Expected: PASS, no ruff findings.

- [ ] **Step 3: Manual smoke (turn loop + prompt touched)**

Follow `src/noble_agent/SMOKE.md` for the text-chat path (`/chat`): start a session, confirm (a) the first-turn profile block shows the phone; (b) after telling the agent a name, the agent asks to confirm the booking phone when scheduling; (c) a booking with a different number lands on the booking row without changing the profile phone.
Expected: behaviors as described; no traceback in server logs.

- [ ] **Step 4: Final commit (if smoke required any doc note)**

```bash
git add -A
git commit -m "test: verify customer profile load-once + booking phone flow (suite + smoke)"
```

---

## Self-Review

**Spec coverage:**
- Bootstrap-once from `customers` + `bookings_flat` by phone → Tasks 1, 2, 5. ✓
- Freeze profile block; remove dynamic rebuild → Tasks 3, 4, 5. ✓
- Booking phone confirmation, row-only, never overwrites `customer.phone` → Task 6 (executor/schema) + Task 7 (prompt flow). ✓
- Proactive name ask at booking/consult → Task 7 (rule 6) + existing rule 1/4 (kept). ✓
- `update_customer` persists to Mongo → unchanged (already fires `save_customer_persistent`); phone now always present so it always persists. No task needed. ✓
- CMS = Mongo writes, no HTTP → Global Constraints; no task adds HTTP. ✓
- Drop Noble Profile ecosystem → Task 8. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; every test has assertions; commands have expected output. ✓

**Type consistency:** `bootstrap_customer_profile(customer: Customer) -> None`, `render_customer_block(agent, customer) -> str`, `build_system_prompt(..., customer_block=None)`, `load_latest_booking_hint_by_phone(phone) -> dict` — names/signatures identical across Tasks 1/2/3/4/5. `schedule_viewing` signature unchanged (reads `args["phone"]`). ✓

**Notes / accepted scope:**
- `dispatcher.consume_customer_dirty` / `mark_customer_dirty` stay (tests in `test_dispatcher.py` keep them green); only the runner stops calling them. Dead-for-prompt but low-risk to keep.
- `semcache/sandbox.py` and `agent/qwen_transcript.py` keep calling `build_system_prompt` with 3 positional args → they render live (semcache off by default; transcript is a debug artifact). Accepted per spec.
- `CUSTOMER_PROFILE.md` unchanged — its trailing "gọi update_customer" instruction still drives persistence under the frozen-block model.
