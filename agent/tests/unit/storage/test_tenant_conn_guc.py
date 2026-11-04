from noble_agent.storage.postgres_client import tenant_conn


class _FakeConn:
    def __init__(self): self.calls = []
    def transaction(self):
        conn = self
        class _Txn:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False
        return _Txn()
    async def execute(self, sql, *args): self.calls.append((sql, args))


class _FakePool:
    def __init__(self, conn): self._conn = conn
    def acquire(self):
        conn = self._conn
        class _Acq:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False
        return _Acq()


async def test_tenant_conn_sets_both_gucs():
    conn = _FakeConn()
    async with tenant_conn(_FakePool(conn), "t1") as c:
        assert c is conn
    guc_calls = [args[0] for sql, args in conn.calls if "set_config" in sql]
    keys = [sql.split("'")[1] for sql, _ in conn.calls if "set_config" in sql]
    assert set(keys) == {"app.current_tenant", "app.tenant_id"}
    assert all(a == "t1" for a in guc_calls)
