"""Tenant loader — TENANT_ID → tenants/<id>/manifest.toml → TenantContext.

Fails LOUD on a missing/broken manifest (never silently serves an empty
tenant). Process-singleton mirrors get_settings(). Provider selection is NOT
resolved here this phase (still driven by settings.noble_data_source)."""

from __future__ import annotations

import tomllib
from importlib import util as _importlib_util
from pathlib import Path

import noble_agent
from noble_agent.tenant.context import TenantContext

_ctx_by_tenant: dict[str, TenantContext] = {}


def _tenants_root() -> Path:
    """Directory holding all tenant bundles (inside the package)."""
    return Path(noble_agent.__file__).resolve().parent / "tenants"


def _build_store(settings):
    """Build the MinIO tenant store (LEGACY path only — agent_config_source != 'db').

    Retired from the serving path in the Postgres control-plane migration
    (2026-08-04); reachable only for legacy MinIO bundles. Deletion is a
    follow-up. See docs/superpowers/plans/2026-08-04-retire-minio-postgres-control-plane.md.
    """
    from noble_agent.tenant.store import MinioTenantStore

    return MinioTenantStore.from_settings(settings)


def _resolve_tenant_dir(tenant_id: str, settings) -> tuple[Path, bool]:
    """Return (bundle_dir, is_materialized). Store-first (active only), else
    the in-wheel package dir. Raises FileNotFoundError if neither exists."""
    from noble_agent.tenant.identity import is_valid_tenant_id

    # `is_valid_tenant_id` giờ chỉ kiểm HÌNH DẠNG id (không còn đòi tiền tố org,
    # xem `identity.py`), nên nhánh store mở cho mọi id hợp lệ — kể cả in-wheel
    # `noble`. Cổng thật vẫn là `tenant_store_enabled` (mặc định False) và
    # `read_meta` trả None cho tenant không có trong store, rồi rơi về dir in-wheel.
    if getattr(settings, "tenant_store_enabled", False) and is_valid_tenant_id(tenant_id):
        from noble_agent.tenant.materialize import materialize_tenant

        store = _build_store(settings)
        meta = store.read_meta(tenant_id)
        if meta is not None and meta.status == "active":
            d = materialize_tenant(store, tenant_id, settings.tenant_materialize_dir)
            return d, True
    pkg = _tenants_root() / tenant_id
    if not pkg.is_dir():
        raise FileNotFoundError(f"tenant dir not found: {pkg}")
    return pkg, False


def _import_tenant_tools_from_dir(tenant_id: str, tools_dir: Path) -> None:
    """Import each tools/*.py from a materialized bundle by file path so
    @tool-decorated executors self-register. No-op if the dir is absent."""
    if not tools_dir.is_dir():
        return
    for py in sorted(tools_dir.glob("*.py")):
        if py.name == "__init__.py":
            continue
        mod_name = f"noble_agent._tenant_tools.{tenant_id}.{py.stem}"
        spec = _importlib_util.spec_from_file_location(mod_name, py)
        if spec is None or spec.loader is None:
            continue
        module = _importlib_util.module_from_spec(spec)
        spec.loader.exec_module(module)


def _context_from_dir(tenant_id: str, tenant_dir: Path, *, is_materialized: bool) -> TenantContext:
    """Parse a bundle dir's manifest + import its tools → TenantContext.

    Fails LOUD on a missing/broken manifest or a missing required key. Used by
    both the boot-time loader (in-wheel/materialized) and the version resolver
    (per-version materialized dirs)."""
    manifest_path = tenant_dir / "manifest.toml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.toml not found for tenant {tenant_id!r}: {manifest_path}")
    try:
        data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"manifest.toml for tenant {tenant_id!r} is not valid TOML: {e}") from e

    data_source = data.get("data_source")
    persona_rel = data.get("persona_dir")
    tools = (data.get("tools") or {}).get("enabled")
    required = (("data_source", data_source), ("persona_dir", persona_rel), ("tools.enabled", tools))
    missing = [k for k, v in required if not v]
    if missing:
        raise ValueError(f"manifest.toml for tenant {tenant_id!r} missing required key(s): {', '.join(missing)}")

    brand = {str(k): str(v) for k, v in (data.get("brand") or {}).items()}
    if is_materialized:
        _import_tenant_tools_from_dir(tenant_id, tenant_dir / "tools")
    else:
        _import_tenant_tools(tenant_id)
    from noble_agent.agent.agent_config import resolve_tool_aliases

    return TenantContext(
        tenant_id=tenant_id,  # path/resolver is authoritative (minted ids aren't in the manifest)
        data_source=str(data_source),
        persona_dir=(tenant_dir / str(persona_rel)).resolve(),
        # Bundle cũ còn chở tên tool trước merge 2026-09-07 → map về tool hợp nhất.
        enabled_tools=resolve_tool_aliases(str(t) for t in tools),
        rankers=frozenset(str(r) for r in ((data.get("tools") or {}).get("rankers") or [])),
        media_channel=str((data.get("tools") or {}).get("media_channel") or "none"),
        brand=brand,
    )


def load_tenant(tenant_id: str, settings) -> TenantContext:
    tenant_dir, is_materialized = _resolve_tenant_dir(tenant_id, settings)
    return _context_from_dir(tenant_id, tenant_dir, is_materialized=is_materialized)


def _import_tenant_tools(tenant_id: str) -> None:
    """Import every submodule of ``noble_agent.tenants.<id>.tools`` so
    @tool-decorated custom tools self-register. A tenant with no ``tools/``
    package is a no-op; a broken import inside a present tools module
    propagates (fail loud)."""
    import importlib
    import pkgutil

    try:
        pkg = importlib.import_module(f"noble_agent.tenants.{tenant_id}.tools")
    except ModuleNotFoundError as e:
        # Only swallow "the tools package itself is absent"; a missing import
        # INSIDE a present tools package must surface.
        if e.name in (f"noble_agent.tenants.{tenant_id}.tools", f"noble_agent.tenants.{tenant_id}"):
            return
        raise
    for m in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"{pkg.__name__}.{m.name}")


def get_tenant_context() -> TenantContext:
    """The TenantContext for the CURRENT tenant (per-request), cached per tenant.

    Resolves the tenant via current_tenant() (contextvar → settings fallback),
    so a shared process serves each tenant its own frozen bundle. Cached per
    tenant id: bundles are immutable per boot, so one load each.

    db-mode (settings.agent_config_source == "db"): returns the cached
    db-context (set by the config-from-DB build path) or a safe pg_kb default
    — never touches the MinIO manifest path.
    """
    from noble_agent.config import get_settings
    from noble_agent.tenant.current import current_tenant

    tid = current_tenant()
    settings = get_settings()
    if getattr(settings, "agent_config_source", "legacy") == "db":
        from noble_agent.agent.facade import _skeleton_dir
        from noble_agent.tenant.db_context import default_db_context, get_db_context

        return get_db_context(tid) or default_db_context(tid, skeleton_dir=_skeleton_dir())

    ctx = _ctx_by_tenant.get(tid)
    if ctx is None:
        ctx = load_tenant(tid, settings)
        _ctx_by_tenant[tid] = ctx
    return ctx


def reset_tenant_context_for_tests() -> None:
    _ctx_by_tenant.clear()
