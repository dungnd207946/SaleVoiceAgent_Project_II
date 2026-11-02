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


async def test_run_non_dict_args_none():
    out = await analytics.run(None)
    assert "SQL không hợp lệ" in out


async def test_run_non_dict_args_list():
    out = await analytics.run([])
    assert "SQL không hợp lệ" in out


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
