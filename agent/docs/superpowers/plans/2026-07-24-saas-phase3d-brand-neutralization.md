# SaaS Phase 3d — Brand Neutralization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the standard tool layer tenant-neutral so a non-Noble tenant isn't shipping Noble's brand or Vietnam-specific feng-shui: rename the brand-carrying tool `noble_search` → `kb_search`, template the company/app brand strings in tool descriptions + SOUL via `{{ brand.* }}` from `TenantContext`, and gate the feng-shui overlay behind the manifest `rankers` list. **Behaviour is functionally identical for `TENANT_ID=noble`** (brand vars render to "Noble"/"NobleX"; `feng_shui` is enabled in Noble's manifest; the rename is name-only).

**Architecture:** `build_schemas(names)` (already the single schema-build path, from Phase 2) gains two tenant-aware passes driven by `get_tenant_context()`: (1) render `{{ brand.company }}`/`{{ brand.app_name }}` tokens in every tool description; (2) when `"feng_shui"` is not in `ctx.rankers`, strip the feng-shui params (`birth_year`/`gender`/`menh`/`zodiac`) from `recommend_units`. SOUL is rendered with `brand` in `load_agent_def`. The `recommend_units` executor guards the overlay on `ctx.rankers` for defense in depth. The `kb_search` rename is a mechanical token rename across schema/registration/manifest/persona/tests; the internal RAG module (`noble_kb.query_noble_kb`, `_NobleKBAdapter`) keeps its names (not LLM-facing).

**Tech Stack:** Python 3.11–3.13, jinja2 (already used for prompts), pytest (`asyncio_mode=auto`), ruff (line-length 120).

## Global Constraints

- **Branch:** `feat/refactor2` only. Never touch `develop`; no push/PR/merge/worktree/rebase without explicit user instruction. Local commits fine.
- **Functionally identical for `TENANT_ID=noble`.** Brand tokens render to the current literals (`company="Noble"`, `app_name="NobleX"`); `feng_shui` is in Noble's `manifest.rankers` so `recommend_units` keeps all params + overlay; `kb_search` does exactly what `noble_search` did (RAG unchanged). The system prompt is functionally equivalent (the only change is the tool NAME `noble_search`→`kb_search` and identical rendered brand strings).
- **Brand templating scope:** template ONLY clearly company/app brand strings. **Do NOT template project-name examples** (`"Noble Crystal"` in `get_project_overview`/`find_project` descriptions — those are literal project names, not brand). **Leave `RULES.md` untouched** (its few "Noble" mentions are persona copy a new tenant overrides wholesale; templating them risks the project-name trap — out of scope, noted).
- **Deferred (documented, NOT in this plan):** media_channel full abstraction (only the app-name string is templated here); provider-through-`TenantContext` cutover (still `settings.noble_data_source`); relocating Noble-specific core DTO fields into `extras` (spec Part 1). These are riskier / orthogonal and become a follow-on slice.
- **`schemas_for` stays literal.** It is the raw static accessor used by legacy callers/tests; brand rendering + ranker stripping happen ONLY in `build_schemas`. Tokens (`{{ brand.* }}`) live in the static `SCHEMAS` dict, so `schemas_for` returns them un-rendered — that is acceptable (only `build_schemas` feeds the LLM); update any test that asserts the raw description text of a templated field.
- Commit message final line, verbatim: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Reply to the user in Vietnamese.

---

## File Structure

