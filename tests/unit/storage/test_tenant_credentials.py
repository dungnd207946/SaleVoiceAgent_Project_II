"""Registry in-process credential PG per-tenant (worker nhận từ gateway)."""

from datetime import UTC, datetime, timedelta

from noble_agent.storage import tenant_credentials as tc


def setup_function():
    tc.clear_for_tests()


def _exp(sec=3600):
    return datetime.now(UTC) + timedelta(seconds=sec)


def test_register_and_get():
    tc.register("anphu", role="agent_anphu", password="pw", expires_at=_exp())
    got = tc.get("anphu")
    assert got is not None
    assert got.role == "agent_anphu" and got.password == "pw"


def test_get_unknown_tenant():
    assert tc.get("nope") is None


def test_expired_credential_dropped():
    tc.register("anphu", role="agent_anphu", password="pw", expires_at=_exp(-1))
    assert tc.get("anphu") is None
    assert tc.get("anphu") is None  # idempotent sau khi drop


def test_register_overwrites():
    tc.register("anphu", role="agent_anphu", password="old", expires_at=_exp())
    tc.register("anphu", role="agent_anphu", password="new", expires_at=_exp())
    assert tc.get("anphu").password == "new"


def test_credential_chi_mang_role_password_han():
    """`deployment_id`/`kind` đã bỏ khỏi `TenantPgCredential` (`0941`/`0919`).

    Hai bài cũ canh việc LƯU hai trường đó. Bài này canh chiều ngược lại — chúng không
    quay lại — vì người đọc duy nhất của `kind` là một phép so trong `pg_heartbeat.beat()`
    không bao giờ đúng, và nó giữ nhịp tim chết suốt `0919`→`0941`."""
    tc.register("anphu", role="agent_anphu", password="pw", expires_at=_exp())
    cred = tc.get("anphu")
    assert (cred.role, cred.password) == ("agent_anphu", "pw")
    assert not hasattr(cred, "deployment_id")
    assert not hasattr(cred, "kind")
