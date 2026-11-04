"""TenantContext — the per-deploy tenant config bundle.

Resolved once at boot from ``TENANT_ID`` → ``tenants/<id>/manifest.toml`` by
``tenant.loader``. Frozen; mirrors the ``get_settings()`` singleton pattern.
This phase only ``persona_dir`` + ``enabled_tools`` are consumed (by the
facade); ``data_source``/``brand``/``rankers``/``media_channel`` are declared
here as the manifest's source of truth, ready for later slices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    data_source: str                       # "pg_kb"
    persona_dir: Path                      # absolute dir holding SOUL/RULES/… + config.json
    enabled_tools: tuple[str, ...]         # offered-tool list (runtime source of truth)
    rankers: frozenset[str] = frozenset()  # e.g. {"feng_shui"} — consumed in a later slice
    media_channel: str = "none"            # "noblex_app" | "none" — consumed in a later slice
    brand: dict[str, str] = field(default_factory=dict)  # {"company":…, "app_name":…}
