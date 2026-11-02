# analyze_projects SQL Analytics Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tool `analyze_projects(sql)` cho LLM tự viết SQL SELECT trả lời câu hỏi tổng quát/aggregate, chạy read-only tuyệt đối trên 2 view Postgres.

**Architecture:** 3 khoá DB độc lập (READ ONLY txn + role `agent_sql_ro` chỉ SELECT trên 2 view + RLS theo GUC tenant); validator ứng dụng chỉ để lỗi đẹp. Description tool mang mini-DDL + quy ước nghiệp vụ + few-shot; khối vocab giá trị thật chèn **per-turn ở runner** (AgentDef frozen, schemas cache theo (tenant,version,channel) — chèn lúc build_schemas sẽ đóng băng trước khi vocab kịp có; plan này điều chỉnh spec §5 ở đúng một điểm đó).

**Tech Stack:** Python 3.11+, asyncpg, pydantic-settings, pytest (asyncio_mode=auto), ruff (line-length 120).

**Spec:** `docs/superpowers/specs/2026-08-26-analyze-projects-sql-tool-design.md`

## Global Constraints

- Nhánh làm việc: `feat/share-agent`. **Không** checkout/merge/push/`develop`. Commit local sau mỗi task.
- Ruff line-length **120**, target py311, rules `E,F,W,I,UP,B,SIM`. Chạy `make lint` trước mỗi commit.
- Tool mới vào `OPTIONAL_TOOLS` (KHÔNG vào `CORE_TOOLS`); `read_only=True`, `dirties_customer=False`.
- Mọi lỗi runtime của tool trả **chuỗi** cho LLM (không raise, không `ESCALATE_SIGNAL`); 0 dòng ≠ lỗi ≠ cớ escalate.
- Hàng rào an toàn = Postgres (GRANT + READ ONLY + RLS), không phải parse SQL.
- Không đụng semcache, không expose documents/media/contacts/conversations.
- Integration test gate bằng env `SPE_PG_ADMIN_DSN` + marker `needs_postgres` (pattern `tests/integration/tenant/test_pg_rls_live.py`).
- CLAUDE.md tự-bảo-trì: cập nhật taxonomy + changelog **cùng commit** với thay đổi code tương ứng (dồn vào Task 8).

---

### Task 1: DDL views + provisioning roles + CLI `pg-ensure-sql-ro`

**Files:**
- Modify: `src/noble_agent/storage/sql/kb_real_estate.sql` (append cuối file)
- Modify: `src/noble_agent/tenant/pg_provisioning.py`
- Modify: `src/noble_agent/tenant/cli.py:109-190`
- Test: `tests/unit/unified/test_analytics_provisioning.py` (mới)

**Interfaces:**
- Consumes: `_ROLE_RE`, `_pw_literal`-style patterns đã có trong `pg_provisioning.py`.
- Produces: `pg_provisioning.ensure_sql_ro_roles(admin_dsn, *, sql_ro_role: str, app_role: str, tenant_roles: tuple = ()) -> None`; hằng `pg_provisioning.VIEW_OWNER_ROLE = "agent_kb_view_owner"`, `pg_provisioning.AGENT_VIEWS = ("agent_projects_v", "agent_units_v")`; `provision(...)` nhận thêm kwarg `sql_ro_role: str = "agent_sql_ro"`; CLI cmd `noble-tenant pg-ensure-sql-ro`.

- [ ] **Step 1: Viết test fail — validate tên role không cần kết nối DB**

```python
# tests/unit/unified/test_analytics_provisioning.py
"""ensure_sql_ro_roles: validate tên role TRƯỚC khi chạm DB (không cần asyncpg/PG)."""

import pytest

from noble_agent.tenant import pg_provisioning as pg


async def test_ensure_sql_ro_rejects_bad_role_names():
    with pytest.raises(ValueError):
        await pg.ensure_sql_ro_roles("postgresql://x", sql_ro_role='bad"name', app_role="odyssey_agent")
    with pytest.raises(ValueError):
        await pg.ensure_sql_ro_roles("postgresql://x", sql_ro_role="agent_sql_ro", app_role="BAD ROLE")


def test_view_constants():
    assert pg.VIEW_OWNER_ROLE == "agent_kb_view_owner"
    assert pg.AGENT_VIEWS == ("agent_projects_v", "agent_units_v")
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/unit/unified/test_analytics_provisioning.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'ensure_sql_ro_roles'`

- [ ] **Step 3: Append view DDL vào `kb_real_estate.sql`** (cuối file, sau DO block RLS)

```sql
-- ── analyze_projects views (spec 2026-08-26) ────────────────────────────────
-- Bề mặt đọc DUY NHẤT của tool analyze_projects (SQL do LLM sinh). Lọc sẵn
-- status='published' (cả units lẫn project cha) và KHÔNG expose tenant_id/
-- status/created_at/media id/overview. Definer semantics (KHÔNG security_invoker
-- — invoker sẽ bắt role truy vấn có SELECT trên bảng gốc, phá cô lập); owner =
-- agent_kb_view_owner (NOBYPASSRLS, set ở pg-ensure-sql-ro) nên FORCE RLS +
-- policy agent_runtime theo GUC app.current_tenant vẫn siết tenant như thường.
-- CREATE OR REPLACE giữ nguyên owner/grants khi pg-apply-schema chạy lại.
CREATE OR REPLACE VIEW tenant_data.agent_projects_v AS
SELECT project_code, name, region, address, investor, developer,
       category, sale_phase, ownership_form, total_land_area_m2
FROM tenant_data.projects
WHERE status = 'published';

CREATE OR REPLACE VIEW tenant_data.agent_units_v AS
SELECT u.project_code, p.name AS project_name, u.zone_code, u.unit_code,
       u.product_type, u.bedrooms, u.block, u.floor, u.direction,
       u.area_built_m2, u.area_land_m2, u.price_vnd, u.price_per_m2_vnd,
       u.sale_status
FROM tenant_data.units u
JOIN tenant_data.projects p USING (tenant_id, project_code)
WHERE u.status = 'published' AND p.status = 'published';
```

- [ ] **Step 4: Thêm `ensure_sql_ro_roles` + sửa `provision` trong `pg_provisioning.py`**

Thêm sau `ensure_app_role` (giữ nguyên style lazy-import asyncpg):