- `src/noble_agent/agent/tools/schemas.py` — **modify**: rename `noble_search` entry → `kb_search` (key + `function.name`); update cross-references to the tool name in other descriptions; insert `{{ brand.* }}` tokens at the company/app brand spots.
- `src/noble_agent/agent/tools/builtins.py` — **modify**: register the built-in under name `kb_search` (executor still calls `noble_search.run`).
- `src/noble_agent/agent/tools/build`… `schemas.py build_schemas` — **modify**: add brand-render + feng-shui-strip passes (both read `get_tenant_context()`).
- `src/noble_agent/agent/tools/projects_info.py` — **modify**: `recommend_units` skips the feng-shui overlay when `"feng_shui"` not in `ctx.rankers`.
- `src/noble_agent/tenants/noble/manifest.toml` — **modify**: `enabled` list `noble_search`→`kb_search`.
- `src/noble_agent/tenants/noble/persona/{SOUL.md,RULES.md}` — **modify**: SOUL brand token; RULES `noble_search`→`kb_search` in the tool-catalog (tool NAME only; leave brand prose).
- `src/noble_agent/agent/base.py` — **modify**: `load_agent_def` renders SOUL with `brand`.
- Tests: `_persona.py` (`NOBLE_TOOLS`), `test_tool_schemas.py`, `test_schemas_dynamic_enum.py`, `test_builtins.py`, `test_sandbox_readonly.py`, `test_agent_def.py`, + any other referencing `noble_search` — **modify** (rename + brand/ranker tests).
- `tests/unit/tools/test_brand_and_rankers.py` — **create**.

---

## Task 1: Rename the `noble_search` tool → `kb_search`

**Files:** `schemas.py`, `builtins.py`, `manifest.toml`, `persona/RULES.md`, `_persona.py`, and every test referencing the tool name.

**Interfaces:**
- Produces: the offered tool is now named `kb_search` (was `noble_search`); its schema, executor behaviour, and RAG path are otherwise unchanged. The internal `noble_kb.query_noble_kb` / `_NobleKBAdapter` / `agent/tools/noble_search.py` module keep their names (not LLM-facing).

- [ ] **Step 1: Write/adjust the failing test** — in `tests/unit/unified/test_tool_schemas.py`, change the ordering test to the new name and add an absence check:

```python
def test_schemas_for_returns_in_order():
    out = schemas_for(["update_customer", "kb_search"])
    assert [s["function"]["name"] for s in out] == ["update_customer", "kb_search"]


def test_noble_search_renamed_to_kb_search():
    assert "kb_search" in SCHEMAS
    assert "noble_search" not in SCHEMAS
    assert SCHEMAS["kb_search"]["function"]["name"] == "kb_search"
```

Run: `pytest tests/unit/unified/test_tool_schemas.py::test_noble_search_renamed_to_kb_search -v` → FAIL (`kb_search` not in SCHEMAS).

- [ ] **Step 2: Rename in `schemas.py`** — change the dict key `"noble_search"` → `"kb_search"` and its inner `"name": "noble_search"` → `"name": "kb_search"`. Update the description's self-reference if any. Update OTHER tool descriptions that name the tool: search `schemas.py` for `noble_search` and replace the tool-name references (e.g. `find_project`'s description lists `noble_search` among the data tools → `kb_search`). Do NOT touch `project_filter` param name.

- [ ] **Step 3: Rename in `builtins.py`** — the `_BUILTINS` entry `("noble_search", _noble_search, False, True)` → `("kb_search", _noble_search, False, True)`. The adapter fn may keep the name `_noble_search` (internal) or rename to `_kb_search` — rename for clarity; it still calls `noble_search.run(rag, dispatcher, args)`.

- [ ] **Step 4: Rename in the manifest + persona + test helper** —
  - `tenants/noble/manifest.toml`: `enabled` list `"noble_search"` → `"kb_search"`.
  - `tenants/noble/persona/RULES.md`: in the tool-catalog table, the `noble_search` row/mentions → `kb_search` (grep RULES for `noble_search`). Leave company brand prose alone.
  - `tests/unit/unified/_persona.py`: `NOBLE_TOOLS` `"noble_search"` → `"kb_search"`.

