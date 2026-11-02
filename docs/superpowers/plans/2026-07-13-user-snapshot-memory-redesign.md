# User Snapshot Memory Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-session summary memory with one evolving free-text snapshot per caller (keyed by phone), keep short-term (last-K-turns), and remove the long-term Qdrant RAG (`recall_memory`) layer entirely.

**Architecture:** New Mongo collection `hotline_user_snapshots` (1 doc/phone) merged fire-and-forget at call-end by an LLM (old snapshot + full history → new narrative). A Redis per-phone lock makes the next call from the same phone wait (bounded) for the in-flight merge. Bootstrap loads the snapshot + last-K prior-session turns into the frozen `customer_block`. The `hotline_call_summaries` collection and its dashboard consumers are untouched.

**Tech Stack:** Python 3.11+, motor (MongoDB), redis.asyncio, pytest (`asyncio_mode=auto`), fakeredis for lock tests.

## Global Constraints

- Branch: `feat/refactor2`. Never touch `develop`. Local commits only.
- Memory must NEVER break a call: every DAO / lock / entry-helper op is log-and-continue (swallow exceptions), returns a safe default.
- Do NOT modify `hotline_call_summaries`, `generate_call_summary`, `save_call_summary`, `record_handoff`, or any dashboard consumer — the snapshot is a parallel additional write.
- Snapshot is FREE-TEXT narrative only (no structured facts — those live in the customer profile).
- Merge prompt MUST preserve distinct old facts (never drop/blur) and update only matching/conflicting facts to latest.
- `merge_snapshot` returning `""` (LLM failure) MUST skip the save (never overwrite a snapshot with empty).
- Snapshot memory is ALWAYS ON when a real phone is present (no enable flag).
- Ruff: line-length 120, target py311. Run `make lint` before final commit.
- Collection name is exactly `hotline_user_snapshots`.

---

### Task 1: Snapshot storage DAO + Mongo index

**Files:**
- Create: `src/noble_agent/storage/user_snapshots.py`
- Modify: `src/noble_agent/storage/connection.py` (add index next to the `hotline_call_summaries` block, ~line 92-102)
- Test: `tests/unit/unified/test_user_snapshots.py`

**Interfaces:**
- Produces:
  - `async load_snapshot(phone: str) -> dict | None` — the caller's snapshot doc (`_id` stringified) or None.
  - `async save_snapshot(phone: str, snapshot_text: str, session_id: str) -> str | None` — upsert on `phone`; returns `_id` string or None.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_user_snapshots.py
"""user_snapshots DAO: upsert-by-phone + load, via mongo_client.get_db."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from noble_agent.storage import mongo_client, user_snapshots


class _Coll:
    def __init__(self):
        self.calls: list[tuple] = []
        self.doc: dict | None = None

    async def update_one(self, flt, update, upsert=False):
        self.calls.append((flt, update, upsert))
        return MagicMock(upserted_id="oid-1", matched_count=0)

    async def find_one(self, flt, projection=None):
        return self.doc


class _DB:
    def __init__(self):
        self.hotline_user_snapshots = _Coll()


@pytest.fixture
def db(monkeypatch):
    d = _DB()
    monkeypatch.setattr(mongo_client, "get_db", AsyncMock(return_value=d))
    return d


async def test_save_snapshot_upserts_by_phone(db):
    out = await user_snapshots.save_snapshot("0912345678", "Anh Dự quan tâm NCTH.", "sid-1")
    assert out == "oid-1"
    flt, update, upsert = db.hotline_user_snapshots.calls[-1]
    assert upsert is True
    assert flt == {"phone": "0912345678"}
    set_doc = update["$set"]
    assert set_doc["snapshot"] == "Anh Dự quan tâm NCTH."
    assert set_doc["last_session_id"] == "sid-1"
    assert "updated_at" in set_doc
    assert "created_at" not in set_doc  # created_at is insert-only
    assert "created_at" in update["$setOnInsert"]


async def test_load_snapshot_returns_doc_with_str_id(db):
    db.hotline_user_snapshots.doc = {"_id": MagicMock(), "phone": "0912345678", "snapshot": "x"}
    out = await user_snapshots.load_snapshot("0912345678")
    assert out is not None and out["snapshot"] == "x"
    assert isinstance(out["_id"], str)


async def test_load_snapshot_none_when_absent(db):
    db.hotline_user_snapshots.doc = None
    assert await user_snapshots.load_snapshot("0912345678") is None


async def test_dao_noop_when_db_none(monkeypatch):
    monkeypatch.setattr(mongo_client, "get_db", AsyncMock(return_value=None))
    assert await user_snapshots.save_snapshot("09", "x", "sid") is None
    assert await user_snapshots.load_snapshot("09") is None


async def test_save_noop_when_phone_or_text_empty(db):
    assert await user_snapshots.save_snapshot("", "x", "sid") is None
    assert await user_snapshots.save_snapshot("09", "", "sid") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_user_snapshots.py -v`
Expected: FAIL — `ModuleNotFoundError: noble_agent.storage.user_snapshots`

- [ ] **Step 3: Write the DAO**

```python
# src/noble_agent/storage/user_snapshots.py
"""MongoDB DAO for `hotline_user_snapshots` — one cumulative snapshot per caller.

Keyed uniquely by `phone`; upserted at call-end by the snapshot merge. Separate
from `hotline_call_summaries` (which the CMS dashboard owns, per-session). This
collection holds only the evolving free-text narrative used to bootstrap the
next call from the same caller.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger("storage.user_snapshots")