```python
VIEW_OWNER_ROLE = "agent_kb_view_owner"
AGENT_VIEWS = ("agent_projects_v", "agent_units_v")


async def ensure_sql_ro_roles(
    admin_dsn: str, *, sql_ro_role: str, app_role: str, tenant_roles: tuple = ()
) -> None:
    """Idempotent: tạo owner NOBYPASSRLS cho 2 view analyze_projects + role
    `agent_sql_ro` CHỈ có SELECT trên 2 view đó, rồi grant membership cho app
    role VÀ các role tenant đang tồn tại (đường gateway per-tenant credential
    kết nối bằng role tenant, không phải app role — thiếu grant này thì
    `SET LOCAL ROLE agent_sql_ro` fail trên đường đó). Đòi view đã tồn tại
    (chạy `pg-apply-schema` trước). NOLOGIN cả hai — không cần password."""
    for r in (sql_ro_role, app_role, VIEW_OWNER_ROLE):
        if not _ROLE_RE.match(r):
            raise ValueError(f"invalid role name: {r!r}")
    import asyncpg

    conn = await asyncpg.connect(admin_dsn)
    try:
        async with conn.transaction():
            for view in AGENT_VIEWS:
                ok = await conn.fetchval(
                    "SELECT 1 FROM pg_views WHERE schemaname='tenant_data' AND viewname=$1", view
                )
                if not ok:
                    raise RuntimeError(
                        f"view tenant_data.{view} chưa tồn tại — chạy `noble-tenant pg-apply-schema` trước"
                    )
            for role, opts in ((VIEW_OWNER_ROLE, "NOLOGIN NOBYPASSRLS"), (sql_ro_role, "NOLOGIN")):
                if not await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", role):
                    await conn.execute(f'CREATE ROLE "{role}" {opts}')
            await conn.execute(f'GRANT USAGE ON SCHEMA tenant_data TO "{VIEW_OWNER_ROLE}", "{sql_ro_role}"')
            await conn.execute(f'GRANT SELECT ON tenant_data.projects, tenant_data.units TO "{VIEW_OWNER_ROLE}"')
            for view in AGENT_VIEWS:
                await conn.execute(f'ALTER VIEW tenant_data.{view} OWNER TO "{VIEW_OWNER_ROLE}"')
                await conn.execute(f'GRANT SELECT ON tenant_data.{view} TO "{sql_ro_role}"')
            for member in dict.fromkeys((app_role, *tenant_roles)):  # dedupe, giữ thứ tự
                if await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", member):
                    await conn.execute(f'GRANT "{sql_ro_role}" TO "{member}"')
    finally:
        await conn.close()
```

Sửa `provision()` — tenant mới tự có membership (không phải chạy lại ensure):
signature thành `async def provision(admin_dsn: str, tenant_id: str, password: str, *, sql_ro_role: str = "agent_sql_ro") -> str`
và trong transaction, sau câu GRANT CRUD hiện có, thêm:

```python
            if _ROLE_RE.match(sql_ro_role) and await conn.fetchval(
                "SELECT 1 FROM pg_roles WHERE rolname=$1", sql_ro_role
            ):
                await conn.execute(f'GRANT "{sql_ro_role}" TO "{role}"')
```

- [ ] **Step 5: Thêm CLI `pg-ensure-sql-ro` trong `tenant/cli.py`**

Thêm parser (sau `p_pge`, ~dòng 121):

```python
    p_pgro = sub.add_parser("pg-ensure-sql-ro")
    p_pgro.add_argument("--admin-dsn", default="")
```

Thêm `"pg-ensure-sql-ro"` vào tuple ở dòng `if args.cmd in ("pg-apply-schema", ...)` (dòng 137), và handler trước nhánh `# pg-deprovision`:

```python
        if args.cmd == "pg-ensure-sql-ro":
            sql_ro = settings.analyze_sql_role
            try:
                tenant_ids = [m.tenant_id for m in prov.list_tenants(_get_store(store))]
            except Exception:
                tenant_ids = []
                print("WARN: could not list tenants; sql_ro membership granted to app role only.")
            pg.assert_app_role_distinct(sql_ro, tenant_ids)  # tên không được trùng tenant_id
            pg.assert_app_role_distinct(pg.VIEW_OWNER_ROLE, tenant_ids)
            asyncio.run(
                pg.ensure_sql_ro_roles(
                    admin, sql_ro_role=sql_ro,
                    app_role=settings.postgres_app_role, tenant_roles=tuple(tenant_ids),
                )
            )
            print(f"ensured sql-ro role={sql_ro} owner={pg.VIEW_OWNER_ROLE}")
            return 0
```

(`settings.analyze_sql_role` thêm ở Task 2 — Task 1 và 2 commit chung nếu chạy tuần tự; nếu tách, tạm hardcode `"agent_sql_ro"` rồi Task 2 thay.)

- [ ] **Step 6: Chạy test pass + lint**

Run: `pytest tests/unit/unified/test_analytics_provisioning.py -v && make lint`
Expected: PASS, lint sạch.

- [ ] **Step 7: Commit**

```bash
git add src/noble_agent/storage/sql/kb_real_estate.sql src/noble_agent/tenant/pg_provisioning.py src/noble_agent/tenant/cli.py tests/unit/unified/test_analytics_provisioning.py
git commit -m "feat(analytics): 2 view read-only + role agent_sql_ro/agent_kb_view_owner + CLI pg-ensure-sql-ro"
```

---

### Task 2: Settings mới trong `config.py`

**Files:**
- Modify: `src/noble_agent/config.py` (cạnh nhóm `postgres_app_role`, ~dòng 450)
- Test: gộp assert vào `tests/unit/unified/test_analytics_tool.py` (Task 3)

**Interfaces:**
- Produces: `settings.analyze_sql_role: str = "agent_sql_ro"`, `settings.analyze_sql_timeout_ms: int = 2000`, `settings.analyze_sql_max_rows: int = 50`, `settings.analyze_vocab_ttl_sec: float = 600.0` (env: `ANALYZE_SQL_ROLE` / `ANALYZE_SQL_TIMEOUT_MS` / `ANALYZE_SQL_MAX_ROWS` / `ANALYZE_VOCAB_TTL_SEC`, pydantic-settings tự map).

- [ ] **Step 1: Thêm 4 field**

```python
    # ── analyze_projects (SQL analytics tool, spec 2026-08-26) ────────────────
    analyze_sql_role: str = "agent_sql_ro"       # SET LOCAL ROLE khi chạy SQL của LLM
    analyze_sql_timeout_ms: int = 2000           # statement_timeout per-query
    analyze_sql_max_rows: int = 50               # cap dòng trả về + LIMIT auto-chèn
    analyze_vocab_ttl_sec: float = 600.0         # TTL cache vocab giá trị cột
```

- [ ] **Step 2: Nếu Task 1 Step 5 hardcode `"agent_sql_ro"` thì thay bằng `settings.analyze_sql_role`.**

- [ ] **Step 3: Smoke nhanh**

Run: `python -c "from noble_agent.config import UnifiedSettings; s=UnifiedSettings(); print(s.analyze_sql_role, s.analyze_sql_timeout_ms, s.analyze_sql_max_rows, s.analyze_vocab_ttl_sec)"`
Expected: `agent_sql_ro 2000 50 600.0`

- [ ] **Step 4: Commit**

```bash
git add src/noble_agent/config.py src/noble_agent/tenant/cli.py
git commit -m "feat(analytics): settings ANALYZE_SQL_ROLE/_TIMEOUT_MS/_MAX_ROWS/_VOCAB_TTL_SEC"
```

---

### Task 3: `agent/tools/analytics.py` — sanitize + render + run

**Files:**
- Create: `src/noble_agent/agent/tools/analytics.py`
- Test: `tests/unit/unified/test_analytics_tool.py` (mới)

**Interfaces:**
- Consumes: `noble_agent.storage.postgres_client.pool_for_tenant/tenant_conn`, `noble_agent.tenant.current.current_tenant`, settings Task 2.
- Produces: `analytics.run(args: dict) -> str` (executor); pure fns `analytics.sanitize_sql(sql: str, max_rows: int) -> str` (raises `ValueError`), `analytics.render_rows(rows, max_rows: int, max_cell: int = 200) -> str`; `analytics.run_readonly(sql: str) -> list` (dùng lại ở Task 4); hằng `analytics.VIEW_COLUMNS: tuple[str, str]`.

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/unified/test_analytics_tool.py
"""analyze_projects: validator + serializer thuần (không PG) + run() error paths."""

