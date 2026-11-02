"""Schema KB BĐS theo template `real_estate` (02a §4).

Đây là bản VIẾT LẠI: schema M4a cũ (gate đọc · agent_enabled · import_jobs · 3 bảng con hẹp)
đã bị thay. Tài liệu `docs/build_module_knowledgebase/` là nguồn sự thật, KHÔNG phải file này.
"""

import uuid

import asyncpg
import pytest

pytestmark = pytest.mark.integration

BANG_KB = ("projects", "zones", "units", "documents", "media")


def _tenant_moi() -> str:
    # Tiền tố chữ (CHECK id ~ '^[a-z][a-z0-9_]{1,30}$' của control.tenants) +
    # hex ngẫu nhiên để các test chạy song song không đụng mã.
    return f"kbt{uuid.uuid4().hex[:10]}"


# `control.tenants.org_id` NOT NULL là cột của migration `0102_organizations`
# (M2a — tầng tổ chức, KHÔNG thuộc task này). Task 1 không sở hữu cột đó, chỉ
# cần một giá trị hợp lệ để INSERT tenant test được — 'noble' là org mặc định
# mà chính migration 0102 seed sẵn cho mọi dữ liệu đang có.
_ORG = "noble"


async def _co_cot(pool: asyncpg.Pool, bang: str, cot: str) -> bool:
    return await pool.fetchval(
        """SELECT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_schema = 'tenant_data' AND table_name = $1 AND column_name = $2)""",
        bang,
        cot,
    )


@pytest.fixture
async def kb_tenant(pool: asyncpg.Pool):
    """Một tenant + 1 project + 1 zone gốc, đủ để thoả FK khi test insert vào bảng con.

    `enforce_tenant_isolation()` bật FORCE RLS cho cả owner (`portal_migrator` —
    role của fixture `pool`), nên phải SET LOCAL app.tenant_id trước khi ghi,
    đúng luật đã ghi ở header migration 0003.
    """
    tenant = _tenant_moi()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')", tenant)
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
            await conn.execute(
                "INSERT INTO tenant_data.projects (tenant_id, project_code, name) VALUES ($1, 'P1', 'Test')", tenant
            )
            await conn.execute(
                "INSERT INTO tenant_data.zones (tenant_id, project_code, zone_code, name) VALUES ($1, 'P1', 'Z1', 'Z')",
                tenant,
            )
            await conn.execute(
                """INSERT INTO tenant_data.units (tenant_id, project_code, zone_code, unit_code, product_type)
                   VALUES ($1, 'P1', 'Z1', 'U1', 'chung_cu')""",
                tenant,
            )
            await conn.execute(
                "INSERT INTO tenant_data.documents (tenant_id, project_code, title) VALUES ($1, 'P1', 'Doc')", tenant
            )
            await conn.execute(
                """INSERT INTO tenant_data.media (tenant_id, project_code, content_type, category, media_url)
                   VALUES ($1, 'P1', 'image', 'tong_quan', 'https://x/1.webp')""",
                tenant,
            )
    yield tenant
    async with pool.acquire() as conn:
        # ON DELETE CASCADE của _TENANT_FK dọn hết 5 bảng con — không cần xoá tay.
        await conn.execute("DELETE FROM control.tenants WHERE id = $1", tenant)


async def _nhan_duoc_status(pool: asyncpg.Pool, tenant: str, bang: str, v: str) -> bool:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
        await conn.execute(f"UPDATE tenant_data.{bang} SET status = $1 WHERE tenant_id = $2", v, tenant)
        got = await conn.fetchval(f"SELECT status FROM tenant_data.{bang} WHERE tenant_id = $1", tenant)
    return got == v


# — bộ cột chung (02 §6), mọi bảng KB
@pytest.mark.parametrize("bang", BANG_KB)
async def test_bo_cot_chung(pool: asyncpg.Pool, bang: str):
    for cot in ("id", "tenant_id", "status", "created_at", "updated_at"):
        assert await _co_cot(pool, bang, cot), f"{bang} thiếu {cot}"


