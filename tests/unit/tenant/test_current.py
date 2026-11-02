# tests/unit/tenant/test_current.py
import asyncio

from noble_agent.config import reset_settings_for_tests
from noble_agent.tenant.current import (
    current_agent_key_id,
    current_tenant,
    reset_current_agent_key_id,
    reset_current_tenant,
    set_current_agent_key_id,
    set_current_tenant,
    use_tenant,
)


def test_unset_falls_back_to_settings_tenant_id(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()
    assert current_tenant() == "noble"


def test_set_overrides_settings(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()
    tok = set_current_tenant("acme")
    try:
        assert current_tenant() == "acme"
    finally:
        reset_current_tenant(tok)
    assert current_tenant() == "noble"


def test_use_tenant_scopes_and_restores(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()
    with use_tenant("acme"):
        assert current_tenant() == "acme"
    assert current_tenant() == "noble"


def test_empty_string_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()
    with use_tenant(""):
        assert current_tenant() == "noble"


def test_agent_key_id_unset_is_empty():
    assert current_agent_key_id() == ""


def test_agent_key_id_set_and_reset():
    tok = set_current_agent_key_id("ak_9")
    try:
        assert current_agent_key_id() == "ak_9"
    finally:
        reset_current_agent_key_id(tok)
    assert current_agent_key_id() == ""


async def test_agent_key_id_flows_into_created_task():
    """fire_and_forget dùng create_task — context phải chảy xuống task con."""

    async def read():
        return current_agent_key_id()

    tok = set_current_agent_key_id("ak_9")
    try:
        assert await asyncio.create_task(read()) == "ak_9"
    finally:
        reset_current_agent_key_id(tok)


# Hai test `test_current_org_*` XOÁ 2026-08-15: hàm suy "org của tenant hiện tại"
# đã gỡ khỏi `tenant/current.py` cùng khái niệm org (xem `identity.py`).
