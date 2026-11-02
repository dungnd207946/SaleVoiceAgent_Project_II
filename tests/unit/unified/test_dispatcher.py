import json

import pytest

from noble_agent.agent.tools.dispatcher import ToolDispatcher
from noble_agent.storage.models import Customer, State


class _StubCallbacks:
    async def on_token(self, token): ...
    async def on_tool_start(self, name, args): ...
    async def on_tool_done(self, name, result): ...
    async def on_agent_switch(self, **kw): ...
    async def on_done(self): ...


def _tc(name: str, args: dict, tc_id: str = "c1") -> dict:
    return {
        "id": tc_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


@pytest.fixture
def dispatcher_ctx():
    customer = Customer()
    state = State()
    cb = _StubCallbacks()
    d = ToolDispatcher(state=state, customer=customer, rag=None, callbacks=cb, session_id="sid")
    return d, customer, state


async def test_update_customer_sets_field_and_marks_dirty(dispatcher_ctx):
    d, customer, _ = dispatcher_ctx
    out = await d.dispatch(_tc("update_customer", {"name": "Hùng"}))
    assert out  # tool returns SOMETHING
    assert customer.name == "Hùng"
    assert d.consume_customer_dirty() is True
    # Subsequent consume returns False.
    assert d.consume_customer_dirty() is False


async def test_unknown_tool_returns_error_string(dispatcher_ctx):
    d, _, _ = dispatcher_ctx
    out = await d.dispatch(_tc("totally_nonexistent_tool", {}))
    assert "error" in out.lower() or "unknown" in out.lower()


async def test_switch_agent_no_longer_raises(dispatcher_ctx):
    d, _, _ = dispatcher_ctx
    # switch_agent doesn't exist as a tool in unified — must NOT raise.
    # It should be treated as an unknown tool.
    out = await d.dispatch(_tc("switch_agent", {"target": "CA", "reason": "x"}))
    assert "error" in out.lower() or "unknown" in out.lower()


async def test_booking_read_actions_do_not_mark_customer_dirty(dispatcher_ctx):
    """check_availability / list don't mutate Customer; the dispatcher must
    NOT force a system-prompt rebuild on every booking turn."""
    d, _, _ = dispatcher_ctx
    for action in ("check_availability", "list"):
        await d.dispatch(_tc("booking", {"action": action}))
        assert d.consume_customer_dirty() is False, f"action={action} should not dirty"


async def test_booking_schedule_marks_customer_dirty(dispatcher_ctx):
    """action=schedule writes back to Customer via schedule_viewing → dirty."""
    d, _, _ = dispatcher_ctx
    await d.dispatch(_tc("booking", {"action": "schedule"}))
    assert d.consume_customer_dirty() is True


async def test_send_media_items_stripped_from_context_but_sent_to_client(monkeypatch):
    """send_media's items[] is display-only: the client gets the FULL result via
    on_tool_done, but the value returned to the runner (→ state.history / LLM
    context) must NOT contain items[] — every other field is preserved."""
    from noble_agent.agent.tools import support_ops

    full = {
        "ok": True,
        "project_name": "VINHOMES OCEAN PARK 2",
        "caption": "Hình ảnh dự án VINHOMES OCEAN PARK 2",
        "items": [
            {"kind": "image", "url": "https://x/a.png", "thumb": "https://s3/a.webp"},
            {"kind": "image", "url": "https://x/b.png", "thumb": "https://s3/b.webp"},
        ],
        "count": 2,
        "message": "Dạ em gửi hình dự án qua app rồi ạ.",
    }

    async def _fake_send_media(customer, args, *, session_id):  # noqa: ARG001
        return json.dumps(full, ensure_ascii=False)

    monkeypatch.setattr(support_ops, "send_media", _fake_send_media)

    done_events = []

    class _RecordingCallbacks:
        async def on_token(self, token): ...
        async def on_tool_start(self, name, args): ...
        async def on_tool_done(self, name, result):
            done_events.append((name, result))

        async def on_agent_switch(self, **kw): ...
        async def on_done(self): ...

    d = ToolDispatcher(state=State(), customer=Customer(), rag=None, callbacks=_RecordingCallbacks(), session_id="sid")
    returned = await d.dispatch(_tc("send_media", {"query": "tổng quan"}))

    # Client channel (on_tool_done): FULL payload incl. items[].
    assert len(done_events) == 1
    client_payload = json.loads(done_events[0][1])
    assert client_payload["items"] == full["items"]
    assert client_payload["count"] == 2

    # Context channel (return value → history): items[] stripped, rest intact.
    ctx = json.loads(returned)
    assert "items" not in ctx
    assert ctx["ok"] is True
    assert ctx["project_name"] == "VINHOMES OCEAN PARK 2"
    assert ctx["caption"] == full["caption"]
    assert ctx["count"] == 2
    assert ctx["message"] == full["message"]


def test_strip_display_items_only_touches_allowlisted_tools():
    """The strip is scoped to display-only media tools (_DISPLAY_ITEMS_TOOLS).
    A NON-media tool that returns items[] as real content keeps it intact —
    guards against accidentally dropping another tool's meaningful items."""
    from noble_agent.agent.tools.dispatcher import _DISPLAY_ITEMS_TOOLS, _strip_display_items

    payload = json.dumps({"ok": True, "items": [{"kind": "image", "url": "u"}], "count": 1}, ensure_ascii=False)

    # send_media (allowlisted) -> items stripped, other fields kept.
    stripped = json.loads(_strip_display_items("send_media", payload))
    assert "items" not in stripped
    assert stripped["ok"] is True and stripped["count"] == 1

    # A different tool (not allowlisted) -> items preserved verbatim.
    assert "send_media" in _DISPLAY_ITEMS_TOOLS
    other = json.loads(_strip_display_items("some_other_tool", payload))
    assert other["items"] == [{"kind": "image", "url": "u"}]

    # Non-JSON (e.g. the plain ESCALATE_SIGNAL sentinel) -> returned verbatim.
    assert _strip_display_items("send_media", "Thông tin đã được chuyển") == "Thông tin đã được chuyển"


async def test_crashed_update_customer_does_not_mark_dirty(monkeypatch, dispatcher_ctx):
    """Regression: a tool that raises must NOT flip the customer_dirty flag —
    no state mutation happened, so a system-prompt rebuild would be wasted
    work AND mask the failure with a misleading cache-invalidation signal.
    """
    from noble_agent.agent.tools import update_customer as uc_mod

    async def _boom(*_a, **_k):  # noqa: ARG001 - simulate impl failure
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(uc_mod, "run", _boom)

    d, _, _ = dispatcher_ctx
    out = await d.dispatch(_tc("update_customer", {"name": "Hùng"}))
    assert "crashed" in out.lower() or "error" in out.lower()
    assert d.consume_customer_dirty() is False


async def _dispatch_signal(d, monkeypatch) -> list[dict]:
    """Cho `get_document` (read_only) trả ESCALATE_SIGNAL, thu lại mọi lời gọi escalate."""
    from noble_agent.agent.tools import get_document as gd_mod
    from noble_agent.agent.tools import support_ops
    from noble_agent.data.providers.base import ESCALATE_SIGNAL

    async def _khong_co_du_lieu(*_a, **_k):
        return ESCALATE_SIGNAL

    goi: list[dict] = []

    async def _ghi_nhan(state, customer, args, **kw):  # noqa: ARG001
        goi.append({**args, **kw})
        return "đã chuyển"

    monkeypatch.setattr(gd_mod, "run", _khong_co_du_lieu)
    monkeypatch.setattr(support_ops, "escalate", _ghi_nhan)
    await d.dispatch(_tc("get_document", {"project_code": "SGI"}))
    return goi


async def test_tool_bi_du_lieu_thi_tu_escalate(monkeypatch, dispatcher_ctx):
    d, _, _ = dispatcher_ctx

    assert len(await _dispatch_signal(d, monkeypatch)) == 1


async def test_sandbox_khong_duoc_ghi_escalate(monkeypatch):
    """Lượt ghost của semcache dùng CHUNG session_id thật; để nó escalate là ghi
    một ca chuyển sale cho nhu cầu khách chưa từng nói."""
    d = ToolDispatcher(
        state=State(),
        customer=Customer(),
        rag=None,
        callbacks=_StubCallbacks(),
        session_id="sid",
        sandbox=True,
    )

    assert await _dispatch_signal(d, monkeypatch) == []


async def test_escalate_without_department_defaults_to_tenant_handoff():
    """LLM bỏ trống `department` → dùng bộ phận tiếp nhận của tenant, không phải "CVTV" cứng."""
    d = ToolDispatcher(
        state=State(),
        customer=Customer(),
        rag=None,
        callbacks=_StubCallbacks(),
        session_id="sid",
        handoff_department="CSKH",
    )
    out = await d.dispatch(_tc("escalate", {"action": "transfer", "reason": "khách hỏi hợp đồng"}))
    assert json.loads(out)["department"] == "CSKH"


async def test_escalate_explicit_department_wins_over_default():
    d = ToolDispatcher(
        state=State(),
        customer=Customer(),
        rag=None,
        callbacks=_StubCallbacks(),
        session_id="sid",
        handoff_department="CSKH",
    )
    out = await d.dispatch(_tc("escalate", {"action": "transfer", "department": "Kế toán", "reason": "x"}))
    assert json.loads(out)["department"] == "Kế toán"


async def test_dispatcher_records_session_facts_from_tool_results(monkeypatch, dispatcher_ctx):
    from noble_agent.agent.tools import projects_info

    async def _fake_search(args, *, state, customer):
        return json.dumps(
            {
                "units": [
                    {
                        "unit_code": "A-1203",
                        "bedrooms": 2,
                        "price_vnd": 3200000000,
                        "project_name": "Noble Crystal",
                        "project_code": "NCR",
                    }
                ]
            }
        )

    monkeypatch.setattr(projects_info, "search_units", _fake_search)
    d, customer, state = dispatcher_ctx
    await d.dispatch(_tc("search_units", {"scope": "all_projects", "max_price": 4000000000}))
    from noble_agent.agent import session_facts

    assert "A-1203" in session_facts.render(state, customer)


async def test_sandbox_dispatcher_does_not_record_session_facts(monkeypatch):
    from noble_agent.agent.tools import projects_info

    async def _fake_search(args, *, state, customer):
        return json.dumps({"units": [{"unit_code": "A-1203", "bedrooms": 2, "price_vnd": 1, "project_name": "P"}]})

    monkeypatch.setattr(projects_info, "search_units", _fake_search)
    state, customer = State(), Customer()
    d = ToolDispatcher(
        state=state, customer=customer, rag=None, callbacks=_StubCallbacks(), session_id="sid", sandbox=True
    )
    await d.dispatch(_tc("search_units", {"scope": "all_projects"}))
    from noble_agent.agent import session_facts

    assert session_facts.render(state, customer) == ""
