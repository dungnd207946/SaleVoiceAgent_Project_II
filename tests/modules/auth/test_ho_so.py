"""Màn «Hồ sơ & tuỳ chọn» — ba đường self-service: `PATCH /me/ho-so` ·
`GET /me/avatar-goi-y` · `POST /me/mat-khau`.

Cả ba là việc của CHÍNH người đang đăng nhập, không đụng tài nguyên workspace
nào — nên đi khuôn `require(None, ly_do=…)` + `lay_ban_ghi_phien` như
`/me/workspace`, KHÔNG mở lại khối `/users*` (USERS_ADMIN_ENABLED) vốn sửa được
BẤT KỲ ai.

Avatar: chỉ lưu SEED (`control.users.avatar_seed`, migration 0952), avatar là
hàm tất định của seed — NULL = suy từ `name` như trước.
"""

import pytest

from portal.core.auth import password as pw
from portal.core.auth.session import BanGhiPhien
from portal.core.avatar import TEN_STYLES_GOI_Y, avatar_data_uri
from portal.modules.auth import loi as loi_auth
from portal.modules.auth import service

MAT_KHAU = "mat-khau-cu-du-dai"

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def du_lieu(pool):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('cs_hoso', 'Hồ Sơ Land', 'u_seed_test')"
        )
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name, phone, job_title) VALUES ($1,$2,$3,$4,$5,$6)",
            "u_hs",
            "hs@anphuland.vn",
            pw.bam(MAT_KHAU),
            "Trần Hải Đăng",
            None,
            None,
        )
        # User đăng nhập Google — không có mật khẩu để so (0108 nới CHECK).
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name) VALUES ($1,$2,NULL,$3)",
            "u_gg",
            "gg@anphuland.vn",
            "Người Google",
        )
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_hs', 'cs_hoso', $1)",
            r_admin,
        )
    yield
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id = 'cs_hoso'")
        await conn.execute("DELETE FROM control.users WHERE id IN ('u_hs', 'u_gg')")


