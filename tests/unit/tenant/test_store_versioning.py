import pytest

from noble_agent.tenant.store import Bundle, FakeTenantStore, TenantMeta, VersionInfo, bundle_hash


def _bundle(tid, body="v"):
    files = {"persona/SOUL.md": body}
    mtext = f'tenant_id="{tid}"\n'
    meta = TenantMeta(tid, "active", 1, bundle_hash(mtext, files))
    return Bundle(tid, mtext, files, meta)


def test_version_info_frozen_defaults():
    vi = VersionInfo(tenant_id="t", version=3, bundle_hash="sha256:x")
    assert (vi.version, vi.parent_version, vi.field_policy) == (3, None, None)
    import dataclasses

    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        vi.version = 4  # type: ignore[misc]


def test_tenant_meta_has_version_fields():
    m = TenantMeta("t", "active", version=2, bundle_hash="sha256:x", published_version=2, latest_version=2)
    assert (m.published_version, m.latest_version, m.version) == (2, 2, 2)


def test_write_read_version_and_pointer():
    s = FakeTenantStore()
    b1 = _bundle("t", "one")
    s.write_version_bundle("t", 1, b1, VersionInfo("t", 1, b1.meta.bundle_hash))
    s.write_pointer("t", 1)
    assert s.list_versions("t") == [1]
    assert s.read_pointer("t") == 1
    assert s.read_version_bundle("t", 1).files["persona/SOUL.md"] == "one"


def test_read_bundle_returns_pointed_version_not_draft():
    s = FakeTenantStore()
    b1 = _bundle("t", "published")
    s.write_version_bundle("t", 1, b1, VersionInfo("t", 1, b1.meta.bundle_hash))
    s.write_pointer("t", 1)
    s.write_draft("t", _bundle("t", "draft-wip"))
    assert s.read_bundle("t").files["persona/SOUL.md"] == "published"
    assert s.read_draft("t").files["persona/SOUL.md"] == "draft-wip"


def test_write_version_twice_raises_immutable():
    s = FakeTenantStore()
    b1 = _bundle("t")
    s.write_version_bundle("t", 1, b1, VersionInfo("t", 1, b1.meta.bundle_hash))
    with pytest.raises(Exception):
        s.write_version_bundle("t", 1, b1, VersionInfo("t", 1, b1.meta.bundle_hash))


def test_legacy_in_place_reads_as_v1():
    s = FakeTenantStore()
    s.write_bundle(_bundle("t", "legacy"))  # old in-place path, no pointer
    assert s.read_pointer("t") is None
    assert s.list_versions("t") == [1]
    assert s.read_bundle("t").files["persona/SOUL.md"] == "legacy"
    assert s.read_meta("t").published_version == 1


class _S3:
    def __init__(self):
        self.objs = {}

    def put_object(self, Bucket, Key, Body):  # noqa: N803
        self.objs[(Bucket, Key)] = Body if isinstance(Body, bytes) else Body.encode("utf-8")

    def get_object(self, Bucket, Key):  # noqa: N803
        if (Bucket, Key) not in self.objs:
            raise KeyError(Key)
        import io

        return {"Body": io.BytesIO(self.objs[(Bucket, Key)])}

    def list_objects_v2(self, Bucket, Prefix="", Delimiter=None):  # noqa: N803
        keys = [k for (b, k) in self.objs if b == Bucket and k.startswith(Prefix)]
        if Delimiter:
            pres = sorted({Prefix + k[len(Prefix):].split("/")[0] + "/" for k in keys})
            return {"CommonPrefixes": [{"Prefix": p} for p in pres]}
        return {"Contents": [{"Key": k} for k in keys]}


def test_minio_version_pointer_roundtrip():
    from noble_agent.tenant.store import MinioTenantStore

    tid = "org_c0ffee12_t_0001"
    s = MinioTenantStore(_S3(), "buck")
    b1 = _bundle(tid, "one")
    s.write_version_bundle(tid, 1, b1, VersionInfo(tid, 1, b1.meta.bundle_hash, created_at="ts"))
    s.write_pointer(tid, 1)
    assert s.read_pointer(tid) == 1
    assert s.list_versions(tid) == [1]
    assert s.read_version_bundle(tid, 1).files["persona/SOUL.md"] == "one"
    assert s.read_bundle(tid).files["persona/SOUL.md"] == "one"
