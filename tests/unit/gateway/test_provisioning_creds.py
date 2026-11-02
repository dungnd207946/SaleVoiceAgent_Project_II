"""Tests for provisioning credential API + endpoint_url."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from noble_agent.tenant import credentials as c
from noble_agent.tenant import provisioning as prov
from noble_agent.tenant.store import Bundle, FakeTenantStore, TenantMeta


def _seed(st, tid="t1"):
    """Seed a tenant into the store."""
    st.write_bundle(Bundle(tid, "tenant_id='t1'", {}, TenantMeta(tid, "active", 1, "sha256:x")))


def test_issue_then_verify_and_list():
    """Issue a credential, verify it works, list it without leaking hash/salt."""
    st = FakeTenantStore()
    _seed(st)
    plaintext = prov.issue_credential(st, "t1", now="t")
    entries = c.parse_creds(st.read_creds_raw("t1"))
    assert c.verify(plaintext, entries) is not None
    listed = prov.list_credentials(st, "t1")
    assert len(listed) == 1 and "hash" not in listed[0] and listed[0]["revoked_at"] == ""


def test_revoke_disables_verify():
    """Revoke a credential; verify no longer verifies."""
    st = FakeTenantStore()
    _seed(st)
    plaintext = prov.issue_credential(st, "t1", now="t")
    key_id = prov.list_credentials(st, "t1")[0]["key_id"]
    prov.revoke_credential(st, "t1", key_id, now="t2")
    assert c.verify(plaintext, c.parse_creds(st.read_creds_raw("t1"))) is None


def test_issue_unknown_tenant_raises():
    """Issue on a non-existent tenant raises ValueError."""
    with pytest.raises(ValueError):
        prov.issue_credential(FakeTenantStore(), "ghost", now="t")


def test_endpoint_url_renders_voice_and_chat():
    """endpoint_url renders voice and chat paths from the template."""
    s = SimpleNamespace(tenant_endpoint_template="wss://{tenant_id}.agents.noblex.vn")
    assert prov.endpoint_url("t1", s) == {
        "voice": "wss://t1.agents.noblex.vn/v1/voice",
        "chat": "wss://t1.agents.noblex.vn/v1/chat",
    }
