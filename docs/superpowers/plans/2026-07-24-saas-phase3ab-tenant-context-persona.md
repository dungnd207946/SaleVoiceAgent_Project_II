# SaaS Phase 3a+3b — TenantContext + Persona Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a per-tenant config bundle — a `TenantContext` resolved at boot from `TENANT_ID` → `tenants/<id>/manifest.toml` — and migrate Noble's persona (`agent/definitions/*`) into `tenants/noble/persona/`, with the manifest as the runtime source of truth for the offered-tool list. **Behaviour is identical for `TENANT_ID=noble` (the only tenant).**

**Architecture:** `TenantContext` (frozen) mirrors the existing `get_settings()` singleton pattern via `get_tenant_context()`. The loader reads `TENANT_ID` (a new setting, default `noble`), parses `tenants/<id>/manifest.toml` (stdlib `tomllib`), and builds the context. The **only runtime consumer this phase** is the facade's `_build_runner`, which reads `ctx.persona_dir` + `ctx.enabled_tools`. Provider selection **stays on `settings.noble_data_source`** (unchanged) — routing the provider through the context is a later slice, so every `NOBLE_DATA_SOURCE=…` test keeps passing. `data_source`/`brand`/`rankers`/`media_channel` are declared in the manifest and exposed on the context but **not yet consumed** (they are the source of truth ready for slices 3c/3d).

**Tech Stack:** Python 3.11–3.13 (stdlib `tomllib`), frozen dataclasses, pydantic-settings, pytest (`asyncio_mode=auto`), ruff (line-length 120).

## Global Constraints

- **Branch:** `feat/refactor2` only. **Never** touch `develop`; no `git push`/`gh pr create`/`worktree add`/`merge`/`rebase --onto` without explicit user instruction. Local commits on `feat/refactor2` are fine. Use `git mv` for the persona move (preserve history).
- **Behaviour-identical for `TENANT_ID=noble`.** The offered tools, system prompt, provider, and every tool output must match today's behaviour. This is a structural refactor, not a behaviour change.
- **Provider selection is UNCHANGED this phase.** `get_provider(settings)` keeps reading `settings.noble_data_source`. Do NOT route the provider through `TenantContext` yet (that breaks the `NOBLE_DATA_SOURCE=…` tests and is a later slice). The manifest's `data_source` value must EQUAL the current default (`nbx`); a test asserts this so the two can't silently diverge before the later cutover.
- **One source of truth for the tool list at runtime = `manifest.enabled`.** Remove `"tools"` from the persona `config.json`; `load_agent_def` no longer reads it. `config.json` keeps only `name`/`model`/`temperature`/`max_tokens`.
- **Directory:** the tenant bundle lives INSIDE the package at `src/noble_agent/tenants/<id>/` (ships in the wheel exactly like `agent/definitions/` does today). This is a deliberate, documented deviation from the spec's top-level `tenants/` diagram — chosen so the files ship with the package and are importable when Phase 3c adds custom tools. Read by filesystem path this phase (no import).
- **Loader fails LOUD** on: unknown/missing tenant dir, missing/unparseable `manifest.toml`, missing required key (`data_source`, `persona_dir`, `[tools].enabled`). It does NOT check that `persona_dir` exists (that is enforced naturally by `load_agent_def` when it reads the files).
- **No import cycle.** `tenant/context.py` imports only DTO types. `tenant/loader.py` is imported lazily where needed. `providers/__init__` is NOT changed this phase.
- Commit message final line, verbatim:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Reply to the user in Vietnamese.

---

## File Structure

