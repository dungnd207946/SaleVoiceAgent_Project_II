"""Tenant bundle models + store abstraction (SaaS slice #1).

A bundle = manifest.toml + persona/* + optional tools/*, stored under an
S3/MinIO prefix ``<tenant_id>/`` with a sibling ``_meta.json`` carrying
orchestration metadata (status/version/bundle_hash).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

_MANIFEST = "manifest.toml"
_META = "_meta.json"
_CREDS = "_creds.json"
_POINTER = "pointer.json"
_HEARTBEAT = "_heartbeat.json"
_VERSION = "version.json"
_VERSIONS_DIR = "versions"
_DRAFT_DIR = "draft"


def _is_missing(exc: Exception) -> bool:
    """True only for a genuine missing-object error (so every other backend
    failure — MinIO down, network, auth, throttling — re-raises instead of
    masquerading as "tenant not found")."""
    if isinstance(exc, KeyError):  # the in-memory test fake
        return True
    resp = getattr(exc, "response", None)  # boto3 ClientError, no eager import
    code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
    return code in ("NoSuchKey", "404")


@dataclass(frozen=True)
class TenantMeta:
    tenant_id: str
    status: str  # "active" | "draft" | "disabled"
    version: int
    bundle_hash: str
    created_at: str = ""
    updated_at: str = ""
    published_version: int = 0
    latest_version: int = 0


@dataclass(frozen=True)
class VersionInfo:
    tenant_id: str
    version: int
    bundle_hash: str
    created_at: str = ""
    created_by: str = ""
    parent_version: int | None = None
    field_policy: None = None  # reserved for SP-E field-column policy


@dataclass(frozen=True)
class Bundle:
    tenant_id: str
    manifest_text: str
    files: dict[str, str]  # rel path -> UTF-8 text; excludes manifest.toml & _meta.json
    meta: TenantMeta


def bundle_hash(manifest_text: str, files: dict[str, str]) -> str:
    """Deterministic content hash over manifest + files (path-sorted)."""
    h = hashlib.sha256()
    items = sorted([(_MANIFEST, manifest_text), *files.items()])
    for path, content in items:
        h.update(path.encode("utf-8"))
        h.update(b"\0")
        h.update(content.encode("utf-8"))
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


@runtime_checkable
class TenantStore(Protocol):
    def read_meta(self, tenant_id: str) -> TenantMeta | None: ...
    def list_ids(self) -> list[str]: ...
    def read_bundle(self, tenant_id: str) -> Bundle | None: ...
    def write_bundle(self, bundle: Bundle) -> None: ...
    def read_creds_raw(self, tenant_id: str) -> str | None: ...
    def write_creds_raw(self, tenant_id: str, raw: str) -> None: ...
    # -- heartbeat (SP-D) --
    def read_heartbeat(self, tenant_id: str) -> dict | None: ...
    def write_heartbeat(self, tenant_id: str, doc: dict) -> None: ...
    # -- versioned primitives (SP-C1) --
    def read_pointer(self, tenant_id: str) -> int | None: ...
    def write_pointer(self, tenant_id: str, version: int) -> None: ...
    def list_versions(self, tenant_id: str) -> list[int]: ...
    def read_version_bundle(self, tenant_id: str, version: int) -> Bundle | None: ...
    def write_version_bundle(self, tenant_id: str, version: int, bundle: Bundle, info: VersionInfo) -> None: ...
    def read_draft(self, tenant_id: str) -> Bundle | None: ...
    def write_draft(self, tenant_id: str, bundle: Bundle) -> None: ...
    def delete_draft(self, tenant_id: str) -> None: ...
    def write_status(self, tenant_id: str, status: str) -> None: ...


class FakeTenantStore:
    """In-memory TenantStore for tests."""

    def __init__(self) -> None:
        self._bundles: dict[str, Bundle] = {}  # legacy in-place
        self._versions: dict[str, dict[int, tuple[Bundle, VersionInfo]]] = {}
        self._pointers: dict[str, int] = {}
        self._drafts: dict[str, Bundle] = {}
        self._status: dict[str, str] = {}  # mutable orchestration status
        self._creds: dict[str, str] = {}
        self._heartbeats: dict[str, dict] = {}

    # -- heartbeat (SP-D) --------------------------------------------------
    def read_heartbeat(self, tenant_id: str) -> dict | None:
        return self._heartbeats.get(tenant_id)

    def write_heartbeat(self, tenant_id: str, doc: dict) -> None:
        self._heartbeats[tenant_id] = doc

    # -- versioned primitives ---------------------------------------------
    def read_pointer(self, tenant_id: str) -> int | None:
        return self._pointers.get(tenant_id)

    def write_pointer(self, tenant_id: str, version: int) -> None:
        self._pointers[tenant_id] = version

    def list_versions(self, tenant_id: str) -> list[int]:
        if tenant_id in self._versions:
            return sorted(self._versions[tenant_id])
        return [1] if tenant_id in self._bundles else []

    def read_version_bundle(self, tenant_id: str, version: int) -> Bundle | None:
        v = self._versions.get(tenant_id, {}).get(version)
        return v[0] if v else None

    def write_version_bundle(self, tenant_id: str, version: int, bundle: Bundle, info: VersionInfo) -> None:
        vs = self._versions.setdefault(tenant_id, {})
        if version in vs:
            raise ValueError(f"version {version} already exists for {tenant_id!r}")
        vs[version] = (bundle, info)

    def read_draft(self, tenant_id: str) -> Bundle | None:
        return self._drafts.get(tenant_id)

    def write_draft(self, tenant_id: str, bundle: Bundle) -> None:
        self._drafts[tenant_id] = bundle

    def delete_draft(self, tenant_id: str) -> None:
        self._drafts.pop(tenant_id, None)

    def write_status(self, tenant_id: str, status: str) -> None:
        self._status[tenant_id] = status

    # -- back-compat reads -------------------------------------------------
    def read_meta(self, tenant_id: str) -> TenantMeta | None:
        ptr = self._pointers.get(tenant_id)
        if ptr is not None:
            _, info = self._versions[tenant_id][ptr]
            latest = max(self._versions[tenant_id])
            status = self._status.get(tenant_id, "active")
            created = self._versions[tenant_id][min(self._versions[tenant_id])][1].created_at
            return TenantMeta(
                tenant_id,
                status,
                ptr,
                info.bundle_hash,
                created_at=created,
                updated_at=info.created_at,
                published_version=ptr,
                latest_version=latest,
            )
        draft = self._drafts.get(tenant_id)
        if draft is not None and tenant_id not in self._bundles:
            status = self._status.get(tenant_id, draft.meta.status)
            return TenantMeta(
                tenant_id,
                status,
                0,
                draft.meta.bundle_hash,
                created_at=draft.meta.created_at,
                updated_at=draft.meta.updated_at,
                published_version=0,
                latest_version=0,
            )
        b = self._bundles.get(tenant_id)
        if b is None:
            return None
        status = self._status.get(tenant_id, b.meta.status)
        return TenantMeta(
            tenant_id,
            status,
            1,
            b.meta.bundle_hash,
            created_at=b.meta.created_at,
            updated_at=b.meta.updated_at,
            published_version=1,
            latest_version=1,
        )

    def list_ids(self) -> list[str]:
        ids = set(self._bundles) | set(self._versions) | set(self._drafts)
        return sorted(ids)

    def read_bundle(self, tenant_id: str) -> Bundle | None:
        ptr = self._pointers.get(tenant_id)
        if ptr is not None:
            b = self.read_version_bundle(tenant_id, ptr)
            if b is None:
                raise ValueError(f"pointer→{ptr} but version missing for {tenant_id!r}")
            return b
        return self._bundles.get(tenant_id)

    def write_bundle(self, bundle: Bundle) -> None:
        self._bundles[bundle.tenant_id] = bundle

    def read_creds_raw(self, tenant_id: str) -> str | None:
        return self._creds.get(tenant_id)

    def write_creds_raw(self, tenant_id: str, raw: str) -> None:
        self._creds[tenant_id] = raw


class MinioTenantStore:
    """TenantStore backed by an S3/MinIO client (injected for tests)."""

    def __init__(self, client, bucket: str) -> None:
        self._c = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, settings) -> MinioTenantStore:
        import boto3  # lazy: keep test collection offline

        # `or None` chứ không truyền thẳng: botocore coi "" là một endpoint/credential
        # ĐÃ khai, không phải "chưa khai" — endpoint_url="" ném ValueError ngay lúc dựng
        # client, còn key rỗng thì ký request bằng Credentials("","") rồi ăn
        # InvalidAccessKeyId. None mới cho nó tự giải: endpoint AWS thật + credential
        # chain (instance role trên EC2). Nhờ vậy cùng một code chạy được MinIO ở dev
        # (khai đủ 3 biến) và S3 dùng chung với portal-backend ở deploy (bỏ trống cả 3).
        client = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint or None,
            aws_access_key_id=settings.minio_root_user or None,
            aws_secret_access_key=settings.minio_root_password or None,
        )
        return cls(client, settings.tenant_bucket)

    def _prefix(self, tenant_id: str) -> str:
        """Object-key prefix — just the tenant id.

        Was ``<org>/<tenant>`` until 2026-08-15, with the org parsed out of the id
        itself. That nesting only ever applied when `tenant_store_enabled` was on
        AND the id matched the org shape — which no real tenant id does, since the
        Portal mints plain ``slug(name)``. See `identity.py` for the full record.
        """
        return tenant_id

    # -- reads -------------------------------------------------------------
    def _get_text(self, key: str) -> str | None:
        try:
            resp = self._c.get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            if _is_missing(exc):
                return None
            raise  # fail loud: a real backend error must NOT read as "not found"
        return resp["Body"].read().decode("utf-8")

    def _read_version_info(self, tenant_id: str, version: int) -> dict | None:
        raw = self._get_text(f"{self._prefix(tenant_id)}/{_VERSIONS_DIR}/{version}/{_VERSION}")
        return json.loads(raw) if raw is not None else None

    def _meta_doc(self, tenant_id: str) -> dict:
        raw = self._get_text(f"{self._prefix(tenant_id)}/{_META}")
        return json.loads(raw) if raw is not None else {}

    def read_meta(self, tenant_id: str) -> TenantMeta | None:
        ptr = self.read_pointer(tenant_id)
        if ptr is not None:
            info = self._read_version_info(tenant_id, ptr)
            if info is None:
                raise ValueError(f"pointer→{ptr} but version missing for {tenant_id!r}")
            versions = self.list_versions(tenant_id)
            latest = max(versions) if versions else ptr
            created = ""
            first = self._read_version_info(tenant_id, min(versions)) if versions else None
            if first is not None:
                created = first.get("created_at", "")
            doc = self._meta_doc(tenant_id)
            return TenantMeta(
                tenant_id,
                doc.get("status", "active"),
                ptr,
                info["bundle_hash"],
                created_at=created,
                updated_at=info.get("created_at", ""),
                published_version=ptr,
                latest_version=latest,
            )
        # legacy in-place bundle (no pointer) reads as v1.
        legacy_manifest = self._get_text(f"{self._prefix(tenant_id)}/{_MANIFEST}")
        if legacy_manifest is not None:
            raw = self._get_text(f"{self._prefix(tenant_id)}/{_META}")
            if raw is None:
                return None
            d = json.loads(raw)
            return TenantMeta(
                tenant_id=d.get("tenant_id", tenant_id),
                status=d.get("status", "active"),
                version=1,
                bundle_hash=d["bundle_hash"],
                created_at=d.get("created_at", ""),
                updated_at=d.get("updated_at", ""),
                published_version=1,
                latest_version=1,
            )
        # draft-only tenant (created but not yet published).
        draft = self.read_draft(tenant_id)
        if draft is not None:
            doc = self._meta_doc(tenant_id)
            return TenantMeta(
                tenant_id,
                doc.get("status", "draft"),
                0,
                bundle_hash(draft.manifest_text, draft.files),
                published_version=0,
                latest_version=0,
            )
        return None

    def list_ids(self) -> list[str]:
        """Tenant ids = top-level prefixes.

        Trước 2026-08-15 hàm này duyệt HAI tầng (`<org>/<tenant>/`) vì bố cục lồng
        theo org. Bố cục đó đã bỏ cùng `_prefix()`; xem `identity.py`.
        """
        from noble_agent.tenant.identity import is_valid_tenant_id

        resp = self._c.list_objects_v2(Bucket=self._bucket, Prefix="", Delimiter="/")
        return sorted(
            tid
            for p in resp.get("CommonPrefixes", [])
            if is_valid_tenant_id(tid := p["Prefix"].rstrip("/"))
        )

    def read_bundle(self, tenant_id: str) -> Bundle | None:
        ptr = self.read_pointer(tenant_id)
        if ptr is not None:
            b = self.read_version_bundle(tenant_id, ptr)
            if b is None:
                raise ValueError(f"pointer→{ptr} but version missing for {tenant_id!r}")
            return b
        meta = self.read_meta(tenant_id)
        if meta is None:
            return None
        manifest = self._get_text(f"{self._prefix(tenant_id)}/{_MANIFEST}") or ""
        prefix = f"{self._prefix(tenant_id)}/"
        listing = self._c.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
        files: dict[str, str] = {}
        for obj in listing.get("Contents", []):
            key = obj["Key"]
            rel = key[len(prefix) :]
            if rel in (_META, _MANIFEST, _CREDS, _POINTER, _HEARTBEAT) or not rel:
                continue
            if rel.startswith(f"{_VERSIONS_DIR}/") or rel.startswith(f"{_DRAFT_DIR}/"):
                continue
            text = self._get_text(key)
            if text is not None:
                files[rel] = text
        return Bundle(tenant_id, manifest, files, meta)

    # -- versioned primitives (SP-C1) --------------------------------------
    def read_pointer(self, tenant_id: str) -> int | None:
        raw = self._get_text(f"{self._prefix(tenant_id)}/{_POINTER}")
        if raw is None:
            return None
        return int(json.loads(raw)["published_version"])

    def write_pointer(self, tenant_id: str, version: int) -> None:
        doc = {"published_version": int(version), "updated_at": "", "updated_by": ""}
        self._c.put_object(
            Bucket=self._bucket, Key=f"{self._prefix(tenant_id)}/{_POINTER}", Body=json.dumps(doc).encode("utf-8")
        )

    def list_versions(self, tenant_id: str) -> list[int]:
        prefix = f"{self._prefix(tenant_id)}/{_VERSIONS_DIR}/"
        resp = self._c.list_objects_v2(Bucket=self._bucket, Prefix=prefix, Delimiter="/")
        vers: list[int] = []
        for p in resp.get("CommonPrefixes", []):
            part = p["Prefix"][len(prefix) :].rstrip("/")
            if part.isdigit():
                vers.append(int(part))
        if vers:
            return sorted(vers)
        if self._get_text(f"{self._prefix(tenant_id)}/{_MANIFEST}") is not None:
            return [1]  # legacy in-place
        return []

    def read_version_bundle(self, tenant_id: str, version: int) -> Bundle | None:
        prefix = f"{self._prefix(tenant_id)}/{_VERSIONS_DIR}/{version}/"
        info = self._read_version_info(tenant_id, version)
        if info is None:
            return None
        manifest = self._get_text(prefix + _MANIFEST) or ""
        listing = self._c.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
        files: dict[str, str] = {}
        for obj in listing.get("Contents", []):
            key = obj["Key"]
            rel = key[len(prefix) :]
            if rel in (_MANIFEST, _VERSION) or not rel:
                continue
            text = self._get_text(key)
            if text is not None:
                files[rel] = text
        meta = TenantMeta(
            tenant_id,
            "active",
            version,
            info["bundle_hash"],
            created_at=info.get("created_at", ""),
            published_version=version,
            latest_version=version,
        )
        return Bundle(tenant_id, manifest, files, meta)

    def write_version_bundle(self, tenant_id: str, version: int, bundle: Bundle, info: VersionInfo) -> None:
        prefix = f"{self._prefix(tenant_id)}/{_VERSIONS_DIR}/{version}/"
        if self._get_text(prefix + _VERSION) is not None:
            raise ValueError(f"version {version} already exists for {tenant_id!r}")
        self._c.put_object(Bucket=self._bucket, Key=prefix + _MANIFEST, Body=bundle.manifest_text.encode("utf-8"))
        for rel, content in bundle.files.items():
            self._c.put_object(Bucket=self._bucket, Key=prefix + rel, Body=content.encode("utf-8"))
        version_doc = {
            "version": info.version,
            "bundle_hash": info.bundle_hash,
            "created_at": info.created_at,
            "created_by": info.created_by,
            "parent_version": info.parent_version,
            "field_policy": info.field_policy,
        }
        self._c.put_object(Bucket=self._bucket, Key=prefix + _VERSION, Body=json.dumps(version_doc).encode("utf-8"))

    def read_draft(self, tenant_id: str) -> Bundle | None:
        prefix = f"{self._prefix(tenant_id)}/{_DRAFT_DIR}/"
        manifest = self._get_text(prefix + _MANIFEST)
        if manifest is None:
            return None
        listing = self._c.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
        files: dict[str, str] = {}
        for obj in listing.get("Contents", []):
            key = obj["Key"]
            rel = key[len(prefix) :]
            if rel == _MANIFEST or not rel:
                continue
            text = self._get_text(key)
            if text is not None:
                files[rel] = text
        meta = TenantMeta(tenant_id, "draft", 0, bundle_hash(manifest, files))
        return Bundle(tenant_id, manifest, files, meta)

    def write_draft(self, tenant_id: str, bundle: Bundle) -> None:
        prefix = f"{self._prefix(tenant_id)}/{_DRAFT_DIR}/"
        # Clear any stale draft objects so a shrunk file set doesn't linger.
        stale = self._c.list_objects_v2(Bucket=self._bucket, Prefix=prefix).get("Contents", [])
        delete = getattr(self._c, "delete_object", None)
        if callable(delete):
            for obj in stale:
                delete(Bucket=self._bucket, Key=obj["Key"])
        self._c.put_object(Bucket=self._bucket, Key=prefix + _MANIFEST, Body=bundle.manifest_text.encode("utf-8"))
        for rel, content in bundle.files.items():
            self._c.put_object(Bucket=self._bucket, Key=prefix + rel, Body=content.encode("utf-8"))

    def delete_draft(self, tenant_id: str) -> None:
        prefix = f"{self._prefix(tenant_id)}/{_DRAFT_DIR}/"
        stale = self._c.list_objects_v2(Bucket=self._bucket, Prefix=prefix).get("Contents", [])
        delete = getattr(self._c, "delete_object", None)
        if callable(delete):
            for obj in stale:
                delete(Bucket=self._bucket, Key=obj["Key"])

    def write_status(self, tenant_id: str, status: str) -> None:
        doc = self._meta_doc(tenant_id)
        doc["status"] = status
        doc.setdefault("tenant_id", tenant_id)
        self._c.put_object(
            Bucket=self._bucket, Key=f"{self._prefix(tenant_id)}/{_META}", Body=json.dumps(doc).encode("utf-8")
        )

    # -- writes ------------------------------------------------------------
    def write_bundle(self, bundle: Bundle) -> None:
        base = f"{self._prefix(bundle.tenant_id)}/"
        self._c.put_object(Bucket=self._bucket, Key=base + _MANIFEST, Body=bundle.manifest_text.encode("utf-8"))
        for rel, content in bundle.files.items():
            self._c.put_object(Bucket=self._bucket, Key=base + rel, Body=content.encode("utf-8"))
        meta = bundle.meta
        meta_doc = {
            "tenant_id": meta.tenant_id,
            "status": meta.status,
            "version": meta.version,
            "bundle_hash": meta.bundle_hash,
            "created_at": meta.created_at,
            "updated_at": meta.updated_at,
        }
        self._c.put_object(Bucket=self._bucket, Key=base + _META, Body=json.dumps(meta_doc).encode("utf-8"))

    def read_creds_raw(self, tenant_id: str) -> str | None:
        return self._get_text(f"{self._prefix(tenant_id)}/{_CREDS}")

    def write_creds_raw(self, tenant_id: str, raw: str) -> None:
        self._c.put_object(Bucket=self._bucket, Key=f"{self._prefix(tenant_id)}/{_CREDS}", Body=raw.encode("utf-8"))

    # -- heartbeat (SP-D) --------------------------------------------------
    def read_heartbeat(self, tenant_id: str) -> dict | None:
        raw = self._get_text(f"{self._prefix(tenant_id)}/{_HEARTBEAT}")
        return json.loads(raw) if raw is not None else None

    def write_heartbeat(self, tenant_id: str, doc: dict) -> None:
        self._c.put_object(
            Bucket=self._bucket, Key=f"{self._prefix(tenant_id)}/{_HEARTBEAT}", Body=json.dumps(doc).encode("utf-8")
        )

    # `_legacy_top_prefixes` + `migrate_legacy_layout` XOÁ 2026-08-15: chúng di
    # chuyển bundle phẳng sang bố cục lồng theo org, mà bố cục đó không còn.

