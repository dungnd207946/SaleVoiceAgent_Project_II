import pytest

from noble_agent.tenant import provisioning as P
from noble_agent.tenant.materialize import materialize_tenant
from noble_agent.tenant.store import Bundle, FakeTenantStore, TenantMeta, bundle_hash

_VERSIONED_MANIFEST = 'tenant_id="acme"\ndata_source="nbx"\npersona_dir="persona"\n[tools]\nenabled=["escalate"]\n'
_VERSIONED_FILES = {
    "persona/SOUL.md": "v1",
    "persona/RULES.md": "escalate",
    "persona/PROMPT_TEMPLATE.md": "x",
    "persona/CUSTOMER_PROFILE.md": "x",
    "persona/config.json": "{}",
}


def _bundle(tid="acme", soul="soul"):
    files = {"persona/SOUL.md": soul, "tools/loan.py": "x"}
    manifest = "data_source='nbx'"
    h = bundle_hash(manifest, files)
    meta = TenantMeta(tid, "active", 1, h)
    return Bundle(tid, manifest, files, meta)


def test_materialize_writes_tree(tmp_path):
    store = FakeTenantStore()
    store.write_bundle(_bundle())
    dest = materialize_tenant(store, "acme", tmp_path)
    assert dest == tmp_path / "acme"
    assert (dest / "manifest.toml").read_text() == "data_source='nbx'"
    assert (dest / "persona" / "SOUL.md").read_text() == "soul"
    assert (dest / "tools" / "loan.py").read_text() == "x"
    assert (dest / ".bundle_hash").read_text().strip().startswith("sha256:")


def test_materialize_is_idempotent_and_skips_rewrite(tmp_path, monkeypatch):
    store = FakeTenantStore()
    store.write_bundle(_bundle())
    materialize_tenant(store, "acme", tmp_path)

    # Second call must NOT re-read the bundle (hash marker matches).
    def _boom(_):
        raise AssertionError("read_bundle should not be called when hash matches")

    monkeypatch.setattr(store, "read_bundle", _boom)
    dest = materialize_tenant(store, "acme", tmp_path)
    assert (dest / "persona" / "SOUL.md").read_text() == "soul"


def test_materialize_refreshes_on_hash_change(tmp_path):
    store = FakeTenantStore()
    store.write_bundle(_bundle(soul="v1"))
    materialize_tenant(store, "acme", tmp_path)
    store.write_bundle(_bundle(soul="v2"))  # new hash
    dest = materialize_tenant(store, "acme", tmp_path)
    assert (dest / "persona" / "SOUL.md").read_text() == "v2"


def test_materialize_missing_tenant_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        materialize_tenant(FakeTenantStore(), "ghost", tmp_path)


def test_materialize_failure_on_first_materialize_leaves_no_dest(tmp_path, monkeypatch):
    store = FakeTenantStore()
    store.write_bundle(_bundle())

    def _boom(_):
        raise RuntimeError("simulated mid-materialize failure")

    monkeypatch.setattr(store, "read_bundle", _boom)
    with pytest.raises(RuntimeError):
        materialize_tenant(store, "acme", tmp_path)

    assert not (tmp_path / "acme").exists()
    assert list(tmp_path.glob(".acme.*.tmp")) == []


def test_materialize_failure_on_refresh_leaves_dest_and_tmp_untouched(tmp_path, monkeypatch):
    store = FakeTenantStore()
    store.write_bundle(_bundle(soul="v1"))
    materialize_tenant(store, "acme", tmp_path)
    original = (tmp_path / "acme" / "persona" / "SOUL.md").read_text()

    store.write_bundle(_bundle(soul="v2"))  # new hash on the store, not yet materialized

    def _boom(_):
        raise RuntimeError("simulated mid-materialize failure")

    monkeypatch.setattr(store, "read_bundle", _boom)
    with pytest.raises(RuntimeError):
        materialize_tenant(store, "acme", tmp_path)

    # The original good tree must never be left half-written or half-swapped.
    assert (tmp_path / "acme" / "persona" / "SOUL.md").read_text() == original
    assert list(tmp_path.glob(".acme.*.tmp")) == []


def test_materialize_writes_published_version_and_follows_pointer(tmp_path):
    # Back-compat: materialize (which uses the unchanged read_bundle/read_meta
    # signatures) must resolve the pointed version on a versioned store.
    store = FakeTenantStore()
    P.create_tenant(store, "acme", _VERSIONED_MANIFEST, dict(_VERSIONED_FILES), status="active")
    P.save_draft(store, "acme", files={**_VERSIONED_FILES, "persona/SOUL.md": "v2"})
    P.publish(store, "acme")  # -> published v2

    dest = materialize_tenant(store, "acme", tmp_path)
    assert (dest / "persona" / "SOUL.md").read_text() == "v2"

    # Rollback moves the pointer; materialize must now reflect v1 (hash changed).
    P.rollback(store, "acme", 1)
    dest = materialize_tenant(store, "acme", tmp_path)
    assert (dest / "persona" / "SOUL.md").read_text() == "v1"
