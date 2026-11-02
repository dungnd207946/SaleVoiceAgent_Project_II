"""Code-driven escalate when a data tool returns ESCALATE_SIGNAL.

The prompt asks Luna to call escalate after seeing the sentinel, but the model
does so intermittently — the customer gets promised a callback that was never
recorded. The dispatcher now performs the transfer itself whenever a tool
result carries the sentinel, so the handoff always lands in scratchpad.
"""

import json

import pytest

from noble_agent.agent.tools.dispatcher import ToolDispatcher
from noble_agent.data.providers.base import ESCALATE_SIGNAL
from noble_agent.storage.models import Customer, State


class _RecordingCallbacks:
    def __init__(self):
        self.events = []

    async def on_token(self, token): ...

    async def on_tool_start(self, name, args):
        self.events.append(("start", name, args))

    async def on_tool_done(self, name, result):
        self.events.append(("done", name, result))

    async def on_agent_switch(self, **kw): ...

    async def on_done(self): ...


class _Down:
    """Provider stub whose search_units yields nothing → tool escalates."""

    async def search_units(self, _q):
        return None

    async def discover_projects(self, _q):
        return None


def _tc(name: str, args: dict, tc_id: str = "c1") -> dict:
    return {
        "id": tc_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


@pytest.fixture
def ctx():
    customer = Customer()
    state = State()
    cb = _RecordingCallbacks()
    d = ToolDispatcher(state=state, customer=customer, rag=None, callbacks=cb, session_id="sid")
    return d, state, cb


async def test_search_units_sentinel_triggers_auto_escalate(monkeypatch, ctx):
    from noble_agent.agent.tools import projects_info

    monkeypatch.setattr(projects_info.providers, "get_provider", lambda _s: _Down())

    d, state, _ = ctx
    out = await d.dispatch(_tc("search_units", {"project_code": "SGR"}))
    # The LLM-facing result stays the documented sentinel string.
    assert out == ESCALATE_SIGNAL
    # ...but the transfer was actually recorded by code.
    assert state.scratchpad.get("escalation_transferred") == "1"
    assert "search_units" in state.scratchpad.get("escalation_summary", "")


async def test_discover_projects_sentinel_also_escalates(monkeypatch, ctx):
    from noble_agent.agent.tools import projects_info

    monkeypatch.setattr(projects_info.providers, "get_provider", lambda _s: _Down())

    d, state, _ = ctx
    out = await d.dispatch(_tc("discover_projects", {"region": "Hà Nội"}))
    assert out == ESCALATE_SIGNAL
    assert state.scratchpad.get("escalation_transferred") == "1"


async def test_normal_result_does_not_escalate(ctx):
    d, state, _ = ctx
    out = await d.dispatch(_tc("update_customer", {"name": "Hùng"}))
    assert ESCALATE_SIGNAL not in out
    assert "escalation_transferred" not in state.scratchpad


async def test_auto_escalate_emits_tool_events(monkeypatch, ctx):
    from noble_agent.agent.tools import projects_info

    monkeypatch.setattr(projects_info.providers, "get_provider", lambda _s: _Down())

    d, _, cb = ctx
    await d.dispatch(_tc("search_units", {"project_code": "SGR"}))
    escalate_starts = [e for e in cb.events if e[0] == "start" and e[1] == "escalate"]
    escalate_dones = [e for e in cb.events if e[0] == "done" and e[1] == "escalate"]
    assert len(escalate_starts) == 1
    assert escalate_starts[0][2].get("action") == "transfer"
    assert len(escalate_dones) == 1


async def test_auto_escalate_failure_does_not_break_dispatch(monkeypatch, ctx):
    from noble_agent.agent.tools import projects_info, support_ops

    async def _boom(*_a, **_k):
        raise RuntimeError("escalate down")

    monkeypatch.setattr(projects_info.providers, "get_provider", lambda _s: _Down())
    monkeypatch.setattr(support_ops, "escalate", _boom)

    d, _, _ = ctx
    out = await d.dispatch(_tc("search_units", {"project_code": "SGR"}))
    # The original tool result must survive an auto-escalate failure.
    assert out == ESCALATE_SIGNAL


async def test_auto_escalate_ghi_ten_tool_bi_du_lieu(monkeypatch, ctx):
    """Cửa code tự gọi phải nói rõ tool nào bí dữ liệu — sale cần tra tay đúng chỗ."""
    from noble_agent.agent.tools import projects_info, support_ops

    ghi: dict = {}
    that = support_ops.escalate

    async def _bat(state, customer, args, **kw):
        ghi.update(kw)
        return await that(state, customer, args, **kw)

    monkeypatch.setattr(projects_info.providers, "get_provider", lambda _s: _Down())
    monkeypatch.setattr(support_ops, "escalate", _bat)

    d, _, _ = ctx
    await d.dispatch(_tc("search_units", {"project_code": "SGR"}))
    assert ghi["missing_data_tool"] == "search_units"
    assert ghi["session_id"] == "sid"


async def test_escalate_llm_goi_thang_thi_khong_co_missing_tool(monkeypatch, ctx):
    """Luna chủ động chuyển → cột missing_data_tool rỗng."""
    from noble_agent.agent.tools import support_ops

    ghi: dict = {}
    that = support_ops.escalate

    async def _bat(state, customer, args, **kw):
        ghi.update(kw)
        return await that(state, customer, args, **kw)

    monkeypatch.setattr(support_ops, "escalate", _bat)

    d, _, _ = ctx
    await d.dispatch(_tc("escalate", {"action": "transfer", "reason": "khách hỏi sổ hồng"}))
    assert ghi.get("missing_data_tool", "") == ""
    assert ghi["session_id"] == "sid"


async def test_escalate_tool_itself_does_not_recurse(ctx):
    """A direct escalate call whose result mentions nothing sentinel-like must
    not re-trigger; and even if it did, name == escalate is excluded."""
    d, state, cb = ctx
    await d.dispatch(_tc("escalate", {"action": "transfer", "reason": "khách yêu cầu", "department": "CVTV"}))
    escalate_starts = [e for e in cb.events if e[0] == "start" and e[1] == "escalate"]
    assert len(escalate_starts) == 1  # only the direct call, no auto duplicate
    assert state.scratchpad.get("escalation_transferred") == "1"


async def test_auto_escalate_uses_tenant_handoff_department(monkeypatch):
    """Tenant config đặt bộ phận tiếp nhận (scope.handoff_department); auto-escalate
    phải chuyển vào ĐÚNG bộ phận đó, không phải "CVTV" cứng của tenant noble."""
    from noble_agent.agent.tools import projects_info

    monkeypatch.setattr(projects_info.providers, "get_provider", lambda _s: _Down())
    cb = _RecordingCallbacks()
    d = ToolDispatcher(
        state=State(), customer=Customer(), rag=None, callbacks=cb, session_id="sid", handoff_department="CSKH"
    )
    await d.dispatch(_tc("search_units", {"project_code": "SGR"}))
    starts = [e for e in cb.events if e[0] == "start" and e[1] == "escalate"]
    assert starts and starts[0][2]["department"] == "CSKH"


async def test_auto_escalate_default_department_stays_cvtv(monkeypatch, ctx):
    """Legacy bundle (tenants/noble) không có config bộ phận → giữ "CVTV" như trước."""
    from noble_agent.agent.tools import projects_info

    monkeypatch.setattr(projects_info.providers, "get_provider", lambda _s: _Down())
    d, _, cb = ctx
    await d.dispatch(_tc("search_units", {"project_code": "SGR"}))
    starts = [e for e in cb.events if e[0] == "start" and e[1] == "escalate"]
    assert starts and starts[0][2]["department"] == "CVTV"
