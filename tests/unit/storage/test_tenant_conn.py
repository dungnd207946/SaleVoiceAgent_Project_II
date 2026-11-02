import pytest


class _FakeTxn:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.calls.append("BEGIN")
        return self

    async def __aexit__(self, *a):
        self.conn.calls.append("COMMIT")
        return False


class _FakeConn:
    def __init__(self):
        self.calls = []

    def transaction(self):
        return _FakeTxn(self)

    async def execute(self, sql, *args):
        self.calls.append((sql, args))


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Acq:
            async def __aenter__(s):
                return conn

            async def __aexit__(s, *a):
                conn.calls.append("RELEASE")
                return False

        return _Acq()


@pytest.mark.asyncio
async def test_tenant_conn_sets_config_in_txn():
    from noble_agent.storage.postgres_client import tenant_conn
    conn = _FakeConn()
    pool = _FakePool(conn)
    async with tenant_conn(pool, "acme") as c:
        assert c is conn
        c.calls.append("DAO")
    assert conn.calls[0] == "BEGIN"
    assert conn.calls[1] == ("SELECT set_config('app.current_tenant', $1, true)", ("acme",))
    assert "DAO" in conn.calls
    assert conn.calls[-2:] == ["COMMIT", "RELEASE"]
