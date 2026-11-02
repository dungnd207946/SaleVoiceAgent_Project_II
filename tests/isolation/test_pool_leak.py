"""CỔNG 4 — rò rỉ tenant qua connection pool. Điều kiện 4 của cách ly.

Lỗi này CHỈ hiện khi có tải thật: ở máy dev một người bấm một lúc thì không bao
giờ thấy. Không có cổng này thì nó sống tới production.

max_size=1 để BUỘC hai request dùng đúng một kết nối vật lý — đó là điều kiện
tái hiện, không phải chi tiết ngẫu nhiên.
"""

import asyncio

import pytest

from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn

pytestmark = pytest.mark.integration


@pytest.fixture
async def one_conn_pool(api_dsn):
    p = await create_pool(api_dsn, min_size=1, max_size=1)
    yield p
    await p.close()


async def test_request_sau_khong_ke_thua_tenant_cua_request_truoc(seeded, one_conn_pool):
    async with tenant_conn(one_conn_pool, "t1") as conn:
        assert [r["unit_code"] for r in await conn.fetch("SELECT unit_code FROM tenant_data.units")] == ["A-01"]

    # Cùng kết nối vật lý, KHÔNG set tenant. Phải ra 0 hàng, không phải A-01.
    async with one_conn_pool.acquire() as conn, conn.transaction():
        rows = await conn.fetch("SELECT unit_code FROM tenant_data.units")
    assert [r["unit_code"] for r in rows] == [], "kế thừa tenant của request trước — cách ly vỡ"


async def test_guc_khong_song_qua_ranh_gioi_giao_dich(seeded, one_conn_pool):
    """set_config(..., is_local => true) tự hết hiệu lực khi transaction kết thúc."""
    async with tenant_conn(one_conn_pool, "t1"):
        pass
    async with one_conn_pool.acquire() as conn:
        assert await conn.fetchval("SELECT portal.current_tenant()") is None


async def test_hai_tenant_xen_ke_khong_lan_nhau(seeded, one_conn_pool):
    """Chạy xen kẽ trên cùng pool max_size=1 — asyncpg xếp hàng, mỗi lượt phải đúng tenant."""

    async def doc(tenant: str) -> list[str]:
        async with tenant_conn(one_conn_pool, tenant) as conn:
            rows = await conn.fetch("SELECT unit_code FROM tenant_data.units ORDER BY unit_code")
        return [r["unit_code"] for r in rows]

    got = await asyncio.gather(*(doc(t) for t in ("t1", "t2", "t1", "t2", "t1")))
    assert got == [["A-01"], ["B-01"], ["A-01"], ["B-01"], ["A-01"]]


async def test_set_tran_song_qua_ranh_gioi_giao_dich_tren_cung_ket_noi(seeded, one_conn_pool):
    """Chứng minh SET trần LÀ lỗ hổng — đây là lý do tenant_conn() dùng SET LOCAL.

    Chỗ rò KHÔNG phải ở ranh giới acquire: asyncpg tự gọi RESET ALL khi trả kết nối
    về pool (PoolConnectionHolder.release -> Connection.reset), nên hai lượt acquire
    riêng biệt đã được driver che. Chỗ rò là TRONG một kết nối đang giữ: SET trần
    sống qua ranh giới GIAO DỊCH, nên giao dịch sau kế thừa tenant của giao dịch trước.

    Và có một tầng nữa driver không che được: pgbouncer chế độ transaction-pooling
    ghép nhiều client lên chung một kết nối máy chủ theo từng giao dịch. RESET ALL của
    asyncpg xảy ra ở phía client, không phải phía pgbouncer. Nên luật là SET LOCAL,
    không phải 'tin vào driver'.

    Test này đỏ nếu Postgres đổi phạm vi của SET — lúc đó phải rà lại toàn bộ lập luận
    của tenant_conn().
    """
    async with one_conn_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SET app.tenant_id = 't1'")  # KHÔNG có LOCAL
            assert await conn.fetchval("SELECT portal.current_tenant()") == "t1"

        # Giao dịch mới, CÙNG kết nối, không set gì: vẫn thấy tenant của giao dịch trước.
        async with conn.transaction():
            ke_thua = await conn.fetchval("SELECT portal.current_tenant()")
            assert ke_thua == "t1", "SET trần không sống qua giao dịch nữa — xem lại giả định của cổng 4"
            rows = await conn.fetch("SELECT unit_code FROM tenant_data.units")
        assert [r["unit_code"] for r in rows] == ["A-01"], "kế thừa tenant mà vẫn không đọc được — giả định sai"

        await conn.execute("RESET app.tenant_id")
        # Belt and braces: dù asyncpg sẽ RESET ALL khi trả kết nối về pool, vẫn dọn
        # tường minh ở đây — không để một kết nối mang GUC đã set quay về pool dùng chung.
        assert await conn.fetchval("SELECT portal.current_tenant()") is None


async def test_pool_dua_vao_reset_mac_dinh_cua_asyncpg(seeded, one_conn_pool):
    """Ranh giới acquire an toàn NHỜ asyncpg, không nhờ code của ta.

    create_pool() không truyền reset= nên asyncpg chạy RESET ALL lúc trả kết nối.
    Ai đó truyền một reset= tuỳ biến vào create_pool() là gỡ lớp bảo vệ này mà không
    có gì báo — test này biến sự phụ thuộc vô hình đó thành hữu hình.
    """
    async with one_conn_pool.acquire() as conn:
        await conn.execute("SET app.tenant_id = 't1'")
    async with one_conn_pool.acquire() as conn:
        assert await conn.fetchval("SELECT portal.current_tenant()") is None
