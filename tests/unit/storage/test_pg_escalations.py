# tests/unit/storage/test_pg_escalations.py
import pytest

from noble_agent.storage import pg_data_plane as dp


def _stub_conn(seen: dict, tra_ve):
    """Conn + tenant_conn giả, ghi lại tenant và args của câu SQL."""

    class _Conn:
        async def execute(self, sql, *a):
            seen["sql"] = sql
            seen["args"] = a

        async def fetchrow(self, sql, *a):
            seen["sql"] = sql
            seen["args"] = a
            return tra_ve

        async def fetchval(self, sql, *a):
            seen["sql"] = sql
            seen["args"] = a
            return tra_ve

    class _CM:
        def __init__(self, tid):
            seen["tenant"] = tid

        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *a):
            return False

    return _CM


@pytest.fixture
def moi_truong(monkeypatch):
    from noble_agent.config import reset_settings_for_tests

    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()


@pytest.mark.asyncio
async def test_record_escalation_scopes_to_current_tenant(moi_truong, monkeypatch):
    from noble_agent.tenant.current import use_tenant

    seen: dict = {}

    async def _pool_stub(tid):
        return object()

    monkeypatch.setattr(dp, "_pool_or_none", _pool_stub)
    monkeypatch.setattr(dp, "tenant_conn", lambda pool, tid: _stub_conn(seen, {"id": 12})(tid))

    with use_tenant("acme"):
        out = await dp.record_escalation(
            session_id="sess_1",
            phone="0900000000",
            customer_name="Nguyễn Văn Nam",
            project="SGI",
            missing_data_tool="search_units",
            summary="Khách hỏi tồn kho",
            message_seq=7,
        )

    assert out == 12
    assert seen["tenant"] == "acme"  # scope theo tenant của request, không phải settings
    assert seen["args"][0] == "acme"  # tenant_id vẫn là tham số tường minh
    assert "escalations" in seen["sql"]


@pytest.mark.asyncio
async def test_record_escalation_khong_ghi_status_va_handled(moi_truong, monkeypatch):
    """4 cột Portal sở hữu phải để DB tự đặt mặc định — agent không đụng vào."""
    from noble_agent.tenant.current import use_tenant

    seen: dict = {}

    async def _pool_stub(tid):
        return object()

    monkeypatch.setattr(dp, "_pool_or_none", _pool_stub)
    monkeypatch.setattr(dp, "tenant_conn", lambda pool, tid: _stub_conn(seen, {"id": 1})(tid))

    with use_tenant("acme"):
        await dp.record_escalation(session_id="s", summary="x")

    sql = seen["sql"]
    for cot in ("status", "handled_by", "handled_at", "handled_note", "summary_at"):
        assert cot not in sql, f"INSERT không được ghi {cot}"


@pytest.mark.asyncio
async def test_save_escalation_summary_dong_dau_summary_at(moi_truong, monkeypatch):
    """Bản LLM về thì đóng dấu `summary_at` trong CÙNG câu UPDATE — dashboard
    dựa vào cột này để biết summary còn là bản tạm hay đã xong."""
    from noble_agent.tenant.current import use_tenant

    seen: dict = {}

    async def _pool_stub(tid):
        return object()

    monkeypatch.setattr(dp, "_pool_or_none", _pool_stub)
    monkeypatch.setattr(dp, "tenant_conn", lambda pool, tid: _stub_conn(seen, None)(tid))

    with use_tenant("acme"):
        await dp.save_escalation_summary(12, "bản LLM")

    assert seen["tenant"] == "acme"
    assert seen["args"] == ("acme", 12, "bản LLM")
    assert "summary_at" in seen["sql"]


@pytest.mark.asyncio
async def test_wrapper_no_op_khi_chua_cau_hinh_postgres(moi_truong, monkeypatch):
    """PG chưa cấu hình → wrapper im lặng bỏ qua, không ném lên đường chạy nóng."""
    from noble_agent.tenant.current import use_tenant

    async def _pool_none(tid):
        return None

    monkeypatch.setattr(dp, "_pool_or_none", _pool_none)

    with use_tenant("acme"):
        assert await dp.record_escalation(session_id="s", summary="x") is None
        await dp.save_escalation_summary(1, "y")  # không được ném


@pytest.mark.asyncio
async def test_persist_conversation_bat_co_khi_da_tung_escalate(moi_truong, monkeypatch):
    """`transferred_to_sales` phải hỏi bảng escalations, và hỏi trong CÙNG một
    khối tenant_conn với câu INSERT — không mở thêm transaction thứ hai."""
    from noble_agent.tenant.current import use_tenant

    goi: list = []
    so_lan_mo_conn = 0

    class _Conn:
        async def fetchval(self, sql, *a):
            goi.append(("fetchval", sql, a))
            return True  # session này đã escalate

        async def fetchrow(self, sql, *a):
            goi.append(("fetchrow", sql, a))
            return {"id": 5}

    class _CM:
        async def __aenter__(self):
            nonlocal so_lan_mo_conn
            so_lan_mo_conn += 1
            return _Conn()

        async def __aexit__(self, *a):
            return False

    async def _pool_stub(tid):
        return object()

    monkeypatch.setattr(dp, "_pool_or_none", _pool_stub)
    monkeypatch.setattr(dp, "tenant_conn", lambda pool, tid: _CM())

    with use_tenant("acme"):
        out = await dp.persist_conversation(
            {"transferred_to_sales": False, "summary": "x"},
            phone="0900000000",
            session_id="sess_1",
        )

    assert out == 5
    assert so_lan_mo_conn == 1, "phải dùng chung một tenant_conn"
    assert any("escalations" in sql for kind, sql, _ in goi if kind == "fetchval")
    insert = next(a for kind, sql, a in goi if kind == "fetchrow")
    assert True in insert, "summary_doc nói False nhưng escalations nói có → phải là True"


@pytest.mark.asyncio
async def test_record_escalation_bo_qua_khi_thieu_session_id(moi_truong, monkeypatch):
    called = False

    async def _pool_stub(tid):
        nonlocal called
        called = True
        return object()

    monkeypatch.setattr(dp, "_pool_or_none", _pool_stub)

    from noble_agent.tenant.current import use_tenant

    with use_tenant("acme"):
        assert await dp.record_escalation(session_id="", summary="x") is None
    assert not called, "session_id rỗng thì không được chạm tới pool"