- `src/noble_agent/config.py` — **modify**: add `tenant_id: str = "noble"` setting.
- `src/noble_agent/tenant/__init__.py` — **create**: empty package marker.
- `src/noble_agent/tenant/context.py` — **create**: `TenantContext` frozen dataclass.
- `src/noble_agent/tenant/loader.py` — **create**: `load_tenant(tenant_id, settings)`, `get_tenant_context()` singleton, `reset_tenant_context_for_tests()`.
- `src/noble_agent/tenants/noble/manifest.toml` — **create**: Noble's tenant manifest.
- `src/noble_agent/tenants/noble/persona/{SOUL.md,RULES.md,PROMPT_TEMPLATE.md,CUSTOMER_PROFILE.md,config.json}` — **git-mv** from `src/noble_agent/agent/definitions/*` (config.json edited to drop `"tools"`).
- `src/noble_agent/agent/base.py` — **modify**: `load_agent_def(persona_dir, *, tool_names, agent_name=None)` — `tool_names` required; stop reading `config["tools"]`.
- `src/noble_agent/agent/facade.py` — **modify**: `_build_runner` resolves `ctx = get_tenant_context()`, uses `ctx.persona_dir` + `list(ctx.enabled_tools)`.
- `tests/unit/unified/_persona.py` — **create**: shared `PERSONA_DIR` + `NOBLE_TOOLS` for tests.
- Test call-site updates (path + `tool_names`): `tests/unit/unified/{test_suggestions,test_cache_warm,test_conversation_persist,test_prompt_builder,test_facade,test_agent_def,test_runner}.py`, `tests/unit/{test_streaming_no_repeat_after_tool,test_interrupt}.py`, `tests/integration/unified/conftest.py`.
- `tests/unit/tenant/{test_context.py,test_loader.py}` — **create**.

---

## Task 1: `tenant_id` setting + `TenantContext` dataclass

**Files:**
- Modify: `src/noble_agent/config.py`
- Create: `src/noble_agent/tenant/__init__.py` (empty)
- Create: `src/noble_agent/tenant/context.py`
- Test: `tests/unit/tenant/test_context.py`

**Interfaces:**
- Produces:
  - `settings.tenant_id: str` (default `"noble"`).
  - `tenant.context.TenantContext(tenant_id: str, data_source: str, persona_dir: Path, enabled_tools: tuple[str, ...], rankers: frozenset[str], media_channel: str, brand: dict[str, str])` — frozen.

- [ ] **Step 1: Write the failing test** — create `tests/unit/tenant/__init__.py` (empty) and `tests/unit/tenant/test_context.py`:

```python
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from noble_agent.tenant.context import TenantContext


def test_tenant_context_fields_and_frozen():
    ctx = TenantContext(
        tenant_id="noble",
        data_source="nbx",
        persona_dir=Path("/x/persona"),
        enabled_tools=("find_project", "booking"),
        rankers=frozenset({"feng_shui"}),
        media_channel="noblex_app",
        brand={"company": "Noble", "app_name": "NobleX"},
    )
    assert ctx.tenant_id == "noble"
    assert ctx.enabled_tools == ("find_project", "booking")
    assert "feng_shui" in ctx.rankers
    assert ctx.brand["app_name"] == "NobleX"
    with pytest.raises(FrozenInstanceError):
        ctx.tenant_id = "other"  # type: ignore[misc]


def test_tenant_id_setting_default():
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings(_env_file=None)
    assert s.tenant_id == "noble"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tenant/test_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.tenant'`.

- [ ] **Step 3: Create the package + dataclass** — `src/noble_agent/tenant/__init__.py` (empty file), then `src/noble_agent/tenant/context.py`:

```python
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
    data_source: str                       # "nbx" | "mongo" | "sales_api"
    persona_dir: Path                      # absolute dir holding SOUL/RULES/… + config.json
    enabled_tools: tuple[str, ...]         # offered-tool list (runtime source of truth)
    rankers: frozenset[str] = frozenset()  # e.g. {"feng_shui"} — consumed in a later slice
    media_channel: str = "none"            # "noblex_app" | "none" — consumed in a later slice
    brand: dict[str, str] = field(default_factory=dict)  # {"company":…, "app_name":…}
```

- [ ] **Step 4: Add the `tenant_id` setting** — in `src/noble_agent/config.py`, add a field near the other top-level settings (e.g. next to `agent_name`). Search for `agent_name` to find the block; add:

```python
    tenant_id: str = "noble"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/tenant/test_context.py -v`
