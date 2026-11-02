"""SQL của M2a. Dùng `pool` (fixture của M1) — kết nối control, không phải tenant_conn.

VÌ SAO KHÔNG tenant_conn: memberships là control-plane. Muốn đọc membership để
BIẾT tenant thì đã phải biết tenant trước — vòng tròn. Xem lý do đã khai ở
tests/isolation/test_isolation_catalog.py.
"""

import pytest

from portal.modules.auth import repo

pytestmark = pytest.mark.integration

BAM_GIA = "$argon2id$v=19$m=65536,t=3,p=4$khonglaMhashthat"


@pytest.fixture
async def du_lieu(pool):
    """1 user · 3 workspace · 2 membership — cùng hình dạng với seed dev (§7 spec).
    `haven` KHÔNG có membership: đó là thứ chứng minh phép lọc thật sự lọc.

    migration 0104 xoá `memberships.role`, thay bằng `role_id` trỏ
    `control.roles` — vai trò giờ là tên do tổ chức tự đặt, không còn 4 mã cố
    định. Org 'noble' đã có 4 vai trò mẫu (trigger + backfill của 0104), fixture
    chỉ TRA id theo tên tương ứng ('admin' cũ -> 'Quản trị', 'care' cũ -> 'CSKH').
    """
    async with pool.acquire() as conn, conn.transaction():
        for tid, ten in [("cs_anphu", "An Phú Land"), ("cs_sunrise", "Sunrise"), ("cs_haven", "Havenly")]:
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $2, 'u_seed_test')", tid, ten
            )
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name) VALUES ($1, $2, $3, $4)",
            "u_dang",
            "dang@anphuland.vn",
            BAM_GIA,
            "Trần Hải Đăng",
        )
        r_quan_tri = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        r_cskh = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'CSKH'")
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_dang', 'cs_anphu', $1)",
            r_quan_tri,
        )
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_dang', 'cs_sunrise', $1)",
            r_cskh,
        )
    yield
    async with pool.acquire() as conn, conn.transaction():
        # tenants TRƯỚC users: `tenants.created_by` là FK không CASCADE (0106).
        await conn.execute("DELETE FROM control.tenants WHERE created_by LIKE 'u\\_%' AND created_by <> 'u_seed_test'")
        await conn.execute("DELETE FROM control.users WHERE id LIKE 'u\\_%' AND id <> 'u_seed_test'")
        await conn.execute("DELETE FROM control.tenants WHERE id LIKE 'cs\\_%'")


async def test_tim_user_theo_email(pool, du_lieu):
    async with pool.acquire() as conn:
        u = await repo.tim_user_theo_email(conn, "dang@anphuland.vn")
    assert u is not None and u.id == "u_dang" and u.lifecycle == "active"


async def test_tim_user_email_khong_co_tra_None(pool, du_lieu):
    async with pool.acquire() as conn:
        assert await repo.tim_user_theo_email(conn, "khongco@x.vn") is None


async def test_liet_ke_workspace_chi_tra_ws_co_membership(pool, du_lieu):
    """`cs_haven` tồn tại trong DB mà không hiện — toàn bộ ý nghĩa của phép lọc này."""
    async with pool.acquire() as conn:
        ws = await repo.liet_ke_workspace(conn, "u_dang")
    assert [w.id for w in ws] == ["cs_anphu", "cs_sunrise"]


async def test_liet_ke_workspace_bo_qua_membership_het_han(pool, du_lieu):
    """Vé hỗ trợ hết hạn không được còn hiện trên switcher — nếu không thì người
    ta bấm vào rồi ăn 403, và tưởng hệ thống hỏng."""
    async with pool.acquire() as conn, conn.transaction():
        r_viewer = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Người xem'")
        await conn.execute(
            """INSERT INTO control.memberships (user_id, tenant_id, role_id, expires_at)
               VALUES ('u_dang','cs_haven',$1, now() - interval '1 hour')""",
            r_viewer,
        )
        ws = await repo.liet_ke_workspace(conn, "u_dang")
    assert [w.id for w in ws] == ["cs_anphu", "cs_sunrise"]


async def test_workspace_plan_luon_None(pool, du_lieu):
    """control.tenants CỐ Ý không có cột plan (hoá đơn không gắn vào khoá cách ly,
    xem migration 0002). Trả 'Growth' cứng là bơm dữ liệu giả vào luồng thật."""
    async with pool.acquire() as conn:
        ws = await repo.liet_ke_workspace(conn, "u_dang")
    assert all(w.plan is None for w in ws)


async def test_workspace_slug_bang_id(pool, du_lieu):
    """Dư có chủ ý (spec §4.3②) — neo lại để không ai "sửa" thành hai giá trị khác
    nhau rồi làm FE trỏ sai khoá cách ly."""
    async with pool.acquire() as conn:
        ws = await repo.liet_ke_workspace(conn, "u_dang")
    assert all(w.slug == w.id for w in ws)


async def test_liet_ke_thanh_vien_theo_workspace(pool, du_lieu):
    async with pool.acquire() as conn:
        ds = await repo.liet_ke_thanh_vien(conn, "cs_anphu")
        r_quan_tri = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
    assert [(m.userId, m.role) for m in ds] == [("u_dang", "Quản trị")]
    # `MemberOut` phải mang CẢ id: bảng thành viên bên FE cũng có ô chọn vai trò, và
    # dò ngược tên -> id trên danh sách `/roles` là chỗ khớp sai đã đo được.
    assert [m.roleId for m in ds] == [r_quan_tri]
