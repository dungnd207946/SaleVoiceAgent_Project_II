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
    args = args if isinstance(args, dict) else {}
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
