"""Unit tests for session store — customer, bookings, state, speakers."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_redis():
    """Create a mock Redis that stores data in a dict."""
    store = {}

    async def mock_get(key):
        return store.get(key)

    async def mock_set(key, value, ex=None):
        store[key] = value

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=mock_get)
    redis.set = AsyncMock(side_effect=mock_set)
    return redis, store


@pytest.fixture
def mock_conn():
    redis, store = _mock_redis()
    conn = MagicMock()
    conn.redis = redis
    with patch("noble_agent.storage.session_store._conn", return_value=conn):
        yield store


@pytest.mark.asyncio
class TestCustomerStore:
    async def test_save_and_load(self, mock_conn):
        from noble_agent.storage.session_store import load_customer, save_customer

        await save_customer("s1", {"name": "Minh", "gender": "M"})
        c = await load_customer("s1")
        assert c["name"] == "Minh"
        assert c["gender"] == "M"

    async def test_merge_preserves_existing(self, mock_conn):
        from noble_agent.storage.session_store import load_customer, save_customer

        await save_customer("s1", {"name": "Minh", "phone": "0912345678"})
        await save_customer("s1", {"gender": "M"})
        c = await load_customer("s1")
        assert c["name"] == "Minh"
        assert c["phone"] == "0912345678"
        assert c["gender"] == "M"

    async def test_empty_values_not_overwrite(self, mock_conn):
        from noble_agent.storage.session_store import load_customer, save_customer

        await save_customer("s1", {"name": "Minh"})
        await save_customer("s1", {"name": ""})  # empty → should not overwrite
        c = await load_customer("s1")
        assert c["name"] == "Minh"

    async def test_defaults_when_no_data(self, mock_conn):
        from noble_agent.storage.session_store import load_customer

        c = await load_customer("nonexistent")
        assert c["name"] == ""
        assert c["gender"] == ""
        assert c["is_noble_customer"] is False


@pytest.mark.asyncio
class TestAgentState:
    async def test_save_and_load_state(self, mock_conn):
        from noble_agent.storage.session_store import load_state, save_state

        await save_state("s1", {"current_agent": "advisor"})
        state = await load_state("s1")
        assert state["current_agent"] == "advisor"

    async def test_state_merge(self, mock_conn):
        from noble_agent.storage.session_store import load_state, save_state

        await save_state("s1", {"current_agent": "router"})
        await save_state("s1", {"some_flag": True})
        state = await load_state("s1")
        assert state["current_agent"] == "router"
        assert state["some_flag"] is True
