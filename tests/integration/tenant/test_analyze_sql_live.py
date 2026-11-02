"""3 khoá của tool agent `analyze_projects` — migration `0958_analyze_projects_sql_ro`.

Kiểm trên DB thật (không mock role/RLS) bằng cách nối ĐÚNG như agent sẽ làm:
`agent_<tenant>` (role runtime per-tenant, có từ `control.dat_mat_khau_agent`) rồi
`SET LOCAL ROLE agent_sql_ro` trong một transaction `READ ONLY` — xem
`docs/contracts/agent-analyze-projects-sql-ro-contract.md` §5 (checklist gốc) và
`docs/superpowers/specs/2026-09-07-analyze-projects-sql-ro-portal-design.md`.

⚠️ HAI BÀI CUỐI LÀ `xfail(strict=True)`, KHÔNG PHẢI BỎ QUA: chúng ghi lại lỗ hổng
đã đo được 2026-09-07 (spec trên, §0) — `agent_sql_ro` KHÔNG bị chặn khỏi
`tenant_data.contacts`/bảng gốc chưa lọc, vì `tenant_data.*` có
`GRANT SELECT ... TO PUBLIC` từ `0909` và Postgres không cho REVOKE riêng một
role khỏi quyền đã cấp cho PUBLIC. `strict=True` nghĩa là: nếu ai đó đóng lỗ hổng
(vd bằng RESTRICTIVE RLS policy) mà quên gỡ `xfail`, bài sẽ XPASS và CI đỏ — đó
là cách bắt buộc phải quay lại đúng chỗ này khi sửa xong.
"""

import asyncpg
import pytest
from tests.conftest import dsn_as

pytestmark = pytest.mark.integration

TENANT = "sqlro_test"
MAT_KHAU = "z" * 43
"""43 ký tự base64url — khuôn của `bi_mat.dan_xuat()`, helper đòi >= 20."""


@pytest.fixture
async def agent_role_dsn(pool: asyncpg.Pool, pg_dsn: str) -> str:
    """Tenant thật + role `agent_sqlro_test` thật, có dữ liệu để phân biệt
    published/draft và một hàng `contacts` (dùng ở hai bài `xfail` cuối).

    Dọn role TRƯỚC tenant — `DROP ROLE` thất bại nếu role còn bị ACL tham chiếu
    (cùng thứ tự `test_tenant_id_gach_ngang.py`).
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')
               ON CONFLICT (id) DO UPDATE SET lifecycle = 'active'""",
            TENANT,
        )
        await conn.execute("SELECT control.dat_mat_khau_agent($1, $2)", TENANT, MAT_KHAU)

        await conn.execute("DELETE FROM tenant_data.units WHERE tenant_id = $1", TENANT)
        await conn.execute("DELETE FROM tenant_data.zones WHERE tenant_id = $1", TENANT)
        await conn.execute("DELETE FROM tenant_data.projects WHERE tenant_id = $1", TENANT)
        await conn.execute("DELETE FROM tenant_data.contacts WHERE tenant_id = $1", TENANT)

        await conn.execute(
            """INSERT INTO tenant_data.projects (tenant_id, project_code, name, status)
               VALUES ($1, 'PUB', 'Dự án đã published', 'published')""",
            TENANT,
        )
        await conn.execute(
            """INSERT INTO tenant_data.projects (tenant_id, project_code, name, status)
               VALUES ($1, 'DRAFT', 'Dự án còn nháp', 'draft')""",
            TENANT,
        )
        for project_code in ("PUB", "DRAFT"):
            await conn.execute(
                "INSERT INTO tenant_data.zones (tenant_id, project_code, zone_code) VALUES ($1, $2, 'Z1')",
                TENANT,
                project_code,
            )
        await conn.execute(
            """INSERT INTO tenant_data.units
                   (tenant_id, project_code, zone_code, unit_code, product_type, status)
               VALUES ($1, 'PUB', 'Z1', 'U-PUB', 'chung_cu', 'published')""",
            TENANT,
        )
        await conn.execute(
            """INSERT INTO tenant_data.units
                   (tenant_id, project_code, zone_code, unit_code, product_type, status)
               VALUES ($1, 'DRAFT', 'Z1', 'U-DRAFT', 'chung_cu', 'draft')""",
            TENANT,
        )
        await conn.execute(
            "INSERT INTO tenant_data.contacts (tenant_id, phone) VALUES ($1, '0900000000')",
            TENANT,
        )

    yield dsn_as(pg_dsn, f"agent_{TENANT}", MAT_KHAU)

    async with pool.acquire() as conn:
        await conn.execute(f'DROP ROLE IF EXISTS "agent_{TENANT}"')
        await conn.execute("DELETE FROM control.tenants WHERE id = $1", TENANT)


