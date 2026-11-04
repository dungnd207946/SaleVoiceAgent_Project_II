"""Provisioning library — create/update/disable/list tenant bundles (slice #1).

Pure over an injected TenantStore. Validates before every write; never
executes tenant tool code.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from noble_agent.tenant import credentials
from noble_agent.tenant.identity import slugify
from noble_agent.tenant.store import Bundle, TenantMeta, TenantStore, VersionInfo, bundle_hash
from noble_agent.tenant.validation import validate_bundle


def _now(now: str | None) -> str:
    return now or datetime.now(UTC).isoformat()


def create_tenant(
    store: TenantStore,
    tenant_id: str,
    manifest_text: str,
    files: dict[str, str],
    *,
    status: str = "draft",
    now: str | None = None,
) -> TenantMeta:
    if store.read_meta(tenant_id) is not None:
        raise ValueError(f"tenant already exists: {tenant_id!r}")
    report = validate_bundle(tenant_id, manifest_text, files, existing_ids=store.list_ids())
    if not report.ok:
        raise ValueError("bundle invalid: " + "; ".join(report.errors))
    ts = _now(now)
    draft_meta = TenantMeta(tenant_id, status, 0, bundle_hash(manifest_text, files), created_at=ts, updated_at=ts)
    store.write_draft(tenant_id, Bundle(tenant_id, manifest_text, files, draft_meta))
    store.write_status(tenant_id, status)
    if status == "active":
        publish(store, tenant_id, now=now)
    return store.read_meta(tenant_id) or draft_meta


def provision_tenant(
    store: TenantStore,
    *,
    name: str,
    manifest_text: str,
    files: dict[str, str],
    status: str = "draft",
    now: str | None = None,
) -> tuple[str, TenantMeta]:
    """Mint a tenant id from the display name and create the bundle.

    The id is ``slugify(name)`` — deterministic, so a duplicate display name is
    rejected. The org prefix (and the `org_id` parameter) went away 2026-08-15;
    see `identity.py`. Returns (tenant_id, meta).

    ⚠ This is the CLI/store path, not the serving path. Tenant ids that matter are
    minted by the Portal (`workspace/service.sinh_tenant_id`), which appends
    ``_2``..``_50`` on collision instead of raising.
    """
    tenant_id = slugify(name)
    if store.read_meta(tenant_id) is not None:
        raise ValueError(
            f"a tenant named {name!r} already exists (tenant_id={tenant_id!r}); "
            f"choose a different name"
        )
    meta = create_tenant(store, tenant_id, manifest_text, files, status=status, now=now)
    return tenant_id, meta


# `list_orgs` XOÁ 2026-08-15 cùng khái niệm org.


def save_draft(
    store: TenantStore,
    tenant_id: str,
    *,
    manifest_text: str | None = None,
    files: dict[str, str] | None = None,
    now: str | None = None,
) -> None:
    """Write/replace the mutable ``<tenant>/draft/``. No validation (a draft may be broken)."""
    cur = store.read_draft(tenant_id) or store.read_bundle(tenant_id)
    if cur is None:
        raise ValueError(f"tenant not found: {tenant_id!r}")
    mtext = manifest_text if manifest_text is not None else cur.manifest_text
    fs = files if files is not None else cur.files
    store.write_draft(tenant_id, Bundle(tenant_id, mtext, fs, cur.meta))


def publish(store: TenantStore, tenant_id: str, *, created_by: str = "", now: str | None = None) -> VersionInfo:
    """Snapshot the draft into a new immutable version, then move the pointer (BR07).

    Runs the structural validator (E08) first; writes nothing on failure.
    """
    draft = store.read_draft(tenant_id)
    if draft is None:
        raise ValueError(f"no draft to publish for {tenant_id!r}")
    report = validate_bundle(tenant_id, draft.manifest_text, draft.files)
    if not report.ok:
        raise ValueError("bundle invalid: " + "; ".join(report.errors))
    ts = _now(now)
    versions = store.list_versions(tenant_id)
    n = (max(versions) + 1) if versions else 1
    bh = bundle_hash(draft.manifest_text, draft.files)
    info = VersionInfo(
        tenant_id, n, bh, created_at=ts, created_by=created_by, parent_version=(max(versions) if versions else None)
    )
    meta = TenantMeta(tenant_id, "active", n, bh, updated_at=ts, published_version=n, latest_version=n)
    # BR07: snapshot first ...
    store.write_version_bundle(tenant_id, n, Bundle(tenant_id, draft.manifest_text, draft.files, meta), info)
    # ... then the pointer.
    store.write_pointer(tenant_id, n)
    store.delete_draft(tenant_id)
    return info


def update_tenant(
    store: TenantStore,
    tenant_id: str,
    *,
    manifest_text: str | None = None,
    files: dict[str, str] | None = None,
    status: str | None = None,
    now: str | None = None,
) -> TenantMeta:
    """Write the tenant's DRAFT (no auto-publish, no pointer move) — BR04: publish is a separate step."""
    if store.read_bundle(tenant_id) is None and store.read_draft(tenant_id) is None:
        raise ValueError(f"tenant not found: {tenant_id!r}")
    save_draft(store, tenant_id, manifest_text=manifest_text, files=files, now=now)
    if status is not None:
        set_status(store, tenant_id, status, now=now)
    return store.read_meta(tenant_id)


