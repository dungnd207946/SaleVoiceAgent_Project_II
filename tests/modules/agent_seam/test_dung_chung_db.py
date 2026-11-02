"""Cổng cho ba thay đổi để Portal và agent DÙNG CHUNG một database.

Bối cảnh: khảo sát DB `odyssey` của team agent (`docs/contracts/danh-gia-dung-chung-db.md`)
cho thấy `tenant_data` hai bên gần trùng khít, nhưng ba chỗ lệch chặn việc nạp dữ liệu và
chặn agent đọc config. Ba migration 0902/0903/0904 đóng ba chỗ đó. File này canh chúng.

Cổng ở đây kiểm HÀNH VI trên dữ liệu thật của họ, không kiểm "cột có tồn tại":
  · zone_code: 3015/3015 hàng của họ có `zone_code IS NULL` và bảng `zones` rỗng
  · ba bảng write-back: agent đang ghi chúng, Portal chưa có chỗ chứa
  · (con trỏ config `0904` — bảng `config_live` đã DROP ở `0966`, cổng của nó bỏ theo)
"""

import uuid

import asyncpg
import pytest

from portal.core.db.session import tenant_conn

pytestmark = pytest.mark.integration

_ORG = "noble"
BANG_WRITE_BACK = ("contacts", "conversations", "appointments")


def _tenant_moi() -> str:
    return f"seam{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def api_pool(api_dsn: str):
    """Pool nối bằng `portal_api` — role runtime THẬT.

    BẮT BUỘC cho mọi assertion về cách ly: `pool` nối bằng `portal_migrator`, và trong
    container test role đó là bootstrap user của image postgres, tức **SUPERUSER** —
    superuser bỏ qua RLS kể cả khi bảng đã FORCE ROW LEVEL SECURITY. Một test cách ly
    chạy trên `pool` đo được đúng con số 0 hay 1 tuỳ may mắn, không đo được cách ly.
    Đây là luật đã ghi ở docstring fixture `pool` trong tests/conftest.py.
    """
    from portal.core.db.pool import create_pool

    p = await create_pool(api_dsn, min_size=1, max_size=2)
    yield p
    await p.close()


@pytest.fixture
async def hai_tenant(pool: asyncpg.Pool):
    """Hai tenant thật — cần HAI để chứng minh cách ly, một cái thì không chứng minh gì."""
    a, b = _tenant_moi(), _tenant_moi()
    async with pool.acquire() as conn, conn.transaction():
        for t in (a, b):
            await conn.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')", t)
    yield a, b
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id = ANY($1::text[])", [a, b])


async def _chen_project(conn, tenant: str, code: str = "P1") -> None:
    await conn.execute(
        """INSERT INTO tenant_data.projects (tenant_id, project_code, name, category, sale_phase, status)
           VALUES ($1, $2, $2, ARRAY['chung_cu'], 'dang_ban', 'published')""",
        tenant,
        code,
    )


# ─── 0902 · units.zone_code nullable ────────────────────────────────────────────


async def test_chen_unit_khong_co_zone_code(pool: asyncpg.Pool, hai_tenant):
    """Dữ liệu của team agent có `zone_code IS NULL` ở 100% hàng và `zones` rỗng.

    `zone_code` NOT NULL làm 0/3015 hàng nạp được. Nới ra là theo TIỀN LỆ có sẵn
    trong cùng migration 0400: `media.zone_code` đã nullable với đúng cùng FK tổ hợp
    (tenant_id, project_code, zone_code) — Postgres MATCH SIMPLE bỏ qua FK khi một cột
    của nó là NULL, nên FK vẫn nguyên vẹn cho hàng CÓ zone_code.
    """
    t, _ = hai_tenant
    async with tenant_conn(pool, t) as conn:
        await _chen_project(conn, t)
        await conn.execute(
            """INSERT INTO tenant_data.units
                   (tenant_id, project_code, zone_code, unit_code, product_type, status)
               VALUES ($1, 'P1', NULL, 'U-01', 'chung_cu', 'published')""",
            t,
        )
        assert await conn.fetchval("SELECT zone_code FROM tenant_data.units WHERE unit_code='U-01'") is None
        # Agent phải THẤY hàng đó — không có FK nào tới zones chặn nó lại.
        assert [r["unit_code"] for r in await conn.fetch("SELECT unit_code FROM tenant_data.units")] == ["U-01"]


