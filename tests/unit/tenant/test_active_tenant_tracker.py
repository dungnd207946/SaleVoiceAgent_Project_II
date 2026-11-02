from noble_agent.tenant.pg_heartbeat import ActiveTenantTracker


def test_mark_and_active_within_ttl():
    t = [100.0]
    tr = ActiveTenantTracker(60, clock=lambda: t[0])
    tr.mark("a")
    tr.mark("b")
    assert set(tr.active()) == {"a", "b"}


def test_expires_after_ttl():
    t = [100.0]
    tr = ActiveTenantTracker(60, clock=lambda: t[0])
    tr.mark("a")
    t[0] = 161.0
    tr.mark("b")
    assert tr.active() == ["b"]
