"""text-chat WS close persists customer + call summary (parity with voice)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from noble_agent.agent.summary import generator as summary_gen
from noble_agent.server import text_chat
from noble_agent.storage import pg_data_plane, session_store


class _FakeWS:
    def __init__(self, messages):
        self._messages = list(messages)
        self.sent: list = []

    def __aiter__(self):
        async def gen():
            for m in self._messages:
                yield m

        return gen()

    async def send(self, data):
        self.sent.append(data)


@pytest.fixture
def stub_llm(monkeypatch):
    llm = MagicMock()
    llm.ensure_session_started = AsyncMock()
    llm.stream_response = AsyncMock(return_value="chào anh")
    llm.reset = AsyncMock()
    llm.pinned_version = 0
    monkeypatch.setattr(text_chat, "_create_llm", AsyncMock(return_value=llm))
    return llm


async def test_close_persists_customer_and_summary(stub_llm, monkeypatch):
    saver = AsyncMock()
    summ = AsyncMock(return_value={"summary": "ok"})
    persist_conv = AsyncMock(return_value=1)
    monkeypatch.setattr(session_store, "load_customer", AsyncMock(return_value={"phone": "0912345678", "name": "An"}))
    monkeypatch.setattr(session_store, "save_customer_persistent", saver)
    monkeypatch.setattr(
        session_store, "load_history_from_state", AsyncMock(return_value=[{"role": "user", "content": "hi"}])
    )
    monkeypatch.setattr(summary_gen, "generate_call_summary", summ)
    monkeypatch.setattr(pg_data_plane, "persist_conversation", persist_conv)

    ws = _FakeWS([json.dumps({"type": "user_text", "text": "chào"})])
    await text_chat.handle_text_session(ws, "sid-T")

    saver.assert_awaited_once()
    summ.assert_awaited_once()
    persist_conv.assert_awaited_once()
    assert persist_conv.await_args.kwargs["session_id"] == "sid-T"
    assert persist_conv.await_args.kwargs["source"] == "chat"


async def test_close_no_persist_without_phone(stub_llm, monkeypatch):
    saver = AsyncMock()
    monkeypatch.setattr(session_store, "load_customer", AsyncMock(return_value={"phone": ""}))
    monkeypatch.setattr(session_store, "save_customer_persistent", saver)

    ws = _FakeWS([])
    await text_chat.handle_text_session(ws, "sid-T2")

    saver.assert_not_awaited()
