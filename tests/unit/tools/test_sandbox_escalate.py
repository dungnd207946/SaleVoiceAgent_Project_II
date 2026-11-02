import jinja2
import pytest

import noble_agent.agent.tools.builtins  # noqa: F401 — registers built-ins
from noble_agent.agent.base import AgentDef
from noble_agent.agent.tools import get_document as gd_mod
from noble_agent.agent.tools import support_ops
from noble_agent.data.providers.base import ESCALATE_SIGNAL
from noble_agent.semcache import sandbox as sb
from noble_agent.storage.models import Customer, State


def _agent() -> AgentDef:
    return AgentDef(
        name="Luna",
        model="m",
        temperature=0.3,
        max_tokens=256,
        prompt_template=jinja2.Template(""),
        sections={},
        tool_names=["get_document"],
        tool_schemas=[],
    )


def _tc(name: str, args: str = "{}") -> dict:
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": args}}


class _Llm:
    """Lượt 1 gọi tool, lượt 2 chốt câu trả lời."""

    def __init__(self, tool_calls: list[dict]):
        self.so_lan = 0
        self._tc = tool_calls

    async def stream_completion(self, **_kw):
        self.so_lan += 1
        return ("", self._tc) if self.so_lan == 1 else ("Dạ em gửi anh/chị ạ.", [])


@pytest.fixture
def da_goi_escalate(monkeypatch):
    goi: list[str] = []

    async def _ghi_nhan(_state, _customer, args, **_kw):
        goi.append(args.get("reason", ""))
        return "đã chuyển"

    monkeypatch.setattr(sb, "build_system_prompt", lambda *_a, **_k: "sys")
    monkeypatch.setattr(support_ops, "escalate", _ghi_nhan)
    from noble_agent.tenant import loader

    monkeypatch.setattr(loader, "get_tenant_context", lambda: type("T", (), {"tenant_id": "noble"})())
    return goi


async def _chay(llm):
    return await sb.run_sandbox_turn(
        agent=_agent(),
        base_history=[],
        customer=Customer(),
        state=State(),
        prior_summary=None,
        llm=llm,
        rag=None,
        sid="sid",
        predicted_query="csbh dự án sao ạ",
    )


async def test_tool_bi_du_lieu_thi_bo_luot_ghost(monkeypatch, da_goi_escalate):
    """Lượt ghost dùng chung session_id thật — escalate ở đây là ghi ca chuyển
    sale cho nhu cầu khách chưa từng nói."""

    async def _rong(*_a, **_k):
        return ESCALATE_SIGNAL

    monkeypatch.setattr(gd_mod, "run", _rong)
    llm = _Llm([_tc("get_document", '{"project_code":"SGI"}')])

    assert await _chay(llm) == (None, [], {})
    assert da_goi_escalate == []
    assert llm.so_lan == 1


async def test_co_du_lieu_thi_van_chay_het_luot(monkeypatch, da_goi_escalate):
    async def _co(*_a, **_k):
        return '{"count": 1}'

    monkeypatch.setattr(gd_mod, "run", _co)
    mode, chain, _ = await _chay(_Llm([_tc("get_document", '{"project_code":"SGI"}')]))

    assert mode == "full"
    assert [m.role for m in chain] == ["assistant", "tool", "assistant"]