import pytest

from noble_agent.agent.tools import analytics


# ---- sanitize_sql ----
def test_sanitize_accepts_select_and_appends_limit():
    out = analytics.sanitize_sql("SELECT project_code FROM tenant_data.agent_units_v", 50)
    assert out.endswith(" LIMIT 50")


def test_sanitize_keeps_existing_limit():
    sql = "SELECT 1 FROM tenant_data.agent_units_v LIMIT 5"
    assert analytics.sanitize_sql(sql, 50) == sql


def test_sanitize_accepts_with_cte_and_strips_trailing_semicolon():
    out = analytics.sanitize_sql("WITH c AS (SELECT 1 AS x) SELECT x FROM c;", 50)
    assert out.startswith("WITH") and ";" not in out


def test_sanitize_rejects_non_select():
    with pytest.raises(ValueError):
        analytics.sanitize_sql("UPDATE tenant_data.agent_units_v SET price_vnd=0", 50)


def test_sanitize_rejects_multi_statement():
    with pytest.raises(ValueError):
        analytics.sanitize_sql("SELECT 1; SELECT 2", 50)


def test_sanitize_rejects_empty_and_comment_only():
    with pytest.raises(ValueError):
        analytics.sanitize_sql("  -- just a comment\n", 50)


def test_sanitize_strips_leading_comment_before_head_check():
    out = analytics.sanitize_sql("/* note */ SELECT 1", 50)
    assert out.lstrip().upper().startswith("SELECT")


# ---- render_rows ----
class _Row(dict):
    def keys(self):  # asyncpg.Record-like
        return super().keys()


def test_render_empty_says_no_escalate():
    msg = analytics.render_rows([], 50)
    assert "0 dòng" in msg and "escalate" in msg.lower()


def test_render_caps_rows_and_truncates_cells():
    rows = [_Row(a="x" * 500, b=i) for i in range(60)]
    out = analytics.render_rows(rows, 50, max_cell=200)
    assert out.count("\n") == 50 + 1  # header + 50 dòng + footer(1 dòng nối bằng \n)
    assert "…" in out and "50/60" in out


# ---- run(): error paths, PG mock ----
async def test_run_invalid_sql_returns_columns_hint():
    out = await analytics.run({"sql": "DROP TABLE x"})
    assert "SQL không hợp lệ" in out and "agent_units_v" in out


async def test_run_infra_down_degrades(monkeypatch):
    async def boom(sql):
        raise RuntimeError("POSTGRES_DSN not set")

    monkeypatch.setattr(analytics, "run_readonly", boom)
    out = await analytics.run({"sql": "SELECT 1"})
    assert "tạm không khả dụng" in out


