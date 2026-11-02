"""Read the tenant's agent config from Postgres (flat table
`tenant_data.agent_config`, one row per tenant), with a last-good on-disk
fallback (E01). See docs/handoff/agent-config-bang-phang.md.

`PublishedConfig.config` is the flat row (column name → value) consumed by
`agent.agent_config.parse_config`; `departments`/`skills` jsonb columns are
decoded to Python lists here."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("noble_agent.storage.agent_config")

# The table is NOT RLS-scoped (no portal.current_tenant() predicate), so the
# tenant filter MUST be explicit in the WHERE clause.
_COLUMNS = (
    "name", "brand_name", "self_pronoun", "customer_pronoun", "greeting",
    "scope_does", "scope_does_not", "refusal_line", "departments",
    "tone", "reply_length", "skills", "tts_normalization", "version",
)
_SQL = f"SELECT {', '.join(_COLUMNS)} FROM tenant_data.agent_config WHERE tenant_id = $1"
_JSON_COLUMNS = ("departments", "skills")
# Separate set on purpose: _JSON_COLUMNS decodes with `or []`, and `{}` is falsy in
# Python — an empty dictionary passed through `or []` would come out as a list.
_JSON_OBJECT_COLUMNS = ("tts_normalization",)
_CACHE_DIR = Path("/var/lib/noble/agent_config_cache")


@dataclass(frozen=True)
class PublishedConfig:
    version: int
    config: dict


def _decode(value):
    """asyncpg returns jsonb as a str by default — decode to list/dict."""
    if isinstance(value, (str, bytes)):
        return json.loads(value)
    return value


async def _read_from_db(tenant_id: str, *, pool=None) -> PublishedConfig | None:
    from noble_agent.storage.postgres_client import pool_for_tenant, tenant_conn

    pool = pool or await pool_for_tenant(tenant_id)
    async with tenant_conn(pool, tenant_id) as conn:
        row = await conn.fetchrow(_SQL, tenant_id)
    if row is None:
        return None
    config = dict(row)
    for col in _JSON_COLUMNS:
        config[col] = _decode(config.get(col)) or []
    for col in _JSON_OBJECT_COLUMNS:
        config[col] = _decode(config.get(col)) or {}
    version = int(config.pop("version"))
    return PublishedConfig(version=version, config=config)


def _cache_file(tenant_id: str) -> Path:
    return _CACHE_DIR / f"{tenant_id}.json"


def _write_last_good(tenant_id: str, pc: PublishedConfig) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_file(tenant_id).write_text(
            json.dumps({"version": pc.version, "config": pc.config}, ensure_ascii=False), "utf-8"
        )
    except Exception:
        logger.warning("agent_config: last-good write failed for %s", tenant_id, exc_info=True)


def _read_last_good(tenant_id: str) -> PublishedConfig | None:
    try:
        raw = json.loads(_cache_file(tenant_id).read_text("utf-8"))
        return PublishedConfig(version=int(raw["version"]), config=dict(raw["config"]))
    except Exception:
        return None


async def read_published_config(tenant_id: str, *, pool=None) -> PublishedConfig | None:
    try:
        pc = await _read_from_db(tenant_id, pool=pool)
    except Exception:
        logger.warning("agent_config: DB read failed for %s — serving last-good", tenant_id, exc_info=True)
        return _read_last_good(tenant_id)
    if pc is not None:
        _write_last_good(tenant_id, pc)
    return pc
