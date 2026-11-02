"""`PgHeartbeatWriter` sau khi Portal bỏ khái niệm deployment (`0941`).

Nhịp tim khoá theo `tenant_id` — `control.agent_heartbeats` không còn cột
`deployment_id`, và `control.deployments` không còn tồn tại.

⚠️ NHỊP TIM ĐÃ CHẾT SẴN TỪ `0919`, ĐÂY LÀ BẢN HỒI SINH. Bản cũ chỉ dùng pool tenant khi
`cred.kind == self._kind`, mà `kind` được parse từ response `/runtime-credentials` —
trường Portal đã bỏ ở `0919`. Nên `cred.kind` luôn `''`, không bao giờ khớp
`'chat'`/`'voice'`, và mọi lượt beat rơi xuống nhánh `SELECT control.deployments` bằng
role `agent_<tenant>` — role chưa bao giờ có SELECT trên bảng đó. Không test nào bắt
được vì mọi bài đều TIÊM `read_deployment_id` giả; đường thật chưa từng chạy.

Bài học đã ghim thành `test_beat_khong_query_bang_nao_ngoai_heartbeat`: đừng tiêm một
lối thoát mà production không có.
"""

from datetime import UTC, datetime, timedelta

import pytest

from noble_agent.storage import tenant_credentials as tc
from noble_agent.tenant.pg_heartbeat import PgHeartbeatWriter


class _Conn:
    def __init__(self):
        self.upserts = []
        self.sql = []

    def transaction(self):
        c = self

        class _T:
            async def __aenter__(self):
                return c

            async def __aexit__(self, *a):
                return False

        return _T()

    async def execute(self, sql, *a):
        self.sql.append(sql)
        if "agent_heartbeats" in sql:
            self.upserts.append(a)


class _Pool:
    def __init__(self, c):
        self._c = c

    def acquire(self):
        c = self._c

        class _A:
            async def __aenter__(self):
                return c

            async def __aexit__(self, *a):
                return False

        return _A()


async def _pc_v5(tid, **kw):
    from noble_agent.storage.agent_config_store import PublishedConfig

    return PublishedConfig(version=5, config={})


async def _pc_none(tid, **kw):
    return None


def _register_cred():
    tc.clear_for_tests()
    tc.register(
        "t1",
        role="agent_t1",
        password="pw",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


@pytest.fixture(autouse=True)
def _sach():
    tc.clear_for_tests()
    yield
    tc.clear_for_tests()


# ─── Hình dạng câu ghi ───────────────────────────────────────────────────────


async def test_beat_ghi_theo_tenant_khong_co_deployment_id():
    conn = _Conn()
    w = PgHeartbeatWriter("chat", "1.0", pool=_Pool(conn), read_published=_pc_v5)

    assert await w.beat("t1") is True
    assert conn.upserts[0][:2] == ("t1", 5)

    (sql,) = [q for q in conn.sql if "agent_heartbeats" in q]
    assert "deployment_id" not in sql
    assert "ON CONFLICT (tenant_id)" in sql


async def test_beat_chua_publish_thi_running_version_None():
    conn = _Conn()
    w = PgHeartbeatWriter("chat", "1.0", pool=_Pool(conn), read_published=_pc_none)

    assert await w.beat("t1") is True
    assert conn.upserts[0][:2] == ("t1", None)


async def test_beat_khong_query_bang_nao_ngoai_heartbeat():
    """CỔNG THẬT: không lời gọi nào chạm `control.deployments`.

    Bảng đó đã bị Portal `DROP` — một câu SELECT còn sót lại không ném lúc import, nó
    ném lúc chạy, và `beat()` nuốt mọi exception. Tức là nó hỏng IM LẶNG, đúng kiểu đã
    giấu được cái chết của nhịp tim suốt một tuần.
    """
    conn = _Conn()
    w = PgHeartbeatWriter("chat", "1.0", pool=_Pool(conn), read_published=_pc_v5)
    await w.beat("t1")

    assert all("deployments" not in q for q in conn.sql), conn.sql


def test_writer_khong_con_nhan_read_deployment_id():
    with pytest.raises(TypeError):
        PgHeartbeatWriter("chat", "1.0", read_deployment_id=lambda *a, **k: 1)


# ─── Chọn pool ───────────────────────────────────────────────────────────────


async def test_co_credential_thi_dung_pool_cua_tenant(monkeypatch):
    """Có credential per-tenant ⇒ nối bằng role `agent_<tenant>` (đã được GRANT INSERT
    trên `control.agent_heartbeats`), không dùng pool dùng chung.

    Bản trước còn đòi `cred.kind == self._kind`. `kind` biến mất khỏi response từ
    `0919` nên điều kiện đó KHÔNG BAO GIỜ đúng — nó chính là thứ giết nhịp tim.
    """
    _register_cred()
    conn = _Conn()
    goi = {}

    async def fake_pool_for_tenant(tid):
        goi["tid"] = tid
        return _Pool(conn)

    monkeypatch.setattr("noble_agent.storage.postgres_client.pool_for_tenant", fake_pool_for_tenant)

    class _PoolCam:
        def acquire(self):
            raise AssertionError("có credential thì không được dùng pool dùng chung")

    w = PgHeartbeatWriter("chat", "1.0", pool=_PoolCam(), read_published=_pc_v5)
    assert await w.beat("t1") is True
    assert goi["tid"] == "t1"
    assert conn.upserts[0][:2] == ("t1", 5)


async def test_khong_credential_thi_dung_pool_dung_chung():
    conn = _Conn()
    w = PgHeartbeatWriter("chat", "1.0", pool=_Pool(conn), read_published=_pc_v5)

    assert await w.beat("t1") is True
    assert conn.upserts[0][:2] == ("t1", 5)


async def test_beat_nuot_loi_va_tra_False():
    """Nhịp tim hỏng KHÔNG được giết vòng lặp gọi nó."""

    class _ConnNo(_Conn):
        async def execute(self, sql, *a):
            raise RuntimeError("pg down")

    w = PgHeartbeatWriter("chat", "1.0", pool=_Pool(_ConnNo()), read_published=_pc_v5)
    assert await w.beat("t1") is False
