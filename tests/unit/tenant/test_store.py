import io
import json

import pytest

from noble_agent.config import UnifiedSettings
from noble_agent.tenant.store import Bundle, FakeTenantStore, MinioTenantStore, TenantMeta, bundle_hash


def test_tenant_store_settings_defaults():
    s = UnifiedSettings(_env_file=None)
    assert s.tenant_store_enabled is False
    assert s.tenant_bucket == "hotline-tenants"
    assert s.tenant_materialize_dir == "/var/lib/noble/tenants"
    assert s.minio_endpoint == ""
    assert s.minio_root_user == ""
    assert s.minio_root_password == ""


def _meta(h="sha256:x"):
    return TenantMeta(tenant_id="acme", status="active", version=1, bundle_hash=h)


_T1 = "acme_0001"
_T2 = "globex_0002"  # một tenant khác
_P1 = f"{_T1}"
_P2 = f"{_T2}"


def _meta_for(tid, h="sha256:x"):
    return TenantMeta(tenant_id=tid, status="active", version=1, bundle_hash=h)


def test_bundle_hash_is_deterministic_and_order_independent():
    a = bundle_hash("m=1", {"persona/SOUL.md": "s", "tools/x.py": "x"})
    b = bundle_hash("m=1", {"tools/x.py": "x", "persona/SOUL.md": "s"})
    assert a == b and a.startswith("sha256:")


def test_bundle_hash_changes_with_content():
    assert bundle_hash("m=1", {"a": "1"}) != bundle_hash("m=1", {"a": "2"})
    assert bundle_hash("m=1", {"a": "1"}) != bundle_hash("m=2", {"a": "1"})


def test_fake_store_roundtrip():
    store = FakeTenantStore()
    assert store.read_meta("acme") is None
    assert store.list_ids() == []
    b = Bundle("acme", "data_source='nbx'", {"persona/SOUL.md": "s"}, _meta())
    store.write_bundle(b)
    assert store.list_ids() == ["acme"]
    assert store.read_meta("acme").status == "active"
    got = store.read_bundle("acme")
    assert got.manifest_text == "data_source='nbx'"
    assert got.files == {"persona/SOUL.md": "s"}


class _FakeS3:
    """Minimal in-memory stand-in for the boto3 S3 client surface we use."""

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

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)


def test_minio_store_write_then_read(monkeypatch):
    s3 = _FakeS3()
    store = MinioTenantStore(s3, "hotline-tenants")
    b = Bundle(_T1, "data_source='nbx'", {"persona/SOUL.md": "s", "tools/loan.py": "x"}, _meta_for(_T1, "sha256:h1"))
    store.write_bundle(b)
    # _meta.json + manifest.toml + 2 files nằm dưới prefix `<tenant_id>/`.
    assert json.loads(s3.objects[f"{_P1}/_meta.json"])["bundle_hash"] == "sha256:h1"
    assert s3.objects[f"{_P1}/manifest.toml"] == b"data_source='nbx'"
    got = store.read_bundle(_T1)
    assert got.manifest_text == "data_source='nbx'"
    assert got.files == {"persona/SOUL.md": "s", "tools/loan.py": "x"}
    assert store.read_meta(_T1).bundle_hash == "sha256:h1"


def test_minio_store_list_ids():
    s3 = _FakeS3()
    store = MinioTenantStore(s3, "hotline-tenants")
    store.write_bundle(Bundle(_T1, "m", {}, _meta_for(_T1)))
    store.write_bundle(Bundle(_T2, "m", {}, _meta_for(_T2)))
    assert store.list_ids() == sorted([_T1, _T2])


def test_minio_store_read_missing_is_none():
    store = MinioTenantStore(_FakeS3(), "hotline-tenants")
    assert store.read_meta(_T1) is None
    assert store.read_bundle(_T1) is None


def test_fake_store_heartbeat_roundtrip():
    store = FakeTenantStore()
    assert store.read_heartbeat("acme") is None
    store.write_heartbeat("acme", {"tenant_id": "acme", "status_hint": "serving"})
    assert store.read_heartbeat("acme")["status_hint"] == "serving"