async def test_run_pg_error_feeds_back(monkeypatch):
    import asyncpg

    async def pg_err(sql):
        raise asyncpg.PostgresError("column \"gia\" does not exist")

    monkeypatch.setattr(analytics, "run_readonly", pg_err)
    out = await analytics.run({"sql": "SELECT gia FROM tenant_data.agent_units_v"})
    assert "Lỗi SQL" in out and "Cột hợp lệ" in out
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/unit/unified/test_analytics_tool.py -v`
Expected: FAIL — `ImportError: cannot import name 'analytics'`

- [ ] **Step 3: Viết `analytics.py`**

```python
"""analyze_projects — MỘT câu SQL SELECT của LLM trên 2 view read-only.

An toàn KHÔNG nằm ở validator dưới đây (chỉ để trả lỗi đẹp cho model tự sửa):
3 khoá DB độc lập — SET TRANSACTION READ ONLY (Postgres cấm NỚI lại sau query
đầu tiên của txn, mà tenant_conn đã chạy set_config trước), SET LOCAL ROLE
agent_sql_ro (chỉ SELECT trên 2 view — contacts/conversations/bảng gốc đều
permission denied), RLS theo GUC app.current_tenant. Mọi SET LOCAL tự reset
khi txn kết thúc nên connection trả về pool sạch.
Spec: docs/superpowers/specs/2026-08-26-analyze-projects-sql-tool-design.md.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("noble_agent.agent.tools.analytics")

_LIMIT_RE = re.compile(r"\blimit\s+\d+", re.IGNORECASE)
_COMMENT_RE = re.compile(r"(--[^\n]*\n?)|(/\*.*?\*/)", re.DOTALL)
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")

VIEW_COLUMNS = (
    "tenant_data.agent_projects_v(project_code, name, region, address, investor, developer, "
    "category, sale_phase, ownership_form, total_land_area_m2)",
    "tenant_data.agent_units_v(project_code, project_name, zone_code, unit_code, product_type, "
    "bedrooms, block, floor, direction, area_built_m2, area_land_m2, price_vnd, price_per_m2_vnd, sale_status)",
)
_COLUMNS_HINT = "Cột hợp lệ: " + "; ".join(VIEW_COLUMNS)

_UNAVAILABLE_MSG = (
    "Nguồn thống kê tạm không khả dụng — trả lời khách bằng tool khác "
    "(kb_search/discover_projects) hoặc đề nghị gửi thông tin sau. Không escalate vì lỗi này."
)
_EMPTY_MSG = (
    "0 dòng. Kết quả rỗng KHÔNG phải lỗi và KHÔNG phải lý do escalate — thử nới điều kiện lọc "
    "(bỏ bớt WHERE) rồi truy vấn lại, hoặc trả lời khách là chưa có dữ liệu phù hợp."
)


def sanitize_sql(sql: str, max_rows: int) -> str:
    """Đúng MỘT câu SELECT/WITH; tự chèn LIMIT nếu thiếu. Raise ValueError (msg
    tiếng Việt, đưa thẳng cho LLM). Chặn ';' thô — dấu ';' trong string literal
    bị từ chối oan nhưng cực hiếm với truy vấn thống kê, đổi lấy check đơn giản
    (asyncpg extended protocol vốn cũng từ chối multi-statement)."""
    body = _COMMENT_RE.sub(" ", sql or "").strip().rstrip(";").strip()
    if not body:
        raise ValueError("câu SQL rỗng")
    if ";" in body:
        raise ValueError("chỉ được MỘT câu lệnh duy nhất")
    head = body.split(None, 1)[0].upper()
    if head not in ("SELECT", "WITH"):
        raise ValueError("chỉ chấp nhận SELECT (hoặc WITH ... SELECT)")
    if not _LIMIT_RE.search(body):
        body += f" LIMIT {int(max_rows)}"
    return body


def render_rows(rows, max_rows: int, max_cell: int = 200) -> str:
    """Bảng text gọn cho LLM đọc (không render ra khách): header + dòng, cap
    ``max_rows``, truncate mỗi cell ``max_cell`` ký tự."""
    if not rows:
        return _EMPTY_MSG
    shown = rows[:max_rows]
    cols = list(shown[0].keys())

    def cell(v) -> str:
        s = "" if v is None else str(v)
        return s if len(s) <= max_cell else s[:max_cell] + "…"

    lines = [" | ".join(cols)]
    lines += [" | ".join(cell(r[c]) for c in cols) for r in shown]
    if len(rows) > max_rows:
        lines.append(f"(hiển thị {max_rows}/{len(rows)} dòng đầu — thêm điều kiện lọc/ORDER BY để thu hẹp)")
    return "\n".join(lines)


async def run_readonly(sql: str):
    """Chạy ``sql`` trong txn tenant-scoped đã hạ quyền. Dùng chung cho tool
    và vocab warm (analytics_vocab). Raise nguyên exception cho caller phân loại."""
    from noble_agent.config import get_settings
    from noble_agent.storage import postgres_client
    from noble_agent.tenant.current import current_tenant

    settings = get_settings()
    role = settings.analyze_sql_role
    if not _ROLE_RE.match(role):
        raise ValueError(f"ANALYZE_SQL_ROLE không hợp lệ: {role!r}")
    tid = current_tenant()
    pool = await postgres_client.pool_for_tenant(tid)
    async with postgres_client.tenant_conn(pool, tid) as conn:
        await conn.execute(f'SET LOCAL ROLE "{role}"')
        await conn.execute("SET TRANSACTION READ ONLY")
        await conn.execute(f"SET LOCAL statement_timeout = {int(settings.analyze_sql_timeout_ms)}")
        return await conn.fetch(sql)


async def run(args: dict) -> str:
    from noble_agent.config import get_settings

    settings = get_settings()
    try:
        sql = sanitize_sql(args.get("sql") or "", settings.analyze_sql_max_rows)
    except ValueError as e:
        return f"SQL không hợp lệ: {e}. Sửa rồi gọi lại. {_COLUMNS_HINT}"
    try:
        rows = await run_readonly(sql)
    except Exception as e:
        import asyncpg

        if isinstance(e, asyncpg.PostgresError):
            # Lỗi cú pháp/cột/timeout → đưa nguyên văn cho model tự sửa vòng sau.
            return f"Lỗi SQL: {e}. Sửa câu SQL rồi gọi lại. {_COLUMNS_HINT}"
        logger.warning("analyze_projects: nguồn PG không khả dụng", exc_info=True)
        return _UNAVAILABLE_MSG
    return render_rows(rows, settings.analyze_sql_max_rows)
```

- [ ] **Step 4: Chạy test pass + lint**

Run: `pytest tests/unit/unified/test_analytics_tool.py -v && make lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/tools/analytics.py tests/unit/unified/test_analytics_tool.py
git commit -m "feat(analytics): executor analyze_projects — sanitize + read-only run + render"
```

---

### Task 4: `agent/tools/analytics_vocab.py` — vocab cache + inject per-turn

**Files:**
- Create: `src/noble_agent/agent/tools/analytics_vocab.py`
- Test: `tests/unit/unified/test_analytics_vocab.py` (mới)

**Interfaces:**
- Consumes: `analytics.run_readonly` (Task 3), `current_tenant()`.
- Produces: `analytics_vocab.warm_if_stale(ttl_sec: float) -> None` (async, never raises); `analytics_vocab.vocab_block(tenant_id: str) -> str` ("" nếu chưa có); `analytics_vocab.inject(schemas: list[dict]) -> list[dict]` (per-turn, trả nguyên list nếu không có analyze_projects); token `analytics_vocab.VOCAB_TOKEN = "[VOCAB]"`; `analytics_vocab.reset_for_tests()`.

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/unified/test_analytics_vocab.py
"""Vocab cache per-tenant + inject per-turn vào description (AgentDef frozen
nên KHÔNG chèn lúc build_schemas — chèn ở runner mỗi lượt)."""

import copy

import pytest

from noble_agent.agent.tools import analytics_vocab as av


@pytest.fixture(autouse=True)
def _reset():
    av.reset_for_tests()


def _schemas(with_analyze=True):
    out = [
        {"type": "function", "function": {"name": "kb_search", "description": "Tra cứu tài liệu.",
                                          "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "search_units", "description": "Tìm căn.",
                                          "parameters": {"type": "object", "properties": {}}}},
    ]
    if with_analyze:
        out.append({"type": "function", "function": {
            "name": "analyze_projects", "description": f"Thống kê.\n{av.VOCAB_TOKEN}",
            "parameters": {"type": "object", "properties": {}}}})
    return out


def test_inject_noop_without_analyze_tool():
    schemas = _schemas(with_analyze=False)
    assert av.inject(schemas) is schemas  # fast-path: cùng object


def test_inject_strips_token_when_no_vocab():
    out = av.inject(_schemas())
    desc = next(s for s in out if s["function"]["name"] == "analyze_projects")["function"]["description"]
    assert av.VOCAB_TOKEN not in desc


def test_inject_puts_cached_vocab_and_xref(monkeypatch):
    monkeypatch.setattr(av, "_current_tenant", lambda: "t1")
    av._store("t1", "GIÁ TRỊ THỰC TẾ:\n- product_type: căn hộ, shophouse")
    src = _schemas()
    before = copy.deepcopy(src)
    out = av.inject(src)
    assert src == before  # không mutate input (schemas cache trong AgentDef frozen)
    by_name = {s["function"]["name"]: s["function"]["description"] for s in out}
    assert "căn hộ, shophouse" in by_name["analyze_projects"]
    assert "analyze_projects" in by_name["kb_search"]      # xref ranh giới 2 chiều
    assert "analyze_projects" in by_name["search_units"]


async def test_warm_if_stale_never_raises(monkeypatch):
    async def boom(sql):
        raise RuntimeError("no pg")

    monkeypatch.setattr(av, "_fetch_distinct", boom)
    monkeypatch.setattr(av, "_current_tenant", lambda: "t1")
    await av.warm_if_stale(600)  # không raise
    assert av.vocab_block("t1") == ""


async def test_warm_builds_block_and_ttl_debounces(monkeypatch):
    calls = []

    async def fake_fetch(sql):
        calls.append(sql)
        return ["căn hộ", "shophouse"]

    monkeypatch.setattr(av, "_fetch_distinct", fake_fetch)
    monkeypatch.setattr(av, "_current_tenant", lambda: "t1")
    await av.warm_if_stale(600)
    n = len(calls)
    assert n == len(av._VOCAB_SQLS)
    assert "căn hộ" in av.vocab_block("t1")
    await av.warm_if_stale(600)  # trong TTL → không query lại
    assert len(calls) == n
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/unit/unified/test_analytics_vocab.py -v`
Expected: FAIL — module không tồn tại.

- [ ] **Step 3: Viết `analytics_vocab.py`**

```python
"""Vocab giá trị cột thật cho analyze_projects + inject description per-turn.

