"""Test `scripts/seed_bds.py` — Task 5.

Tự tạo/xoá MỘT `control.tenants` riêng cho mỗi test (không dùng `workspace_re`
của `conftest.py`: fixture đó dùng chung cho nhiều test CRUD khác trong module,
seed script cần đếm hàng CHÍNH XÁC trước/sau nên không thể chia sẻ tenant với
test khác chạy song song).
"""

import uuid

import asyncpg
import httpx
import pytest
from scripts import seed_bds

from portal.modules.realestate.completeness import thieu_truong

pytestmark = pytest.mark.integration

# `control.tenants.org_id` NOT NULL (migration 0102, M2a) — 'noble' seed sẵn.
# Cùng hằng số ở `test_repo.py`/`test_schema.py`.
_ORG = "noble"
MAT_KHAU = "MatKhauDaiVaManh!1"


def _tenant_moi() -> str:
    return f"sbd{uuid.uuid4().hex[:10]}"


@pytest.fixture
async def tenant(pool: asyncpg.Pool):
    tid = _tenant_moi()
    await pool.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')", tid)
    yield tid
    await pool.execute("DELETE FROM control.tenants WHERE id = $1", tid)


async def _chay_seed(pool: asyncpg.Pool, tenant_id: str) -> int:
    """Đúng cách `_main()` gọi `seed()`: một giao dịch, `SET LOCAL app.tenant_id`
    do CHÍNH `seed()` đặt bên trong (xem docstring `seed_bds.seed`)."""
    async with pool.acquire() as conn, conn.transaction():
        return await seed_bds.seed(conn, tenant_id)