def test_minio_store_heartbeat_roundtrip():
    s3 = _FakeS3()
    store = MinioTenantStore(s3, "hotline-tenants")
    assert store.read_heartbeat(_T1) is None
    store.write_heartbeat(_T1, {"tenant_id": _T1, "running_version": 3})
    assert json.loads(s3.objects[f"{_P1}/_heartbeat.json"])["running_version"] == 3
    assert store.read_heartbeat(_T1)["running_version"] == 3


def test_minio_read_bundle_excludes_heartbeat():
    s3 = _FakeS3()
    store = MinioTenantStore(s3, "hotline-tenants")
    store.write_bundle(Bundle(_T1, "data_source='nbx'", {"persona/SOUL.md": "s"}, _meta_for(_T1, "sha256:h1")))
    store.write_heartbeat(_T1, {"status_hint": "serving"})  # sibling object at tenant root
    got = store.read_bundle(_T1)
    assert got.files == {"persona/SOUL.md": "s"}  # _heartbeat.json must NOT leak into the bundle


class _FakeS3Down(_FakeS3):
    """Backend that fails hard on read (not a missing-object error)."""

    def get_object(self, Bucket, Key):  # noqa: N803
        raise RuntimeError("minio down")


def test_minio_store_read_backend_error_propagates():
    store = MinioTenantStore(_FakeS3Down(), "hotline-tenants")
    with pytest.raises(RuntimeError, match="minio down"):
        store.read_meta(_T1)


def test_minio_keys_phang_theo_tenant():
    s3 = _FakeS3()
    store = MinioTenantStore(s3, "hotline-tenants")
    store.write_bundle(Bundle(_T1, "data_source='pg_kb'", {"persona/SOUL.md": "s"}, _meta_for(_T1)))
    assert "acme_0001/manifest.toml" in s3.objects
    assert "acme_0001/_meta.json" in s3.objects
    got = store.read_bundle(_T1)
    assert got.files == {"persona/SOUL.md": "s"}
    store.write_heartbeat(_T1, {"running_version": 3})
    assert "acme_0001/_heartbeat.json" in s3.objects
    assert store.read_heartbeat(_T1)["running_version"] == 3


def test_minio_list_ids_nhieu_tenant():
    s3 = _FakeS3()
    store = MinioTenantStore(s3, "hotline-tenants")
    store.write_bundle(Bundle(_T1, "m", {}, _meta_for(_T1)))
    store.write_bundle(Bundle(_T2, "m", {}, _meta_for(_T2)))
    assert store.list_ids() == sorted([_T1, _T2])


def test_minio_read_bundle_excludes_siblings_when_nested():
    s3 = _FakeS3()
    store = MinioTenantStore(s3, "hotline-tenants")
    store.write_bundle(Bundle(_T1, "m", {"persona/SOUL.md": "s"}, _meta_for(_T1)))
    store.write_heartbeat(_T1, {"status_hint": "serving"})
    store.write_creds_raw(_T1, "[]")
    assert store.read_bundle(_T1).files == {"persona/SOUL.md": "s"}


def test_list_ids_bo_qua_id_khong_hop_le():
    """`list_ids` lọc theo `is_valid_tenant_id`, không theo hình dạng org.

    Bản trước lọc "chỉ id org-format mới là tenant thật" và vì thế BỎ QUA một
    bundle phẳng như `noble/` — cái mà hôm nay là id hợp lệ. Sau 2026-08-15 bố
    cục chỉ còn một tầng, nên `noble` PHẢI hiện; thứ bị lọc là prefix không khớp
    `TENANT_RE` (chữ hoa, dấu, ký tự đầu là `-`/`_`).
    """
    s3 = _FakeS3()
    store = MinioTenantStore(s3, "hotline-tenants")
    s3.put_object(Bucket="hotline-tenants", Key="noble/manifest.toml", Body="m")
    s3.put_object(Bucket="hotline-tenants", Key="_rac/manifest.toml", Body="m")
    s3.put_object(Bucket="hotline-tenants", Key="HOA/manifest.toml", Body="m")
    store.write_bundle(Bundle("acme_0001", "m", {}, _meta_for("acme_0001")))
    assert store.list_ids() == ["acme_0001", "noble"]


# `test_migrate_legacy_layout_moves_bundle_under_org` XOÁ 2026-08-15: bố cục lồng
# theo org không còn, và `migrate_legacy_layout` đã gỡ khỏi store.
