"""CỔNG 1 — cách ly hàng. KHÔNG ĐƯỢC skip.

Cổng này canh: portal_api chỉ thấy hàng của tenant đã SET LOCAL, và không ghi
được hàng sang tenant khác. Phần agent role thêm ở Task 5.
"""

import asyncpg
import pytest

from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn
from tests.conftest import dsn_as

pytestmark = pytest.mark.integration


async def test_portal_api_chi_thay_tenant_da_set(seeded, api_pool):
    async with tenant_conn(api_pool, "t1") as conn:
        rows = await conn.fetch("SELECT unit_code FROM tenant_data.units ORDER BY unit_code")
    assert [r["unit_code"] for r in rows] == ["A-01"]

    async with tenant_conn(api_pool, "t2") as conn:
        rows = await conn.fetch("SELECT unit_code FROM tenant_data.units ORDER BY unit_code")
    assert [r["unit_code"] for r in rows] == ["B-01"]


async def test_khong_ghi_duoc_hang_sang_tenant_khac(seeded, api_pool):
    """WITH CHECK của policy chặn chiều GHI, USING chặn chiều ĐỌC.

    match="row-level security" để phân biệt với permission denied (thiếu GRANT)
    — cả hai đều là SQLSTATE 42501, nhưng chỉ cái đầu chứng minh WITH CHECK.
    """
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        async with tenant_conn(api_pool, "t1") as conn:
            # zone_code/project_code/unit_code/product_type NOT NULL trên schema mới
            # (0400_kb_real_estate.py) — điền đủ để lỗi bật ra ĐÚNG ở RLS, không phải
            # ở một NOT NULL constraint không liên quan.
            await conn.execute(
                """INSERT INTO tenant_data.units (tenant_id, project_code, zone_code, unit_code, product_type)
                   VALUES ('t2', 'P-t2', 'Z1', 'X-99', 'chung_cu')"""
            )


async def test_ghi_duoc_hang_cua_chinh_tenant_minh(seeded, api_pool):
    """Đối chứng cho test trên: WITH CHECK chặn ĐÚNG hàng sai tenant, không phải chặn mọi INSERT."""
    async with tenant_conn(api_pool, "t1") as conn:
        await conn.execute(
            """INSERT INTO tenant_data.units (tenant_id, project_code, zone_code, unit_code, product_type)
               VALUES ('t1', 'P-t1', 'Z1', 'A-02', 'chung_cu')"""
        )
        codes = [r["unit_code"] for r in await conn.fetch("SELECT unit_code FROM tenant_data.units ORDER BY unit_code")]
    assert codes == ["A-01", "A-02"]


async def test_khong_xoa_duoc_hang_tenant_khac(seeded, api_pool):
    async with tenant_conn(api_pool, "t1") as conn:
        deleted = await conn.execute("DELETE FROM tenant_data.units WHERE unit_code = 'B-01'")
    assert deleted == "DELETE 0"
    async with tenant_conn(api_pool, "t2") as conn:
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.units") == 1


async def test_tenant_conn_tu_choi_tenant_rong(api_pool):
    with pytest.raises(ValueError, match="tenant_id rỗng"):
        async with tenant_conn(api_pool, ""):
            pass


async def test_tenant_conn_bao_loi_khi_tenant_hieu_luc_khac_tham_so(pool, pg_dsn):
    """Chốt guard trong tenant_conn(): current_tenant() ưu tiên tên role agent_<x>
    hơn GUC app.tenant_id — nên nếu pool nối bằng một role agent_<khác>, SET LOCAL
    bị bỏ qua âm thầm và phải lộ ra bằng lỗi to, không phải đọc nhầm tenant im lặng.

    Role `agent_probe_mismatch` dưới đây là role TẠM tự dựng chỉ để khớp regex
    '^agent_(.+)$' của portal.current_tenant() — KHÔNG phải role agent_<tenant> thật
    mà Task 5 mới tạo (agent_all, quy trình cấp quyền theo tenant). Guard chỉ cần
    tên role đúng dạng để test được ngay bây giờ, không cần chờ hạ tầng Task 5.
    """
    role = "agent_probe_mismatch"
    async with pool.acquire() as conn:
        await conn.execute(f"DROP ROLE IF EXISTS {role}")
        await conn.execute(f"CREATE ROLE {role} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD 'probedev'")
        await conn.execute(f"GRANT USAGE ON SCHEMA portal TO {role}")
        await conn.execute(f"GRANT EXECUTE ON FUNCTION portal.current_tenant() TO {role}")

    p = await create_pool(dsn_as(pg_dsn, role, "probedev"), min_size=1, max_size=1)
    try:
        with pytest.raises(RuntimeError, match="tenant hiệu lực"):
            async with tenant_conn(p, "t1"):
                pass
    finally:
        await p.close()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP OWNED BY {role}")
            await conn.execute(f"DROP ROLE IF EXISTS {role}")


