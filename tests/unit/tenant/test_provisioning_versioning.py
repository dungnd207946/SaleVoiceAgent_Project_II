import pytest

from noble_agent.tenant import provisioning as P
from noble_agent.tenant.store import FakeTenantStore

VALID_MANIFEST = 'tenant_id="tt"\ndata_source="nbx"\npersona_dir="persona"\n[tools]\nenabled=["escalate"]\n'
VALID_FILES = {
    "persona/SOUL.md": "x",
    "persona/RULES.md": "escalate",
    "persona/PROMPT_TEMPLATE.md": "x",
    "persona/CUSTOMER_PROFILE.md": "x",
    "persona/config.json": "{}",
}


def _seed(store):  # a tenant that already has v1 published
    P.create_tenant(store, "tt", VALID_MANIFEST, VALID_FILES, status="active")


def test_publish_creates_immutable_version_and_moves_pointer():
    s = FakeTenantStore()
    _seed(s)
    assert s.list_versions("tt") == [1] and s.read_pointer("tt") == 1
    P.save_draft(s, "tt", files={**VALID_FILES, "persona/SOUL.md": "v2-soul"})
    info = P.publish(s, "tt", created_by="alice")
    assert info.version == 2 and s.read_pointer("tt") == 2
    assert s.list_versions("tt") == [1, 2]
    assert s.read_version_bundle("tt", 1).files["persona/SOUL.md"] == "x"  # v1 untouched
    assert s.read_bundle("tt").files["persona/SOUL.md"] == "v2-soul"


def test_publish_rejects_invalid_draft_no_write():
    s = FakeTenantStore()
    _seed(s)
    P.save_draft(s, "tt", manifest_text='tenant_id="tt"\n')  # missing data_source/persona/tools
    with pytest.raises(ValueError):
        P.publish(s, "tt")
    assert s.read_pointer("tt") == 1 and s.list_versions("tt") == [1]  # unchanged


def test_publish_without_draft_raises():
    s = FakeTenantStore()
    _seed(s)
    with pytest.raises(ValueError):
        P.publish(s, "tt")


def test_rollback_moves_pointer_no_new_version():
    s = FakeTenantStore()
    _seed(s)
    P.save_draft(s, "tt", files={**VALID_FILES, "persona/SOUL.md": "v2"})
    P.publish(s, "tt")  # -> v2, pointer 2
    assert P.rollback(s, "tt", 1) == 1
    assert s.read_pointer("tt") == 1
    assert s.list_versions("tt") == [1, 2]  # NO v3 created
    assert s.read_bundle("tt").files["persona/SOUL.md"] == "x"


def test_rollback_unknown_version_raises():
    s = FakeTenantStore()
    _seed(s)
    with pytest.raises(ValueError):
        P.rollback(s, "tt", 99)


def test_diff_versions_paths():
    s = FakeTenantStore()
    _seed(s)
    P.save_draft(
        s,
        "tt",
        files={
            "persona/SOUL.md": "x",
            "persona/RULES.md": "escalate",
            "persona/PROMPT_TEMPLATE.md": "x",
            "persona/CUSTOMER_PROFILE.md": "x",
            "persona/config.json": "{}",
            "persona/NEW.md": "n",
        },
    )
    P.publish(s, "tt")
    d = P.diff_versions(s, "tt", 1, 2)
    assert "persona/NEW.md" in d["added"]


def test_create_active_publishes_v1():
    s = FakeTenantStore()
    P.create_tenant(s, "tt", VALID_MANIFEST, VALID_FILES, status="active")
    assert s.read_pointer("tt") == 1 and s.list_versions("tt") == [1]
    assert s.read_meta("tt").status == "active"


def test_create_draft_no_pointer():
    s = FakeTenantStore()
    P.create_tenant(s, "tt", VALID_MANIFEST, VALID_FILES, status="draft")
    assert s.read_pointer("tt") is None
    assert s.read_draft("tt") is not None


def test_update_writes_draft_not_published():
    s = FakeTenantStore()
    P.create_tenant(s, "tt", VALID_MANIFEST, VALID_FILES, status="active")
    P.update_tenant(s, "tt", files={**VALID_FILES, "persona/SOUL.md": "edited"})
    assert s.read_bundle("tt").files["persona/SOUL.md"] == "x"  # published unchanged
    assert s.read_draft("tt").files["persona/SOUL.md"] == "edited"  # draft has edit
