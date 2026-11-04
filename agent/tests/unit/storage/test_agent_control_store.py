from noble_agent.storage import agent_control_store as acs


class _Conn:
    def __init__(self, rows_by_sql): self._rows = rows_by_sql
    def transaction(self):
        c = self
        class _T:
            async def __aenter__(self): return c
            async def __aexit__(self, *a): return False
        return _T()
    async def execute(self, *a): pass
    async def fetchval(self, sql, *a):
        return self._rows.get(("val", sql.split()[3] if len(sql.split()) > 3 else sql))
    async def fetch(self, sql, *a): return self._rows.get("keys", [])
    async def fetchrow(self, sql, *a): return self._rows.get("row")


class _Pool:
    def __init__(self, conn): self._c = conn
    def acquire(self):
        c = self._c
        class _A:
            async def __aenter__(self): return c
            async def __aexit__(self, *a): return False
        return _A()


def test_khong_con_ham_doc_deployment_id():
    """`read_deployment_id` đã xoá (`0941` DROP `control.deployments`).

    Bài cũ (`picks_max`) tiêm một `_Conn` giả nên nó xanh suốt, kể cả khi hàm thật KHÔNG
    chạy được: role `agent_<tenant>` chưa bao giờ có SELECT trên bảng đó. Đúng lớp lỗi
    "tiêm một lối thoát mà production không có" — giữ lại một bài canh sự VẮNG MẶT thì
    không tái phạm được."""
    assert not hasattr(acs, "read_deployment_id")