async def test_agent_role_chi_thay_tenant_cua_minh(agent_pool):
    """CỔNG 1 lõi: agent_t1 đọc thẳng bảng gốc chỉ thấy hàng của t1.

    Không SET LOCAL gì cả — tenant suy từ session_user. Agent KHÔNG tự đổi được.

    Từ `0917`: agent đọc thẳng `tenant_data.units` (không qua view `agent_api` nữa) —
    cách ly còn lại hoàn toàn dựa vào RLS FORCE (`0913`), không còn "không có quyền gì
    trên bảng gốc" như thiết kế `0005` ban đầu. Đây là đánh đổi có chủ ý, xem `0917`.
    """
    p1 = await agent_pool("t1")
    async with p1.acquire() as conn:
        rows = await conn.fetch("SELECT unit_code FROM tenant_data.units ORDER BY unit_code")
    assert [r["unit_code"] for r in rows] == ["A-01"]

    p2 = await agent_pool("t2")
    async with p2.acquire() as conn:
        rows = await conn.fetch("SELECT unit_code FROM tenant_data.units ORDER BY unit_code")
    assert [r["unit_code"] for r in rows] == ["B-01"]


async def test_agent_dat_guc_tenant_khac_cung_vo_dung(agent_pool):
    """Thứ tự COALESCE: tên role thắng GUC. Agent không leo thang được."""
    p1 = await agent_pool("t1")
    async with p1.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', 't2', true)")
        rows = await conn.fetch("SELECT unit_code FROM tenant_data.units")
    assert [r["unit_code"] for r in rows] == ["A-01"], "GUC đè được tên role — cách ly agent vỡ"


async def test_agent_chi_doc_khong_ghi_duoc_tren_bang_chi_doc(agent_pool):
    """Từ `0917`: agent CÓ SELECT trên `tenant_data.units` (đánh đổi đã chọn thay cho
    "không có quyền gì" của `0005`) — nhưng KHÔNG được có INSERT/UPDATE/DELETE. `units`
    không nằm trong `AGENT_WRITABLE_TENANT_DATA_TABLES` (`test_role_privileges.py`); nếu
    một GRANT lỡ tay mở thêm quyền ghi ở đây thì đây là cổng canh hành vi thật, không chỉ
    canh catalog.
    """
    p1 = await agent_pool("t1")
    async with p1.acquire() as conn:
        assert await conn.fetch("SELECT unit_code FROM tenant_data.units")  # đọc được, không raise
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(
                "INSERT INTO tenant_data.units (tenant_id, project_code, zone_code, unit_code, product_type) "
                "VALUES ('t1', 'P-t1', 'Z1', 'X-99', 'chung_cu')"
            )


async def test_agent_ghi_duoc_bang_write_back_va_doc_lai(agent_pool):
    """Đường GHI của agent chạy được THẬT, bằng role agent thật.

    Kiểm hành vi chứ không kiểm quyền: `has_table_privilege(INSERT)` xanh mà agent vẫn
    không chèn được hàng nào nếu thiếu USAGE trên sequence của cột `bigserial`
    (`conversations.id`). Chỉ một câu INSERT thật mới bắt được chuyện đó — và nó đã xảy
    ra một lần, lúc kiểm chứng DB dùng chung với hệ agent.

    Đọc-lại-được là nửa sau của hợp đồng write-back: agent ghi rồi phải thấy cái nó ghi,
    đó là lý do ba bảng này đi qua `grant_agent_write()` thay vì qua view `agent_api`.
    """
    p1 = await agent_pool("t1")
    async with p1.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO tenant_data.conversations (tenant_id, session_id) VALUES ('t1', 'phien-agent-1')"
        )
        await conn.execute(
            "INSERT INTO tenant_data.appointments (tenant_id, appointment_id) VALUES ('t1', 'hen-agent-1')"
        )
        await conn.execute(
            "INSERT INTO tenant_data.contacts (tenant_id, phone, snapshot) VALUES ('t1', '0900000009', 'x')"
        )
        assert await conn.fetchval("SELECT session_id FROM tenant_data.conversations") == "phien-agent-1"
        assert await conn.fetchval("SELECT appointment_id FROM tenant_data.appointments") == "hen-agent-1"
        assert await conn.fetchval("SELECT phone FROM tenant_data.contacts") == "0900000009"


async def test_agent_khong_ghi_duoc_write_back_cua_tenant_khac(agent_pool):
    """WITH CHECK của policy phải chặn agent t1 ghi hàng mang tenant_id của t2.

    Không có test này thì `grant_agent_write()` mở đường GHI xuyên tenant: agent t1 chỉ
    cần đặt tenant_id = 't2' trong câu INSERT.
    """
    p1 = await agent_pool("t1")
    async with p1.acquire() as conn, conn.transaction():
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("INSERT INTO tenant_data.conversations (tenant_id, session_id) VALUES ('t2', 'cua-t2')")


async def test_agent_role_chi_thay_project_cua_minh(agent_pool):
    """Đối xứng với test units. Không có test này thì tắt RLS trên `tenant_data.projects`
    là rò toàn bộ dự án giữa các workspace mà cả bộ test vẫn xanh."""
    p1 = await agent_pool("t1")
    async with p1.acquire() as conn:
        rows = await conn.fetch("SELECT project_code FROM tenant_data.projects ORDER BY project_code")
    assert [r["project_code"] for r in rows] == ["P-t1"]

    p2 = await agent_pool("t2")
    async with p2.acquire() as conn:
        rows = await conn.fetch("SELECT project_code FROM tenant_data.projects ORDER BY project_code")
    assert [r["project_code"] for r in rows] == ["P-t2"]
