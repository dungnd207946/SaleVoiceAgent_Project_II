from types import SimpleNamespace

import pytest

from noble_agent.agent.tools import registry as reg
from noble_agent.tenant import loader
from noble_agent.tenant import provisioning as prov
from noble_agent.tenant.store import FakeTenantStore

# Store tenants are org-formatted (plan D7); a non-org id like "noble" never
# lives in the store and is served from the in-wheel package instead.
_TID = "org_a1b2c3d4_acme_0001"
_MANIFEST = """\
tenant_id = "org_a1b2c3d4_acme_0001"
data_source = "nbx"
persona_dir = "persona"
[tools]
enabled = ["kb_search", "check_loan"]
"""
_CONFIG = '{"name":"Ava","model":"m","temperature":0.3,"max_tokens":800}'
_TOOL = '''\
from noble_agent.agent.tools.registry import tool

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "check_loan",
        "description": "d",
        "parameters": {"type": "object", "properties": {}},
    },
}


@tool(name="check_loan", schema=_SCHEMA, tenant="org_a1b2c3d4_acme_0001")
async def check_loan(args, *, provider, tenant, **_):
    return "ok"
'''


def _seed(store):
    files = {
        "persona/config.json": _CONFIG,
        "persona/SOUL.md": "soul",
        "persona/RULES.md": "rules",
        "persona/PROMPT_TEMPLATE.md": "tmpl",
        "persona/CUSTOMER_PROFILE.md": "cust",
        "tools/loan.py": _TOOL,
    }
    prov.create_tenant(store, _TID, _MANIFEST, files, status="active", now="2026-07-29T00:00:00+00:00")


@pytest.fixture(autouse=True)
def _clean():
    reg.clear_tenant_for_tests(_TID)
    yield
    reg.clear_tenant_for_tests(_TID)


def test_store_disabled_falls_back_to_package(tmp_path):
    s = SimpleNamespace(tenant_store_enabled=False)
    d, is_mat = loader._resolve_tenant_dir("noble", s)
    assert is_mat is False
    assert d.name == "noble"


def test_store_active_tenant_materializes(tmp_path, monkeypatch):
    store = FakeTenantStore()
    _seed(store)
    monkeypatch.setattr(loader, "_build_store", lambda settings: store)
    s = SimpleNamespace(tenant_store_enabled=True, tenant_materialize_dir=str(tmp_path))
    d, is_mat = loader._resolve_tenant_dir(_TID, s)
    assert is_mat is True
    assert (d / "persona" / "SOUL.md").read_text() == "soul"


def test_load_tenant_from_store_end_to_end(tmp_path, monkeypatch):
    store = FakeTenantStore()
    _seed(store)
    monkeypatch.setattr(loader, "_build_store", lambda settings: store)
    s = SimpleNamespace(
        tenant_store_enabled=True, tenant_materialize_dir=str(tmp_path),
    )
    ctx = loader.load_tenant(_TID, s)
    assert ctx.tenant_id == _TID
    assert ctx.data_source == "nbx"
    assert ctx.persona_dir.is_absolute()
    assert "check_loan" in ctx.enabled_tools
    # The materialized custom tool self-registered under the tenant.
    assert reg.resolve(_TID, "check_loan") is not None
    assert reg.resolve("noble", "check_loan") is None


def test_draft_tenant_not_served_falls_back(tmp_path, monkeypatch):
    store = FakeTenantStore()
    prov.import_from_package(store, "noble", status="draft", now="2026-07-29T00:00:00+00:00")
    monkeypatch.setattr(loader, "_build_store", lambda settings: store)
    s = SimpleNamespace(tenant_store_enabled=True, tenant_materialize_dir=str(tmp_path))
    d, is_mat = loader._resolve_tenant_dir("noble", s)
    assert is_mat is False  # draft is not served → package fallback


def test_store_enabled_absent_tenant_and_no_package_raises(tmp_path, monkeypatch):
    """Store ENABLED, tenant absent from the store (read_meta -> None), AND no
    in-wheel package dir for it -> fail loud, never silently serve nothing."""
    store = FakeTenantStore()
    monkeypatch.setattr(loader, "_build_store", lambda settings: store)
    s = SimpleNamespace(tenant_store_enabled=True, tenant_materialize_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        loader._resolve_tenant_dir("ghost_tenant", s)