Expected: PASS (2).

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/config.py src/noble_agent/tenant/__init__.py src/noble_agent/tenant/context.py tests/unit/tenant/__init__.py tests/unit/tenant/test_context.py
git commit -m "feat(tenant): TenantContext dataclass + TENANT_ID setting

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Noble `manifest.toml` + loader + `get_tenant_context()`

**Files:**
- Create: `src/noble_agent/tenants/noble/manifest.toml`
- Create: `src/noble_agent/tenant/loader.py`
- Test: `tests/unit/tenant/test_loader.py`

**Interfaces:**
- Consumes: `TenantContext` (Task 1), `settings.tenant_id`.
- Produces:
  - `loader.load_tenant(tenant_id: str, settings) -> TenantContext` — resolves `<pkg>/tenants/<tenant_id>/manifest.toml`, parses, validates, builds the context. Fails loud (`ValueError`/`FileNotFoundError`) on missing dir, missing/bad manifest, or missing required key.
  - `loader.get_tenant_context() -> TenantContext` — process singleton, built from `get_settings().tenant_id` on first call.
  - `loader.reset_tenant_context_for_tests() -> None`.

Note: the tenant dir is `Path(noble_agent.__file__).parent / "tenants" / tenant_id`; `persona_dir` = `tenant_dir / manifest["persona_dir"]` (absolute, existence NOT checked here).

- [ ] **Step 1: Write the failing test** — create `tests/unit/tenant/test_loader.py`:

```python
from pathlib import Path

import pytest

from noble_agent.config import get_settings
from noble_agent.tenant import loader


def test_load_noble_manifest_matches_current_defaults():
    ctx = loader.load_tenant("noble", get_settings())
    assert ctx.tenant_id == "noble"
    # Provider selection is unchanged this phase; the manifest MUST mirror the
    # current default so the two don't silently diverge before the cutover.
    assert ctx.data_source == "nbx"
    assert ctx.persona_dir.name == "persona"
    assert ctx.persona_dir.is_absolute()
    assert set(ctx.enabled_tools) == {
        "find_project", "update_customer", "noble_search", "discover_projects",
        "get_project_overview", "get_project_financial", "search_units",
        "recommend_units", "booking", "escalate", "send_media", "check_inventory",
    }
    assert ctx.rankers == frozenset({"feng_shui"})
    assert ctx.media_channel == "noblex_app"
    assert ctx.brand == {"company": "Noble", "app_name": "NobleX"}


def test_unknown_tenant_fails_loud():
    with pytest.raises((FileNotFoundError, ValueError)):
        loader.load_tenant("does_not_exist", get_settings())


def test_missing_required_key_fails_loud(tmp_path, monkeypatch):
    # A fixture tenant dir with a manifest missing [tools].enabled.
    tdir = tmp_path / "tenants" / "broken"
    tdir.mkdir(parents=True)
    (tdir / "manifest.toml").write_text('data_source = "nbx"\npersona_dir = "persona"\n', encoding="utf-8")
    monkeypatch.setattr(loader, "_tenants_root", lambda: tmp_path / "tenants")
    with pytest.raises(ValueError):
        loader.load_tenant("broken", get_settings())


def test_get_tenant_context_is_singleton():
    loader.reset_tenant_context_for_tests()
    a = loader.get_tenant_context()
    b = loader.get_tenant_context()
    assert a is b
    loader.reset_tenant_context_for_tests()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/tenant/test_loader.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: module 'noble_agent.tenant.loader' has no attribute 'load_tenant'`.

- [ ] **Step 3a: Create the manifest** — `src/noble_agent/tenants/noble/manifest.toml`:

```toml
# Noble tenant manifest — the per-deploy config bundle (TENANT_ID=noble).
tenant_id = "noble"
# Provider selection is still driven by NOBLE_DATA_SOURCE this phase; this MUST
# mirror the current default. The provider-through-context cutover is a later slice.
data_source = "nbx"
persona_dir = "persona"

[tools]
enabled = [
    "find_project",
    "update_customer",
    "noble_search",
    "discover_projects",
    "get_project_overview",
    "get_project_financial",
    "search_units",
    "recommend_units",
    "booking",
    "escalate",
    "send_media",
    "check_inventory",
]
rankers = ["feng_shui"]
media_channel = "noblex_app"

[brand]
company = "Noble"
app_name = "NobleX"
```

