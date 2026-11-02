"""CỔNG 3 — chủ bảng KHÔNG được đi xuyên RLS.

Postgres MIỄN RLS cho role sở hữu bảng; chỉ FORCE ROW LEVEL SECURITY mới áp.
Không có cổng này thì mọi test một-tenant vẫn xanh trong khi cách ly đã vỡ.

VÌ SAO PHẢI TẠO ROLE OWNER RIÊNG: trong testcontainers, POSTGRES_USER
(portal_migrator) chính là bootstrap superuser — mà superuser bỏ qua RLS bất kể
FORCE. Nên cổng này tạo một role NOSUPERUSER, cho nó làm owner một bảng thử, và
kiểm trên đó. Test này CŨNG chứng minh chính FORCE là thứ đang làm việc: tắt
FORCE đi thì owner thấy cả hai tenant.
"""

import pytest

from portal.core.db.pool import create_pool
from tests.conftest import dsn_as

pytestmark = pytest.mark.integration

OWNER_ROLE = "t_probe_owner"
OWNER_PASSWORD = "probedev"


@pytest.fixture
async def owned_probe(seeded, pool):
    """Bảng tenant_data.probe do một role NOSUPERUSER sở hữu, đã bật cách ly."""
    async with pool.acquire() as conn:
        # DROP TABLE trước DROP ROLE: nếu lần chạy trước chết giữa chừng (chưa
        # tới teardown), role cũ vẫn còn sở hữu probe -> DROP ROLE ở dưới sẽ chết
        # theo và fixture không tự hồi phục được. Xoá bảng trước loại bỏ phụ
        # thuộc đó nên DROP ROLE luôn thực hiện được.
        await conn.execute("DROP TABLE IF EXISTS tenant_data.probe")
        await conn.execute(f"DROP ROLE IF EXISTS {OWNER_ROLE}")
        # Khai rõ NOSUPERUSER NOBYPASSRLS thay vì dựa vào mặc định của CREATE
        # ROLE: toàn bộ hiệu lực của cổng 3 đứng trên việc role probe không phải
        # superuser và không có BYPASSRLS — phải NÓI RÕ, không phải NGẦM ĐỊNH.
        await conn.execute(f"CREATE ROLE {OWNER_ROLE} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{OWNER_PASSWORD}'")
        r = await conn.fetchrow("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = $1", OWNER_ROLE)
        assert r["rolsuper"] is False, "role probe là superuser — toàn bộ cổng 3 vô nghĩa"
        assert r["rolbypassrls"] is False, "role probe có BYPASSRLS — toàn bộ cổng 3 vô nghĩa"
        await conn.execute(
            """CREATE TABLE tenant_data.probe (
                   id        bigserial PRIMARY KEY,
                   tenant_id text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
                   note      text NOT NULL DEFAULT ''
               )"""
        )
        await conn.execute("SELECT control.enforce_tenant_isolation('tenant_data.probe')")
        # Seed TRƯỚC khi chuyển owner: lúc này portal_migrator là superuser nên
        # bỏ qua RLS, ghi được cả hai tenant trong một lượt.
        await conn.execute("INSERT INTO tenant_data.probe (tenant_id, note) VALUES ('t1', 'của t1'), ('t2', 'của t2')")
        await conn.execute(f"ALTER TABLE tenant_data.probe OWNER TO {OWNER_ROLE}")
        await conn.execute(f"GRANT USAGE ON SCHEMA tenant_data, portal, control TO {OWNER_ROLE}")
        await conn.execute(f"GRANT EXECUTE ON FUNCTION portal.current_tenant() TO {OWNER_ROLE}")
        await conn.execute(f"GRANT SELECT ON control.tenants TO {OWNER_ROLE}")
    yield
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS tenant_data.probe")
        # DROP ROLE thất bại với DependentObjectsStillExistError nếu không thu
        # hồi trước các GRANT (schema/function/table) đã cấp ở trên — DROP OWNED
        # BY thu hồi toàn bộ quyền đã cấp cho role trước khi xoá nó.
        await conn.execute(f"DROP OWNED BY {OWNER_ROLE}")
        await conn.execute(f"DROP ROLE IF EXISTS {OWNER_ROLE}")


async def test_chu_bang_bi_rls_chan_khi_co_force(owned_probe, pg_dsn):
    p = await create_pool(dsn_as(pg_dsn, OWNER_ROLE, OWNER_PASSWORD), min_size=1, max_size=1)
    try:
        async with p.acquire() as conn, conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', 't1', true)")
            rows = await conn.fetch("SELECT note FROM tenant_data.probe")
        assert [r["note"] for r in rows] == ["của t1"], "chủ bảng thấy hàng của tenant khác"
    finally:
        await p.close()


async def test_tat_force_di_thi_chu_bang_thay_het(owned_probe, pool, pg_dsn):
    """Chứng minh chính FORCE là thứ đang làm việc — không phải may mắn.

    Nếu ai đó bỏ FORCE khỏi enforce_tenant_isolation(), test trên sẽ đỏ và test
    này sẽ là chỗ giải thích tại sao.
    """
    async with pool.acquire() as conn:
        await conn.execute("ALTER TABLE tenant_data.probe NO FORCE ROW LEVEL SECURITY")

    p = await create_pool(dsn_as(pg_dsn, OWNER_ROLE, OWNER_PASSWORD), min_size=1, max_size=1)
    try:
        async with p.acquire() as conn, conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', 't1', true)")
            count = await conn.fetchval("SELECT count(*) FROM tenant_data.probe")
        assert count == 2, "bỏ FORCE mà chủ bảng vẫn bị chặn — giả định của cổng 3 sai"
    finally:
        # KHÔNG khôi phục FORCE ở đây: owned_probe teardown DROP TABLE probe ngay
        # sau test này, nên "khôi phục" chỉ tạo ảo giác đang bảo vệ container dùng
        # chung trong khi thực ra không có gì để bảo vệ nữa.
        await p.close()
