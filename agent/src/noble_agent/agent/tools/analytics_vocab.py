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