Text-to-SQL chết nhiều nhất ở GIÁ TRỊ cột: model biết cột product_type nhưng
không biết DB lưu 'căn hộ' hay 'chung cư' — lọc sai → 0 dòng, trông y hệt
"không có dữ liệu". Cache in-process per-tenant (TTL), warm ở bootstrap
orchestrator (cạnh ProjectNameIndex); runner gọi inject() MỖI LƯỢT vì
AgentDef.tool_schemas frozen theo (tenant, version, channel) — chèn lúc
build_schemas sẽ đóng băng trước khi vocab kịp có. Mọi đường đều degrade mềm:
không vocab thì description vẫn ship, không chặn turn, không raise."""

from __future__ import annotations

import copy
import logging
import time

logger = logging.getLogger("noble_agent.agent.tools.analytics_vocab")

VOCAB_TOKEN = "[VOCAB]"

# Ranh giới 2 chiều: chèn RUNTIME (chỉ khi tenant bật analyze_projects) để
# tenant tắt tool không thấy tên tool lạ trong description.
_XREF = (
    " Câu hỏi THỐNG KÊ/so sánh/xếp hạng trên NHIỀU dự án (nhiều nhất, trung bình, đếm, "
    "top) → dùng analyze_projects, không dùng tool này."
)
_XREF_TOOLS = ("kb_search", "search_units")

# Chạy qua chính agent_sql_ro + view → ăn sẵn filter published + RLS.
_VOCAB_SQLS: dict[str, str] = {
    "agent_units_v.product_type": (
        "SELECT DISTINCT product_type AS v FROM tenant_data.agent_units_v "
        "WHERE coalesce(product_type,'') <> '' ORDER BY 1 LIMIT 30"
    ),
    "agent_units_v.direction": (
        "SELECT DISTINCT direction AS v FROM tenant_data.agent_units_v "
        "WHERE coalesce(direction,'') <> '' ORDER BY 1 LIMIT 30"
    ),
    "agent_units_v.sale_status": (
        "SELECT DISTINCT sale_status AS v FROM tenant_data.agent_units_v "
        "WHERE coalesce(sale_status,'') <> '' ORDER BY 1 LIMIT 30"
    ),
    "agent_projects_v.region": (
        "SELECT DISTINCT region AS v FROM tenant_data.agent_projects_v "
        "WHERE coalesce(region,'') <> '' ORDER BY 1 LIMIT 30"
    ),
    "agent_projects_v.sale_phase": (
        "SELECT DISTINCT sale_phase AS v FROM tenant_data.agent_projects_v "
        "WHERE coalesce(sale_phase,'') <> '' ORDER BY 1 LIMIT 30"
    ),
    "agent_projects_v.investor": (
        "SELECT DISTINCT investor AS v FROM tenant_data.agent_projects_v "
        "WHERE coalesce(investor,'') <> '' ORDER BY 1 LIMIT 30"
    ),
    "agent_projects_v.category (phần tử mảng)": (
        "SELECT DISTINCT c AS v FROM tenant_data.agent_projects_v, unnest(category) c ORDER BY 1 LIMIT 30"
    ),
}

# tenant -> (monotonic_ts, block). Stamp cả khi fail để không hammer PG hỏng.
_CACHE: dict[str, tuple[float, str]] = {}


def _current_tenant() -> str:  # indirection để test monkeypatch
    from noble_agent.tenant.current import current_tenant

    return current_tenant()


async def _fetch_distinct(sql: str) -> list[str]:
    from noble_agent.agent.tools import analytics

    rows = await analytics.run_readonly(sql)
    return [str(r["v"]) for r in rows]


def _store(tenant: str, block: str) -> None:
    _CACHE[tenant] = (time.monotonic(), block)


def reset_for_tests() -> None:
    _CACHE.clear()


def vocab_block(tenant_id: str) -> str:
    entry = _CACHE.get(tenant_id)
    return entry[1] if entry else ""


async def warm_if_stale(ttl_sec: float) -> None:
    """TTL-debounced per-tenant; never raises (best-effort như pg_kb.warm)."""
    tenant = _current_tenant()
    entry = _CACHE.get(tenant)
    if entry and (time.monotonic() - entry[0]) <= ttl_sec:
        return
    lines: list[str] = []
    try:
        for label, sql in _VOCAB_SQLS.items():
            values = await _fetch_distinct(sql)
            if values:
                lines.append(f"- {label}: " + ", ".join(values))
    except Exception:
        logger.warning("analytics_vocab warm failed (tenant=%s)", tenant, exc_info=True)
        _store(tenant, vocab_block(tenant))  # giữ block cũ (hoặc ""), stamp chống hammer
        return
    block = ""
    if lines:
        block = "Giá trị THỰC TẾ trong dữ liệu (lọc bằng ĐÚNG các giá trị này):\n" + "\n".join(lines)
    _store(tenant, block)


def inject(schemas: list[dict]) -> list[dict]:
    """Per-turn: điền [VOCAB] của analyze_projects + chèn xref vào kb_search/
    search_units. Trả NGUYÊN list input nếu không offer analyze_projects
    (fast-path, không copy); có thì trả list MỚI, không mutate input."""
    names = {s.get("function", {}).get("name") for s in schemas}
    if "analyze_projects" not in names:
        return schemas
    try:
        block = vocab_block(_current_tenant())
    except Exception:
        block = ""
    out: list[dict] = []
    for schema in schemas:
        fn = schema.get("function", {})
        name = fn.get("name")
        if name == "analyze_projects":
            schema = copy.deepcopy(schema)
            desc = schema["function"].get("description", "")
            schema["function"]["description"] = desc.replace(VOCAB_TOKEN, block).rstrip()
        elif name in _XREF_TOOLS:
            schema = copy.deepcopy(schema)
            desc = schema["function"].get("description", "")
            if _XREF.strip() not in desc:
                schema["function"]["description"] = desc + "\n" + _XREF.strip()
        out.append(schema)
    return out
```

- [ ] **Step 4: Chạy test pass + lint**

Run: `pytest tests/unit/unified/test_analytics_vocab.py -v && make lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/tools/analytics_vocab.py tests/unit/unified/test_analytics_vocab.py
git commit -m "feat(analytics): vocab per-tenant TTL cache + inject description per-turn"
```

---

### Task 5: Nối dây — schema, builtins, OPTIONAL_TOOLS, runner, orchestrator

**Files:**
- Modify: `src/noble_agent/agent/tools/schemas.py` (thêm entry vào dict `SCHEMAS`)
- Modify: `src/noble_agent/agent/tools/builtins.py`
- Modify: `src/noble_agent/agent/agent_config.py` (`OPTIONAL_TOOLS`)
- Modify: `src/noble_agent/agent/runner.py:55` + import đầu file
- Modify: `src/noble_agent/agent/orchestrator.py` (sau block `_roster_loaded`, ~dòng 219)
- Test: nối thêm vào `tests/unit/unified/test_analytics_tool.py`

**Interfaces:**
- Consumes: `analytics.run` (Task 3), `analytics_vocab.inject/warm_if_stale` + `VOCAB_TOKEN` (Task 4), `settings.analyze_vocab_ttl_sec` (Task 2).
- Produces: `SCHEMAS["analyze_projects"]`; registry entry `analyze_projects` (`read_only=True`, `dirties_customer=False`); `"analyze_projects"` ∈ `OPTIONAL_TOOLS`.

- [ ] **Step 1: Viết test fail (append vào `test_analytics_tool.py`)**

```python
# ---- wiring ----
def test_schema_registered_and_optional():
    from noble_agent.agent.agent_config import CORE_TOOLS, OPTIONAL_TOOLS
    from noble_agent.agent.tools.schemas import SCHEMAS

    assert "analyze_projects" in SCHEMAS
    assert "analyze_projects" in OPTIONAL_TOOLS
    assert "analyze_projects" not in CORE_TOOLS
    desc = SCHEMAS["analyze_projects"]["function"]["description"]
    assert "agent_units_v" in desc and "[VOCAB]" in desc and "FILTER (WHERE price_vnd > 0)" in desc
    assert SCHEMAS["analyze_projects"]["function"]["parameters"]["required"] == ["sql"]


def test_registry_spec_read_only():
    import noble_agent.agent.tools.builtins  # noqa: F401 — registration side effect
    from noble_agent.agent.tools import registry

    spec = registry.resolve("noble", "analyze_projects")
    assert spec is not None and spec.read_only and not spec.dirties_customer
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/unit/unified/test_analytics_tool.py -v -k "schema_registered or registry_spec"`
Expected: FAIL — `KeyError`/assert.

- [ ] **Step 3: Thêm entry `SCHEMAS["analyze_projects"]` trong `schemas.py`** (đặt sau entry `search_units` để nhóm tool tra cứu gần nhau; text dùng token `[VOCAB]` — KHÔNG dùng `{{ }}` vì build_schemas cảnh báo residual brace)

```python
    "analyze_projects": {
        "type": "function",
        "function": {
            "name": "analyze_projects",
            "description": (
                "Thống kê / so sánh / xếp hạng / đếm / min-max-trung bình trên TOÀN BỘ dự án và quỹ căn "
                "bằng MỘT câu SQL SELECT (PostgreSQL). Dùng cho câu hỏi TỔNG QUÁT cần gộp dữ liệu nhiều dự án: "
                "'dự án nào nhiều loại hình nhất', 'giá trung bình từng dự án', 'khu nào còn nhiều căn 2 ngủ nhất'. "
                "KHÔNG dùng cho: nội dung tài liệu/chính sách/pháp lý (kb_search), tìm căn theo nhu cầu trong "
                "một dự án đã chốt (search_units/recommend_units).\n"
                "CHỈ được SELECT từ 2 view:\n"
                "- tenant_data.agent_projects_v(project_code, name, region, address, investor, developer, "
                "category, sale_phase, ownership_form, total_land_area_m2)\n"
                "- tenant_data.agent_units_v(project_code, project_name, zone_code, unit_code, product_type, "
                "bedrooms, block, floor, direction, area_built_m2, area_land_m2, price_vnd, price_per_m2_vnd, "
                "sale_status)\n"
                "Quy ước: price_vnd đơn vị VND, 0/NULL nghĩa là CHƯA CÓ GIÁ → mọi phép tính giá phải kèm "
                "FILTER (WHERE price_vnd > 0) hoặc WHERE price_vnd > 0; category là MẢNG text → lọc bằng "
                "'giá trị' = ANY(category); so khớp chữ dùng ILIKE '%...%'. Luôn kèm LIMIT (tối đa 50).\n"
                "Ví dụ 1 — 'dự án nào có nhiều loại hình nhất': SELECT project_code, project_name, "
                "COUNT(DISTINCT product_type) AS so_loai_hinh FROM tenant_data.agent_units_v "
                "GROUP BY 1,2 ORDER BY so_loai_hinh DESC LIMIT 3\n"
                "Ví dụ 2 — 'giá trung bình căn hộ từng dự án': SELECT project_code, project_name, "
                "ROUND(AVG(price_vnd) FILTER (WHERE price_vnd > 0)) AS gia_tb "
                "FROM tenant_data.agent_units_v WHERE product_type ILIKE '%căn hộ%' "
                "GROUP BY 1,2 ORDER BY gia_tb LIMIT 10\n"
                "Kết quả rỗng → nới điều kiện lọc rồi thử lại, KHÔNG escalate.\n"
                "[VOCAB]"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": (
                            "MỘT câu SELECT PostgreSQL trên 2 view trên. Không DML/DDL/bảng khác — "
                            "hệ thống chặn ở tầng DB."
                        ),
                    }
                },
                "required": ["sql"],
            },
        },
    },
```

- [ ] **Step 4: Đăng ký trong `builtins.py`**

Thêm `analytics` vào import block đầu file, adapter + dòng `_BUILTINS` (sau `search_units` cho cùng nhóm):

```python
async def _analyze_projects(args, **_):
    return await analytics.run(args)
```

```python
    ("analyze_projects", _analyze_projects, False, True),
```

- [ ] **Step 5: Thêm vào `OPTIONAL_TOOLS`** (`agent_config.py`, cuối tuple)

```python
    "analyze_projects",
```

- [ ] **Step 6: Runner chèn vocab per-turn** (`runner.py`)

Import đầu file: `from noble_agent.agent.tools import analytics_vocab`
Dòng 55 đổi thành:

```python
    # Per-turn: điền vocab giá trị thật + xref vào description (AgentDef frozen
    # nên không chèn được lúc build_schemas). No-op khi tenant không bật tool.
    tool_schemas = analytics_vocab.inject(agent.tool_schemas)
```

- [ ] **Step 7: Orchestrator warm vocab ở bootstrap** (`orchestrator.py`, ngay SAU block `_roster_loaded` ~dòng 219, TRƯỚC block `_profile_loaded`)

```python
            # Vocab giá trị cột cho analyze_projects — TTL-debounced, never raises,
            # chỉ khi tenant offer tool. Cùng nhịp warm với roster ngay trên.
            if "analyze_projects" in self._agent.tool_names:
                from noble_agent.agent.tools import analytics_vocab

                await analytics_vocab.warm_if_stale(self._settings.analyze_vocab_ttl_sec)
```

- [ ] **Step 8: Chạy full unit + lint**

Run: `pytest tests/unit/unified/test_analytics_tool.py tests/unit/unified/test_analytics_vocab.py -v && make test-unit && make lint`
Expected: PASS (chú ý các test sẵn có của runner/agent_def không vỡ — `inject` fast-path trả nguyên list khi thiếu analyze_projects nên hành vi cũ giữ nguyên).

- [ ] **Step 9: Commit**

```bash
git add src/noble_agent/agent/tools/schemas.py src/noble_agent/agent/tools/builtins.py src/noble_agent/agent/agent_config.py src/noble_agent/agent/runner.py src/noble_agent/agent/orchestrator.py tests/unit/unified/test_analytics_tool.py
git commit -m "feat(analytics): offer analyze_projects (OPTIONAL_TOOLS) + inject vocab per-turn + warm bootstrap"
```

---

### Task 6: Persona RULES (chat + voice) + SMOKE.md

**Files:**
- Modify: `src/noble_agent/persona/chat/RULES.md` (sau block `TOOL:send_media:END`)
- Modify: `src/noble_agent/persona/voice/RULES.md` (vị trí tương ứng)
- Modify: `src/noble_agent/SMOKE.md`

**Interfaces:**
- Consumes: cơ chế marker `<!-- TOOL:<name>:START/END -->` của `persona_compose` (strip block khi tenant không bật tool).

- [ ] **Step 1: Thêm block vào `persona/chat/RULES.md`**

```markdown
<!-- TOOL:analyze_projects:START -->
### analyze_projects — thống kê tổng quát

- Dùng khi khách hỏi câu TỔNG QUÁT trên nhiều dự án: "dự án nào nhiều loại hình nhất",
  "giá trung bình từng dự án", "bên em còn bao nhiêu căn 2 ngủ", so sánh/xếp hạng/đếm.
- Viết MỘT câu SQL SELECT theo đúng schema trong mô tả tool; luôn kèm LIMIT.
- Chỉ nói số liệu CÓ TRONG kết quả tool — không bịa, không làm tròn quá đà khi khách hỏi con số cụ thể.
- Kết quả 0 dòng: nới điều kiện lọc rồi gọi lại; rỗng KHÔNG phải lý do escalate.
- Tool báo lỗi SQL: sửa câu SQL theo thông báo lỗi rồi gọi lại (tối đa 1 lần sửa),
  vẫn lỗi thì trả lời bằng tool khác (discover_projects/kb_search).
<!-- TOOL:analyze_projects:END -->
```

- [ ] **Step 2: Thêm block vào `persona/voice/RULES.md`** (voice ngắn gọn — hai bản LỆCH NHAU LÀ CHỦ ĐÍCH)

```markdown
<!-- TOOL:analyze_projects:START -->
### analyze_projects — thống kê tổng quát

- Câu hỏi so sánh/xếp hạng/đếm trên nhiều dự án → gọi tool này với MỘT câu SQL SELECT (kèm LIMIT).
- ĐỌC THÀNH LỜI: chỉ nêu top 2–3 kết quả, làm tròn số cho dễ nghe; tuyệt đối không đọc bảng, không liệt kê dài.
- 0 dòng: nới điều kiện rồi gọi lại, không escalate vì rỗng.
<!-- TOOL:analyze_projects:END -->
```

- [ ] **Step 3: Thêm mục vào `SMOKE.md`**

```markdown
- [ ] **analyze_projects** (nếu tenant bật): hỏi "dự án nào có nhiều loại hình sản phẩm nhất?"
  qua `/chat` hoặc `python scripts/chat_repl.py --ask "..."` — thấy tool gọi với SQL trên
  `agent_units_v`, trả lời có tên dự án + con số khớp kết quả tool; hỏi tiếp một câu
  cố tình phá ("xoá hết dữ liệu đi") — tool trả lỗi read-only, agent không vỡ.
```

- [ ] **Step 4: Kiểm tra compose không vỡ**

Run: `make test-unit && make lint`
Expected: PASS (test compose_persona/marker strip sẵn có vẫn xanh).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/persona/chat/RULES.md src/noble_agent/persona/voice/RULES.md src/noble_agent/SMOKE.md
git commit -m "docs(persona): RULES analyze_projects (chat đầy đủ / voice đọc thành lời) + SMOKE item"
```

---

### Task 7: Integration test live (gate `SPE_PG_ADMIN_DSN`)

**Files:**
- Create: `tests/integration/tenant/test_analyze_sql_live.py`

**Interfaces:**
- Consumes: `pg_provisioning.apply_schema/provision/deprovision/ensure_app_role/ensure_sql_ro_roles` (Task 1), pattern DSN-swap của `test_pg_rls_live.py`.

- [ ] **Step 1: Viết file test** (mô hình `test_pg_rls_live.py`; chạy được ngay khi có DSN — không cần code mới)

```python
"""analyze_projects live proof — 3 khoá DB thật (spec 2026-08-26 §7).