async def _conn_sql_ro(dsn: str) -> tuple[asyncpg.Connection, asyncpg.transaction.Transaction]:
    """Nối bằng `agent_<tenant>` rồi hạ xuống `agent_sql_ro` — đúng đường agent đi.

    Trả cả `Transaction` vì `Connection` (khác `asyncpg.Pool.acquire()`) không có
    `.rollback()`/`.commit()` tiện dụng — phải rollback qua chính object giao dịch.
    """
    conn = await asyncpg.connect(dsn)
    tr = conn.transaction()
    await tr.start()
    await conn.execute('SET LOCAL ROLE "agent_sql_ro"')
    await conn.execute("SET TRANSACTION READ ONLY")
    return conn, tr


async def test_membership_du_cho_role_runtime(agent_role_dsn: str):
    """Khoá §5 mục 1: `agent_<tenant>` phải là thành viên `agent_sql_ro`.

    Grant thẳng `agent_sql_ro TO agent_all` (migration `0958`) — role runtime nào
    cũng là thành viên `agent_all` từ lúc tạo, nên membership này KHÔNG cần
    backfill riêng cho tenant mới, kể cả tenant vừa tạo trong fixture ở trên.
    """
    conn = await asyncpg.connect(agent_role_dsn)
    try:
        assert await conn.fetchval("SELECT pg_has_role($1, 'agent_sql_ro', 'member')", f"agent_{TENANT}")
    finally:
        await conn.close()


async def test_view_chi_thay_hang_published(agent_role_dsn: str):
    """Khoá §5 mục 2 + bất biến contract §4: view lọc `status='published'`."""
    conn, tr = await _conn_sql_ro(agent_role_dsn)
    try:
        rows = await conn.fetch("SELECT unit_code FROM tenant_data.agent_units_v")
        assert [r["unit_code"] for r in rows] == ["U-PUB"], "hàng draft lọt qua view"

        cols = set((await conn.fetchrow("SELECT * FROM tenant_data.agent_units_v LIMIT 1")).keys())
        assert "tenant_id" not in cols, "view lộ tenant_id — allowlist cột đã thủng"
    finally:
        await tr.rollback()
        await conn.close()


async def test_read_only_chan_ghi(agent_role_dsn: str):
    """Khoá §5 mục 2: `SET TRANSACTION READ ONLY` chặn mọi DML, kể cả giấu trong CTE."""
    conn, tr = await _conn_sql_ro(agent_role_dsn)
    try:
        with pytest.raises(asyncpg.exceptions.ReadOnlySQLTransactionError):
            await conn.execute("WITH x AS (DELETE FROM tenant_data.units RETURNING *) SELECT 1")
    finally:
        await tr.rollback()
        await conn.close()


async def test_set_local_role_tu_het_hieu_luc_ngoai_transaction(agent_role_dsn: str):
    """`SET LOCAL` reset khi transaction kết thúc — connection về pool "sạch",
    không mắc kẹt ở `agent_sql_ro` cho câu lệnh tiếp theo của cùng connection."""
    conn, tr = await _conn_sql_ro(agent_role_dsn)
    await tr.rollback()

    current_user = await conn.fetchval("SELECT current_user")
    assert current_user == f"agent_{TENANT}", "SET LOCAL ROLE rò rỉ ra ngoài transaction đã kết thúc"
    await conn.close()


@pytest.mark.xfail(
    reason=(
        "Lỗ hổng ĐÃ BIẾT, chưa sửa (quyết định 2026-09-07) — xem "
        "docs/superpowers/specs/2026-09-07-analyze-projects-sql-ro-portal-design.md §0. "
        "GRANT SELECT ... TO PUBLIC trên tenant_data (0909) làm agent_sql_ro vẫn đọc "
        "được bảng nhạy cảm; Postgres không cho REVOKE riêng một role khỏi quyền PUBLIC. "
        "XPASS ở đây nghĩa là ai đó đã đóng lỗ hổng — gỡ xfail và xác nhận."
    ),
    strict=True,
)
async def test_bang_nhay_cam_PHAI_bi_chan__CHUA_DAT(agent_role_dsn: str):
    """Đúng như contract §0/§5 mô tả: `agent_sql_ro` KHÔNG được đọc `contacts`."""
    conn, tr = await _conn_sql_ro(agent_role_dsn)
    try:
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.fetch("SELECT * FROM tenant_data.contacts")
    finally:
        await tr.rollback()
        await conn.close()


@pytest.mark.xfail(
    reason=(
        "Cùng lỗ hổng với bài trên — agent_sql_ro đọc thẳng được bảng gốc CHƯA LỌC "
        "status='published', bỏ qua đúng allowlist mà 2 view tồn tại để thi hành."
    ),
    strict=True,
)
async def test_bang_goc_CHUA_LOC_PHAI_bi_chan__CHUA_DAT(agent_role_dsn: str):
    conn, tr = await _conn_sql_ro(agent_role_dsn)
    try:
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.fetch("SELECT * FROM tenant_data.projects")
    finally:
        await tr.rollback()
        await conn.close()
