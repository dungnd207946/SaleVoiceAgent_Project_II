"""Tenant id format — validate + slugify. Pure, no I/O.

⚠ THE ORG PREFIX IS GONE (2026-08-15).

This module used to mint and parse ids shaped ``org_<rand8>_<slug>``, with
``org_of()`` recovering the org by prefix parse. That scheme was never on the
serving path:

  · Real tenant ids are minted by the **Portal** (`workspace/service.sinh_tenant_id`)
    as ``slug(name)`` plus a ``_2``..``_50`` suffix on collision — no org prefix.
    The Portal's own docstring records that the original spec §7 was wrong to
    assume otherwise.
  · `loader.get_tenant_context` only consulted the store when
    `is_valid_tenant_id()` matched the org shape, so real ids (`noble`,
    `bao-ngoc`) skipped that branch entirely.
  · `tenant_store_enabled` defaults to False, and the retire-MinIO plan states
    "MinIO store + CLI keep the code, only leave the serving path".

The organization layer itself was removed from the Portal control-plane in
migrations 0105/0106. See
`odyssey-portal-backend/docs/superpowers/specs/2026-08-15-bo-organization-design.md` §7.

`TENANT_RE` now matches what the Portal actually produces.
"""

from __future__ import annotations

import re

TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
"""Same shape as `control.tenants.id` (`tenants_id_check`, migration 0002 +
0911 which widened it to allow hyphens). First character must be `[a-z0-9]` —
0911 explicitly did NOT relax the leading position."""


def is_valid_tenant_id(s: str) -> bool:
    return bool(TENANT_RE.match(s or ""))


def slugify(name: str) -> str:
    """Fold a display name to ``[a-z0-9-]`` (spaces/punct → single '-'); never empty."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    s = s[:40].rstrip("-")
    return s or "t"
