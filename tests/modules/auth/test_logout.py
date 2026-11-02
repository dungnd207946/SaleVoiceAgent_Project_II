"""CỔNG 10 — đăng xuất THẬT SỰ thu hồi, không chỉ xoá cookie phía client.

Xoá cookie mà giữ bản ghi Redis nghĩa là ai còn giữ giá trị cookie cũ (log,
history, một tab khác) vẫn vào được.
"""

import pytest

from portal.core.auth import password as pw
from portal.core.auth.session import TEN_COOKIE

pytestmark = pytest.mark.integration


@pytest.fixture
async def du_lieu(pool):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ('cs_a', 'A', 'u_seed_test')")
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name) VALUES ('u_a', 'a@x.vn', $1, 'A')",
            pw.bam("mk"),
        )
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_a', 'cs_a', $1)",
            r_admin,
        )
    yield
    async with pool.acquire() as conn, conn.transaction():
        # tenants TRƯỚC users: `tenants.created_by` là FK không CASCADE (0106).
        await conn.execute("DELETE FROM control.tenants WHERE created_by LIKE 'u\\_%' AND created_by <> 'u_seed_test'")
        await conn.execute("DELETE FROM control.users WHERE id LIKE 'u\\_%' AND id <> 'u_seed_test'")
        await conn.execute("DELETE FROM control.tenants WHERE id LIKE 'cs\\_%'")


async def test_cookie_cu_dung_lai_sau_logout_bi_401(app_client, du_lieu):
    await app_client.post("/api/v1/auth/login", json={"email": "a@x.vn", "password": "mk"})
    cookie_cu = app_client.cookies[TEN_COOKIE]

    r = await app_client.post("/api/v1/auth/logout")
    assert r.status_code == 204

    # Gắn lại cookie cũ bằng tay — mô phỏng kẻ giữ được giá trị cookie (từ log,
    # history, hay một tab khác). Đây là phép thử THẬT của cổng 10: nếu logout chỉ
    # xoá cookie phía client mà giữ bản ghi Redis thì bước này vào được.
    app_client.cookies.set(TEN_COOKIE, cookie_cu)
    r2 = await app_client.get("/api/v1/me")
    assert r2.status_code == 401


async def test_logout_bao_trinh_duyet_xoa_cookie(app_client, du_lieu):
    """Vế thứ hai của đăng xuất. Không có nó thì trình duyệt gửi một giá trị đã
    chết ở mọi request sau đó, và devtool vẫn hiện cookie phiên như còn đăng nhập."""
    await app_client.post("/api/v1/auth/login", json={"email": "a@x.vn", "password": "mk"})

    r = await app_client.post("/api/v1/auth/logout")

    assert TEN_COOKIE in r.headers.get("set-cookie", "")
    assert app_client.cookies.get(TEN_COOKIE) in (None, "")


async def test_logout_khong_co_phien_van_tra_204(app_client, du_lieu):
    """Bấm Đăng xuất rồi nhận lỗi là vô lý — và tệ hơn: FE sẽ không biết có nên
    xoá state phía client hay không. Đăng xuất là thao tác luỹ đẳng."""
    r = await app_client.post("/api/v1/auth/logout")
    assert r.status_code == 204


async def test_logout_hai_lan_van_204(app_client, du_lieu):
    await app_client.post("/api/v1/auth/login", json={"email": "a@x.vn", "password": "mk"})

    assert (await app_client.post("/api/v1/auth/logout")).status_code == 204
    assert (await app_client.post("/api/v1/auth/logout")).status_code == 204