- [ ] **Step 3b: Create the loader** — `src/noble_agent/tenant/loader.py`:

```python
"""Tenant loader — TENANT_ID → tenants/<id>/manifest.toml → TenantContext.

Fails LOUD on a missing/broken manifest (never silently serves an empty
tenant). Process-singleton mirrors get_settings(). Provider selection is NOT
resolved here this phase (still driven by settings.noble_data_source)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import noble_agent
from noble_agent.tenant.context import TenantContext

_ctx_singleton: TenantContext | None = None


def _tenants_root() -> Path:
    """Directory holding all tenant bundles (inside the package)."""
    return Path(noble_agent.__file__).resolve().parent / "tenants"


def load_tenant(tenant_id: str, settings) -> TenantContext:
    tenant_dir = _tenants_root() / tenant_id
    if not tenant_dir.is_dir():
        raise FileNotFoundError(f"tenant dir not found: {tenant_dir}")
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
    missing = [k for k, v in (("data_source", data_source), ("persona_dir", persona_rel), ("tools.enabled", tools)) if not v]
    if missing:
        raise ValueError(f"manifest.toml for tenant {tenant_id!r} missing required key(s): {', '.join(missing)}")

    brand = {str(k): str(v) for k, v in (data.get("brand") or {}).items()}
    return TenantContext(
        tenant_id=data.get("tenant_id", tenant_id),
        data_source=str(data_source),
        persona_dir=(tenant_dir / str(persona_rel)).resolve(),
        enabled_tools=tuple(str(t) for t in tools),
        rankers=frozenset(str(r) for r in ((data.get("tools") or {}).get("rankers") or [])),
        media_channel=str((data.get("tools") or {}).get("media_channel") or "none"),
        brand=brand,
    )


def get_tenant_context() -> TenantContext:
    global _ctx_singleton
    if _ctx_singleton is None:
        from noble_agent.config import get_settings

        settings = get_settings()
        _ctx_singleton = load_tenant(settings.tenant_id, settings)
    return _ctx_singleton


def reset_tenant_context_for_tests() -> None:
    global _ctx_singleton
    _ctx_singleton = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/tenant/test_loader.py -v`
Expected: PASS (4).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/tenants/noble/manifest.toml src/noble_agent/tenant/loader.py tests/unit/tenant/test_loader.py
git commit -m "feat(tenant): manifest.toml + loader + get_tenant_context singleton

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Migrate persona to `tenants/noble/persona/` + wire facade to context

**Files:**
- git-mv: `src/noble_agent/agent/definitions/{SOUL.md,RULES.md,PROMPT_TEMPLATE.md,CUSTOMER_PROFILE.md,config.json}` → `src/noble_agent/tenants/noble/persona/`
- Modify: `src/noble_agent/tenants/noble/persona/config.json` (drop `"tools"`)
- Modify: `src/noble_agent/agent/base.py` (`load_agent_def` signature)
- Modify: `src/noble_agent/agent/facade.py` (`_build_runner` uses context)
- Create: `tests/unit/unified/_persona.py`
- Modify: 10 test call sites (listed below)

**Interfaces:**
- Consumes: `get_tenant_context()` (Task 2).
- Produces: `load_agent_def(persona_dir: Path | str, *, tool_names: list[str], agent_name: str | None = None) -> AgentDef` — `tool_names` is now REQUIRED and is the sole tool source (no `config["tools"]`).

- [ ] **Step 1: Move the persona files (preserve history)**

