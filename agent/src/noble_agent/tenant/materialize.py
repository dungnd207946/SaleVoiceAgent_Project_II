"""Materialize a store bundle → a local dir (SaaS slice #1).

Idempotent by ``bundle_hash`` (skips the download when the on-disk marker
matches) and atomic (writes to a temp dir, then renames into place) so a
partial sync never leaves a half-written bundle the loader would read.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

_MARKER = ".bundle_hash"


def materialize_tenant(store, tenant_id: str, dest_root) -> Path:
    meta = store.read_meta(tenant_id)
    if meta is None:
        raise FileNotFoundError(f"tenant not in store: {tenant_id!r}")

    dest_root = Path(dest_root)
    dest = dest_root / tenant_id
    marker = dest / _MARKER
    if dest.is_dir() and marker.is_file() and marker.read_text(encoding="utf-8").strip() == meta.bundle_hash:
        return dest  # already up to date

    tmp = dest_root / f".{tenant_id}.{os.getpid()}.{uuid4().hex}.tmp"
    try:
        bundle = store.read_bundle(tenant_id)
        if bundle is None:
            raise FileNotFoundError(f"tenant not in store: {tenant_id!r}")

        tmp.mkdir(parents=True)
        (tmp / "manifest.toml").write_text(bundle.manifest_text, encoding="utf-8")
        for rel, content in bundle.files.items():
            p = tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        (tmp / _MARKER).write_text(meta.bundle_hash, encoding="utf-8")
    except BaseException:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        raise

    if dest.exists():
        shutil.rmtree(dest)
    os.replace(tmp, dest)
    return dest