async def test_fk_zone_van_chan_zone_code_bia(pool: asyncpg.Pool, hai_tenant):
    """Nới NOT NULL KHÔNG được biến FK thành vô nghĩa: zone_code CÓ giá trị mà không
    tồn tại trong `zones` thì vẫn phải bị từ chối. Không có test này thì "nới" và
    "bỏ FK" trông giống nhau."""
    t, _ = hai_tenant
    async with tenant_conn(pool, t) as conn:
        await _chen_project(conn, t)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                """INSERT INTO tenant_data.units
                       (tenant_id, project_code, zone_code, unit_code, product_type)
                   VALUES ($1, 'P1', 'KHONG_TON_TAI', 'U-02', 'chung_cu')""",
                t,
            )


# ─── 0903 · ba bảng write-back của agent ───────────────────────────────────────


@pytest.mark.parametrize("bang", BANG_WRITE_BACK)
async def test_bang_write_back_da_bat_cach_ly(pool: asyncpg.Pool, hai_tenant, bang):
    """Ba bảng agent GHI phải ở dưới cách ly như mọi bảng tenant_data khác.

    Kiểm qua catalog thay vì qua hành vi ở đây là cố ý: cổng
    `test_moi_bang_tenant_data_da_bat_cach_ly` quét động cả schema nên nó đã canh
    hành vi; cái cần khẳng định riêng là ba bảng NÀY không lọt vào schema mà quên
    gọi `enforce_tenant_isolation()`.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT c.relrowsecurity AS rls, c.relforcerowsecurity AS force_rls
                 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'tenant_data' AND c.relname = $1""",
            bang,
        )
    assert row is not None, f"tenant_data.{bang} không tồn tại — migration 0903 chưa chạy"
    assert row["rls"] is True, f"tenant_data.{bang} chưa bật RLS"
    assert row["force_rls"] is True, f"tenant_data.{bang} chưa FORCE RLS (owner cũng phải bị áp)"


async def test_write_back_khong_lan_giua_hai_tenant(api_pool, hai_tenant):
    """Ghi bằng tenant A rồi đọc bằng tenant B — phải không thấy gì.

    Chạy trên `api_pool` (portal_api), KHÔNG phải `pool`: xem docstring fixture api_pool.
    """
    a, b = hai_tenant
    async with tenant_conn(api_pool, a) as conn:
        await conn.execute(
            "INSERT INTO tenant_data.contacts (tenant_id, phone, snapshot) VALUES ($1, '0900000001', 'ghi chú')", a
        )
        await conn.execute("INSERT INTO tenant_data.conversations (tenant_id, session_id) VALUES ($1, 'sess-1')", a)
        await conn.execute(
            """INSERT INTO tenant_data.appointments (tenant_id, appointment_id, session_id, project_code, status)
               VALUES ($1, 'appt-1', 'sess-1', 'NCLB', 'confirmed')""",
            a,
        )
    async with tenant_conn(api_pool, b) as conn:
        for bang in BANG_WRITE_BACK:
            assert await conn.fetchval(f"SELECT count(*) FROM tenant_data.{bang}") == 0, (
                f"tenant {b} đọc được hàng của tenant {a} trên tenant_data.{bang}"
            )


async def test_appointments_khong_co_fk_project_code(pool: asyncpg.Pool, hai_tenant):
    """CỐ Ý KHÔNG có FK về `projects` — quyết định do DỮ LIỆU THẬT ép ra.

    147/147 appointment của họ có `project_code` (`NCLB`, `SLC`) KHÔNG khớp bất kỳ
    hàng nào trong `projects` (41 project, mã khác hẳn). Đặt FK ở đây là từ chối
    100% dữ liệu cần nạp. Ghi thành test để lần sau ai đó "thêm FK cho chuẩn" thì
    phải đọc lý do trước.
    """
    t, _ = hai_tenant
    async with tenant_conn(pool, t) as conn:
        await conn.execute(
            """INSERT INTO tenant_data.appointments (tenant_id, appointment_id, project_code)
               VALUES ($1, 'appt-mo-cua', 'MA_KHONG_CO_TRONG_PROJECTS')""",
            t,
        )
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.appointments") == 1