def rollback(store: TenantStore, tenant_id: str, version: int, *, updated_by: str = "", now: str | None = None) -> int:
    """Move the pointer back to an existing version (BR06/YC06). Creates no new version."""
    if version not in store.list_versions(tenant_id):
        raise ValueError(f"no such version {version} for {tenant_id!r}")
    store.write_pointer(tenant_id, version)
    return version


def list_versions(store: TenantStore, tenant_id: str) -> list[int]:
    return store.list_versions(tenant_id)


def get_version(store: TenantStore, tenant_id: str, version: int) -> Bundle:
    b = store.read_version_bundle(tenant_id, version)
    if b is None:
        raise ValueError(f"no such version {version} for {tenant_id!r}")
    return b


def diff_versions(store: TenantStore, tenant_id: str, a: int, b: int) -> dict[str, list[str]]:
    """Path-level diff between two versions (or published↔draft via list_versions edges)."""
    ba = store.read_version_bundle(tenant_id, a) or get_tenant(store, tenant_id)
    bb = store.read_version_bundle(tenant_id, b) or store.read_draft(tenant_id)
    if bb is None:
        raise ValueError(f"no such version {b} for {tenant_id!r}")
    fa = {"manifest.toml": ba.manifest_text, **ba.files}
    fb = {"manifest.toml": bb.manifest_text, **bb.files}
    added = sorted(set(fb) - set(fa))
    removed = sorted(set(fa) - set(fb))
    changed = sorted(k for k in set(fa) & set(fb) if fa[k] != fb[k])
    return {"added": added, "removed": removed, "changed": changed}


def set_status(store: TenantStore, tenant_id: str, status: str, *, now: str | None = None) -> TenantMeta:
    if store.read_meta(tenant_id) is None:
        raise ValueError(f"tenant not found: {tenant_id!r}")
    store.write_status(tenant_id, status)
    meta = store.read_meta(tenant_id)
    assert meta is not None
    return meta


def disable_tenant(store: TenantStore, tenant_id: str, *, now: str | None = None) -> TenantMeta:
    return set_status(store, tenant_id, "disabled", now=now)


def list_tenants(store: TenantStore) -> list[TenantMeta]:
    """Mọi tenant trong store. Tham số `org_id` đã bỏ 2026-08-15."""
    out = []
    for i in store.list_ids():
        try:
            m = store.read_meta(i)
            if m is None:
                continue
        except ValueError:
            # A legacy/bad id whose read_meta raises: skip, don't crash.
            continue
        out.append(m)
    return out


def get_tenant(store: TenantStore, tenant_id: str) -> Bundle:
    b = store.read_bundle(tenant_id)
    if b is None:
        raise ValueError(f"tenant not found: {tenant_id!r}")
    return b


def _read_package_bundle(tenant_id: str) -> tuple[str, dict[str, str]]:
    from noble_agent.tenant.loader import _tenants_root

    root = _tenants_root() / tenant_id
    if not root.is_dir():
        raise ValueError(f"package tenant not found: {tenant_id!r}")
    manifest_text = (root / "manifest.toml").read_text(encoding="utf-8")
    files: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in ("manifest.toml", "_meta.json") or rel.endswith(".pyc") or "__pycache__" in rel:
            continue
        files[rel] = path.read_text(encoding="utf-8")
    return manifest_text, files


def import_from_package(
    store: TenantStore, tenant_id: str, *, status: str = "active", now: str | None = None
) -> TenantMeta:
    manifest_text, files = _read_package_bundle(tenant_id)
    return create_tenant(store, tenant_id, manifest_text, files, status=status, now=now)


def issue_credential(store: TenantStore, tenant_id: str, *, now: str | None = None) -> str:
    """Generate and persist a new API credential for a tenant.

    Returns the plaintext credential (returned once, never stored).
    Raises ValueError if the tenant does not exist.
    """
    if store.read_meta(tenant_id) is None:
        raise ValueError(f"tenant not found: {tenant_id!r}")
    entries = credentials.parse_creds(store.read_creds_raw(tenant_id) or "[]")
    plaintext, entry = credentials.generate_credential(now=_now(now))
    entries.append(entry)
    store.write_creds_raw(tenant_id, credentials.serialize_creds(entries))
    return plaintext


def revoke_credential(store: TenantStore, tenant_id: str, key_id: str, *, now: str | None = None) -> None:
    """Revoke a credential by key_id.

    Only revokes non-revoked entries. Idempotent: revoking a non-existent or
    already-revoked key is a no-op.
    """
    entries = credentials.parse_creds(store.read_creds_raw(tenant_id) or "[]")
    updated = [replace(e, revoked_at=_now(now)) if (e.key_id == key_id and not e.revoked_at) else e for e in entries]
    store.write_creds_raw(tenant_id, credentials.serialize_creds(updated))


def list_credentials(store: TenantStore, tenant_id: str) -> list[dict]:
    """List credentials for a tenant, returning only public metadata.

    Returns a list of dicts with keys: key_id, created_at, revoked_at.
    Never includes hash or salt.
    """
    entries = credentials.parse_creds(store.read_creds_raw(tenant_id) or "[]")
    return [{"key_id": e.key_id, "created_at": e.created_at, "revoked_at": e.revoked_at} for e in entries]


def endpoint_url(tenant_id: str, settings) -> dict:
    """Render endpoint URLs for a tenant (voice + chat).

    Uses settings.tenant_endpoint_template to build the base URL,
    then appends /v1/voice (voice) and /v1/chat (chat).
    """
    base = settings.tenant_endpoint_template.format(tenant_id=tenant_id).rstrip("/")
    return {"voice": f"{base}/v1/voice", "chat": f"{base}/v1/chat"}
