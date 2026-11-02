"""update_customer fires a fire-and-forget customers upsert when phone present."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

from noble_agent.agent.tools import update_customer
from noble_agent.storage import persist, session_store
from noble_agent.storage.models import Customer


async def _drain():
    # let scheduled fire-and-forget tasks run to completion
    await asyncio.sleep(0)
    tasks = [t for t in persist._bg_tasks if not t.done()]
    if tasks:
        await asyncio.gather(*tasks)


async def test_persist_scheduled_when_phone_present(monkeypatch):
    saver = AsyncMock()
    monkeypatch.setattr(session_store, "save_customer_persistent", saver)
    customer = Customer(phone="0912345678")

    out = await update_customer.run(customer, {"name": "Hùng", "budget": "3 tỷ"})
    await _drain()

    assert json.loads(out)["ok"] is True
    saver.assert_awaited_once()
    phone_arg, data_arg = saver.await_args.args
    assert phone_arg == "0912345678"
    assert data_arg["name"] == "Hùng"


async def test_no_persist_when_phone_missing(monkeypatch):
    saver = AsyncMock()
    monkeypatch.setattr(session_store, "save_customer_persistent", saver)
    customer = Customer(phone=None)

    out = await update_customer.run(customer, {"name": "Hùng"})
    await _drain()

    assert json.loads(out)["ok"] is True
    saver.assert_not_awaited()


async def test_notes_accumulate_across_calls(monkeypatch):
    # The LLM sends context in pieces as the customer talks; overwriting would
    # forget the earlier piece, so notes are merged (dedup, newest kept on cap).
    monkeypatch.setattr(session_store, "save_customer_persistent", AsyncMock())
    customer = Customer(phone=None)

    await update_customer.run(customer, {"notes": "làm ở Long Biên"})
    await update_customer.run(customer, {"notes": "con sắp vào lớp 1"})
    await update_customer.run(customer, {"notes": "Làm ở Long Biên"})  # duplicate, case-insensitive
    assert customer.notes == "làm ở Long Biên; con sắp vào lớp 1"

    await update_customer.run(customer, {"notes": "x" * 400})
    assert len(customer.notes) == update_customer._NOTES_MAX
    assert customer.notes.endswith("x" * 50)  # newest piece survives the cap

    out = await update_customer.run(customer, {"notes": "   "})
    assert json.loads(out)["ok"] is False  # blank pieces are ignored like other fields


async def test_no_persist_when_nothing_updated(monkeypatch):
    saver = AsyncMock()
    monkeypatch.setattr(session_store, "save_customer_persistent", saver)
    customer = Customer(phone="0912345678")

    out = await update_customer.run(customer, {"unknown_field": "x"})
    await _drain()

    assert json.loads(out)["ok"] is False
    saver.assert_not_awaited()
