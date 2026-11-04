import pytest

from noble_agent.tenant import pg_provisioning as PG


def test_role_name_accepts_valid_slug():
    assert PG.role_name("acme") == "acme"
    assert PG.role_name("noble-x_2") == "noble-x_2"


@pytest.mark.parametrize("bad", ["Acme", "1acme", "a b", "a'; DROP ROLE x;--", "", "a" * 64])
def test_role_name_rejects_unsafe(bad):
    with pytest.raises(ValueError):
        PG.role_name(bad)


def test_read_ddl_declares_tables_and_forced_rls():
    ddl = PG.read_ddl()
    assert "CREATE SCHEMA IF NOT EXISTS tenant_data" in ddl
    for t in ("conversations", "appointments", "contacts"):
        assert f"tenant_data.{t}" in ddl
    assert "FORCE ROW LEVEL SECURITY" in ddl
    # isolation must key on the connecting role, not a spoofable GUC
    assert "tenant_id = current_user" in ddl


def test_pw_literal_escapes_quotes():
    assert PG._pw_literal("a'b") == "'a''b'"
    with pytest.raises(ValueError):
        PG._pw_literal("")


def test_assert_app_role_distinct_rejects_collision():
    with pytest.raises(ValueError):
        PG.assert_app_role_distinct("acme", ["noble", "acme"])  # role == a tenant_id


def test_assert_app_role_distinct_ok():
    PG.assert_app_role_distinct("odyssey_agent", ["noble", "acme"])  # no raise


def test_app_role_name_validated_as_slug():
    with pytest.raises(ValueError):
        PG.assert_app_role_distinct("bad name!", [])
