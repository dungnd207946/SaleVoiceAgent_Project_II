import pytest

from noble_agent.tenant import provisioning as prov
from noble_agent.tenant.store import FakeTenantStore

_MANIFEST = """\
tenant_id = "acme"
data_source = "nbx"
persona_dir = "persona"
[tools]
enabled = ["kb_search"]
"""
_PERSONA = {
    "persona/config.json": '{"name":"Ava","model":"m","temperature":0.3,"max_tokens":800}',
    "persona/SOUL.md": "soul",
    "persona/RULES.md": "rules",
    "persona/PROMPT_TEMPLATE.md": "tmpl",
    "persona/CUSTOMER_PROFILE.md": "cust",
}
_NOW = "2026-07-29T00:00:00+00:00"


def test_create_then_get():
    store = FakeTenantStore()
    meta = prov.create_tenant(store, "acme", _MANIFEST, dict(_PERSONA), status="active", now=_NOW)
    assert meta.version == 1 and meta.status == "active"
    assert meta.created_at == _NOW
    b = prov.get_tenant(store, "acme")
    assert b.files["persona/SOUL.md"] == "soul"


def test_create_duplicate_raises():
    store = FakeTenantStore()
    prov.create_tenant(store, "acme", _MANIFEST, dict(_PERSONA), now=_NOW)
    with pytest.raises(ValueError):
        prov.create_tenant(store, "acme", _MANIFEST, dict(_PERSONA), now=_NOW)


def test_create_invalid_bundle_raises():
    store = FakeTenantStore()
    bad = {k: v for k, v in _PERSONA.items() if k != "persona/RULES.md"}
    with pytest.raises(ValueError):
        prov.create_tenant(store, "acme", _MANIFEST, bad, now=_NOW)


def test_update_writes_draft_then_publish_bumps_version_and_hash():
    # New SP-C1 contract: update_tenant writes the DRAFT only (BR04 — publish is a
    # separate step). Publishing the draft is what mints a new immutable version.
    store = FakeTenantStore()
    m1 = prov.create_tenant(store, "acme", _MANIFEST, dict(_PERSONA), status="active", now=_NOW)
    files2 = {**_PERSONA, "persona/SOUL.md": "soul-v2"}
    prov.update_tenant(store, "acme", files=files2, now="2026-07-30T00:00:00+00:00")
    # Published version is unchanged; the edit lives only in the draft.
    assert prov.get_tenant(store, "acme").files["persona/SOUL.md"] == "soul"
    assert store.read_draft("acme").files["persona/SOUL.md"] == "soul-v2"
    # Publishing the draft bumps the version + hash.
    prov.publish(store, "acme")
    m2 = store.read_meta("acme")
    assert m2.version == 2
    assert m2.bundle_hash != m1.bundle_hash
    assert m2.created_at == _NOW  # preserved from v1
    assert prov.get_tenant(store, "acme").files["persona/SOUL.md"] == "soul-v2"


def test_disable_and_list():
    store = FakeTenantStore()
    prov.create_tenant(store, "acme", _MANIFEST, dict(_PERSONA), status="active", now=_NOW)
    prov.disable_tenant(store, "acme", now=_NOW)
    metas = prov.list_tenants(store)
    assert len(metas) == 1 and metas[0].status == "disabled"


def test_import_from_package_seeds_noble():
    store = FakeTenantStore()
    meta = prov.import_from_package(store, "noble", now=_NOW)
    assert meta.status == "active"
    b = prov.get_tenant(store, "noble")
    assert "persona/SOUL.md" in b.files
    assert "manifest" in b.manifest_text or "tenant_id" in b.manifest_text
