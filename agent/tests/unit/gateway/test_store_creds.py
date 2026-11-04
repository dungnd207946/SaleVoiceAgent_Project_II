"""Test store credential I/O (read_creds_raw / write_creds_raw)."""

import io

from noble_agent.tenant.store import Bundle, FakeTenantStore, MinioTenantStore, TenantMeta


def test_fake_store_creds_roundtrip():
    """FakeTenantStore read/write creds JSON."""
    st = FakeTenantStore()
    assert st.read_creds_raw("t1") is None
    st.write_creds_raw("t1", '[{"key_id":"a"}]')
    assert st.read_creds_raw("t1") == '[{"key_id":"a"}]'
    # creds live outside the bundle listing (not a tenant of their own)
    assert "t1" not in st.list_ids()


class _FakeS3:
    """Minimal in-memory stand-in for the boto3 S3 client surface we use.

    Replicated from tests/unit/tenant/test_store.py so the creds exclusion is
    exercised through the real MinioTenantStore.read_bundle code path.
    """

    def __init__(self):
        self.objects: dict[str, bytes] = {}  # key -> body

    def put_object(self, Bucket, Key, Body):  # noqa: N803 (boto3 kwarg names)
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.encode("utf-8")

    def get_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, Bucket, Prefix="", Delimiter=None):  # noqa: N803
        if Delimiter:
            prefixes = set()
            for k in self.objects:
                if k.startswith(Prefix):
                    rest = k[len(Prefix) :]
                    if Delimiter in rest:
                        prefixes.add(Prefix + rest.split(Delimiter, 1)[0] + Delimiter)
            return {"CommonPrefixes": [{"Prefix": p} for p in sorted(prefixes)]}
        contents = [{"Key": k} for k in sorted(self.objects) if k.startswith(Prefix)]
        return {"Contents": contents}


_T1 = "org_a1b2c3d4_acme_0001"
_P1 = f"org_a1b2c3d4/{_T1}"


def _meta(h="sha256:x"):
    return TenantMeta(tenant_id=_T1, status="active", version=1, bundle_hash=h)


def test_minio_store_creds_roundtrip():
    """read_creds_raw / write_creds_raw roundtrip through MinioTenantStore."""
    store = MinioTenantStore(_FakeS3(), "hotline-tenants")
    assert store.read_creds_raw(_T1) is None
    store.write_creds_raw(_T1, '[{"key_id":"a"}]')
    assert store.read_creds_raw(_T1) == '[{"key_id":"a"}]'


def test_minio_read_bundle_excludes_creds():
    """_creds.json must NEVER leak into read_bundle's files dict (headline guarantee).

    Drives the real MinioTenantStore.read_bundle exclusion code path (the Fake's
    read_bundle just returns the stored Bundle, so it can't cover this).
    """
    s3 = _FakeS3()
    store = MinioTenantStore(s3, "hotline-tenants")
    store.write_bundle(Bundle(_T1, "data_source='nbx'", {"persona/SOUL.md": "s"}, _meta()))
    store.write_creds_raw(_T1, '[{"key_id":"a","secret":"shh"}]')
    # sanity: creds really are persisted under the org-nested prefix
    assert s3.objects[f"{_P1}/_creds.json"] == b'[{"key_id":"a","secret":"shh"}]'

    got = store.read_bundle(_T1)
    assert got is not None
    # the real file is present (so the exclusion assertion below is not vacuous) ...
    assert got.files == {"persona/SOUL.md": "s"}
    # ... and _creds.json never entered the files dict / bundle hash
    assert "_creds.json" not in got.files
