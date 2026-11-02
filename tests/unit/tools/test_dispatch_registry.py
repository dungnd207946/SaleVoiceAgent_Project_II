import json

from noble_agent.agent.tools import dispatcher as _disp
from noble_agent.agent.tools.dispatcher import ToolDispatcher


class _CB:
    interrupt_check = None

    def __init__(self):
        self.starts = []
        self.dones = []

    async def on_tool_start(self, n, a):
        self.starts.append((n, a))

    async def on_tool_done(self, n, r):
        self.dones.append((n, r))


class _State:
    def __init__(self):
        self.scratchpad = {}
        self.history = []


class _Cust:
    project_interest = "NCLB"


async def test_unknown_tool_returns_error():
    d = ToolDispatcher(state=_State(), customer=_Cust(), rag=None, callbacks=_CB(), session_id="s")
    out = await d.dispatch({"function": {"name": "nope", "arguments": "{}"}})
    assert json.loads(out)["error"] == "unknown tool nope"


async def test_default_project_code_fills_from_customer():
    d = ToolDispatcher(state=_State(), customer=_Cust(), rag=None, callbacks=_CB(), session_id="s")
    args = {}
    d.default_project_code(args)
    assert args["project_code"] == "NCLB"


async def test_update_customer_sets_dirty_via_spec(monkeypatch):
    import noble_agent.agent.tools.builtins  # noqa: F401
    d = ToolDispatcher(state=_State(), customer=_Cust(), rag=None, callbacks=_CB(), session_id="s")

    async def _fake_run(customer, args):  # patch the underlying executor target
        return json.dumps({"ok": True})

    monkeypatch.setattr("noble_agent.agent.tools.update_customer.run", _fake_run)
    await d.dispatch({"function": {"name": "update_customer", "arguments": "{}"}})
    assert d.consume_customer_dirty() is True


def test_service_customer_items_stripped_from_history():
    result = json.dumps(
        {
            "ok": True,
            "context": "Chính sách X",
            "items": [{"kind": "image", "url": "u", "label": "Chính sách X"}],
            "count": 1,
        },
        ensure_ascii=False,
    )
    stripped = _disp._strip_display_items("service_customer", result)
    data = json.loads(stripped)
    assert "items" not in data
    # caption chỉ còn 1 lần (trong context), không lặp qua item label
    assert stripped.count("Chính sách X") == 1
    assert data["context"] == "Chính sách X"
