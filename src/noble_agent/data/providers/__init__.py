"""Data-provider factory. Selects the source per-tenant (tenant manifest's
``data_source``, falling back to ``settings.noble_data_source``).

Lazy-imports the concrete provider so importing this package never pulls asyncpg
or httpx unless the chosen provider needs it. One instance per (tenant, source)
is cached (providers hold a warmed registry cache scoped to a tenant, so a
per-tenant singleton is correct — sharing one instance across tenants would
leak one tenant's warmed roster into another's)."""

from __future__ import annotations

from noble_agent.data.providers.base import ESCALATE_SIGNAL, DataProvider

__all__ = ["get_provider", "ESCALATE_SIGNAL", "DataProvider"]

_INSTANCES: dict[tuple[str, str], DataProvider] = {}


def _active_source(settings) -> str:
    """Data source for the CURRENT tenant: the tenant manifest's data_source
    (per-tenant, memo §5b), falling back to settings.noble_data_source."""
    try:
        from noble_agent.tenant.loader import get_tenant_context

        src = get_tenant_context().data_source
    except Exception:
        src = ""
    return (src or getattr(settings, "noble_data_source", "") or "pg_kb").strip()


def get_provider(settings) -> DataProvider:
    from noble_agent.tenant.current import current_tenant

    tenant_id = current_tenant()
    source = _active_source(settings)
    key = (tenant_id, source)
    cached = _INSTANCES.get(key)
    if cached is not None:
        return cached
    if source == "pg_kb":
        from noble_agent.data.providers.postgres_kb import PostgresKBProvider

        provider: DataProvider = PostgresKBProvider()
    else:
        raise ValueError(f"Unknown data source: {source!r} (pg_kb)")
    _INSTANCES[key] = provider
    return provider


def reset_for_tests() -> None:
    _INSTANCES.clear()
