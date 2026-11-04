"""Public registry facade — delegates to the active DataProvider.

Kept as a stable module so orchestrator / runner / catalog / tool-schema
construction need no edits when the data source changes. All roster data now
comes from the provider chosen by ``NOBLE_DATA_SOURCE`` (the warm + bundled
fallback live inside the provider). See
docs/BA/spec_provider.md.

``set_cache_for_tests`` stays a local override so unit tests can inject a roster
without touching a provider; when set, the sync accessors return the injected
rows and never call the provider.
"""

from __future__ import annotations

import logging

from noble_agent.config import get_settings
from noble_agent.data import providers

logger = logging.getLogger("noble_agent.data.db_project_registry")

_test_rows: dict[str, dict] | None = None


def _provider():
    return providers.get_provider(get_settings())


async def warm() -> None:
    """Load the roster into the active provider's cache. Call once at startup."""
    await _provider().warm()


async def warm_if_stale(ttl_sec: float) -> None:
    """Re-warm the active provider only if its last warm was > ``ttl_sec`` ago."""
    await _provider().warm_if_stale(ttl_sec)


def cached_codes() -> list[str]:
    """Project codes from the active provider (or test override). Sync, no I/O."""
    if _test_rows is not None:
        return list(_test_rows)
    return _provider().cached_codes()


def code_to_name() -> dict[str, str]:
    """``{code: commercial name}`` from the active provider (or test override)."""
    if _test_rows is not None:
        return {c: v.get("name", "") for c, v in _test_rows.items()}
    return _provider().code_to_name()


def registry_rows() -> list[dict]:
    """``[{code, name, region, type}]`` — legacy dict shape. Consumed by
    ``orchestrator._build_project_index()`` to build the ``find_project``
    project-name index (``data/project_matching/index.py``). Converts the
    provider's ``ProjectRegistryRow`` DTOs to dicts. Sync, no I/O."""
    if _test_rows is not None:
        return [
            {
                "code": v.get("code", c),
                "name": v.get("name", ""),
                "region": v.get("region", ""),
                "type": v.get("type", ""),
            }
            for c, v in _test_rows.items()
        ]
    return [
        {"code": r.code, "name": r.name, "region": r.region, "type": r.type}
        for r in _provider().registry_rows()
    ]


def set_cache_for_tests(rows: dict[str, dict] | None) -> None:
    """Test hook: inject/clear a local roster override without hitting a provider."""
    global _test_rows
    _test_rows = dict(rows) if rows else None
