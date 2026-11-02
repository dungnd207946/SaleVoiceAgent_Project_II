"""Cổng 1–4 của spec M2b §7 — `POST /api/v1/users`.

Hai cổng ở đây (3 và 4) kiểm **không để lại hàng nào** sau khi thất bại. Đó là
phép kiểm giao dịch của §4.3, và nó là thứ DUY NHẤT phân biệt "router có
`conn.transaction()`" với "router trông như có": bỏ `conn.transaction()` đi thì
cả hai test đỏ, còn mọi test khác trong file này vẫn xanh.
"""

import httpx
import pytest


async def _dem(pool, sql: str, *args) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(sql, *args)


def _than_hop_le(id_vai_tro: dict[str, str]) -> dict:
    """Biên tập — tên vai trò mẫu tương ứng với `editor` cũ (PQ_01 §2.4, chết ở
    0104). `roleId`, không phải tên — quyết định 2026-08-04 spec §4.0."""
    return {
        "email": "Mai.Anh@AnPhuLand.VN",  # chữ hoa CỐ Ý — kiểm luôn phép chuẩn hoá
        "name": "  Lê Mai Anh  ",  # dấu cách hai đầu CỐ Ý
        "phone": "",  # rỗng -> None, xem `_rong_thanh_none`
        "jobTitle": "Trưởng phòng KD",
        "memberships": [{"workspaceId": "cs_anphu", "roleId": id_vai_tro["Biên tập"], "expiresAt": None}],
    }


async def test_cong_1_owner_tao_user_thanh_pending_co_mot_loi_moi(owner_dang_nhap: httpx.AsyncClient, pool, id_vai_tro):
    """Cổng 1: user `pending` · `password_hash IS NULL` · đúng MỘT hàng invite."""
    r = await owner_dang_nhap.post("/api/v1/users", json=_than_hop_le(id_vai_tro))
    assert r.status_code == 201, r.text
    ra = r.json()

    # id suy từ local-part của email, đọc được bằng mắt (xem `sinh_user_id`).
    assert ra["user"]["id"] == "u_mai_anh"
    assert ra["user"]["email"] == "mai.anh@anphuland.vn", "phải lower() ở biên nhập"
    assert ra["user"]["name"] == "Lê Mai Anh", "phải strip()"
    assert ra["user"]["phone"] is None, "'' và None cùng nghĩa — gộp về None"
    assert ra["user"]["lifecycle"] == "pending"
    # `roleId` đi kèm `role`: id là handle ổn định để FE neo <select> vào, tên chỉ
    # để hiện. Không hardcode được — vai trò mẫu sinh id bằng uuid4().hex ở trigger
    # của 0104, nên phải tra qua fixture `id_vai_tro`.
    assert ra["user"]["memberships"] == [
        {
            "workspaceId": "cs_anphu",
            "workspaceName": "An Phú Land",
            "roleId": id_vai_tro["Biên tập"],
            "role": "Biên tập",
            "expiresAt": None,
        }
    ]

    # LẦN DUY NHẤT token thô ra khỏi server — DB chỉ có sha256 của nó.
    assert ra["invitePath"].startswith("/invite/")
    token = ra["invitePath"].removeprefix("/invite/")
    assert len(token) > 30

    async with pool.acquire() as conn:
        hang = await conn.fetchrow("SELECT password_hash FROM control.users WHERE id = 'u_mai_anh'")
        assert hang["password_hash"] is None, "CHECK song điều kiện: pending <=> hash NULL"

        assert await conn.fetchval("SELECT count(*) FROM control.invites WHERE user_id = 'u_mai_anh'") == 1
        assert await conn.fetchval("SELECT token_hash FROM control.invites") != token, "chỉ lưu sha256"


async def test_cong_1b_nhat_ky_ghi_cap_he_thong_khong_co_tenant_id(
    owner_dang_nhap: httpx.AsyncClient, pool, id_vai_tro
):
    """Hàng nhật ký có `tenant_id` NULL — hành động không thuộc workspace nào.

    Bản cũ còn khẳng định `org_id` có giá trị; cột đó bỏ ở 0106 cùng CHECK
    `audit_log_co_pham_vi_check`. `tenant_id IS NULL` từ nay là toàn bộ phát biểu.

    Và token KHÔNG được nằm trong `chi_tiet`: audit_log là bảng chỉ-ghi-thêm mà
    nhiều người đọc được, một token ở đó là một thư mời dùng được sống vĩnh viễn.
    """
    r = await owner_dang_nhap.post("/api/v1/users", json=_than_hop_le(id_vai_tro))
    assert r.status_code == 201
    token = r.json()["invitePath"].removeprefix("/invite/")

    async with pool.acquire() as conn:
        hang = await conn.fetchrow(
            "SELECT tenant_id, actor, chi_tiet::text FROM control.audit_log WHERE hanh_dong = 'user.tao'"
        )
    assert hang is not None, "tạo user phải vào nhật ký"
    assert hang["tenant_id"] is None
    assert hang["actor"] == "u_dang"
    assert token not in hang["chi_tiet"]


