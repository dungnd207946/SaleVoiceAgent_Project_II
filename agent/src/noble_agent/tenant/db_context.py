"""Dựng TenantContext từ published config (db-mode) — thay manifest.toml MinIO.

Cache per-tenant để provider-factory (_active_source) đọc data_source ở request-time
mà không cần MinIO. brand map từ config.identity.brand → {company, app_name}
(build_schemas/load_agent_def dùng shape này)."""
from __future__ import annotations

from pathlib import Path

from noble_agent.agent.agent_config import AgentConfig
from noble_agent.tenant.context import TenantContext

_db_ctx: dict[str, TenantContext] = {}


def context_from_config(tenant_id: str, cfg: AgentConfig, *, skeleton_dir: Path) -> TenantContext:
    brand = {"company": cfg.identity.brand, "app_name": cfg.identity.brand}
    rankers = frozenset({"feng_shui"}) if cfg.feng_shui else frozenset()
    return TenantContext(
        tenant_id=tenant_id,
        data_source=cfg.data_source or "pg_kb",
        persona_dir=skeleton_dir,
        enabled_tools=cfg.enabled_tools,
        rankers=rankers,
        media_channel=cfg.media_channel,
        brand=brand,
    )


def default_db_context(tenant_id: str, *, skeleton_dir: Path) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id, data_source="pg_kb", persona_dir=skeleton_dir, enabled_tools=()
    )


def set_db_context(tenant_id: str, ctx: TenantContext) -> None:
    _db_ctx[tenant_id] = ctx


def get_db_context(tenant_id: str) -> TenantContext | None:
    return _db_ctx.get(tenant_id)


def reset_db_context_for_tests() -> None:
    _db_ctx.clear()