async def save_snapshot(phone: str, snapshot_text: str, session_id: str) -> str | None:
    """Upsert the caller's snapshot. Returns `_id` string on success, None otherwise."""
    from noble_agent.storage.mongo_client import get_db

    if not phone or not snapshot_text:
        return None
    db = await get_db()
    if db is None:
        logger.warning("save_snapshot: Mongo unavailable — skipping")
        return None
    try:
        now = datetime.now(UTC)
        update = {
            "$set": {
                "phone": phone,
                "snapshot": snapshot_text,
                "last_session_id": session_id,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        }
        result = await db.hotline_user_snapshots.update_one({"phone": phone}, update, upsert=True)
        if result.upserted_id:
            return str(result.upserted_id)
        existing = await db.hotline_user_snapshots.find_one({"phone": phone}, {"_id": 1})
        return str(existing["_id"]) if existing else None
    except Exception as exc:
        logger.warning("save_snapshot failed: %s", exc)
        return None


async def load_snapshot(phone: str) -> dict | None:
    """The caller's snapshot doc (`_id` stringified) or None."""
    from noble_agent.storage.mongo_client import get_db

    if not phone:
        return None
    db = await get_db()
    if db is None:
        return None
    try:
        doc = await db.hotline_user_snapshots.find_one({"phone": phone})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc
    except Exception as exc:
        logger.warning("load_snapshot failed: %s", exc)
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_user_snapshots.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Add the Mongo index**

In `src/noble_agent/storage/connection.py`, immediately after the `hotline_call_summaries` index try/except block (the one ending ~line 102), add:

```python
            # User snapshot: one cumulative narrative per caller (keyed by phone).
            try:
                await self._mongo_db.hotline_user_snapshots.create_index("phone", unique=True)
            except Exception as idx_exc:
                logger.warning("hotline_user_snapshots.phone index failed: %s", idx_exc)
```

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/storage/user_snapshots.py src/noble_agent/storage/connection.py tests/unit/unified/test_user_snapshots.py
git commit -m "feat(memory): user_snapshots DAO + phone unique index"
```

---

### Task 2: Redis per-phone snapshot lock

**Files:**
- Create: `src/noble_agent/storage/snapshot_lock.py`
- Test: `tests/unit/unified/test_snapshot_lock.py`

**Interfaces:**
- Produces:
  - `async acquire_snapshot_lock(phone: str, ttl_sec: int = 60) -> bool`
  - `async release_snapshot_lock(phone: str) -> None`
  - `async wait_snapshot_lock_clear(phone: str, max_wait_sec: float = 10.0, poll_sec: float = 0.5) -> bool` — True if the lock is (or became) clear, False on timeout.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_snapshot_lock.py
"""Redis per-phone snapshot lock: acquire / release / wait (clear + timeout)."""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from noble_agent.storage import redis_client, snapshot_lock


@pytest.fixture(autouse=True)
def fake_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client.set_redis_for_tests(client)
    yield client
    redis_client.set_redis_for_tests(None)


async def test_acquire_then_release(fake_redis):
    assert await snapshot_lock.acquire_snapshot_lock("09", ttl_sec=60) is True
    assert await fake_redis.get("snapshot:lock:09") == "1"
    await snapshot_lock.release_snapshot_lock("09")
    assert await fake_redis.get("snapshot:lock:09") is None


async def test_wait_returns_true_when_already_clear():
    assert await snapshot_lock.wait_snapshot_lock_clear("09", max_wait_sec=1.0) is True


async def test_wait_times_out_while_held(fake_redis):
    await snapshot_lock.acquire_snapshot_lock("09", ttl_sec=60)
    # Lock stays held → wait must time out and return False (bounded, not forever).
    assert await snapshot_lock.wait_snapshot_lock_clear("09", max_wait_sec=0.3, poll_sec=0.1) is False


async def test_wait_returns_true_after_release(fake_redis):
    await snapshot_lock.acquire_snapshot_lock("09", ttl_sec=60)
    await snapshot_lock.release_snapshot_lock("09")
    assert await snapshot_lock.wait_snapshot_lock_clear("09", max_wait_sec=0.3, poll_sec=0.1) is True


async def test_ops_safe_when_redis_none(monkeypatch):
    # Redis unavailable → never raise; treat lock as clear so a call is never blocked.
    async def _none():
        return None

    monkeypatch.setattr(redis_client, "get_redis", _none)
    assert await snapshot_lock.acquire_snapshot_lock("09") is False
    await snapshot_lock.release_snapshot_lock("09")  # no raise
    assert await snapshot_lock.wait_snapshot_lock_clear("09", max_wait_sec=0.2) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_snapshot_lock.py -v`
Expected: FAIL — `ModuleNotFoundError: noble_agent.storage.snapshot_lock`

- [ ] **Step 3: Write the lock module**

```python
# src/noble_agent/storage/snapshot_lock.py
"""Redis per-phone lock guarding the fire-and-forget snapshot merge.

Cross-process (aiortc / livekit / telephony are separate processes), so the lock
lives in Redis (already the session-state backend). The merge acquires the lock;
the next call from the same phone waits (bounded) for it to clear before it
bootstraps, so it reads the freshest snapshot. All ops log-and-continue: if Redis
is down, acquire returns False, release is a no-op, and wait reports "clear" so a
call is never blocked by a memory concern.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("noble_agent.storage.snapshot_lock")


def _lock_key(phone: str) -> str:
    return f"snapshot:lock:{phone}"


async def acquire_snapshot_lock(phone: str, ttl_sec: int = 60) -> bool:
    """Set the lock with a TTL (self-heal if the merge crashes). Best-effort."""
    if not phone:
        return False
    try:
        from noble_agent.storage.redis_client import get_redis

        client = await get_redis()
        if client is None:
            return False
        await client.set(_lock_key(phone), "1", ex=ttl_sec)
        return True
    except Exception as exc:
        logger.warning("acquire_snapshot_lock failed: %s", exc)
        return False


async def release_snapshot_lock(phone: str) -> None:
    """Delete the lock. Best-effort — always safe to call in a finally."""
    if not phone:
        return
    try:
        from noble_agent.storage.redis_client import get_redis

        client = await get_redis()
        if client is None:
            return
        await client.delete(_lock_key(phone))
    except Exception as exc:
        logger.warning("release_snapshot_lock failed: %s", exc)


async def wait_snapshot_lock_clear(phone: str, max_wait_sec: float = 10.0, poll_sec: float = 0.5) -> bool:
    """Poll until the lock is absent or `max_wait_sec` elapses.

    Returns True if clear (immediately or after release), False on timeout.
    Redis errors → True (unblock the call). Never waits longer than max_wait_sec.
    """
    if not phone:
        return True
    try:
        from noble_agent.storage.redis_client import get_redis

        client = await get_redis()
        if client is None:
            return True
        waited = 0.0
        while waited < max_wait_sec:
            if not await client.exists(_lock_key(phone)):
                return True
            await asyncio.sleep(poll_sec)
            waited += poll_sec
        logger.warning("wait_snapshot_lock_clear: timeout phone=%s after %.1fs", phone, max_wait_sec)
        return False
    except Exception as exc:
        logger.warning("wait_snapshot_lock_clear failed: %s", exc)
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_snapshot_lock.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/storage/snapshot_lock.py tests/unit/unified/test_snapshot_lock.py
git commit -m "feat(memory): redis per-phone snapshot lock"
```

---

### Task 3: Snapshot merge + short-term context (`agent/memory/snapshot.py`)

**Files:**
- Create: `src/noble_agent/agent/memory/snapshot.py`
- Test: `tests/unit/unified/test_snapshot_merge.py`, `tests/unit/unified/test_snapshot_short_term.py`

**Interfaces:**
- Consumes: `storage.user_snapshots.load_snapshot`; `storage.call_summaries.list_summaries`; `storage.agent_messages.get_session_messages`.
- Produces:
  - `def build_merge_prompt(old_snapshot: str, history: list[dict]) -> str`
  - `async merge_snapshot(old_snapshot: str, history: list[dict]) -> str` — new narrative, `""` on LLM failure/empty history.
  - `async build_short_term_context(settings, phone: str, current_session_id: str) -> str` — snapshot narrative + last-K prior-session turns; `""` when neither present.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/unified/test_snapshot_merge.py
"""Snapshot merge: prompt construction + LLM-guarded merge_snapshot."""

from __future__ import annotations

from noble_agent.agent.memory import snapshot


def _history():
    return [
        {"role": "user", "content": "Tôi muốn đổi sang NCTH 3 phòng ngủ"},
        {"role": "assistant", "content": "Dạ NCTH có căn 3PN ạ"},
    ]


def test_build_merge_prompt_includes_old_and_history_and_rules():
    p = snapshot.build_merge_prompt("Anh Dự quan tâm NCLB 2PN.", _history())
    assert "Anh Dự quan tâm NCLB 2PN." in p       # old snapshot embedded
    assert "NCTH 3 phòng ngủ" in p                 # history embedded
    assert "GIỮ NGUYÊN" in p                        # preserve-old-facts rule present
    assert "SNAPSHOT MỚI" in p                      # output anchor present


def test_build_merge_prompt_handles_empty_old():
    p = snapshot.build_merge_prompt("", _history())
    assert "NCTH 3 phòng ngủ" in p


async def test_merge_snapshot_returns_llm_text(monkeypatch):
    async def _fake_llm(prompt: str) -> str:
        return "  Anh Dự nay quan tâm NCTH 3PN (đổi từ NCLB).  "

    monkeypatch.setattr(snapshot, "_call_merge_llm", _fake_llm)
    out = await snapshot.merge_snapshot("Anh Dự quan tâm NCLB 2PN.", _history())
    assert out == "Anh Dự nay quan tâm NCTH 3PN (đổi từ NCLB)."


async def test_merge_snapshot_empty_on_llm_failure(monkeypatch):
    async def _fake_llm(prompt: str) -> str:
        return ""

    monkeypatch.setattr(snapshot, "_call_merge_llm", _fake_llm)
    assert await snapshot.merge_snapshot("old", _history()) == ""


async def test_merge_snapshot_empty_when_no_history():
    assert await snapshot.merge_snapshot("old", []) == ""
```

```python
# tests/unit/unified/test_snapshot_short_term.py
"""build_short_term_context renders snapshot + last-K prior-session turns."""

from __future__ import annotations

from types import SimpleNamespace

from noble_agent.agent.memory import snapshot


def _settings(**kw):
    base = dict(user_memory_short_term_turns=2, user_memory_since_days=30)
    base.update(kw)
    return SimpleNamespace(**base)


async def test_renders_snapshot_and_turns(monkeypatch):
    async def _load(phone):
        return {"snapshot": "Anh Dự quan tâm NCTH 3PN."}

    async def _list(phone, limit=5):
        return [{"session_id": "sid-prev"}, {"session_id": "sid-cur"}]

    async def _msgs(sid):
        return [
            {"role": "caller", "content": "còn suất NCTH không?"},
            {"role": "agent", "content": "dạ còn ạ"},
        ]

    monkeypatch.setattr(snapshot.user_snapshots, "load_snapshot", _load)
    monkeypatch.setattr(snapshot.call_summaries, "list_summaries", _list)
    monkeypatch.setattr(snapshot.agent_messages, "get_session_messages", _msgs)

    out = await snapshot.build_short_term_context(_settings(), "sid-cur", "sid-cur")
    assert "Anh Dự quan tâm NCTH 3PN." in out
    assert "còn suất NCTH không?" in out
    assert "Bối cảnh khách hàng" in out


async def test_empty_when_nothing(monkeypatch):
    async def _load(phone):
        return None

    async def _list(phone, limit=5):
        return []

    monkeypatch.setattr(snapshot.user_snapshots, "load_snapshot", _load)
    monkeypatch.setattr(snapshot.call_summaries, "list_summaries", _list)
    out = await snapshot.build_short_term_context(_settings(), "0912345678", "sid-cur")
    assert out == ""
```

> Note: `build_short_term_context(settings, phone, current_session_id)` — in the short-term test the first positional after settings is the phone. The first test passes `"sid-cur"` as phone because `load_snapshot`/`list_summaries` are stubbed and ignore it; keep the real signature `(settings, phone, current_session_id)`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/test_snapshot_merge.py tests/unit/unified/test_snapshot_short_term.py -v`
Expected: FAIL — `ModuleNotFoundError: noble_agent.agent.memory.snapshot`

- [ ] **Step 3: Write the module**

```python
# src/noble_agent/agent/memory/snapshot.py
"""Cumulative per-caller snapshot: merge (call-end) + short-term context (bootstrap).

- merge_snapshot: old snapshot + full call history → new free-text narrative via
  the shared summary provider chain. Careful merge prompt: keep distinct old
  facts, update matching/conflicting ones to the latest. "" on failure → caller
  skips the save (old snapshot preserved).
- build_short_term_context: snapshot narrative + last-K turns of the most recent
  prior session (existing short-term behavior), rendered into one prompt block.
"""

from __future__ import annotations

import logging

from noble_agent.storage import agent_messages, call_summaries, user_snapshots

logger = logging.getLogger("noble_agent.agent.memory.snapshot")

_MERGE_PROVIDER_TIMEOUT_SEC = 12.0
_MAX_MERGE_TOKENS = 500

_MERGE_PROMPT = """Bạn đang duy trì một hồ sơ ghi nhớ (snapshot) tích lũy về MỘT khách hàng qua NHIỀU cuộc gọi.
Dưới đây là snapshot HIỆN TẠI và hội thoại của cuộc gọi VỪA XONG.

Viết lại snapshot MỚI (tiếng Việt, 3-6 câu, plain text, KHÔNG markdown, KHÔNG JSON) theo quy tắc:
- GIỮ NGUYÊN mọi thông tin/fact cũ vẫn còn đúng — KHÔNG được bỏ sót hoặc làm mờ.
- Nếu cuộc gọi mới có fact MÂU THUẪN với snapshot cũ (vd đổi ngân sách, đổi dự án quan tâm) → cập nhật theo thông tin MỚI NHẤT.
- Nếu có fact MỚI khác chủ đề → bổ sung, KHÔNG ghi đè fact cũ.
- Ghi ngắn gọn việc còn dang dở / cần follow-up nếu có.
- KHÔNG bịa thông tin không có trong dữ liệu.

SNAPSHOT HIỆN TẠI:
{old_snapshot}

HỘI THOẠI CUỘC GỌI VỪA XONG:
{history}

SNAPSHOT MỚI:
"""


def _flatten_history(history: list[dict], max_turns: int = 40) -> str:
    recent = history[-max_turns:] if len(history) > max_turns else history
    lines: list[str] = []
    for m in recent:
        content = m.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        role = m.get("role", "")
        prefix = "KH" if role == "user" else "Luna" if role == "assistant" else role
        lines.append(f"{prefix}: {content[:300]}")
    return "\n".join(lines)


def build_merge_prompt(old_snapshot: str, history: list[dict]) -> str:
    return _MERGE_PROMPT.format(
        old_snapshot=(old_snapshot or "(chưa có)").strip(),
        history=_flatten_history(history),
    )


async def _call_merge_llm(prompt: str) -> str:
    """Run the merge prompt through the summary provider chain (non-streaming)."""
    try:
        from noble_agent.agent.facade import build_llm_providers
        from noble_agent.agent.llm.client import StreamingClient
        from noble_agent.config import get_settings, primary_for, provider_model_map
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SNAPSHOT] imports failed: %s", exc)
        return ""

    providers = build_llm_providers()
    if not providers:
        logger.warning("[SNAPSHOT] no LLM providers configured")
        return ""
    settings = get_settings()
    client = StreamingClient(
        providers=providers,
        enable_thinking=settings.llm_enable_thinking,
        openai_reasoning_effort=settings.openai_reasoning_effort,
    )
    primary = primary_for(settings, settings.agent_model or settings.summary_model)
    try:
        text = await client.complete_once(
            messages=[{"role": "user", "content": prompt}],
            model=provider_model_map(settings),
            temperature=0.2,
            max_tokens=_MAX_MERGE_TOKENS,
            primary=primary,
            request_timeout=_MERGE_PROVIDER_TIMEOUT_SEC,
        )
        return (text or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SNAPSHOT] all providers failed: %s", exc)
        return ""


async def merge_snapshot(old_snapshot: str, history: list[dict]) -> str:
    if not history:
        return ""
    prompt = build_merge_prompt(old_snapshot, history)
    return await _call_merge_llm(prompt)


async def _latest_prior_session(phone: str, current_session_id: str, since_days: int) -> str | None:
    try:
        rows = await call_summaries.list_summaries(phone, limit=5)  # newest first
    except Exception:
        return None
    for row in rows:
        sid = row.get("session_id", "")
        if sid and sid != current_session_id:
            return sid
    return None


def _render(snapshot_text: str, turns: list[dict]) -> str:
    body: list[str] = []
    text = (snapshot_text or "").strip()
    if text:
        body.append(text)
    if turns:
        turn_lines = []
        for m in turns:
            role = m.get("role", "")
            who = "Khách" if role == "caller" else "Luna" if role == "agent" else role
            content = (m.get("content") or "").strip()
            if content:
                turn_lines.append(f"- {who}: {content[:200]}")
        if turn_lines:
            body.append("Vài lượt gần nhất:")
            body.extend(turn_lines)
    if not body:
        return ""
    return "\n".join(["## Bối cảnh khách hàng (tích lũy)", *body])


async def build_short_term_context(settings, phone: str, current_session_id: str) -> str:
    k = int(getattr(settings, "user_memory_short_term_turns", 6))
    since_days = int(getattr(settings, "user_memory_since_days", 30))

    doc = await user_snapshots.load_snapshot(phone)
    snapshot_text = (doc or {}).get("snapshot", "") if doc else ""

    prior_sid = await _latest_prior_session(phone, current_session_id, since_days)
    turns: list[dict] = []
    if prior_sid:
        all_msgs = await agent_messages.get_session_messages(prior_sid)
        turns = all_msgs[-k:] if len(all_msgs) > k else all_msgs

    return _render(snapshot_text, turns)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_snapshot_merge.py tests/unit/unified/test_snapshot_short_term.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/memory/snapshot.py tests/unit/unified/test_snapshot_merge.py tests/unit/unified/test_snapshot_short_term.py
git commit -m "feat(memory): snapshot merge + short-term context"
```

---

### Task 4: Rework entry helpers + delete long-term backend

**Files:**
- Modify: `src/noble_agent/agent/memory/__init__.py` (full rewrite)
- Delete: `src/noble_agent/agent/memory/base.py`, `src/noble_agent/agent/memory/qa_vector.py`, `src/noble_agent/agent/memory/vector_store.py`
- Delete tests: `tests/unit/unified/test_memory_qa_vector.py`, `test_memory_vector_store.py`, `test_memory_factory.py`, `test_memory_entry_helpers.py`, `test_memory_config.py`
- Test: `tests/unit/unified/test_snapshot_entry_helpers.py`

**Interfaces:**
- Consumes: `agent.memory.snapshot.merge_snapshot`, `.build_short_term_context`; `storage.snapshot_lock`; `storage.user_snapshots.load_snapshot`.
- Produces:
  - `async update_snapshot_after_call(settings, *, phone: str, session_id: str, history: list[dict]) -> None`
  - `async short_term_block(settings, *, phone: str, session_id: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_snapshot_entry_helpers.py
"""Entry helpers: update_snapshot_after_call lock lifecycle + short_term_block wait."""

from __future__ import annotations

from types import SimpleNamespace

from noble_agent.agent import memory as mem
from noble_agent.agent.memory import snapshot as snap_mod
from noble_agent.storage import snapshot_lock, user_snapshots


def _settings(**kw):
    base = dict(
        user_memory_short_term_turns=4,
        user_memory_since_days=30,
        snapshot_lock_wait_sec=5.0,
        snapshot_lock_ttl_sec=60,
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def test_update_snapshot_acquires_saves_releases(monkeypatch):
    events: list[str] = []

    async def _acq(phone, ttl_sec=60):
        events.append("acquire")
        return True

    async def _rel(phone):
        events.append("release")

    async def _load(phone):
        return {"snapshot": "old"}

    async def _merge(old, history):
        events.append("merge")
        return "new snapshot"

    async def _save(phone, text, sid):
        events.append(f"save:{text}")
        return "oid"

    monkeypatch.setattr(snapshot_lock, "acquire_snapshot_lock", _acq)
    monkeypatch.setattr(snapshot_lock, "release_snapshot_lock", _rel)
    monkeypatch.setattr(user_snapshots, "load_snapshot", _load)
    monkeypatch.setattr(snap_mod, "merge_snapshot", _merge)
    monkeypatch.setattr(user_snapshots, "save_snapshot", _save)

    await mem.update_snapshot_after_call(
        _settings(), phone="09", session_id="sid", history=[{"role": "user", "content": "hi"}]
    )
    assert events == ["acquire", "merge", "save:new snapshot", "release"]


async def test_update_snapshot_releases_even_on_merge_error(monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(snapshot_lock, "acquire_snapshot_lock", lambda p, ttl_sec=60: _true())
    async def _rel(phone):
        events.append("release")
    async def _load(phone):
        return None
    async def _merge(old, history):
        raise RuntimeError("llm boom")
    monkeypatch.setattr(snapshot_lock, "release_snapshot_lock", _rel)
    monkeypatch.setattr(user_snapshots, "load_snapshot", _load)
    monkeypatch.setattr(snap_mod, "merge_snapshot", _merge)

    # Must NOT raise, and MUST release.
    await mem.update_snapshot_after_call(
        _settings(), phone="09", session_id="sid", history=[{"role": "user", "content": "hi"}]
    )
    assert events == ["release"]


async def test_update_snapshot_skips_save_when_merge_empty(monkeypatch):
    saved: list = []
    monkeypatch.setattr(snapshot_lock, "acquire_snapshot_lock", lambda p, ttl_sec=60: _true())
    monkeypatch.setattr(snapshot_lock, "release_snapshot_lock", lambda p: _none())
    monkeypatch.setattr(user_snapshots, "load_snapshot", lambda p: _val(None))
    monkeypatch.setattr(snap_mod, "merge_snapshot", lambda o, h: _val(""))
    monkeypatch.setattr(user_snapshots, "save_snapshot", lambda p, t, s: saved.append(t))
    await mem.update_snapshot_after_call(
        _settings(), phone="09", session_id="sid", history=[{"role": "user", "content": "hi"}]
    )
    assert saved == []


async def test_update_snapshot_noop_without_phone(monkeypatch):
    called = []
    monkeypatch.setattr(snapshot_lock, "acquire_snapshot_lock", lambda p, ttl_sec=60: called.append(p) or _true())
    await mem.update_snapshot_after_call(_settings(), phone="", session_id="sid", history=[{"role": "user", "content": "x"}])
    assert called == []


async def test_short_term_block_waits_then_builds(monkeypatch):
    events: list[str] = []

    async def _wait(phone, max_wait_sec=10.0, poll_sec=0.5):
        events.append("wait")
        return True

    async def _build(settings, phone, sid):
        events.append("build")
        return "## Bối cảnh khách hàng (tích lũy)\nold"

    monkeypatch.setattr(snapshot_lock, "wait_snapshot_lock_clear", _wait)
    monkeypatch.setattr(snap_mod, "build_short_term_context", _build)
    out = await mem.short_term_block(_settings(), phone="09", session_id="sid")
    assert events == ["wait", "build"]
    assert "Bối cảnh" in out


async def test_short_term_block_empty_without_phone():
    assert await mem.short_term_block(_settings(), phone="", session_id="sid") == ""


# ── tiny awaitable helpers for lambda-based monkeypatches ──
async def _true():
    return True


async def _none():
    return None


async def _val(v):
    return v
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_snapshot_entry_helpers.py -v`
Expected: FAIL — `AttributeError: module 'noble_agent.agent.memory' has no attribute 'update_snapshot_after_call'`

- [ ] **Step 3: Rewrite the entry helpers + delete the long-term backend**

Overwrite `src/noble_agent/agent/memory/__init__.py`:

```python
"""User-memory subpackage: cumulative per-caller snapshot keyed by phone.

Entry points used by the rest of the app (both guarded — memory must never break
a call):
  - update_snapshot_after_call(...) → merge + persist the snapshot at call end.
  - short_term_block(...)           → bootstrap context (snapshot + last-K turns).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("noble_agent.agent.memory")


async def update_snapshot_after_call(settings, *, phone: str, session_id: str, history: list[dict]) -> None:
    """Fire-and-forget at call end: lock → load old → merge → save → unlock.

    The lock makes the next call from the same phone wait for this merge. Always
    releases in `finally`; swallows all errors."""
    if not phone:
        return
    from noble_agent.agent.memory import snapshot as snap
    from noble_agent.storage import snapshot_lock, user_snapshots

    ttl = int(getattr(settings, "snapshot_lock_ttl_sec", 60))
    await snapshot_lock.acquire_snapshot_lock(phone, ttl_sec=ttl)
    try:
        old_doc = await user_snapshots.load_snapshot(phone)
        old_text = (old_doc or {}).get("snapshot", "") if old_doc else ""
        new_text = await snap.merge_snapshot(old_text, history)
        if new_text:
            await user_snapshots.save_snapshot(phone, new_text, session_id)
    except Exception:
        logger.exception("update_snapshot_after_call failed session=%s", session_id)
    finally:
        await snapshot_lock.release_snapshot_lock(phone)


async def short_term_block(settings, *, phone: str, session_id: str) -> str:
    """Bootstrap block: wait for any in-flight merge (bounded), then build."""
    if not phone:
        return ""
    from noble_agent.agent.memory import snapshot as snap
    from noble_agent.storage import snapshot_lock

    try:
        wait_sec = float(getattr(settings, "snapshot_lock_wait_sec", 10.0))
        await snapshot_lock.wait_snapshot_lock_clear(phone, max_wait_sec=wait_sec)
        return await snap.build_short_term_context(settings, phone, session_id)
    except Exception:
        logger.exception("short_term_block failed session=%s", session_id)
        return ""


__all__ = ["update_snapshot_after_call", "short_term_block"]
```

Then delete the long-term backend files and their tests:

```bash
git rm src/noble_agent/agent/memory/base.py \
       src/noble_agent/agent/memory/qa_vector.py \
       src/noble_agent/agent/memory/vector_store.py \
       tests/unit/unified/test_memory_qa_vector.py \
       tests/unit/unified/test_memory_vector_store.py \
       tests/unit/unified/test_memory_factory.py \
       tests/unit/unified/test_memory_entry_helpers.py \
       tests/unit/unified/test_memory_config.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_snapshot_entry_helpers.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/memory/__init__.py tests/unit/unified/test_snapshot_entry_helpers.py
git commit -m "feat(memory): snapshot entry helpers; remove qa_vector long-term backend"
```

---

### Task 5: Remove the `recall_memory` tool (long-term)

**Files:**
- Delete: `src/noble_agent/agent/tools/recall_memory.py`, `tests/unit/unified/test_recall_memory.py`, `tests/unit/unified/test_recall_memory_gating.py`
- Modify: `src/noble_agent/agent/definitions/config.json` (remove `"recall_memory"`)
- Modify: `src/noble_agent/agent/tools/dispatcher.py` (remove import line ~22 + branch ~144-145)
- Modify: `src/noble_agent/agent/tools/schemas.py` (remove the `"recall_memory": {...}` entry ~442-451)
- Modify: `src/noble_agent/agent/definitions/RULES.md` (remove the `recall_memory` tool-catalog row)
- Modify: `tests/unit/unified/test_agent_def.py` (11 → 10 tools; assert `recall_memory` absent)

**Interfaces:** none produced.

- [ ] **Step 1: Update the agent-def test first (failing)**

Open `tests/unit/unified/test_agent_def.py`. Find the assertion that the tool count is 11 (or that `recall_memory` is present) and change it to 10 with `recall_memory` absent. Example edit:

```python
def test_agent_def_offers_ten_tools():
    agent = load_agent_def()
    assert len(agent.tool_names) == 10
    assert "recall_memory" not in agent.tool_names
    for t in ("update_customer", "noble_search", "booking", "escalate", "send_media"):
        assert t in agent.tool_names
```

Run: `pytest tests/unit/unified/test_agent_def.py -v`
Expected: FAIL — currently 11 tools / `recall_memory` present.

- [ ] **Step 2: Remove `recall_memory` from config.json**

In `src/noble_agent/agent/definitions/config.json`, delete the `"recall_memory"` line (and fix the trailing comma on `"send_media"`):

```json
  "tools": [
    "update_customer",
    "noble_search",
    "list_projects",
    "get_project_overview",
    "get_project_financial",
    "search_units",
    "match_projects",
    "booking",
    "escalate",
    "send_media"
  ]
```

- [ ] **Step 3: Remove the dispatcher import + branch**

In `src/noble_agent/agent/tools/dispatcher.py`:
- Remove `recall_memory,` from the tools import block (~line 22).
- Remove the branch (~lines 144-145):

```python
        if name == "recall_memory":
            return await recall_memory.run(self.customer, args)
```

- [ ] **Step 4: Remove the schema entry**

In `src/noble_agent/agent/tools/schemas.py`, delete the whole `"recall_memory": { ... }` dict entry (~lines 442-451).

- [ ] **Step 5: Remove the RULES.md row + delete files**

In `src/noble_agent/agent/definitions/RULES.md`, delete the `recall_memory` row from the Tool catalog table.

```bash
git rm src/noble_agent/agent/tools/recall_memory.py \
       tests/unit/unified/test_recall_memory.py \
       tests/unit/unified/test_recall_memory_gating.py
```

- [ ] **Step 6: Run tests to verify green**

Run: `pytest tests/unit/unified/test_agent_def.py tests/unit/unified/test_tool_schemas.py tests/unit/unified/test_schemas_dynamic_enum.py -v`
Expected: PASS (agent-def now 10 tools; schema tests unaffected by the removal). If a schema test enumerates tool names including `recall_memory`, update it to drop that name.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(memory): remove recall_memory long-term tool (11->10 tools)"
```

---

### Task 6: Config — drop long-term settings, add lock settings

**Files:**
- Modify: `src/noble_agent/config.py` (~lines 465-475)
- Modify: `.env.example`
- Test: `tests/unit/unified/test_snapshot_config.py`

**Interfaces:**
- Produces settings fields: `user_memory_short_term_turns: int = 6`, `user_memory_since_days: int = 30`, `snapshot_lock_wait_sec: float = 10.0`, `snapshot_lock_ttl_sec: int = 60`. Removes `user_memory_enabled`, `user_memory_backend`, `user_memory_qdrant_collection`, `user_memory_recall_top_k`, `user_memory_dedup_enabled`, `user_memory_dedup_threshold`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_snapshot_config.py
"""Snapshot memory settings: lock knobs present, removed long-term knobs gone."""

from __future__ import annotations

from noble_agent.config import get_settings


def test_snapshot_lock_settings_defaults():
    s = get_settings()
    assert s.snapshot_lock_wait_sec == 10.0
    assert s.snapshot_lock_ttl_sec == 60
    assert s.user_memory_short_term_turns == 6
    assert s.user_memory_since_days == 30


def test_removed_long_term_settings_absent():
    s = get_settings()
    for gone in (
        "user_memory_enabled",
        "user_memory_backend",
        "user_memory_qdrant_collection",
        "user_memory_recall_top_k",
        "user_memory_dedup_enabled",
        "user_memory_dedup_threshold",
    ):
        assert not hasattr(s, gone), f"{gone} should be removed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_snapshot_config.py -v`
Expected: FAIL — `snapshot_lock_wait_sec` missing / removed fields still present.

- [ ] **Step 3: Edit config.py**

Replace the block at `src/noble_agent/config.py` (~lines 464-475) with:

```python
    # ── User snapshot memory (per-caller cumulative narrative) ───────────────
    # Always on when a real phone is present. Short-term = snapshot + last K turns
    # of the prior session, injected at bootstrap. See
    # docs/superpowers/specs/2026-07-13-user-snapshot-memory-redesign-design.md.
    user_memory_short_term_turns: int = 6
    user_memory_since_days: int = 30
    snapshot_lock_wait_sec: float = 10.0  # bootstrap waits at most this for an in-flight merge
    snapshot_lock_ttl_sec: int = 60       # merge lock TTL (self-heal if the merge crashes)
```

- [ ] **Step 4: Update .env.example**

Remove the `NOBLE_USER_MEMORY_ENABLED` / `USER_MEMORY_*` (backend / qdrant collection / recall_top_k / dedup) lines. Keep/add short docs for the retained knobs. Example replacement block:

```bash
# ── User snapshot memory (always on when a real phone is present) ──
# USER_MEMORY_SHORT_TERM_TURNS=6      # last K prior-session turns injected at bootstrap
# USER_MEMORY_SINCE_DAYS=30           # how far back to look for the prior session
# SNAPSHOT_LOCK_WAIT_SEC=10           # bootstrap waits at most this for an in-flight merge
# SNAPSHOT_LOCK_TTL_SEC=60            # merge lock TTL
```

> Note: `user_memory_short_term_turns` / `user_memory_since_days` keep their existing env aliases if any are declared on the fields; if the current fields have `alias=`/env names, preserve them. (Check the field definitions before/after your edit — they were plain fields without aliases in the original block, so env `USER_MEMORY_SHORT_TERM_TURNS` maps via pydantic's default name uppercasing only if configured; leave behavior as it was for these two.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_snapshot_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/config.py .env.example tests/unit/unified/test_snapshot_config.py
git commit -m "feat(memory): config — drop long-term knobs, add snapshot lock settings"
```

---

### Task 7: Wire bootstrap + call-end paths

**Files:**
- Modify: `src/noble_agent/agent/orchestrator.py` (~lines 146-151)
- Modify: `src/noble_agent/agent/facade.py` (~lines 484-497)
- Modify: `src/noble_agent/server/base_session.py` (~lines 387-405)
- Modify: `src/noble_agent/server/text_chat.py` (~lines 367-380)
- Modify: `src/noble_agent/telephony/session.py` (after ~line 477, inside the `if self.caller_number:` block)
- Test: `tests/unit/unified/test_snapshot_wiring.py`

**Interfaces:**
- Consumes: `agent.memory.short_term_block`, `agent.memory.update_snapshot_after_call`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_snapshot_wiring.py
"""Bootstrap no longer gates short-term on a removed enable flag."""

from __future__ import annotations

import inspect

from noble_agent.agent import orchestrator


def test_orchestrator_no_user_memory_enabled_gate():
    src = inspect.getsource(orchestrator)
    # The removed flag must not be referenced anywhere in the orchestrator.
    assert "user_memory_enabled" not in src
    # short-term block is still wired in.
    assert "short_term_block" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_snapshot_wiring.py -v`
Expected: FAIL — `user_memory_enabled` still present in orchestrator.

- [ ] **Step 3: Update orchestrator bootstrap**

In `src/noble_agent/agent/orchestrator.py`, replace the short-term block (~lines 143-151):

```python
                # Short-term memory: prepend snapshot + prior-call context into
                # the frozen customer_block. Always on when a phone is present;
                # short_term_block waits (bounded) for any in-flight snapshot
                # merge, then returns "" on any error.
                if customer.phone:
                    from noble_agent.agent.memory import short_term_block

                    mem_block = await short_term_block(self._settings, phone=customer.phone, session_id=sid)
                    if mem_block:
                        state.scratchpad["customer_block"] += "\n\n" + mem_block
```

- [ ] **Step 4: Update facade set_customer path**

In `src/noble_agent/agent/facade.py` (~lines 484-497), drop the `settings.user_memory_enabled` gate:

```python
        settings = get_settings()
        if new_customer.phone:
            from noble_agent.agent.memory import short_term_block

            mem_block = await short_term_block(
                settings, phone=new_customer.phone, session_id=self.session_id
            )
            logger.info(
                "[user_memory] set_customer short-term sid=%s phone=%s block_len=%d",
                self.session_id,
                new_customer.phone,
                len(mem_block or ""),
            )
            if mem_block:
```

(Leave the body under `if mem_block:` unchanged.)

- [ ] **Step 5: Update base_session call-end**

In `src/noble_agent/server/base_session.py`, replace the `record_call_memory` block (~lines 387-405):

```python
                # User snapshot memory: merge this call into the caller's
                # cumulative snapshot. Fire-and-forget so stop() stays fast; the
                # helper holds a per-phone Redis lock so the next call from this
                # phone waits for the merge, and swallows all errors.
                try:
                    from noble_agent.agent.memory import update_snapshot_after_call
                    from noble_agent.config import get_settings
                    from noble_agent.storage.persist import fire_and_forget

                    fire_and_forget(
                        update_snapshot_after_call(
                            get_settings(),
                            phone=phone,
                            session_id=self.session_id,
                            history=history,
                        )
                    )
                except Exception as mem_exc:  # noqa: BLE001
                    logger.warning("[MEMORY] snapshot scheduling failed: %s", mem_exc)
```

- [ ] **Step 6: Update text_chat call-end**

In `src/noble_agent/server/text_chat.py`, replace the `record_call_memory` block (~lines 367-380) with the equivalent, using the local `phone`, `session_id`, `history`, and `settings` variables in scope there:

```python
        # User snapshot memory: merge this chat into the caller's cumulative
        # snapshot (fire-and-forget, per-phone Redis lock, error-swallowing).
        try:
            from noble_agent.agent.memory import update_snapshot_after_call
            from noble_agent.config import get_settings
            from noble_agent.storage.persist import fire_and_forget

            fire_and_forget(
                update_snapshot_after_call(
                    get_settings(),
                    phone=phone,
                    session_id=session_id,
                    history=history,
                )
            )
        except Exception as mem_exc:  # noqa: BLE001
            logger.warning("[MEMORY] snapshot scheduling failed: %s", mem_exc)
```

(Match the exact variable names already in scope at that location — confirm `phone`, `session_id`, `history` exist there; they do in the current summary block above it.)

- [ ] **Step 7: Add snapshot write to telephony**

In `src/noble_agent/telephony/session.py`, inside the `if self.caller_number:` block, after the summary save / `_link_summary_if_outbound` (~after line 477, before the `except TimeoutError`), add:

```python
                # User snapshot memory (PSTN is a real-phone path): fire-and-forget.
                try:
                    from noble_agent.agent.memory import update_snapshot_after_call
                    from noble_agent.config import get_settings
                    from noble_agent.storage.persist import fire_and_forget

                    fire_and_forget(
                        update_snapshot_after_call(
                            get_settings(),
                            phone=self.caller_number,
                            session_id=self.session_id,
                            history=history,
                        )
                    )
                except Exception as mem_exc:  # noqa: BLE001
                    logger.warning("[TEL][MEMORY] snapshot scheduling failed: %s", mem_exc)
```

- [ ] **Step 8: Run wiring test + affected suites**

Run: `pytest tests/unit/unified/test_snapshot_wiring.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/noble_agent/agent/orchestrator.py src/noble_agent/agent/facade.py src/noble_agent/server/base_session.py src/noble_agent/server/text_chat.py src/noble_agent/telephony/session.py tests/unit/unified/test_snapshot_wiring.py
git commit -m "feat(memory): wire snapshot bootstrap + call-end (browser/chat/telephony)"
```

---

### Task 8: Docs + full-suite verification

**Files:**
- Modify: `CLAUDE.md` (architecture `agent/memory/` row, tool counts, Change Log)
- Verify: full unit suite

- [ ] **Step 1: Run the full unit suite + lint**

Run: `make test-unit && make lint`
Expected: No NEW failures vs the pre-change baseline (`git stash` is not needed — compare against the known ~65 pre-existing unrelated failures noted in CLAUDE.md: catalog/mongo/qdrant drift, `.env` parsing). None of the surviving failures may touch `agent/memory`, `storage/user_snapshots`, `storage/snapshot_lock`, or the snapshot tests.

If a test outside this feature references removed symbols (`recall_memory`, `qa_vector`, `MemoryBackend`, `user_memory_enabled`), fix that reference (import or assertion) — it is fallout from the removal, not new scope.

- [ ] **Step 2: Update CLAUDE.md architecture table**

Replace the `agent/memory/` row so it describes the snapshot design (drop qa_vector / vector_store / recall_memory / MemoryBackend / enable-flag; describe `snapshot.py`, `user_snapshots` collection, Redis lock, always-on). Update the two tool-count mentions (`10 tools` / drop the "11 when NOBLE_USER_MEMORY_ENABLED" clause) in the layout table and RAG sections.

- [ ] **Step 3: Add a Change Log row**

Prepend a row to the CLAUDE.md Change Log (top of the table):

```
| 2026-07-13 | **Memory redesign: per-user cumulative snapshot replaces per-session summary + long-term RAG removed.** New `hotline_user_snapshots` Mongo collection (1 doc/phone, unique index) holding an evolving free-text narrative, merged fire-and-forget at call-end by an LLM (old snapshot + full history → new narrative; careful merge prompt keeps distinct old facts, updates conflicting ones). A Redis per-phone lock (`snapshot:lock:{phone}`, TTL `SNAPSHOT_LOCK_TTL_SEC=60`) makes the next call from the same phone wait (bounded by `SNAPSHOT_LOCK_WAIT_SEC=10`, then use the old snapshot) before bootstrap. Bootstrap injects snapshot + last-K prior-session turns into `customer_block`. **Removed:** `recall_memory` tool (11→10 tools), `agent/memory/{qa_vector,vector_store,base}.py`, Qdrant `user_memory`, the `NOBLE_USER_MEMORY_ENABLED` flag + `USER_MEMORY_{BACKEND,QDRANT_COLLECTION,RECALL_TOP_K,DEDUP_*}` settings. **Untouched:** `hotline_call_summaries` + dashboard consumers. Snapshot now written on all real-phone paths incl. telephony (previously memory-less). New helpers `agent/memory/update_snapshot_after_call` + `short_term_block`; DAO `storage/user_snapshots.py`; lock `storage/snapshot_lock.py`; merge/short-term `agent/memory/snapshot.py`. Spec `docs/superpowers/specs/2026-07-13-user-snapshot-memory-redesign-design.md`, plan `docs/superpowers/plans/2026-07-13-user-snapshot-memory-redesign.md`. Branch `feat/refactor2`. | Per-session summaries only surfaced the single latest call; long-term RAG was a weak, extra-tool fit for "who is this caller". A cumulative snapshot is always present and covers all prior calls. |
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(memory): CLAUDE.md — snapshot memory redesign + change log"
```

---

## Self-Review

**Spec coverage:**
- Snapshot collection + schema → Task 1. ✓
- Redis per-phone lock + guard timeout → Task 2 (mechanism), Task 4/7 (usage). ✓
- Merge (careful prompt) → Task 3. ✓
- Short-term = snapshot + last-K turns → Task 3. ✓
- Always-on (flag removed) → Task 6 (config), Task 7 (gates). ✓
- Remove long-term (recall_memory + qa_vector + vector_store + base) → Task 4, Task 5. ✓
- Untouched call_summaries / dashboard → enforced by scope (no task modifies them). ✓
- Telephony gains snapshot write → Task 7 Step 7. ✓
- Fire-and-forget at 3 call-end paths → Task 7. ✓
- Config add/remove → Task 6. ✓
- Tests + docs → each task + Task 8. ✓

**Placeholder scan:** No TBD/TODO; every code step has full code. Task 5/8 include small "confirm the exact assertion/variable in the existing file" instructions where the current content isn't quoted verbatim — these are read-then-edit steps, not placeholders.

**Type consistency:** `update_snapshot_after_call(settings, *, phone, session_id, history)` and `short_term_block(settings, *, phone, session_id)` are consistent across Task 4 (definition) and Task 7 (call sites). `build_short_term_context(settings, phone, current_session_id)` consistent between Task 3 (def) and Task 4 (call). `merge_snapshot(old_snapshot, history)` / `_call_merge_llm(prompt)` consistent Task 3 ↔ tests. DAO `load_snapshot(phone)` / `save_snapshot(phone, text, session_id)` consistent Task 1 ↔ Tasks 3/4. Lock signatures consistent Task 2 ↔ Task 4.
