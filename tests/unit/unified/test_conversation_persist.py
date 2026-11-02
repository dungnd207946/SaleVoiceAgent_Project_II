"""`session_store.load_history_from_state` — the Redis state key is the transcript
source for session-end summary generation.

The per-message transcript sink itself (delta-only insert, no-insert-when-save-fails,
role/skip rules) is covered by `test_pg_conversation_messages.py`, which owns the
`tenant_data.conversation_messages` path.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import fakeredis.aioredis
import pytest

from noble_agent.storage import session_store
from noble_agent.storage.repo import StateRepo


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def repo(redis):
    return StateRepo(redis_client=redis, ttl_seconds=3600)


async def test_load_history_from_state_excludes_system(repo):
    from datetime import UTC, datetime

    from noble_agent.storage.models import Customer, Meta, State, ThreadMessage

    now = datetime.now(UTC)
    state = State(
        history=[
            ThreadMessage(role="system", content="PROMPT"),
            ThreadMessage(role="user", content="hỏi"),
            ThreadMessage(role="assistant", content="đáp"),
        ]
    )
    await repo.save_all("sid-E", Meta(session_id="sid-E", started_at=now, last_active=now), Customer(), state)

    # session_store reads via its own connection manager redis; point it at repo's.
    import noble_agent.storage.session_store as ss

    ss_conn = MagicMock(redis=repo._redis)
    orig = ss._conn
    ss._conn = lambda: ss_conn
    try:
        hist = await session_store.load_history_from_state("sid-E")
    finally:
        ss._conn = orig

    roles = [m["role"] for m in hist]
    assert roles == ["user", "assistant"]
