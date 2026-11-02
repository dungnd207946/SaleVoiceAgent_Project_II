"""Version-pinned config resolver (SP-C2, read side).

Resolves the published config version for a tenant, materializes a version's
bundle to disk (atomic temp+rename, idempotent by ``bundle_hash``), verifies
the checksum (E04), and builds a per-version ``TenantContext``. The published
pointer read is TTL-cached (YC03) and falls back to the last-good version when
the store is unreachable (E01).
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from uuid import uuid4

from noble_agent.tenant.store import bundle_hash


class ChecksumError(Exception):
    """Materialized bundle content hash != stored version hash (E04)."""


_MARKER = ".bundle_hash"
_context_cache: dict[tuple[str, int], object] = {}
_ttl: dict[str, tuple[float, int]] = {}
_last_good: dict[str, int] = {}


def materialize_version(store, tenant_id, version, dest_root):
    """Write ``dest_root/<tenant>/versions/<n>/`` atomically; return the dir.

    Raises ``FileNotFoundError`` if the version is absent from the store and
    ``ChecksumError`` (E04) if the computed content hash != the stored hash.
    Idempotent: an already-materialized dir with a matching marker is reused.
    """
    bundle = store.read_version_bundle(tenant_id, version)
    if bundle is None:
        raise FileNotFoundError(f"version {version} not in store for {tenant_id!r}")
    computed = bundle_hash(bundle.manifest_text, bundle.files)
    if computed != bundle.meta.bundle_hash:
        raise ChecksumError(f"{tenant_id} v{version}: {computed} != {bundle.meta.bundle_hash}")
    dest = Path(dest_root) / tenant_id / "versions" / str(version)
    marker = dest / _MARKER
    if dest.is_dir() and marker.is_file() and marker.read_text().strip() == bundle.meta.bundle_hash:
        return dest
    tmp = Path(dest_root) / f".{tenant_id}.v{version}.{os.getpid()}.{uuid4().hex}.tmp"
    try:
        tmp.mkdir(parents=True)
        (tmp / "manifest.toml").write_text(bundle.manifest_text, encoding="utf-8")
        for rel, content in bundle.files.items():
            p = tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        (tmp / _MARKER).write_text(bundle.meta.bundle_hash, encoding="utf-8")
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    os.replace(tmp, dest)
    return dest


def context_for_version(store, settings, tenant_id, version):
    """Get-or-build the ``TenantContext`` for a version (cached by version)."""
    key = (tenant_id, version)
    if key in _context_cache:
        return _context_cache[key]
    from noble_agent.tenant.loader import _context_from_dir

    d = materialize_version(store, tenant_id, version, settings.tenant_materialize_dir)
    ctx = _context_from_dir(tenant_id, d, is_materialized=True)
    _context_cache[key] = ctx
    return ctx


def current_published_version(store, settings, tenant_id, *, clock=time.monotonic):
    """Resolve the tenant's published version (TTL-cached, E01 fallback).

    TTL cache (``settings.noble_config_poll_sec``) on the resolved int per
    tenant (YC03): a hit within the window is served without a store read. A
    ``None`` pointer with a present meta = legacy in-place v1; absent tenant →
    ``FileNotFoundError``. When the store raises, serve the last-good version if
    one was resolved this process (E01), else re-raise.
    """
    now = clock()
    hit = _ttl.get(tenant_id)
    if hit is not None and (now - hit[0]) < settings.noble_config_poll_sec:
        return hit[1]
    try:
        ptr = store.read_pointer(tenant_id)
        if ptr is None:
            if store.read_meta(tenant_id) is None:
                raise FileNotFoundError(f"tenant not in store: {tenant_id!r}")
            ptr = 1  # legacy in-place = v1
    except Exception:
        if tenant_id in _last_good:
            return _last_good[tenant_id]  # E01
        raise
    _ttl[tenant_id] = (now, ptr)
    _last_good[tenant_id] = ptr
    return ptr


def last_good_version(tenant_id):
    """Highest version resolved for the tenant this process, or ``None``.

    The E01 gate for callers that decide versioned-vs-legacy BEFORE reaching
    ``current_published_version``: on a store outage they can serve this instead
    of dropping to the package bundle. ``context_for_version(tenant, N)`` for a
    previously-built N is store-free (``_context_cache`` hit), so serving it
    survives the outage.
    """
    return _last_good.get(tenant_id)


def reset_for_tests():
    _context_cache.clear()
    _ttl.clear()
    _last_good.clear()