@pytest.fixture
async def client_seed(app_client: httpx.AsyncClient, pool: asyncpg.Pool, tenant: str) -> httpx.AsyncClient:
    """Client đăng nhập vào workspace vừa seed — dùng cho kiểm HTTP cuối bài
    (`POST /projects/__ALL__/documents` chạy được sau seed)."""
    from portal.core.auth.password import bam

    uid = f"u_{tenant}"
    email = f"{tenant}@seed.test"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id, name, email, password_hash) VALUES ($1, $2, $3, $4)",
            uid,
            "Seed Tester",
            email,
            bam(MAT_KHAU),
        )
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ($1, $2, $3)",
            uid,
            tenant,
            r_admin,
        )
    r = await app_client.post("/api/v1/auth/login", json={"email": email, "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    return app_client


# ─── Anchor `__ALL__` + dữ liệu mẫu ─────────────────────────────────────────


async def test_seed_tao_anchor_all_published(pool: asyncpg.Pool, tenant: str):
    them = await _chay_seed(pool, tenant)
    assert them > 0

    anchor = await pool.fetchrow(
        "SELECT status, name FROM tenant_data.projects WHERE tenant_id = $1 AND project_code = '__ALL__'",
        tenant,
    )
    assert anchor is not None
    assert anchor["status"] == "published"
    assert anchor["name"] != ""


async def test_seed_tao_du_lieu_mau(pool: asyncpg.Pool, tenant: str):
    await _chay_seed(pool, tenant)

    so_du_an = await pool.fetchval("SELECT count(*) FROM tenant_data.projects WHERE tenant_id = $1", tenant)
    assert so_du_an == 1 + len(seed_bds.DU_AN_MAU)  # __ALL__ + N dự án mẫu

    so_can = await pool.fetchval("SELECT count(*) FROM tenant_data.units WHERE tenant_id = $1", tenant)
    assert so_can == sum(len(d["units"]) for d in seed_bds.DU_AN_MAU)

    so_tai_lieu = await pool.fetchval("SELECT count(*) FROM tenant_data.documents WHERE tenant_id = $1", tenant)
    tong_tai_lieu_mau = len(seed_bds.TAI_LIEU_CHUNG) + sum(len(d["documents"]) for d in seed_bds.DU_AN_MAU)
    assert so_tai_lieu == tong_tai_lieu_mau


# ─── Idempotent ─────────────────────────────────────────────────────────────


async def test_seed_chay_hai_lan_khong_nhan_doi(pool: asyncpg.Pool, tenant: str):
    await _chay_seed(pool, tenant)
    dem = {}
    for bang in ("projects", "zones", "units", "documents"):
        dem[bang] = await pool.fetchval(f"SELECT count(*) FROM tenant_data.{bang} WHERE tenant_id = $1", tenant)

    them_lan_2 = await _chay_seed(pool, tenant)
    assert them_lan_2 == 0, "chạy lần 2 không được ghi thêm hàng nào"

    for bang, so_cu in dem.items():
        so_moi = await pool.fetchval(f"SELECT count(*) FROM tenant_data.{bang} WHERE tenant_id = $1", tenant)
        assert so_moi == so_cu, f"{bang} bị nhân đôi sau lần seed thứ 2"


async def test_seed_khong_de_thay_doi_cua_tenant(pool: asyncpg.Pool, tenant: str):
    """Chạy seed, tenant tự sửa một bản ghi mẫu, chạy seed lại — bản sửa PHẢI
    còn nguyên (`ON CONFLICT DO NOTHING`, không `DO UPDATE`)."""
    await _chay_seed(pool, tenant)
    ma_du_an = seed_bds.DU_AN_MAU[0]["project_code"]
    await pool.execute(
        "UPDATE tenant_data.projects SET name = $1 WHERE tenant_id = $2 AND project_code = $3",
        "Tên tenant tự sửa",
        tenant,
        ma_du_an,
    )

    await _chay_seed(pool, tenant)

    ten = await pool.fetchval(
        "SELECT name FROM tenant_data.projects WHERE tenant_id = $1 AND project_code = $2", tenant, ma_du_an
    )
    assert ten == "Tên tenant tự sửa"


# ─── Dữ liệu mẫu đủ completeness (publish được) ─────────────────────────────


async def test_seed_du_lieu_mau_du_completeness(pool: asyncpg.Pool, tenant: str):
    """Nếu seed ra dữ liệu KHÔNG đủ completeness thì demo dựng ra một dự án
    không agent nào đọc được (task-5-brief.md) — khoá lại bằng `completeness.py`
    thật, không tự đoán lại luật."""
    await _chay_seed(pool, tenant)

    hang_du_an = await pool.fetch(
        # Phải lấy ĐỦ cột của `BAT_BUOC["project"]`: `thieu_truong` tra `ban_ghi[truong]`
        # nên một cột vắng trong SELECT là KeyError, không phải "thiếu dữ liệu".
        "SELECT name, region, overview, investor, product_scale FROM tenant_data.projects "
        "WHERE tenant_id = $1 AND project_code != '__ALL__'",
        tenant,
    )
    assert len(hang_du_an) == len(seed_bds.DU_AN_MAU)
    for h in hang_du_an:
        assert thieu_truong("project", h) == []

    hang_can = await pool.fetch(
        "SELECT price_vnd, area_built_m2, sale_status FROM tenant_data.units WHERE tenant_id = $1", tenant
    )
    assert len(hang_can) > 0
    for h in hang_can:
        assert thieu_truong("unit", h) == []


# ─── Kiểm quan trọng nhất: sau seed, POST /projects/__ALL__/documents chạy được ─


async def test_sau_seed_post_documents_all_chay_duoc(pool: asyncpg.Pool, tenant: str, client_seed: httpx.AsyncClient):
    """Hôm nay (trước Task 5) route này 404 ở production vì chưa có row
    `__ALL__` — đây là việc CHẶN THẬT mà Task 5 phải sửa (task-5-brief.md)."""
    await _chay_seed(pool, tenant)

    r = await client_seed.post("/api/v1/projects/__ALL__/documents", json={"title": "Kiểm tra sau seed"})
    assert r.status_code == 201, r.text
    assert r.json()["projectCode"] == "__ALL__"