# — status 3 giá trị, KHÔNG phải 2 (bỏ agent_enabled, gộp về status — 02 §3)
@pytest.mark.parametrize("bang", BANG_KB)
async def test_status_ba_gia_tri(pool: asyncpg.Pool, kb_tenant: str, bang: str):
    for v in ("draft", "published", "archived"):
        assert await _nhan_duoc_status(pool, kb_tenant, bang, v), f"{bang} không nhận status={v}"


# — RLS + FORCE (02 §5)
@pytest.mark.parametrize("bang", BANG_KB)
async def test_rls_force(pool: asyncpg.Pool, bang: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT c.relrowsecurity, c.relforcerowsecurity,
                      EXISTS (SELECT 1 FROM pg_policy p
                               WHERE p.polrelid = c.oid AND p.polname = 'tenant_isolation') AS co_policy
                 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'tenant_data' AND c.relname = $1""",
            bang,
        )
        policy = await conn.fetchrow(
            """SELECT qual, with_check FROM pg_policies
                WHERE schemaname = 'tenant_data' AND tablename = $1 AND policyname = 'tenant_isolation'""",
            bang,
        )
    assert row is not None, f"bảng {bang} không tồn tại"
    assert row["relrowsecurity"], f"{bang} chưa bật RLS"
    assert row["relforcerowsecurity"], f"{bang} chưa FORCE — chủ bảng bỏ qua policy"
    assert row["co_policy"], f"{bang} thiếu policy tenant_isolation"
    assert "current_tenant" in (policy["qual"] or ""), f"{bang}: USING không tham chiếu current_tenant()"
    assert "current_tenant" in (policy["with_check"] or ""), f"{bang}: WITH CHECK không tham chiếu current_tenant()"


# — trường nội bộ nhạy cảm KHÔNG được tồn tại (02 §1) — QUÉT ĐỘNG
async def test_khong_co_truong_noi_bo_nhay_cam(pool: asyncpg.Pool):
    """Đây là bất biến trung tâm của bản viết lại. Không lưu thì không cần che.
    Cột nào tên gợi hoa hồng/giá net/chiết khấu là sai hướng thiết kế."""
    xau = await pool.fetch(
        """SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema='tenant_data'
              AND (column_name LIKE '%commission%' OR column_name LIKE '%hoa_hong%'
                OR column_name LIKE '%chiet_khau%' OR column_name LIKE '%discount%'
                OR column_name LIKE '%gia_net%' OR column_name LIKE '%net_price%'
                OR column_name LIKE '%bank_support%' OR column_name LIKE '%csbh_full%')"""
    )
    assert not xau, f"trường nội bộ nhạy cảm lọt vào KB: {[dict(r) for r in xau]}"


# — cột hệ cũ phải BIẾN MẤT (02a §2 BỎ)
async def test_cot_he_cu_da_bo(pool: asyncpg.Pool):
    for bang, cot in [
        ("projects", "slug"),
        ("projects", "lat"),
        ("projects", "lng"),
        ("projects", "is_featured"),
        ("projects", "is_hot"),
        ("projects", "sort_hot"),
        ("projects", "sort_order"),
        ("projects", "agent_enabled"),
        ("projects", "parent_code"),
        ("units", "unit_type"),
        ("units", "fund_type"),
        ("units", "check_time"),
        ("units", "sale_email"),
        ("units", "axis"),
    ]:
        assert not await _co_cot(pool, bang, cot), f"{bang}.{cot} lẽ ra đã bị bỏ"


# — bảng hệ cũ phải BIẾN MẤT
async def test_bang_he_cu_da_bo(pool: asyncpg.Pool):
    for b in ("project_highlights", "project_progress", "project_documents", "import_jobs"):
        assert await pool.fetchval("SELECT to_regclass($1)", f"tenant_data.{b}") is None


# — control.field_policy_live (bảng chứa hai cột này) đã DROP hẳn ở 0959, xem
#   test_control_schema.py — không còn cột nào để canh việc "đã rút".


# — FK tổ hợp chặn tham chiếu chéo tenant (02 §2)
async def test_fk_to_hop_chan_tham_chieu_cheo_tenant(pool: asyncpg.Pool):
    """Tenant A tạo zone trỏ tới project_code của tenant B ⇒ Postgres từ chối.
    Đây là lưới an toàn THỨ HAI, sau RLS — RLS lọc đọc, FK chặn ghi bậy."""
    ta, tb = _tenant_moi(), _tenant_moi()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) "
            "VALUES ($1, $1, 'u_seed_test'), ($2, $2, 'u_seed_test')",
            ta,
            tb,
        )
        try:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tb)
                await conn.execute(
                    "INSERT INTO tenant_data.projects (tenant_id, project_code, name) VALUES ($1, 'PB', 'B')", tb
                )
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                async with conn.transaction():
                    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", ta)
                    # ta chưa có project 'PB' của riêng mình — FK tổ hợp (tenant_id,
                    # project_code) không khớp bất kỳ hàng nào dù (tb, 'PB') tồn tại.
                    await conn.execute(
                        """INSERT INTO tenant_data.zones (tenant_id, project_code, zone_code, name)
                           VALUES ($1, 'PB', 'ZX', 'x')""",
                        ta,
                    )
        finally:
            await conn.execute("DELETE FROM control.tenants WHERE id IN ($1, $2)", ta, tb)


# — số về đúng kiểu (02a §1) — FIX nợ hệ cũ lưu chuỗi
async def test_so_dung_kieu(pool: asyncpg.Pool):
    for bang, cot, kieu in [
        ("units", "price_vnd", "numeric"),
        ("units", "area_built_m2", "numeric"),
        ("projects", "total_land_area_m2", "numeric"),
        ("projects", "total_investment_vnd", "bigint"),
        ("projects", "category", "ARRAY"),
    ]:
        got = await pool.fetchval(
            """SELECT data_type FROM information_schema.columns
                WHERE table_schema='tenant_data' AND table_name=$1 AND column_name=$2""",
            bang,
            cot,
        )
        assert got == kieu, f"{bang}.{cot} là {got}, phải là {kieu}"


# — unit_code có index nhưng KHÔNG unique (02a §4.3), khác project_code/zone_code
async def test_unit_code_khong_unique_nhung_co_index(pool: asyncpg.Pool):
    co_unique = await pool.fetchval(
        """SELECT EXISTS (
               SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = 'units' AND c.contype = 'u'
                  AND (SELECT array_agg(a.attname::text) FROM pg_attribute a
                        WHERE a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)) = ARRAY['unit_code']
           )"""
    )
    assert not co_unique, "units.unit_code không được UNIQUE — 02a §4.3"
    co_index = await pool.fetchval(
        """SELECT EXISTS (SELECT 1 FROM pg_indexes
                           WHERE schemaname='tenant_data' AND tablename='units' AND indexdef LIKE '%unit_code%')"""
    )
    assert co_index, "units.unit_code cần có index để tra cứu nhanh"


# — floor và num_floors là hai cột khác nhau (02a §4.3)
async def test_floor_va_num_floors_la_hai_cot_khac_nhau(pool: asyncpg.Pool):
    assert await _co_cot(pool, "units", "floor")
    assert await _co_cot(pool, "units", "num_floors")


# — documents KHÔNG có cột category (02a §4.4 ⚠️)
async def test_documents_khong_co_category(pool: asyncpg.Pool):
    assert not await _co_cot(pool, "documents", "category")


# — vòng FK cover/map ảnh: projects/zones trỏ tới media, media trỏ tới projects
async def test_vong_fk_anh_cover_map(pool: asyncpg.Pool):
    for bang in ("projects", "zones"):
        for cot in ("cover_media_id", "map_media_id"):
            assert await _co_cot(pool, bang, cot), f"{bang}.{cot} thiếu"
    assert await _co_cot(pool, "media", "project_code")
