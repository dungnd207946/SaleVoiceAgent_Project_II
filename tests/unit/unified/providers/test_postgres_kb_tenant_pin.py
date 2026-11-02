"""MỌI câu SQL của pg_kb phải TỰ ghim tenant — không uỷ thác cho RLS.

Bối cảnh (đo thật 2026-08-06, agent + Postgres thật): provider này cố ý giao việc lọc
tenant cho RLS — docstring cũ ghi *"scoped ... by `tenant_conn` + the RLS `agent_runtime`
policy"* — và không câu nào có `WHERE tenant_id`. Portal tắt RLS ở migration `0909`, và
agent phục vụ `anphu` (2 dự án published) nhận về **6**, tức cả ba tenant. `units` 60 thay
vì 20, `documents` 18 thay vì 6.

Đây là loại lỗi không grep ra được: code trông đúng, thiếu sót nằm ở một giả định về
tầng khác. Test này biến giả định đó thành thứ đo được — mỗi phương thức đọc `tenant_data`
phải phát ra SQL có vị từ `tenant_id = $N`, VÀ tham số thứ N phải đúng tenant hiện tại.
"""

from __future__ import annotations

import re

import pytest

from noble_agent.data.providers import base
from noble_agent.data.providers.postgres_kb import PostgresKBProvider
from noble_agent.tenant.current import use_tenant

TENANT = "anphu"


class _BatSql:
    """Ghi lại (sql, args) của mọi lượt fetch/fetchrow."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return []

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return None


class _Ctx:
    def __init__(self, c):
        self._c = c

    async def __aenter__(self):
        return self._c

    async def __aexit__(self, *a):
        return False


def _provider(conn):
    p = PostgresKBProvider()
    p._acquire = lambda: _Ctx(conn)  # noqa: SLF001 — thay đúng seam mà lớp này chừa sẵn
    return p


# (tên, coroutine-factory) — mọi phương thức CÓ đọc tenant_data
GOI = [
    ("warm", lambda p: p.warm()),
    ("list_projects", lambda p: p.list_projects()),
    ("list_projects+region", lambda p: p.list_projects(region="Hà Nội")),
    ("get_overview", lambda p: p.get_overview("NPLB")),
    ("discover_projects", lambda p: p.discover_projects(base.DiscoverQuery())),
    ("search_units", lambda p: p.search_units(base.UnitQuery(project_code="NPLB"))),
    ("search_units+cross", lambda p: p.search_units(base.UnitQuery(project_code="", region="Hà Nội", bedrooms=2))),
    ("get_document", lambda p: p.get_document("NPLB")),
    ("get_document+query", lambda p: p.get_document("NPLB", "pháp lý")),
]


@pytest.mark.parametrize("ten,goi", GOI, ids=[t for t, _ in GOI])
async def test_moi_cau_sql_deu_ghim_tenant(ten, goi):
    conn = _BatSql()
    with use_tenant(TENANT):
        await goi(_provider(conn))

    assert conn.calls, f"{ten}: không phát ra câu SQL nào — test này sẽ mù"
    for sql, args in conn.calls:
        if "tenant_data." not in sql:
            continue
        m = re.search(r"tenant_id\s*=\s*\$(\d+)", sql)
        assert m, f"{ten}: SQL đọc tenant_data mà KHÔNG ghim tenant_id:\n{sql}"
        # Vị từ có mặt là chưa đủ — tham số nó trỏ tới phải đúng tenant hiện tại.
        # Không kiểm điều này thì `tenant_id = $1` trỏ nhầm vào `__ALL__` vẫn xanh.
        vi_tri = int(m.group(1)) - 1
        assert vi_tri < len(args), f"{ten}: ghim `${vi_tri + 1}` nhưng chỉ có {len(args)} tham số"
        assert args[vi_tri] == TENANT, f"{ten}: `${vi_tri + 1}` = {args[vi_tri]!r}, phải là {TENANT!r}"


async def test_discover_ghim_ca_trong_subquery_gia():
    """Ghim bảng ngoài thôi là chưa đủ, và đây là chỗ dễ sót nhất.

    `discover_projects` LEFT JOIN một subquery gộp `min(price_vnd)` theo `project_code`.
    Nếu subquery không ghim tenant, nó gộp giá của MỌI tenant rồi join theo mã dự án —
    "giá từ" hiện cho khách có thể là giá của tenant khác. Rò rỉ im lặng hơn cả rò rỉ
    danh sách dự án, vì con số trông vẫn hợp lý.
    """
    conn = _BatSql()
    with use_tenant(TENANT):
        await _provider(conn).discover_projects(base.DiscoverQuery())

    sql = conn.calls[0][0]
    sub = sql[sql.index("LEFT JOIN (") : sql.index(") pf")]
    assert "tenant_data.units" in sub
    assert re.search(r"tenant_id\s*=\s*\$\d+", sub), f"subquery giá KHÔNG ghim tenant:\n{sub}"


async def test_doi_tenant_thi_tham_so_doi_theo():
    """Ghim phải đọc tenant TẠI THỜI ĐIỂM GỌI, không phải hằng bắt lúc import.

    Một process phục vụ N tenant: nếu giá trị bị chốt sớm, tenant B sẽ dùng ghim của A —
    vẫn có `WHERE tenant_id = $1`, vẫn sai người.
    """
    thay = {}
    for t in ("anphu", "haven"):
        conn = _BatSql()
        with use_tenant(t):
            await _provider(conn).list_projects()
        sql, args = conn.calls[0]
        vi_tri = int(re.search(r"tenant_id\s*=\s*\$(\d+)", sql).group(1)) - 1
        thay[t] = args[vi_tri]

    assert thay == {"anphu": "anphu", "haven": "haven"}, thay