- [ ] **Step 5: Update every remaining test reference** — grep and update: `grep -rn "noble_search" tests/ --include=*.py | grep -v __pycache__`. Expected files: `test_tool_schemas.py` (done Step 1 + `test_project_code_params_have_no_enum` references `noble_search`'s `project_filter` → rename to `kb_search`), `test_schemas_dynamic_enum.py` (`_by_name(["noble_search", ...])` + assertions), `test_builtins.py` (`READ_ONLY` set + `ALL_15`/`ALL_12`), `test_sandbox_readonly.py` (`noble_search` in the read-only loop), `test_agent_def.py` (names set), and any dispatcher/turn test that dispatches `noble_search`. Replace the tool-name token `noble_search` → `kb_search` (do NOT rename the `noble_search.py` module import or `query_noble_kb`).

- [ ] **Step 6: Run** `pytest tests/unit/unified/test_tool_schemas.py tests/unit/unified/test_schemas_dynamic_enum.py tests/unit/tools/test_builtins.py tests/unit/tools/test_sandbox_readonly.py tests/unit/unified/test_agent_def.py -v` → PASS. Also `grep -rn "\"noble_search\"\|'noble_search'" src/ tests/ --include=*.py | grep -v __pycache__` should return nothing (the module file `noble_search.py` + `from ... import noble_search` stay — those are module names, not the quoted tool name).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(tools): rename brand-carrying tool noble_search -> kb_search

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Brand templating (tool descriptions + SOUL) via `{{ brand.* }}`

**Files:** `schemas.py` (tokens), `agent/tools/schemas.py::build_schemas` (render pass), `agent/base.py` (SOUL render), `persona/SOUL.md` (token), + a new test.

**Interfaces:**
- Consumes: `get_tenant_context().brand` (Phase 3a).
- Produces: `build_schemas(names)` replaces `{{ brand.company }}` / `{{ brand.app_name }}` tokens in every tool description with `ctx.brand`'s values (default to `"Noble"`/`"NobleX"` if a key is absent, so a partial manifest never leaks a raw token). `load_agent_def` renders `SOUL.md` with `brand`. For `TENANT_ID=noble`, output is identical to today's literals.

- [ ] **Step 1: Write the failing test** — create `tests/unit/tools/test_brand_and_rankers.py`:

```python
from noble_agent.agent.tools import builtins as _b  # noqa: F401 — registers
from noble_agent.agent.tools import schemas


def test_brand_tokens_rendered_in_descriptions():
    out = {s["function"]["name"]: s for s in schemas.build_schemas(["send_media", "update_customer"])}
    send_desc = out["send_media"]["function"]["description"]
    # Noble renders the app-name literal; NO raw token survives.
    assert "{{ brand.app_name }}" not in send_desc
    assert "NobleX" in send_desc
    upd_desc = out["update_customer"]["function"]["parameters"]["properties"]["is_noble_customer"]["description"]
    assert "{{ brand.company }}" not in upd_desc
    assert "Noble" in upd_desc


def test_project_name_examples_not_templated():
    # "Noble Crystal" is a project name, must survive verbatim (not turned into a token).
    out = {s["function"]["name"]: s for s in schemas.build_schemas(["find_project"])}
    assert "Noble Crystal" in out["find_project"]["function"]["description"]
```

Run → FAIL (tokens not rendered yet / not present).

- [ ] **Step 2: Insert brand tokens in `schemas.py`** — replace ONLY the company/app brand strings (leave project-name examples):
  - `update_customer` `project_interest` desc: `"...danh sách dự án Noble)."` → `"...danh sách dự án {{ brand.company }})."`
  - `update_customer` `is_noble_customer` desc: `"...đã là khách Noble ..."` → `"...đã là khách {{ brand.company }} ..."`
  - `update_customer` `noble_info` desc: `"...nếu khách là khách Noble ..."` → `"...nếu khách là khách {{ brand.company }} ..."`
  - `crm_lookup` desc: `"Tra cứu khách Noble đã mua ..."` → `"Tra cứu khách {{ brand.company }} đã mua ..."`
  - `send_media` desc: `"...qua ứng dụng NobleX:"` → `"...qua ứng dụng {{ brand.app_name }}:"`
  - DO NOT touch `get_project_overview` desc `"dự án Noble Crystal"` or `find_project` desc `"Noble Crystal Tây Hồ"` — project-name examples.

- [ ] **Step 3: Add the brand-render pass to `build_schemas`** — in `src/noble_agent/agent/tools/schemas.py`, after the deep-copy and BEFORE returning, render brand tokens on each schema's description strings. Add a helper + call it:

```python
_BRAND_DEFAULTS = {"company": "Noble", "app_name": "NobleX"}


def _render_brand(text: str, brand: dict) -> str:
    if "{{" not in text:
        return text
    return (
        text.replace("{{ brand.company }}", brand.get("company", _BRAND_DEFAULTS["company"]))
        .replace("{{ brand.app_name }}", brand.get("app_name", _BRAND_DEFAULTS["app_name"]))
    )
```

In `build_schemas`, after building `out` (the deep-copied list) and BEFORE the tool_params injection loop (order doesn't matter, but do it once), resolve the brand and walk descriptions:

```python
    from noble_agent.tenant.loader import get_tenant_context

    try:
        brand = dict(get_tenant_context().brand)
    except Exception:
        brand = dict(_BRAND_DEFAULTS)
    for schema in out:
        fn = schema["function"]
        if "description" in fn:
            fn["description"] = _render_brand(fn["description"], brand)
        for prop in fn.get("parameters", {}).get("properties", {}).values():
            if isinstance(prop, dict) and "description" in prop:
                prop["description"] = _render_brand(prop["description"], brand)
```

(The `try/except` keeps `build_schemas` usable in tests that never boot a tenant — it falls back to Noble defaults, preserving today's literals.)

- [ ] **Step 4: Template SOUL + render it** — in `tenants/noble/persona/SOUL.md`, replace `chuyên viên NobleX` with `chuyên viên {{ brand.app_name }}`. In `src/noble_agent/agent/base.py` `load_agent_def`, pass `brand` to the SOUL render. Add a `brand` param:

```python
def load_agent_def(persona_dir: Path | str, *, tool_names: list[str], agent_name: str | None = None, brand: dict | None = None) -> AgentDef:
```

and where SOUL is rendered:

```python
    _brand = brand or {"company": "Noble", "app_name": "NobleX"}
    soul = env.from_string(_read(d / "SOUL.md")).render(agent_name=name, brand=_brand)
    rules = env.from_string(_read(d / "RULES.md")).render(agent_name=name, brand=_brand)
```

In `facade._build_runner`, pass `brand=dict(ctx.brand)`:

```python
    agent_def = load_agent_def(
        ctx.persona_dir, tool_names=list(ctx.enabled_tools), agent_name=settings.agent_name, brand=dict(ctx.brand)
    )
```

Update the test helper/callers: `load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)` still works (`brand=None` → Noble defaults render the same literals). No test-call change required for brand (default preserves behaviour).

- [ ] **Step 5: Run** `pytest tests/unit/tools/test_brand_and_rankers.py tests/unit/unified/test_prompt_builder.py tests/unit/unified/test_agent_def.py -v` → PASS. Confirm the rendered SOUL for noble still contains "chuyên viên NobleX".

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(tools): template company/app brand in tool descriptions + SOUL via TenantContext

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Feng-shui overlay gated behind `manifest.rankers`

**Files:** `agent/tools/schemas.py::build_schemas` (param strip), `agent/tools/projects_info.py` (`recommend_units` guard), + test.

**Interfaces:**
- Consumes: `get_tenant_context().rankers` (Phase 3a).
- Produces: when `"feng_shui"` ∉ `ctx.rankers`, `build_schemas` removes `recommend_units`'s `birth_year`/`gender`/`menh`/`zodiac` params, and `recommend_units` ignores any feng-shui signal (no overlay). Noble's manifest has `rankers=["feng_shui"]` → all params kept + overlay active (identical to today).

- [ ] **Step 1: Write the failing test** — append to `tests/unit/tools/test_brand_and_rankers.py`:

```python
import pytest

from noble_agent.tenant import loader


@pytest.fixture
def _rankers(monkeypatch):
    def _set(rankers):
        ctx = loader.get_tenant_context()
        from dataclasses import replace
        monkeypatch.setattr(loader, "_ctx_singleton", replace(ctx, rankers=frozenset(rankers)))
    return _set


def test_feng_shui_params_present_when_ranker_enabled(_rankers):
    _rankers({"feng_shui"})
    out = {s["function"]["name"]: s for s in schemas.build_schemas(["recommend_units"])}
    props = out["recommend_units"]["function"]["parameters"]["properties"]
    for p in ("birth_year", "gender", "menh", "zodiac"):
        assert p in props, p


def test_feng_shui_params_stripped_when_ranker_disabled(_rankers):
    _rankers(set())
    out = {s["function"]["name"]: s for s in schemas.build_schemas(["recommend_units"])}
    props = out["recommend_units"]["function"]["parameters"]["properties"]
    for p in ("birth_year", "gender", "menh", "zodiac"):
        assert p not in props, p
    # non-feng-shui params survive
    assert "budget_max" in props and "region" in props
```

Run → FAIL (params not stripped when disabled).

- [ ] **Step 2: Add the ranker-strip pass to `build_schemas`** — after the brand pass, before returning:

```python
    _FENG_SHUI_PARAMS = ("birth_year", "gender", "menh", "zodiac")
    try:
        rankers = get_tenant_context().rankers
    except Exception:
        rankers = frozenset({"feng_shui"})  # default: Noble behaviour
    if "feng_shui" not in rankers:
        for schema in out:
            if schema["function"]["name"] == "recommend_units":
                props = schema["function"]["parameters"].get("properties", {})
                for p in _FENG_SHUI_PARAMS:
                    props.pop(p, None)
```

(`_FENG_SHUI_PARAMS` can be a module constant; keep the `try/except` default so tests without a tenant see Noble's behaviour.)

- [ ] **Step 3: Guard the overlay in the executor** — in `src/noble_agent/agent/tools/projects_info.py` `recommend_units`, before computing the feng-shui overlay, short-circuit when the ranker is disabled:

```python
    from noble_agent.tenant.loader import get_tenant_context
    try:
        _rankers = get_tenant_context().rankers
    except Exception:
        _rankers = frozenset({"feng_shui"})
    feng_shui_on = "feng_shui" in _rankers
```

and gate the existing overlay computation (`birth_year`/`menh`/`zodiac` → directions) on `feng_shui_on` (when off, treat as no feng-shui signal — the recommender falls back to the plain budget/region/bedrooms filter it already does when no signal is given). Do NOT change the non-feng-shui path. For Noble (`feng_shui_on=True`) the code path is unchanged.

- [ ] **Step 4: Run** `pytest tests/unit/tools/test_brand_and_rankers.py tests/unit/unified/test_recommend_units*.py -v` (and any feng-shui test) → PASS. Noble path unchanged; disabled path strips params + skips overlay.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(tools): gate recommend_units feng-shui overlay behind manifest rankers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Verification gate + changelog + ledger

- [ ] **Step 1: Full unit suite** — `make test-unit 2>&1 | tail -5`; extract summary + unique FAILED ids. Expected: the same known baseline (8: 2 USD-normalize, 2 qdrant_adapter, 1 qdrant_store, 1 snapshot_short_term, 1 prompt 'Tên:', 1 local-.env media), **ZERO new**. Confirm the 'Tên:' prompt test still fails identically (it is unrelated to brand/rename) and no NEW prompt/schema test regressed. If the rename or brand touched a test not updated, fix it.

- [ ] **Step 2: Ruff** — `ruff check src/noble_agent/agent/tools/schemas.py src/noble_agent/agent/tools/builtins.py src/noble_agent/agent/tools/projects_info.py src/noble_agent/agent/base.py src/noble_agent/agent/facade.py`. Expected: clean.

- [ ] **Step 3: Behaviour-identity smoke** — confirm noble renders identically:
```bash
python -c "
from noble_agent.tenant.loader import get_tenant_context
from noble_agent.agent.base import load_agent_def
ctx = get_tenant_context()
ad = load_agent_def(ctx.persona_dir, tool_names=list(ctx.enabled_tools), brand=dict(ctx.brand))
names = {s['function']['name'] for s in ad.tool_schemas}
assert 'kb_search' in names and 'noble_search' not in names
rec = [s for s in ad.tool_schemas if s['function']['name']=='recommend_units'][0]
assert 'birth_year' in rec['function']['parameters']['properties']  # feng_shui ON for noble
send = [s for s in ad.tool_schemas if s['function']['name']=='send_media'][0]
assert 'NobleX' in send['function']['description'] and '{{' not in send['function']['description']
assert ad.sections['soul'].find('NobleX') != -1
print('OK: kb_search live, brand rendered to NobleX, feng-shui params present for noble')
"
```

- [ ] **Step 4: Update `CLAUDE.md`** — (a) the RAG-stack / tool sections that name `noble_search` as the RAG tool → note it's now `kb_search` (the `noble_kb.query_noble_kb` entrypoint keeps its name). (b) A Change Log row (2026-07-24, `feat/refactor2`) summarizing: `noble_search`→`kb_search` rename; brand templating (`{{ brand.* }}` in tool descriptions + SOUL, rendered from `TenantContext`, project-name examples + RULES left untouched); feng-shui overlay gated behind `manifest.rankers`; deferred (media_channel full abstraction, provider-through-ctx cutover, DTO field relocation); behaviour-identical for `TENANT_ID=noble`; gate + ZERO new failures.

- [ ] **Step 5: Append a Phase-3d section to `.superpowers/sdd/progress.md`** with each task's commit + gate result + Minors.

- [ ] **Step 6: Commit the docs.**

- [ ] **Step 7: Manual smoke note (report; do NOT merge/push)** — per `SMOKE.md`, a live `/chat` run should confirm the agent boots, offers `kb_search` (RAG works), renders the same brand copy, and `recommend_units` still does feng-shui for noble.

---

## Self-Review

**1. Spec coverage (Part 3 — standard tool set neutralization, sliced):**
- `noble_search`→`kb_search` (brand-neutral) → Task 1. ✅
- Brand templating of tool copy + persona via `{{ brand.* }}` from the manifest `[brand]` → Task 2. ✅ (scoped to company/app strings; project-name examples + RULES left untouched — documented, to avoid the "Noble Crystal" trap.)
- feng-shui as an optional ranker plugin; params dropped when off → Task 3. ✅
- **Deferred (documented):** media_channel full channel-abstraction (only app-name templated); provider-through-`TenantContext` cutover; DTO field relocation (spec Part 1). These are the riskier/orthogonal remainder → a follow-on slice.

**2. Placeholder scan:** No TBD/vague handling; render/strip passes shown in full; the rename is a defined uniform token transform with an explicit grep-verified file list. ✅

**3. Type consistency:** `_render_brand(text, brand)` + `build_schemas` brand/ranker passes read `get_tenant_context().brand`/`.rankers` (Phase 3a fields, correct types: `dict`/`frozenset`). `load_agent_def(..., brand: dict | None = None)` matches the facade call (`brand=dict(ctx.brand)`) and the default-`None` test calls. The `_FENG_SHUI_PARAMS` names match the params defined in `recommend_units`'s schema (`birth_year`/`gender`/`menh`/`zodiac`). `kb_search` is used consistently across schema key, `function.name`, builtins registration, manifest, persona, and tests. ✅