async def dang_nhap(app_client):
    r = await app_client.post("/api/v1/auth/login", json={"email": "hs@anphuland.vn", "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    return r.json()


# ─── PATCH /me/ho-so ─────────────────────────────────────────────────────────


async def test_sua_ho_so_doi_ten_sdt_chuc_danh_tra_session_moi(app_client, du_lieu):
    await dang_nhap(app_client)

    r = await app_client.patch(
        "/api/v1/me/ho-so",
        json={"name": "Lê Văn Mới", "phone": "0900000001", "jobTitle": "Trưởng nhóm"},
    )

    assert r.status_code == 200, r.text
    u = r.json()["user"]
    assert u["name"] == "Lê Văn Mới"
    # Màn Hồ sơ đọc hai trường này từ CHÍNH session — UserOut phải mang chúng.
    assert u["phone"] == "0900000001"
    assert u["jobTitle"] == "Trưởng nhóm"
    # initials + avatar suy lại từ TÊN MỚI (avatar_seed đang NULL).
    assert u["initials"] == "LM"
    assert u["avatar"] == avatar_data_uri("Lê Văn Mới")


async def test_sua_ho_so_vang_khoa_thi_truong_do_khong_doi(app_client, du_lieu):
    await dang_nhap(app_client)
    await app_client.patch("/api/v1/me/ho-so", json={"phone": "0900000002"})

    r = await app_client.patch("/api/v1/me/ho-so", json={"jobTitle": "Sale"})

    assert r.status_code == 200
    # phone gửi ở lượt trước phải còn nguyên — vắng khoá nghĩa là KHÔNG ĐỔI.
    me = await app_client.get("/api/v1/me")
    assert me.json()["user"]["name"] == "Trần Hải Đăng"


async def test_avatar_seed_doi_avatar_va_null_ve_mac_dinh_theo_ten(app_client, du_lieu):
    await dang_nhap(app_client)

    r = await app_client.patch("/api/v1/me/ho-so", json={"avatarSeed": "hat-giong-tu-chon"})
    assert r.json()["user"]["avatar"] == avatar_data_uri("hat-giong-tu-chon")

    # Sửa hồ sơ KHÔNG kèm avatarSeed ⇒ seed đã chọn phải còn nguyên.
    r = await app_client.patch("/api/v1/me/ho-so", json={"jobTitle": "Sale"})
    assert r.json()["user"]["avatar"] == avatar_data_uri("hat-giong-tu-chon")

    # `avatarSeed: null` TƯỜNG MINH = về mặc định suy từ tên.
    r = await app_client.patch("/api/v1/me/ho-so", json={"avatarSeed": None})
    assert r.json()["user"]["avatar"] == avatar_data_uri("Trần Hải Đăng")


async def test_ten_rong_bi_422(app_client, du_lieu):
    await dang_nhap(app_client)

    r = await app_client.patch("/api/v1/me/ho-so", json={"name": "   "})

    assert r.status_code == 422


async def test_sua_ho_so_chua_dang_nhap_401(app_client, du_lieu):
    r = await app_client.patch("/api/v1/me/ho-so", json={"name": "Ai Đó"})

    assert r.status_code == 401


# ─── GET /me/avatar-goi-y ────────────────────────────────────────────────────


async def test_goi_y_tron_nhieu_style_seed_khac_nhau_kem_avatar(app_client, du_lieu):
    """Lưới «Đổi avatar» phải NHIỀU KIỂU khác nhau (người dùng chốt 2026-08-22):
    mỗi style trong sổ `TEN_STYLES_GOI_Y` góp mặt, seed mang tiền tố `style:`
    để lưu một cột mà vẫn dựng lại đúng hình."""
    await dang_nhap(app_client)

    r = await app_client.get("/api/v1/me/avatar-goi-y")

    assert r.status_code == 200
    muc = r.json()
    assert len(muc) == 4 * len(TEN_STYLES_GOI_Y)
    assert len({m["seed"] for m in muc}) == len(muc)
    assert {m["seed"].split(":")[0] for m in muc} == set(TEN_STYLES_GOI_Y)
    for m in muc:
        assert m["avatar"].startswith("data:image/svg+xml")
        # Gợi ý phải khớp CHÍNH hàm sinh thật — chọn xong lưu seed là ra đúng hình này.
        assert m["avatar"] == avatar_data_uri(m["seed"])


# ─── POST /me/mat-khau ───────────────────────────────────────────────────────


async def test_doi_mat_khau_dung_thi_dang_nhap_bang_mat_khau_moi(app_client, du_lieu):
    await dang_nhap(app_client)

    r = await app_client.post(
        "/api/v1/me/mat-khau",
        json={"matKhauHienTai": MAT_KHAU, "matKhauMoi": "mat-khau-moi-du-dai"},
    )
    assert r.status_code == 204, r.text

    cu = await app_client.post("/api/v1/auth/login", json={"email": "hs@anphuland.vn", "password": MAT_KHAU})
    assert cu.status_code == 401
    moi = await app_client.post(
        "/api/v1/auth/login", json={"email": "hs@anphuland.vn", "password": "mat-khau-moi-du-dai"}
    )
    assert moi.status_code == 200


async def test_doi_mat_khau_sai_hien_tai_400_va_hash_khong_doi(app_client, du_lieu):
    await dang_nhap(app_client)

    r = await app_client.post(
        "/api/v1/me/mat-khau",
        json={"matKhauHienTai": "doan-bua", "matKhauMoi": "mat-khau-moi-du-dai"},
    )

    assert r.status_code == 400
    assert r.json()["error"]["code"] == "MAT_KHAU_HIEN_TAI_SAI"
    # Hash không đổi — mật khẩu cũ vẫn đăng nhập được.
    lai = await app_client.post("/api/v1/auth/login", json={"email": "hs@anphuland.vn", "password": MAT_KHAU})
    assert lai.status_code == 200


async def test_user_google_khong_co_mat_khau_409(pool, du_lieu):
    """Mức service — user Google không đăng nhập bằng mật khẩu được nên không
    mint phiên qua /auth/login; đường HTTP đã có các ca trên phủ."""
    async with pool.acquire() as conn:
        with pytest.raises(loi_auth.LoiPortal) as bat:
            await service.doi_mat_khau(
                conn, "u_gg", mat_khau_hien_tai="gi-cung-sai", mat_khau_moi="mat-khau-moi-du-dai"
            )
    assert bat.value.http == 409
    assert bat.value.ma == "KHONG_CO_MAT_KHAU"


# ─── `coMatKhau` trong UserOut ───────────────────────────────────────────────


async def test_login_mang_co_mat_khau_true(app_client, du_lieu):
    body = await dang_nhap(app_client)
    assert body["user"]["coMatKhau"] is True


async def test_user_google_co_mat_khau_false(pool, du_lieu):
    async with pool.acquire() as conn:
        ra = await service.dung_session_out(conn, BanGhiPhien("u_gg", None))
    assert ra.user.coMatKhau is False
