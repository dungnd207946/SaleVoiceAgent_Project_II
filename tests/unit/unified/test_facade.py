from unittest.mock import AsyncMock, MagicMock

import pytest

from noble_agent.agent.base import load_agent_def
from noble_agent.agent.facade import NobleAgent
from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR

# Real agent def — set_customer_fields renders the customer block via its
# CUSTOMER_PROFILE.md template, so the runner mock needs a real `_agent`.
AGENT = load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)


@pytest.fixture
def runner():
    r = MagicMock()
    r.handle_turn = AsyncMock()
    r._settings = MagicMock()
    r._repo = MagicMock()
    r._repo._redis = AsyncMock()
    return r


async def test_stream_response_collects_tokens(runner):
    async def fake_handle_turn(sid, text, cb):
        await cb.on_token("hello ")
        await cb.on_token("world")
        await cb.on_done()

    runner.handle_turn = AsyncMock(side_effect=fake_handle_turn)
    agent = NobleAgent(session_id="s1", runner=runner)
    out = await agent.stream_response("hi")
    assert out == "hello world"


async def test_stream_response_invokes_legacy_sync_callbacks(runner):
    received = []

    async def fake_handle_turn(sid, text, cb):
        await cb.on_token("ab")
        await cb.on_tool_start("kb_search", {"query": "x"})
        await cb.on_tool_done("kb_search", "{}")

    runner.handle_turn = AsyncMock(side_effect=fake_handle_turn)
    agent = NobleAgent(session_id="s1", runner=runner)

    def on_token(t):
        received.append(("tok", t))

    def on_tool_start(name, args):
        received.append(("start", name))

    def on_tool_done(name, res):
        received.append(("done", name))

    await agent.stream_response("hi", on_token=on_token, on_tool_start=on_tool_start, on_tool_done=on_tool_done)
    assert ("tok", "ab") in received
    assert ("start", "kb_search") in received
    assert ("done", "kb_search") in received


async def test_on_agent_switch_kwarg_is_accepted_but_inert(runner):
    runner.handle_turn = AsyncMock()
    agent = NobleAgent(session_id="s1", runner=runner)
    await agent.stream_response("hi", on_agent_switch=lambda **kw: None)


async def test_current_agent_attribute_is_constant(runner):
    agent = NobleAgent(session_id="s1", runner=runner)
    assert agent._current_agent == "unified"


async def test_reset_deletes_session_keys(runner):
    agent = NobleAgent(session_id="abc", runner=runner)
    await agent.reset()
    runner._repo._redis.delete.assert_awaited_once()
    args = runner._repo._redis.delete.call_args.args
    assert "session:abc:meta" in args
    assert "session:abc:customer" in args
    assert "session:abc:state" in args


async def test_refresh_system_prompt_is_noop(runner):
    agent = NobleAgent(session_id="s1", runner=runner)
    assert await agent.refresh_system_prompt() is None


def test_set_interrupt_context_is_noop(runner):
    agent = NobleAgent(session_id="s1", runner=runner)
    assert agent.set_interrupt_context(anything=1) is None


async def test_get_customer_returns_dict_from_repo():
    """get_customer must load through StateRepo (the same key the agent's
    prompt reads from) — not legacy session_store."""
    from datetime import UTC, datetime

    from noble_agent.storage.models import Customer, Meta, State

    now = datetime.now(UTC)
    repo = MagicMock()
    repo.load = AsyncMock(
        return_value=(
            Meta(session_id="s1", started_at=now, last_active=now),
            Customer(name="Hùng", phone="0912345678", gender="M"),
            State(),
        )
    )
    r = MagicMock()
    r._repo = repo
    agent = NobleAgent(session_id="s1", runner=r)

    out = await agent.get_customer()
    assert out["name"] == "Hùng"
    assert out["gender"] == "M"
    repo.load.assert_awaited_once_with("s1")


async def test_set_customer_fields_persists_through_repo():
    """set_customer_fields merges fields into the unified Customer model and
    saves via StateRepo so the next turn sees them in the system prompt."""
    from datetime import UTC, datetime

    from noble_agent.storage.models import Customer, Meta, State

    now = datetime.now(UTC)
    meta = Meta(session_id="s1", started_at=now, last_active=now)
    repo = MagicMock()
    repo.load = AsyncMock(return_value=(meta, Customer(name="old"), State()))
    repo.save_all = AsyncMock()
    r = MagicMock()
    r._repo = repo
    r._agent = AGENT
    agent = NobleAgent(session_id="s1", runner=r)

    out = await agent.set_customer_fields({"name": "Hùng", "phone": "0912345678", "gender": "M"})
    assert out["name"] == "Hùng"
    assert out["phone"] == "0912345678"
    assert out["gender"] == "M"

    repo.save_all.assert_awaited_once()
    saved_customer = repo.save_all.call_args.args[2]
    assert saved_customer.name == "Hùng"
    assert saved_customer.phone == "0912345678"
    assert saved_customer.gender == "M"