# `test_cong_2_member_khong_tao_duoc_user` XOÁ 2026-08-15: cổng nó neo là
# `org_role='member'` -> 403 ở `_lay_owner()`. Cột và hàm đó không còn; khối
# `/users*` giờ đóng bằng cờ `USERS_ADMIN_ENABLED` — xem `test_co_dong_cong.py`.
@pytest.mark.parametrize("duong", ["/api/v1/users", "/api/v1/users/u_dang"])
async def test_chua_dang_nhap_thi_401_khong_phai_403(app_client: httpx.AsyncClient, duong: str):
    """401 chứ không 403: FE phải đẩy về /login, không hiện màn "không có quyền"."""
    r = await app_client.get(duong)
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "NO_SESSION"


async def test_cong_3_email_trung_thi_409_va_khong_de_lai_hang_nao(
    owner_dang_nhap: httpx.AsyncClient, pool, id_vai_tro
):
    """Cổng 3: email đã có -> 409 EMAIL_TAKEN, KHÔNG có user/invite/membership mới.

    `dang@anphuland.vn` là chính admin đang gọi — trùng email nghĩa là "email này
    đã dùng cho một tài khoản khác", không phải "trong tổ chức này": UNIQUE trên
    `users.email` là toàn cục (0100).
    """
    truoc_user = await _dem(pool, "SELECT count(*) FROM control.users")
    truoc_invite = await _dem(pool, "SELECT count(*) FROM control.invites")
    truoc_ms = await _dem(pool, "SELECT count(*) FROM control.memberships")

    r = await owner_dang_nhap.post("/api/v1/users", json={**_than_hop_le(id_vai_tro), "email": "dang@anphuland.vn"})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "EMAIL_TAKEN"

    assert await _dem(pool, "SELECT count(*) FROM control.users") == truoc_user
    assert await _dem(pool, "SELECT count(*) FROM control.invites") == truoc_invite
    assert await _dem(pool, "SELECT count(*) FROM control.memberships") == truoc_ms


# `test_cong_4b_role_org_khac_...` XOÁ 2026-08-15: vai trò đã TOÀN CỤC (0105)
# nên mọi `roleId` tồn tại đều hợp lệ. Mã lỗi đổi `ROLE_NOT_IN_ORG` ->
# `ROLE_NOT_FOUND`; `tests/modules/auth/test_vai_tro.py` canh nó.
async def test_id_trung_thi_them_hau_to_so(owner_dang_nhap: httpx.AsyncClient, pool, id_vai_tro):
    """Hai email khác nhau cùng suy ra một gốc id -> `u_mai_anh` rồi `u_mai_anh_2`.

    `mai.anh@a.vn` và `mai-anh@b.vn` cùng cho gốc `mai_anh` (mọi ký tự không phải
    [a-z0-9] thành `_`). PK sẽ chặn hàng thứ hai bằng UniqueViolation -> 500 nếu
    phép sinh id không tra DB.
    """
    r1 = await owner_dang_nhap.post("/api/v1/users", json={**_than_hop_le(id_vai_tro), "email": "mai.anh@a.vn"})
    assert r1.status_code == 201, r1.text
    r2 = await owner_dang_nhap.post("/api/v1/users", json={**_than_hop_le(id_vai_tro), "email": "mai-anh@b.vn"})
    assert r2.status_code == 201, r2.text

    assert r1.json()["user"]["id"] == "u_mai_anh"
    assert r2.json()["user"]["id"] == "u_mai_anh_2"


# `test_user_org_khac_tra_404_khong_phai_403` XOÁ 2026-08-15: không còn tổ chức
# nào để một user 'thuộc tổ chức khác'. 404 cho user không tồn tại vẫn đúng và
# do `test_user_khong_ton_tai_tra_404` canh.