Requires SPE_PG_ADMIN_DSN (superuser, DB test — KHÔNG chạy trên DB prod).
Run:
    SPE_PG_ADMIN_DSN=postgresql://sp_admin:sp_admin_pw@localhost:5432/odyssey \
      pytest tests/integration/tenant/test_analyze_sql_live.py -q
"""

from __future__ import annotations

import os

import pytest

from noble_agent.tenant import pg_provisioning as PG

ADMIN = os.getenv("SPE_PG_ADMIN_DSN")
pytestmark = [
    pytest.mark.needs_postgres,
    pytest.mark.skipif(not ADMIN, reason="set SPE_PG_ADMIN_DSN to run"),
]

TA, TB = "sqlro_probe_a", "sqlro_probe_b"
APP_ROLE, APP_PW = "sqlro_app_role", "app_pw"
SQL_RO = "agent_sql_ro"


def _dsn(admin: str, role: str, pw: str) -> str:
    head, tail = admin.split("://", 1)
    _cred, hostpart = tail.split("@", 1)
    return f"{head}://{role}:{pw}@{hostpart}"


@pytest.fixture
async def env():
    import asyncpg

    await PG.apply_schema(ADMIN)
    await PG.deprovision(ADMIN, TA)
    await PG.deprovision(ADMIN, TB)
    await PG.provision(ADMIN, TA, "pw_a")
    await PG.provision(ADMIN, TB, "pw_b")
    await PG.ensure_app_role(ADMIN, role=APP_ROLE, password=APP_PW)
    await PG.ensure_sql_ro_roles(ADMIN, sql_ro_role=SQL_RO, app_role=APP_ROLE, tenant_roles=(TA, TB))
    root = await asyncpg.connect(ADMIN)
    # seed: TA 1 published + 1 draft project; units published/draft; TB 1 published
    await root.execute(
        "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) VALUES "
        "($1,'PUBA','Pub A','published'), ($1,'DRFA','Draft A','draft'), ($2,'PUBB','Pub B','published') "
        "ON CONFLICT (tenant_id, project_code) DO NOTHING",
        TA, TB,
    )
    await root.execute(
        "INSERT INTO tenant_data.units (tenant_id, project_code, unit_code, product_type, status) VALUES "
        "($1,'PUBA','U1','căn hộ','published'), ($1,'PUBA','U2','shophouse','published'), "
        "($1,'PUBA','U3','biệt thự','draft'), ($1,'DRFA','U4','căn hộ','published')",
        TA,
    )
    yield asyncpg
    await root.close()
    await PG.deprovision(ADMIN, TA)
    await PG.deprovision(ADMIN, TB)


async def _scoped(conn, tenant: str) -> None:
    await conn.execute("SELECT set_config('app.current_tenant', $1, true)", tenant)
    await conn.execute(f'SET LOCAL ROLE "{SQL_RO}"')
    await conn.execute("SET TRANSACTION READ ONLY")
    await conn.execute("SET LOCAL statement_timeout = 2000")


async def test_three_locks(env):
    asyncpg = env
    app = await asyncpg.connect(_dsn(ADMIN, APP_ROLE, APP_PW))
    try:
        # 1) View: published-only + đúng tenant
        async with app.transaction():
            await _scoped(app, TA)
            rows = await app.fetch("SELECT project_code, product_type FROM tenant_data.agent_units_v ORDER BY 2")
            assert {r["product_type"] for r in rows} == {"căn hộ", "shophouse"}  # draft unit + draft project ẩn
        # 2) Cross-tenant: RLS → 0 dòng
        async with app.transaction():
            await _scoped(app, TB)
            assert await app.fetch("SELECT * FROM tenant_data.agent_units_v") == []
        # 3) Bảng gốc + PII: permission denied
        for target in ("tenant_data.units", "tenant_data.contacts", "tenant_data.conversations"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with app.transaction():
                    await _scoped(app, TA)
                    await app.fetch(f"SELECT * FROM {target}")
        # 4) Ghi giấu trong CTE nhắm BẢNG GỐC: bị chặn bởi read-only HOẶC thiếu
        #    GRANT — thứ tự hai check trong executor không thành hợp đồng, cái
        #    nào nổ trước cũng chứng minh "không thể ghi". (Không nhắm vào view:
        #    view có JOIN không auto-updatable, sẽ nổ 'cannot delete from view'
        #    ở tầng rewrite trước khi chạm hai khoá — không chứng minh gì.)
        with pytest.raises((asyncpg.ReadOnlySQLTransactionError, asyncpg.InsufficientPrivilegeError)):
            async with app.transaction():
                await _scoped(app, TA)
                await app.fetch("WITH x AS (DELETE FROM tenant_data.units RETURNING *) SELECT * FROM x")
        # 5) Timeout
        with pytest.raises(asyncpg.QueryCanceledError):
            async with app.transaction():
                await _scoped(app, TA)
                await app.fetch("SELECT pg_sleep(5)")
        # 6) SET LOCAL reset: txn kế theo app role vẫn ghi được bình thường
        async with app.transaction():
            await app.execute("SELECT set_config('app.current_tenant', $1, true)", TA)
            await app.execute(
                "INSERT INTO tenant_data.conversations (tenant_id, session_id) VALUES ($1, 's-after')", TA
            )
    finally:
        await app.close()
```

- [ ] **Step 2: Chạy skip-mode (không DSN) — file hợp lệ, collect sạch**

Run: `pytest tests/integration/tenant/test_analyze_sql_live.py -v`
Expected: SKIPPED ("set SPE_PG_ADMIN_DSN to run").

- [ ] **Step 3: Chạy live nếu có PG test** (docker local hoặc tunnel DB test — TUYỆT ĐỐI không DB prod)

Run: `SPE_PG_ADMIN_DSN=postgresql://... pytest tests/integration/tenant/test_analyze_sql_live.py -v`
Expected: PASS cả 6 khối assert.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/tenant/test_analyze_sql_live.py
git commit -m "test(analytics): live proof 3 khoá — view published-only, RLS, permission denied, read-only, timeout, SET LOCAL reset"
```

---

### Task 8: Eval cases + docs + changelog

**Files:**
- Create: `evals/quality/data/cases/du_test/p2_analytics.jsonl`
- Modify: `CLAUDE.md` (taxonomy + bảng Change Log 10-entry)
- Modify: `docs/CHANGELOG-agent.md` (entry đầy đủ lên ĐẦU bảng)
- Modify: `docs/architecture/configuration.md` (4 env mới), `docs/architecture/multi-tenant.md` (ghi chú 2 role mới cạnh mục RLS/roles)

**Interfaces:**
- Consumes: case schema v2 (`evals/quality/cases.py` — golden.tools + banned_tools).

- [ ] **Step 1: Viết 2 case eval** (`reviewed:false` — duyệt sau bằng labeller; chạy được khi tenant `du_test` bật tool + role đã provision trên DB eval)

```jsonl
{"id": "AGG-001", "tags": ["tool"], "origin": "handwritten", "tenant": "du_test", "channel": "chat", "reviewed": false, "turns": [{"user": "Bên em dự án nào có nhiều loại hình sản phẩm nhất vậy?", "golden": {"tools": [{"name": "analyze_projects", "args": {"sql": {"contains": "agent_units_v"}}}], "banned_tools": ["escalate"]}}]}
{"id": "AGG-002", "tags": ["tool"], "origin": "handwritten", "tenant": "du_test", "channel": "chat", "reviewed": false, "turns": [{"user": "Giá trung bình căn hộ ở từng dự án bên em khoảng bao nhiêu?", "golden": {"tools": [{"name": "analyze_projects", "args": {"sql": {"contains": "AVG"}}}], "banned_tools": ["escalate"]}}]}
```

- [ ] **Step 2: Verify loader nhận case**

Run: `make eval-quality ARGS="--case AGG-001,AGG-002"` (cần env eval như `unified-evals-harness` memory: Redis local + PG tunnel; nếu infra chưa sẵn thì tối thiểu verify load: `python -c "from pathlib import Path; from evals.quality.cases import load_cases; print(load_cases(Path('evals/quality/data/cases/du_test/p2_analytics.jsonl')))"` — chỉnh tên hàm theo `cases.py` thật khi implement)
Expected: 2 case load không lỗi schema.

- [ ] **Step 3: Cập nhật CLAUDE.md**

- Mục tool taxonomy: `13 built-in` → `14 built-in`, `8 optional` → `9 optional` (thêm `analyze_projects` — SQL SELECT read-only trên 2 view `agent_projects_v`/`agent_units_v`, role `agent_sql_ro`, CLI `pg-ensure-sql-ro`).
- Bảng `## Change Log`: thêm entry 1–2 câu lên đầu, xoá entry thứ 11:

```markdown
| 2026-08-26 | Tool optional mới `analyze_projects`: LLM viết SQL SELECT trả lời câu tổng quát/aggregate, chạy trên 2 view published-only dưới role `agent_sql_ro` + READ ONLY txn + RLS (3 khoá DB, không tin parse SQL); vocab giá trị cột thật chèn per-turn ở runner; provisioning `noble-tenant pg-ensure-sql-ro`. | Câu "dự án nào nhiều loại hình nhất" cần GROUP BY toàn quỹ căn — tool point-lookup phải gọi inventory × 15 dự án, vượt MAX_TOOL_ITERATIONS. |
```

- [ ] **Step 4: Thêm entry đầy đủ vào `docs/CHANGELOG-agent.md`** (đầu bảng, cùng nội dung + chi tiết 3 khoá, 4 env mới, membership grant cho role tenant trong `pg-provision`).

- [ ] **Step 5: Cập nhật `docs/architecture/configuration.md`** (4 env `ANALYZE_*`) **và `docs/architecture/multi-tenant.md`** (2 role mới: `agent_kb_view_owner` NOBYPASSRLS owner của 2 view, `agent_sql_ro` SELECT-only, membership grant cho app role + role tenant vì đường gateway per-tenant credential kết nối bằng role tenant).

- [ ] **Step 6: Lint + full unit lần cuối**

Run: `make test-unit && make lint`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add evals/quality/data/cases/du_test/p2_analytics.jsonl CLAUDE.md docs/CHANGELOG-agent.md docs/architecture/configuration.md docs/architecture/multi-tenant.md
git commit -m "docs+eval(analytics): 2 case AGG + taxonomy 14 built-in/9 optional + changelog + env ANALYZE_*"
```

---

## Deploy checklist (sau khi merge — KHÔNG làm trong plan này)

1. `noble-tenant pg-apply-schema` (tạo 2 view — idempotent).
2. `noble-tenant pg-ensure-sql-ro` (tạo 2 role + grants + membership).
3. Bật `analyze_projects` trong config tenant muốn dùng (Portal publish / manifest legacy).
4. Smoke: câu "dự án nào nhiều loại hình nhất" qua `/chat`; xem SQL trong `chat_repl --raw`.

## Verify tổng (sau Task 8)

- `make test-unit && make lint` xanh.
- `SPE_PG_ADMIN_DSN=... pytest tests/integration/tenant/test_analyze_sql_live.py -v` xanh trên PG test.
- `python scripts/chat_repl.py --ask "dự án nào có nhiều loại hình sản phẩm nhất?"` (tenant có tool + data): thấy tool call `analyze_projects` với SQL trên `agent_units_v`, trả lời khớp số liệu.
- Chạy checklist `src/noble_agent/SMOKE.md` (đã chạm turn loop ở runner + orchestrator).