```bash
mkdir -p src/noble_agent/tenants/noble/persona
git mv src/noble_agent/agent/definitions/SOUL.md src/noble_agent/tenants/noble/persona/SOUL.md
git mv src/noble_agent/agent/definitions/RULES.md src/noble_agent/tenants/noble/persona/RULES.md
git mv src/noble_agent/agent/definitions/PROMPT_TEMPLATE.md src/noble_agent/tenants/noble/persona/PROMPT_TEMPLATE.md
git mv src/noble_agent/agent/definitions/CUSTOMER_PROFILE.md src/noble_agent/tenants/noble/persona/CUSTOMER_PROFILE.md
git mv src/noble_agent/agent/definitions/config.json src/noble_agent/tenants/noble/persona/config.json
rmdir src/noble_agent/agent/definitions 2>/dev/null || true
```

- [ ] **Step 2: Drop `"tools"` from the persona config.json**

Edit `src/noble_agent/tenants/noble/persona/config.json` to:

```json
{
  "name": "Luna",
  "model": "gemini-2.5-flash",
  "temperature": 0.7,
  "max_tokens": 800
}
```

- [ ] **Step 3: Update `load_agent_def` signature** — in `src/noble_agent/agent/base.py`:

Change the signature and drop the `config["tools"]` read. Replace:

```python
def load_agent_def(definitions_dir: Path | str, *, agent_name: str | None = None) -> AgentDef:
    from noble_agent.agent.tools.schemas import build_schemas

    d = Path(definitions_dir)
    config = json.loads(_read(d / "config.json"))
    name = agent_name or config["name"]
```

with:

```python
def load_agent_def(persona_dir: Path | str, *, tool_names: list[str], agent_name: str | None = None) -> AgentDef:
    from noble_agent.agent.tools.schemas import build_schemas

    d = Path(persona_dir)
    config = json.loads(_read(d / "config.json"))
    name = agent_name or config["name"]
```

and replace:

```python
    tool_names = list(config["tools"])
    tool_schemas = build_schemas(tool_names)
```

with:

```python
    tool_names = list(tool_names)
    tool_schemas = build_schemas(tool_names)
```

- [ ] **Step 4: Wire the facade to the context** — in `src/noble_agent/agent/facade.py` `_build_runner`, replace:

```python
    settings = get_settings()
    defs_dir = Path(__file__).resolve().parent / "definitions"
    agent_def = load_agent_def(defs_dir, agent_name=settings.agent_name)
```

with:

```python
    settings = get_settings()
    from noble_agent.tenant.loader import get_tenant_context

    ctx = get_tenant_context()
    agent_def = load_agent_def(
        ctx.persona_dir, tool_names=list(ctx.enabled_tools), agent_name=settings.agent_name
    )
```

(The `from pathlib import Path` import stays — still used elsewhere.)

- [ ] **Step 5: Create the shared test helper** — `tests/unit/unified/_persona.py`:

```python
"""Shared persona-dir + offered-tool list for tests (post-tenant-migration)."""

from pathlib import Path

import noble_agent

PERSONA_DIR = Path(noble_agent.__file__).resolve().parent / "tenants" / "noble" / "persona"

NOBLE_TOOLS = [
    "find_project",
    "update_customer",
    "noble_search",
    "discover_projects",
    "get_project_overview",
    "get_project_financial",
    "search_units",
    "recommend_units",
    "booking",
    "escalate",
    "send_media",
    "check_inventory",
]
```

- [ ] **Step 6: Update all test call sites** — apply this uniform transform to each file. Replace the old constant line

```python
DEFINITIONS = Path("src/noble_agent/agent/definitions")
```

by importing the shared helper (add near the top imports):

```python
from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR
```

and replace every call `load_agent_def(DEFINITIONS)` → `load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)` and `load_agent_def(DEFINITIONS, agent_name="Aria")` → `load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS, agent_name="Aria")`. Remove the now-unused `DEFINITIONS` line and any now-unused `Path` import.

