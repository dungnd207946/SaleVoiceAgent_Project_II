"""CỔNG 7 — ba tình huống sai đăng nhập trả CÙNG một mã.

Phân biệt "email không tồn tại" với "sai mật khẩu" là cho không một máy dò danh
sách email khách hàng của mình.
"""

import pytest

from portal.core.auth import password as pw
from portal.core.auth.actions import ALL_ACTIONS
from portal.core.auth.session import TEN_COOKIE
from portal.core.avatar import avatar_data_uri

pytestmark = pytest.mark.integration

MAT_KHAU = "mat-khau-that-cua-dang"


@pytest.fixture
async def du_lieu(pool):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('cs_anphu', 'An Phú Land', 'u_seed_test')"
        )
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name) VALUES ($1, $2, $3, $4)",
            "u_dang",
            "dang@anphuland.vn",
            pw.bam(MAT_KHAU),
            "Trần Hải Đăng",
        )
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name, lifecycle) VALUES ($1, $2, $3, $4, $5)",
            "u_nghi",
            "nghi@anphuland.vn",
            pw.bam(MAT_KHAU),
            "Người Nghỉ",
            "suspended",
        )
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        r_viewer = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Người xem'")
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_dang', 'cs_anphu', $1)",
            r_admin,
        )
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_nghi', 'cs_anphu', $1)",
            r_viewer,
        )
    yield
    async with pool.acquire() as conn, conn.transaction():
        # tenants TRƯỚC users: `tenants.created_by` là FK không CASCADE (0106).
        await conn.execute("DELETE FROM control.tenants WHERE created_by LIKE 'u\\_%' AND created_by <> 'u_seed_test'")
        await conn.execute("DELETE FROM control.users WHERE id LIKE 'u\\_%' AND id <> 'u_seed_test'")
        await conn.execute("DELETE FROM control.tenants WHERE id LIKE 'cs\\_%'")


async def test_dang_nhap_dung_tra_session_va_cookie(app_client, du_lieu):
    r = await app_client.post("/api/v1/auth/login", json={"email": "dang@anphuland.vn", "password": MAT_KHAU})

    assert r.status_code == 200
    assert TEN_COOKIE in r.cookies
    body = r.json()
    assert body["user"]["email"] == "dang@anphuland.vn"
    assert body["user"]["initials"] == "TĐ"
    assert body["currentWorkspaceId"] == "cs_anphu"
    # `dang` là Quản trị ở `cs_anphu` (fixture `du_lieu`) — phải nhận ĐỦ danh mục
    # hành động. So với `len(ALL_ACTIONS)`, không phải một số đếm tay: điểm cần
    # canh là "vai trò Quản trị có mọi action", không phải "danh mục có đúng N
    # phần tử" — số đó đổi mỗi khi có action mới (đã đổi 13 → 14 lúc thêm
    # `billing.read`, `0945_billing_action`), và khoá một literal ở đây sẽ đỏ vì
    # lý do không liên quan tới thứ bài test này thật sự muốn canh.
    assert len(body["actions"]) == len(ALL_ACTIONS)


async def test_dang_nhap_tra_avatar_dicebear_theo_ten(app_client, du_lieu):
    """`user.avatar` = data URI DiceBear seed bằng TÊN — cùng nguồn `core/avatar.py`.

    So bằng chính `avatar_data_uri(...)` chứ không một literal: thứ cần canh là
    "avatar suy từ name qua đúng một hàm", không phải nội dung SVG của một phiên
    bản DiceBear cụ thể. `test_login_va_me_tra_body_giong_het_nhau` đã kéo /me
    theo, không cần bài riêng cho /me.
    """
    r = await app_client.post("/api/v1/auth/login", json={"email": "dang@anphuland.vn", "password": MAT_KHAU})

    body = r.json()
    assert body["user"]["avatar"] == avatar_data_uri("Trần Hải Đăng")


async def test_cookie_phien_la_httponly(app_client, du_lieu):
    """HttpOnly là thứ làm một lỗ XSS không tự động thành mất phiên. Không có nó
    thì `document.cookie` đọc được, và mọi script chèn được đều lấy được phiên."""
    r = await app_client.post("/api/v1/auth/login", json={"email": "dang@anphuland.vn", "password": MAT_KHAU})
    dat = r.headers["set-cookie"].lower()

    assert "httponly" in dat
    assert "samesite=lax" in dat


async def test_email_duoc_chuan_hoa_ve_lower(app_client, du_lieu):
    """Người dùng gõ hoa/thấp lẫn lộn là chuyện thường. Chuẩn hoá ở biên nhập."""
    r = await app_client.post("/api/v1/auth/login", json={"email": "  DANG@AnPhuLand.VN ", "password": MAT_KHAU})
    assert r.status_code == 200


@pytest.mark.parametrize(
    "email,mat_khau",
    [
        ("dang@anphuland.vn", "sai-mat-khau"),  # có user, sai mật khẩu
        ("khongcoai@x.vn", MAT_KHAU),  # không có user
        ("nghi@anphuland.vn", MAT_KHAU),  # có user, đúng mật khẩu, bị đình chỉ
    ],
    ids=["sai-mat-khau", "khong-co-user", "bi-dinh-chi"],
)
async def test_ba_tinh_huong_sai_cung_mot_ma(app_client, du_lieu, email, mat_khau):
    r = await app_client.post("/api/v1/auth/login", json={"email": email, "password": mat_khau})

    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert TEN_COOKIE not in r.cookies


async def test_thong_diep_loi_khong_he_lo_email_nao_co_that(app_client, du_lieu):
    """Cùng mã 401 mà khác câu chữ thì vẫn rò. Ba đường phải giống nhau từng byte."""
    ba = []
    for email, mk in [
        ("dang@anphuland.vn", "sai"),
        ("khongcoai@x.vn", MAT_KHAU),
        ("nghi@anphuland.vn", MAT_KHAU),
    ]:
        r = await app_client.post("/api/v1/auth/login", json={"email": email, "password": mk})
        ba.append(r.json())

    assert ba[0] == ba[1] == ba[2]


async def test_me_khong_co_cookie_tra_401(app_client, du_lieu):
    r = await app_client.get("/api/v1/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "NO_SESSION"


async def test_me_sau_dang_nhap_tra_cung_hinh_dang(app_client, du_lieu):
    """Cùng hình dạng với login: FE dùng một kiểu `Session` cho cả hai."""
    await app_client.post("/api/v1/auth/login", json={"email": "dang@anphuland.vn", "password": MAT_KHAU})
    r = await app_client.get("/api/v1/me")

    assert r.status_code == 200
    assert r.json()["user"]["id"] == "u_dang"
    assert r.json()["workspaces"][0]["plan"] is None


async def test_login_va_me_tra_body_giong_het_nhau(app_client, du_lieu):
    """FE khai MỘT kiểu `Session` cho cả hai đường. Lệch một trường là một nhánh
    render chỉ hỏng sau khi tải lại trang — loại bug khó lần nhất."""
    a = await app_client.post("/api/v1/auth/login", json={"email": "dang@anphuland.vn", "password": MAT_KHAU})
    b = await app_client.get("/api/v1/me")

    assert a.json() == b.json()