async def test_set_customer_fields_skips_empty_values():
    """Empty / None inputs must not blank existing fields."""
    from datetime import UTC, datetime

    from noble_agent.storage.models import Customer, Meta, State

    now = datetime.now(UTC)
    meta = Meta(session_id="s1", started_at=now, last_active=now)
    repo = MagicMock()
    repo.load = AsyncMock(return_value=(meta, Customer(name="Hùng", phone="0911"), State()))
    repo.save_all = AsyncMock()
    r = MagicMock()
    r._repo = repo
    r._agent = AGENT
    agent = NobleAgent(session_id="s1", runner=r)

    await agent.set_customer_fields({"name": "", "gender": "M"})
    saved_customer = repo.save_all.call_args.args[2]
    assert saved_customer.name == "Hùng"  # unchanged (empty input ignored)
    assert saved_customer.gender == "M"
    assert saved_customer.phone == "0911"


async def test_set_customer_fields_refreezes_profile_block():
    """An explicit identity seed re-renders the frozen profile block and marks
    the profile loaded, so it takes effect even when applied mid-session (after
    the block was frozen) and is authoritative over the first-turn DB bootstrap."""
    from datetime import UTC, datetime

    from noble_agent.storage.models import Customer, Meta, State

    now = datetime.now(UTC)
    meta = Meta(session_id="s1", started_at=now, last_active=now)
    # Simulate a session whose block was already frozen with an empty profile.
    stale = State()
    stale.scratchpad["customer_block"] = "## Hồ sơ khách hàng (đã có)"
    repo = MagicMock()
    repo.load = AsyncMock(return_value=(meta, Customer(), stale))
    repo.save_all = AsyncMock()
    r = MagicMock()
    r._repo = repo
    r._agent = AGENT
    agent = NobleAgent(session_id="s1", runner=r)

    await agent.set_customer_fields({"full_name": "Lê Viết Thúy Nga", "gender": "F"})

    saved_state = repo.save_all.call_args.args[3]
    block = saved_state.scratchpad["customer_block"]
    assert "Lê Viết Thúy Nga" in block  # re-rendered from the applied fields
    assert "Nữ" in block  # gender F surfaced for anh/chị addressing
    assert saved_state.scratchpad["_profile_loaded"] is True


async def test_set_customer_fields_injects_short_term_when_enabled(monkeypatch):
    """set_customer (tester 'Áp dụng hồ sơ' / app provision) freezes the block
    AND marks the profile loaded, so the orchestrator bootstrap is skipped. This
    path must therefore inject short-term memory itself, or a UI-seeded identity
    silently loses prior-call context (the freeze clobbers it)."""
    from datetime import UTC, datetime
    from types import SimpleNamespace

    import noble_agent.agent.facade as facade_mod
    import noble_agent.agent.memory as memory_mod
    from noble_agent.storage.models import Customer, Meta, State

    # Settings content is irrelevant now (always-on when phone present) — this
    # test monkeypatches short_term_block directly.
    monkeypatch.setattr(facade_mod, "get_settings", lambda: SimpleNamespace())

    async def fake_short_term(settings, *, phone, session_id):
        assert phone == "0912345679"
        return "## Bối cảnh lần gọi trước\nTóm tắt: lần trước khách hỏi giá NCLB"

    monkeypatch.setattr(memory_mod, "short_term_block", fake_short_term)

    now = datetime.now(UTC)
    meta = Meta(session_id="s1", started_at=now, last_active=now)
    repo = MagicMock()
    repo.load = AsyncMock(return_value=(meta, Customer(), State()))
    repo.save_all = AsyncMock()
    r = MagicMock()
    r._repo = repo
    r._agent = AGENT
    agent = NobleAgent(session_id="s1", runner=r)

    await agent.set_customer_fields({"phone": "0912345679"})

    saved_state = repo.save_all.call_args.args[3]
    block = saved_state.scratchpad["customer_block"]
    assert "## Bối cảnh lần gọi trước" in block  # short-term appended, not clobbered
    assert saved_state.scratchpad["_profile_loaded"] is True


async def test_set_customer_fields_no_short_term_without_phone(monkeypatch):
    """No phone on the customer → set_customer must not call the memory backend
    or append a block (behaviour identical to before the feature)."""
    from datetime import UTC, datetime
    from types import SimpleNamespace

    import noble_agent.agent.facade as facade_mod
    import noble_agent.agent.memory as memory_mod
    from noble_agent.storage.models import Customer, Meta, State

    monkeypatch.setattr(facade_mod, "get_settings", lambda: SimpleNamespace())

    called = False

    async def fake_short_term(settings, *, phone, session_id):
        nonlocal called
        called = True
        return "SHOULD-NOT-APPEAR"

    monkeypatch.setattr(memory_mod, "short_term_block", fake_short_term)

    now = datetime.now(UTC)
    meta = Meta(session_id="s1", started_at=now, last_active=now)
    repo = MagicMock()
    repo.load = AsyncMock(return_value=(meta, Customer(), State()))
    repo.save_all = AsyncMock()
    r = MagicMock()
    r._repo = repo
    r._agent = AGENT
    agent = NobleAgent(session_id="s1", runner=r)

    # No "phone" field applied → new_customer.phone stays falsy.
    await agent.set_customer_fields({"full_name": "Không Có Số"})

    saved_state = repo.save_all.call_args.args[3]
    assert called is False
    assert "SHOULD-NOT-APPEAR" not in saved_state.scratchpad["customer_block"]
    assert saved_state.scratchpad["_profile_loaded"] is True