Files (exact call shapes vary slightly — grep each for `load_agent_def(` and `DEFINITIONS`):
  - `tests/unit/unified/test_suggestions.py` (const at :25, call at :30)
  - `tests/unit/unified/test_cache_warm.py` (:20, :34)
  - `tests/unit/unified/test_conversation_persist.py` (:18, :31)
  - `tests/unit/unified/test_prompt_builder.py` (:11, :16)
  - `tests/unit/unified/test_facade.py` (inline at :11 — `AGENT = load_agent_def(Path("src/noble_agent/agent/definitions"))` → `AGENT = load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)`)
  - `tests/unit/unified/test_agent_def.py` (const at :5, calls at :9/:25/:33/:41/:50)
  - `tests/unit/unified/test_runner.py` (:17, :22)
  - `tests/unit/test_streaming_no_repeat_after_tool.py` (:28, :33) — import path is `from tests.unit.unified._persona import ...`
  - `tests/unit/test_interrupt.py` (:29, :127)
  - `tests/integration/unified/conftest.py` (:34, :196)

- [ ] **Step 7: Verify no stray references to the old path remain**

Run: `grep -rn "agent/definitions" src/ tests/ --include=*.py | grep -v "__pycache__"`
Expected: only comment/docstring mentions in `base.py:1`, `schemas.py:4`, `config.py:603` remain (harmless prose). No live `Path(...definitions...)` construction. If any live construction remains, fix it.

- [ ] **Step 8: Run the affected suites**

Run: `pytest tests/unit/unified/test_agent_def.py tests/unit/unified/test_facade.py tests/unit/unified/test_prompt_builder.py tests/unit/unified/test_runner.py tests/unit/unified/test_suggestions.py tests/unit/unified/test_cache_warm.py tests/unit/unified/test_conversation_persist.py tests/unit/test_interrupt.py tests/unit/test_streaming_no_repeat_after_tool.py -v`
Expected: PASS (same counts as before the migration — `test_agent_def` still asserts 12 tools).

- [ ] **Step 9: Verify the facade builds the runner from the context (behaviour-identity smoke)**

Run:
```bash
python -c "
from noble_agent.tenant.loader import get_tenant_context
from noble_agent.agent.base import load_agent_def
ctx = get_tenant_context()
ad = load_agent_def(ctx.persona_dir, tool_names=list(ctx.enabled_tools), agent_name='Luna')
names = {s['function']['name'] for s in ad.tool_schemas}
assert len(ad.tool_schemas) == 12, len(ad.tool_schemas)
assert 'find_project' in names and 'booking' in names
assert ad.name == 'Luna'
print('OK: agent_def built from tenant context — 12 tools, persona at', ctx.persona_dir.name)
"
```
Expected: `OK: agent_def built from tenant context — 12 tools, persona at persona`.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat(tenant): migrate Noble persona to tenants/noble/persona + facade reads TenantContext

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Verification gate + changelog + ledger

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.superpowers/sdd/progress.md`

- [ ] **Step 1: Full unit suite**

Run: `make test-unit 2>&1 | tail -5` and extract the summary line.
Expected: the **same pre-existing baseline failures** as Phase 2 (the 8 known: 2 USD-normalize, 2 qdrant_adapter, 1 qdrant_store, 1 snapshot_short_term, 1 prompt 'Tên:', 1 local-.env `test_config_media_search_defaults`). **ZERO new failures.** Passed count rises by the new tenant tests (Task 1: 2, Task 2: 4). Record the exact counts and the unique FAILED ids; confirm each matches the baseline.

- [ ] **Step 2: Ruff on touched files**

Run: `ruff check src/noble_agent/config.py src/noble_agent/tenant/ src/noble_agent/agent/base.py src/noble_agent/agent/facade.py tests/unit/tenant/ tests/unit/unified/_persona.py`
Expected: clean.

- [ ] **Step 3: Confirm the CLAUDE.md architecture table is updated** — the layout table describes `agent/definitions/` as the "single source of truth for prompt + tools". Update that row (and any prose that says definitions live under `agent/`) to reflect `tenants/noble/persona/` + `manifest.toml`. Also update the `agent/base.py` row (`load_agent_def(persona_dir, *, tool_names)`), the `config.json` mention (tools now in manifest), and the `facade.py` row (builds from `TenantContext`).

- [ ] **Step 4: Add a Change Log row to `CLAUDE.md`** (top of the `## Change Log` table), dated `2026-07-24`, branch `feat/refactor2`, summarizing: SaaS Phase 3a+3b — `TenantContext` + `TENANT_ID` + `tenant/loader.py` (`get_tenant_context()` singleton, fail-loud) + `tenants/noble/manifest.toml`; persona git-mv `agent/definitions/*` → `tenants/noble/persona/*`; `load_agent_def(persona_dir, *, tool_names)` (tool list now from `manifest.enabled`, `config.json` "tools" removed); facade builds the runner from the context; provider selection UNCHANGED (still `NOBLE_DATA_SOURCE`, manifest.data_source mirrors it, guarded by test); `brand`/`rankers`/`media_channel` declared-not-yet-consumed; deviation-from-spec-diagram (tenants/ inside the package for wheel shipping) noted; deferred to 3c/3d (registry/custom-tools, brand-neutralization, provider-through-ctx cutover); behaviour-identical for `TENANT_ID=noble`; gate result + ZERO new failures.

