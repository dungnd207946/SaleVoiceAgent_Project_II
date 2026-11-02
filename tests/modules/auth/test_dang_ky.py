"""Task 7 — `POST /auth/register` viết lại: gửi link đặt mật khẩu qua thư, KHÔNG
nhận mật khẩu trực tiếp, KHÔNG tự phát phiên. Ba nhánh (spec §4.1):

  · email chưa tồn tại       -> tạo `pending` + phát token -> 201 {"daGuiLai": False}
  · email tồn tại, `pending` -> phát token MỚI, token cũ chết -> 200 {"daGuiLai": True}
  · email tồn tại, có mật khẩu (active/suspended) -> KHÔNG ghi gì -> 409 EMAIL_TAKEN

`pytestmark` cấp module, không `@pytest.mark.anyio` mỗi hàm: repo dùng
`asyncio_mode = "auto"`, không có marker `anyio` (xem `pyproject.toml`).

⚠ Mã lỗi trùng-email THẬT là `EMAIL_TAKEN` (`portal.modules.auth.loi.email_da_ton_tai`),
KHÔNG phải `EMAIL_EXISTS` như brief task-7 viết — brief lệch code thật, xem báo cáo.
"""

import pytest

from tests.modules.auth.conftest import THU_DA_GUI

pytestmark = pytest.mark.anyio


async def test_dang_ky_moi_tra_201_va_khong_dat_cookie(app_client, pool, mailer_stub):
    res = await app_client.post("/api/v1/auth/register", json={"email": "New@X.vn", "name": "Người Mới"})
    assert res.status_code == 201, res.text
    assert res.json() == {"daGuiLai": False}
    assert "sid" not in res.cookies, "đăng ký KHÔNG còn tự phát phiên — phải qua hộp thư"

    r = await pool.fetchrow(
        """SELECT u.lifecycle, u.password_hash, i.tenant_id
             FROM control.users u JOIN control.invites i ON i.user_id = u.id
            WHERE u.email = 'new@x.vn'"""
    )
    assert r["lifecycle"] == "pending"
    assert r["password_hash"] is None
    assert r["tenant_id"] is None, "token tự đăng ký KHÔNG gắn workspace"

    assert THU_DA_GUI, "phải gửi thư"
    assert THU_DA_GUI[-1]["den"] == "new@x.vn"
    # Router phải CHUYỂN TIẾP ảnh logo: thân HTML đã trỏ `cid:` tới nó, nên thiếu
    # là một ô vuông vỡ ở chỗ nhận diện thương hiệu — không có lỗi nào phát ra.
    cid, png = THU_DA_GUI[-1]["anh_nhung"]
    assert cid == "logo-nx-agent"
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


async def test_dang_ky_lai_khi_pending_tra_200_va_giet_token_cu(app_client, pool, mailer_stub):
    await app_client.post("/api/v1/auth/register", json={"email": "lai@x.vn", "name": "Lại"})
    cu = await pool.fetchval(
        "SELECT token_hash FROM control.invites i JOIN control.users u ON u.id=i.user_id WHERE u.email='lai@x.vn'"
    )

    res = await app_client.post("/api/v1/auth/register", json={"email": "lai@x.vn", "name": "Lại"})
    assert res.status_code == 200, res.text
    assert res.json() == {"daGuiLai": True}

    moi = await pool.fetchval(
        "SELECT token_hash FROM control.invites i JOIN control.users u ON u.id=i.user_id WHERE u.email='lai@x.vn'"
    )
    assert moi != cu


async def test_dang_ky_email_da_active_tra_409_va_khong_ghi_gi(app_client, pool, mailer_stub):
    """Quyết định 2026-08-17: nói thẳng là trùng. Nhánh này KHÔNG được là một
    đường bắt server gửi thư."""
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO control.users (id,email,name,password_hash,lifecycle)
               VALUES ('u_da','da@x.vn','Da','$argon2id$fake','active')"""
        )
    so_thu_truoc = len(THU_DA_GUI)
    res = await app_client.post("/api/v1/auth/register", json={"email": "da@x.vn", "name": "Da"})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "EMAIL_TAKEN"
    assert await pool.fetchval("SELECT count(*) FROM control.invites WHERE user_id='u_da'") == 0
    assert len(THU_DA_GUI) == so_thu_truoc, "409 KHÔNG được gửi thư"


async def test_signup_enabled_false_tra_403(app_client, monkeypatch):
    """`monkeypatch.setenv` LÀ ĐỦ — KHÔNG gọi `get_settings.cache_clear()`.

    ⚠ `get_settings()` dựng `Settings()` MỚI mỗi lần gọi, KHÔNG có `lru_cache`.
    Đó là bất biến có chủ ý — `router._secure()` dựa vào nó ("đọc cấu hình MỖI
    lần"). Đừng thêm cache để làm test này chạy — gọi `cache_clear()` ở đây sẽ
    `AttributeError`, và đó là tín hiệu đúng.
    """
    monkeypatch.setenv("SIGNUP_ENABLED", "false")
    res = await app_client.post("/api/v1/auth/register", json={"email": "z@x.vn", "name": "Z"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FEATURE_DISABLED"


async def test_xem_loi_moi_tra_kind_signup(app_client, mailer_stub):
    await app_client.post("/api/v1/auth/register", json={"email": "k@x.vn", "name": "K"})
    # token thô không đọc lại được từ DB — lấy qua mailer stub ở conftest.
    token = THU_DA_GUI[-1]["token"]
    res = await app_client.get(f"/api/v1/invites/{token}")
    assert res.status_code == 200
    assert res.json()["kind"] == "signup"


async def test_tron_vong_dang_ky_accept_login_phien_khong_workspace(app_client, mailer_stub):
    """Spec §9: register → accept → login ⇒ phiên `currentWorkspaceId=None`,
    `workspaces=[]`. Người vừa tự đăng ký chưa thuộc workspace nào — đó là trạng
    thái HỢP LỆ (đảo ngược PQ_01 Q01, §2.1 spec bỏ tổ chức), không phải lỗi."""
    res = await app_client.post("/api/v1/auth/register", json={"email": "tron.vong@x.vn", "name": "Trọn Vòng"})
    assert res.status_code == 201, res.text

    token = THU_DA_GUI[-1]["token"]
    assert token, "phải lấy được token thô từ thư"

    r_accept = await app_client.post(
        "/api/v1/invites/accept", json={"token": token, "password": "mat-khau-du-10-ky-tu"}
    )
    assert r_accept.status_code == 204, r_accept.text

    r_login = await app_client.post(
        "/api/v1/auth/login", json={"email": "tron.vong@x.vn", "password": "mat-khau-du-10-ky-tu"}
    )
    assert r_login.status_code == 200, r_login.text
    body = r_login.json()
    assert body["currentWorkspaceId"] is None
    assert body["workspaces"] == []
    assert body["actions"] == []


async def test_dang_nhap_van_gop_ba_tinh_huong_vao_mot_ma(app_client, pool):
    """Canh §4.2b: /auth/register lộ email tồn tại KHÔNG kéo theo nới lỏng ở login."""
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO control.users (id,email,name,lifecycle) VALUES ('u_p','p@x.vn','P','pending')")
    a = await app_client.post("/api/v1/auth/login", json={"email": "p@x.vn", "password": "saibet123456"})
    b = await app_client.post("/api/v1/auth/login", json={"email": "khongcoai@x.vn", "password": "saibet123456"})
    assert a.status_code == b.status_code == 401
    assert a.json()["error"] == b.json()["error"]
