"""Phiên KHÔNG workspace là trạng thái HỢP LỆ — đảo ngược PQ_01 Q01 (2026-08-15).

Bản cũ (CỔNG 8) neo điều ngược lại: 0 workspace ⇒ 409 NO_WORKSPACE, vì mọi user
đều ra đời qua lời mời VÀO một workspace nên trạng thái đó chỉ có thể là hỏng.

Tự đăng ký làm nó thành đường CHÍNH: người vừa tạo tài khoản luôn có 0 workspace.
409 ở đó là ngõ cụt — họ không tới được màn tạo workspace đầu tiên. Xem spec
`2026-08-15-bo-organization-design.md` §5.0.

`loi.khong_co_workspace()` (mã `NO_WORKSPACE`) vẫn còn, nhưng chỉ cho
`POST /me/workspace` khi ai đó đổi sang workspace họ không thuộc.
"""

import pytest

from portal.core.auth import password as pw

pytestmark = pytest.mark.integration


@pytest.fixture
async def user_khong_ws(pool):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name) VALUES ($1, $2, $3, $4)",
            "u_treo",
            "treo@x.vn",
            pw.bam("mk"),
            "Người Treo",
        )
    yield
    async with pool.acquire() as conn, conn.transaction():
        # tenants TRƯỚC users: `tenants.created_by` là FK không CASCADE (0106).
        await conn.execute("DELETE FROM control.tenants WHERE created_by LIKE 'u\\_%' AND created_by <> 'u_seed_test'")
        await conn.execute("DELETE FROM control.users WHERE id LIKE 'u\\_%' AND id <> 'u_seed_test'")


async def test_dang_nhap_khong_co_workspace_van_thanh_cong(app_client, user_khong_ws):
    """ĐẢO NGƯỢC PQ_01 Q01 (2026-08-15).

    Bản cũ: 0 workspace ⇒ 409 NO_WORKSPACE, "trạng thái HỎNG, không phải rỗng".
    Đúng khi user chỉ ra đời qua lời mời (được mời VÀO một workspace). Với tự đăng
    ký thì đó là ngõ cụt: người vừa tạo tài khoản có 0 workspace và 409 không cho
    họ đi đâu cả.

    Giờ phiên được tạo với `tenant_id = None`, và FE dùng `currentWorkspaceId is
    null` để đưa tới màn "Tạo workspace đầu tiên". Xem spec bo-organization §5.0.
    """
    r = await app_client.post("/api/v1/auth/login", json={"email": "treo@x.vn", "password": "mk"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workspaces"] == []
    assert body["currentWorkspaceId"] is None
    assert body["actions"] == []


async def test_co_cookie_phien_du_khong_workspace(app_client, user_khong_ws):
    """Có phiên thật — không phải một 409 rồi thôi.

    Thiếu cookie thì người vừa đăng ký không gọi được `POST /workspaces`, và màn
    tạo workspace đầu tiên vô dụng.
    """
    await app_client.post("/api/v1/auth/login", json={"email": "treo@x.vn", "password": "mk"})
    assert app_client.cookies.get("odyssey_session")


async def test_endpoint_can_quyen_tra_403_khong_phai_401(app_client, user_khong_ws):
    """Phiên hợp lệ nhưng chưa có workspace ⇒ 403, KHÔNG phải 401.

    401 sẽ đá họ về `/login` và họ đăng nhập lại vào đúng trạng thái cũ — một
    vòng lặp không lối ra. 403 nói đúng: bạn đã đăng nhập, chỉ là chưa có quyền ở
    đâu cả.
    """
    await app_client.post("/api/v1/auth/login", json={"email": "treo@x.vn", "password": "mk"})
    r = await app_client.get("/api/v1/members")
    assert r.status_code == 403, r.text