- [ ] **Step 5: Append a Phase-3ab section to `.superpowers/sdd/progress.md`** recording each task's commit + the gate result.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: SaaS Phase 3a+3b (tenant context + persona migration) — changelog + gate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Manual smoke note (report to user; do NOT merge/push)**

Per `SMOKE.md` — this touches the system-prompt build path and boot — a live `/chat` run should confirm the agent boots from `TENANT_ID=noble`, offers the same 12 tools, and produces an unchanged system prompt, before prod reliance. Do not merge/push/PR (branch rule).

---

## Self-Review

**1. Spec coverage (Parts 5 & 6, sliced to 3a+3b):**
- `TenantContext` frozen + `get_tenant_context()` singleton → Tasks 1, 2. ✅
- `tenant/loader.py` reads `TENANT_ID` → `manifest.toml` → context; fail-loud → Task 2. ✅
- `agent/definitions/*` → `tenants/noble/persona/*` (git-mv) → Task 3. ✅
- `config.json` offered-tool list merged into `manifest.toml [tools].enabled` (one runtime source) → Tasks 2, 3. ✅
- `build_system_prompt`/`load_agent_def` take the persona dir from the context → Tasks 3, facade. ✅
- **Deliberately deferred (documented, not silently dropped):** provider-through-context cutover (`get_provider()` → `ctx.provider`) — kept on `settings.noble_data_source` to preserve the `NOBLE_DATA_SOURCE=…` tests and behaviour-identity (later slice); `manifest.extra_fields`/`tool_params` (still declared on the provider in code from Phases 1–2); brand templating / `kb_search` rename / feng-shui ranker / media_channel consumption (slice 3d); registry / custom tools (slice 3c). The manifest already carries `data_source`/`brand`/`rankers`/`media_channel` as the source of truth for those slices.
- **Deviation from spec diagram (documented):** `tenants/` lives at `src/noble_agent/tenants/` (in-package) rather than repo-root, so it ships in the wheel like `agent/definitions/` and is importable for 3c. Behaviourally irrelevant this phase (files read by path).

**2. Placeholder scan:** No TBD/TODO/"handle edge cases". New files show full code; the test-migration transform is a single uniform rule applied to an explicit file list with exact line hints (a mechanical repeat across near-identical call sites, not a "similar to Task N" hand-wave). ✅

**3. Type consistency:** `TenantContext(tenant_id, data_source, persona_dir: Path, enabled_tools: tuple, rankers: frozenset, media_channel: str, brand: dict)` identical across Tasks 1, 2. `load_agent_def(persona_dir, *, tool_names, agent_name=None)` matches between the Task-3 definition and every updated call site + the facade. `get_tenant_context()`/`reset_tenant_context_for_tests()` names match between loader (Task 2) and facade/tests. The loader's `_tenants_root` is monkeypatched by name in `test_missing_required_key_fails_loud` and defined in Task 2. ✅
