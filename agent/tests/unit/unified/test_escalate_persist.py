"""`escalate` action=transfer ghi một dòng vào tenant_data.escalations.

Ràng buộc cứng: JSON trả về KHÔNG được đổi — nó là contract đã publish cho
frontend (handoff §204-215). Mọi lỗi ghi DB phải chìm.
"""

import json

import pytest

from noble_agent.agent.tools import support_ops
from noble_agent.storage.models import Customer, State, ThreadMessage


def _khach():
    return Customer(full_name="Nguyễn Văn Nam", phone="0901234567", project_interest="SGI")


def _state():
    s = State()
    s.history = [
        ThreadMessage(role="user", content="anh mua căn ở SGI rồi"),
        ThreadMessage(role="assistant", content="Dạ em nghe ạ"),
    ]
    return s


@pytest.fixture
def bat_ghi(monkeypatch):
    """Chặn 2 side-effect ra ngoài, ghi lại tham số."""
    ghi: dict = {"spawn": []}

    async def _record(**kw):
        ghi["record"] = kw
        return 12

    def _spawn(escalation_id, **kw):
        ghi["spawn"].append((escalation_id, kw))
        return None

    monkeypatch.setattr(support_ops, "record_escalation", _record)
    monkeypatch.setattr(support_ops, "spawn_escalation_summary", _spawn)
    return ghi


@pytest.mark.asyncio
async def test_transfer_ghi_dung_field(bat_ghi):
    state, customer = _state(), _khach()
    await support_ops.escalate(
        state,
        customer,
        {"action": "transfer", "reason": "khách hỏi sổ hồng", "department": "CSKH"},
        session_id="sess_1",
    )

    r = bat_ghi["record"]
    assert r["session_id"] == "sess_1"
    assert r["phone"] == "0901234567"
    assert r["customer_name"] == "Nguyễn Văn Nam"
    assert r["project"] == "SGI"
    assert r["missing_data_tool"] == "", "Luna chủ động gọi → cột này rỗng"
    assert r["message_seq"] == 2
    assert r["summary"].startswith("Khách: Nguyễn Văn Nam"), "bản tạm là chuỗi cơ học"


@pytest.mark.asyncio
async def test_cua_code_tu_goi_ghi_ten_tool_bi_du_lieu(bat_ghi):
    await support_ops.escalate(
        _state(),
        _khach(),
        {"action": "transfer", "reason": "hệ thống không có dữ liệu"},
        session_id="sess_1",
        missing_data_tool="search_units",
    )
    assert bat_ghi["record"]["missing_data_tool"] == "search_units"


@pytest.mark.asyncio
async def test_ban_task_summary_voi_id_vua_tao(bat_ghi):
    await support_ops.escalate(
        _state(), _khach(), {"action": "transfer", "reason": "r"}, session_id="sess_1"
    )
    esc_id, kw = bat_ghi["spawn"][0]
    assert esc_id == 12
    assert len(kw["history_snapshot"]) == 2, "phải là bản copy của history"
    assert kw["reason"] == "r"


@pytest.mark.asyncio
async def test_json_tra_ve_khong_doi_khi_dao_nem_loi(monkeypatch):
    """DB chết → tool vẫn trả đúng payload cũ, Luna vẫn nói được với khách."""

    async def _no(**kw):
        raise RuntimeError("pg chết")

    monkeypatch.setattr(support_ops, "record_escalation", _no)

    out = json.loads(
        await support_ops.escalate(
            _state(), _khach(), {"action": "transfer", "reason": "r"}, session_id="sess_1"
        )
    )
    assert set(out) == {"status", "department", "priority", "summary", "working_hours", "message"}
    assert out["status"] == "transfer_completed"


@pytest.mark.asyncio
async def test_check_state_khong_ghi_gi(bat_ghi):
    await support_ops.escalate(_state(), _khach(), {"action": "check_state"}, session_id="sess_1")
    assert "record" not in bat_ghi


@pytest.mark.asyncio
async def test_khong_co_id_thi_khong_ban_task(monkeypatch):
    """PG chưa cấu hình → wrapper trả None → không bắn task LLM vô ích."""
    da_ban = False

    async def _record(**kw):
        return None

    def _spawn(escalation_id, **kw):
        nonlocal da_ban
        da_ban = True

    monkeypatch.setattr(support_ops, "record_escalation", _record)
    monkeypatch.setattr(support_ops, "spawn_escalation_summary", _spawn)

    await support_ops.escalate(_state(), _khach(), {"action": "transfer", "reason": "r"}, session_id="s")
    assert not da_ban
