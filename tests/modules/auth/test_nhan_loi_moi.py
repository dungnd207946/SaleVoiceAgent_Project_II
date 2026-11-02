"""Cổng 7–8 của spec M2b §7 — hai đường CÔNG KHAI của thư mời.

Đây là vòng chạy đầy-đủ mà §8 gọi là "định nghĩa xong": owner tạo user -> mở link
-> đặt mật khẩu -> đăng nhập bằng tài khoản mới -> thấy ĐÚNG những workspace được
cấp và KHÔNG thấy workspace chưa cấp.

Test cuối cùng của file là chỗ duy nhất chứng minh cả chuỗi đó chạy thật.
"""

import httpx
import pytest

MAT_KHAU_MOI = "mat-khau-cua-mai-anh"


@pytest.fixture
async def client_cf(pool, dang_nhap_san, workspace_cfg):
    """TRÙNG với `client_cf` của `test_thanh_vien.py` — cố ý, không rút ra
    `conftest.py`: fixture khai trong một module test chỉ thấy được TRONG module
    đó (đúng thứ docstring module này cảnh báo ở `client_cfg`/`workspace_cfg`
    phía trên), và `conftest.py` nằm ngoài phạm vi file được sửa của việc này.

    `u_dang` (đã đăng nhập, mở ở `cs_anphu` qua `dang_nhap_san`) được cấp Quản
    trị ở `workspace_cfg` rồi CHUYỂN sang đó làm workspace hiện tại — cần fixture
    này ở đây vì các bài Task 7 (ba nhánh nhận lời mời) phải MỜI qua `/members`
    (seam workspace) trước khi có token `invite_new`/`invite_existing` để nhận.
    """
    async with pool.acquire() as conn:
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        assert r_admin is not None, "migration phải đã seed vai trò mẫu 'Quản trị'"
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_dang', $1, $2)",
            workspace_cfg,
            r_admin,
        )
    r = await dang_nhap_san.post("/api/v1/me/workspace", json={"workspaceId": workspace_cfg})
    assert r.status_code == 200, r.text
    return dang_nhap_san


def _than(id_vai_tro: dict[str, str]) -> dict:
    """Biên tập — vai trò mẫu tương ứng với `editor` cũ (PQ_01 §2.4, chết ở
    0104). `roleId`, không phải tên — quyết định 2026-08-04 spec §4.0."""
    return {
        "email": "mai.anh@anphuland.vn",
        "name": "Lê Mai Anh",
        "jobTitle": "Trưởng phòng KD",
        # cs_anphu ĐƯỢC cấp, cs_sunrise/cs_haven KHÔNG — xem test cuối file.
        "memberships": [{"workspaceId": "cs_anphu", "roleId": id_vai_tro["Biên tập"]}],
    }


async def _tao(client: httpx.AsyncClient, id_vai_tro: dict[str, str], **ghi_de) -> str:
    """Trả token thô. Đây là lần duy nhất nó ra khỏi server."""
    r = await client.post("/api/v1/users", json={**_than(id_vai_tro), **ghi_de})
    assert r.status_code == 201, r.text
    return r.json()["invitePath"].removeprefix("/invite/")


async def test_xem_loi_moi_cong_khai_va_chi_tra_bon_truong(app_client: httpx.AsyncClient, owner_dang_nhap, id_vai_tro):
    """`GET /invites/{token}` không cần phiên, và trả ĐÚNG bốn trường.

    ĐỔI TÊN 2026-08-22 (từ "...ba_truong"): `LoiMoiOut` mọc thêm `workspaceName`
    cùng đợt tách `kind` thành ba giá trị — một cái tên còn nói "ba" trong khi
    bài kiểm bốn trường là một cái tên nói dối, tệ hơn không có tên.

    Dùng `app_client` chứ không `owner_dang_nhap` — nhưng cả hai là cùng một object
    httpx (fixture `owner_dang_nhap` trả lại chính `app_client`), nên đây chưa
    chứng minh được tính công khai. Test dưới làm việc đó bằng cách xoá cookie.

    `kind` thêm 2026-08-17 (Task 7): `"signup"` ở ĐÂY dù `_tao()` gọi `POST /users`
    (đường quản trị, không phải tự đăng ký) — đúng hành vi hiện có của
    `quan_tri_user.tao()`: nó luôn ghi thư mời với `tenant_id=None` (xem docstring
    hàm đó — "TaoUserIn nhận NHIỀU membership, không có MỘT workspace duy nhất để
    gắn"), nên `kind` suy từ `tenant_id IS NULL` cũng ra `"signup"` cho đường này,
    không chỉ cho `POST /auth/register`. `"invite_new"`/`"invite_existing"` chỉ
    xuất hiện cho token do seam `/members` phát (nó biết ĐÚNG một `tenant_id`,
    gắn thẳng vào token) — xem `quan_tri_user._kind`.

    `workspaceName` là `None` ở đây CHỈ VÌ `kind == "signup"` (không workspace nào
    được hứa) — không phải vì trường bị bỏ quên.
    """
    token = await _tao(owner_dang_nhap, id_vai_tro)
    r = await app_client.get(f"/api/v1/invites/{token}")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "email": "mai.anh@anphuland.vn",
        "name": "Lê Mai Anh",
        "kind": "signup",
        "workspaceName": None,
    }, "thêm trường nào vào đây là thêm một trường ai giữ link cũng đọc được"


async def test_hai_duong_thu_moi_chay_khi_KHONG_co_cookie(app_client: httpx.AsyncClient, owner_dang_nhap, id_vai_tro):
    """Xoá sạch cookie rồi mới gọi — nếu không, test "công khai" xanh nhờ phiên của admin.

    Đây là phép kiểm thật của `require(None, ly_do=...)` trên hai đường đó: bắt
    đăng nhập để đặt mật khẩu lần đầu là một vòng tròn (muốn đăng nhập thì phải có
    mật khẩu, mà mật khẩu đặt ở đây).
    """
    token = await _tao(owner_dang_nhap, id_vai_tro)
    app_client.cookies.clear()

    r = await app_client.get(f"/api/v1/invites/{token}")
    assert r.status_code == 200, r.text

    r = await app_client.post("/api/v1/invites/accept", json={"token": token, "password": MAT_KHAU_MOI})
    assert r.status_code == 204, r.text


async def test_cong_7_nhan_moi_thanh_active_va_token_chet_sau_mot_lan(
    app_client: httpx.AsyncClient, owner_dang_nhap, pool, id_vai_tro
):
    """Cổng 7: nhận mời -> `active` + có hash; dùng token lần hai -> 404.

    Thiếu lệnh `UPDATE invites SET used_at` là để token sống tiếp sau khi mật khẩu
    đã đặt — ai đọc được link vẫn đặt lại được mật khẩu của người đó. Đó là điều
    nửa sau của test này canh.
    """
    token = await _tao(owner_dang_nhap, id_vai_tro)

    r = await app_client.post("/api/v1/invites/accept", json={"token": token, "password": MAT_KHAU_MOI})
    assert r.status_code == 204, r.text

    async with pool.acquire() as conn:
        hang = await conn.fetchrow("SELECT lifecycle, password_hash FROM control.users WHERE id = 'u_mai_anh'")
        assert hang["lifecycle"] == "active"
        assert hang["password_hash"] is not None
        assert hang["password_hash"] != MAT_KHAU_MOI, "phải là hash Argon2, không phải mật khẩu thô"
        assert await conn.fetchval("SELECT used_at FROM control.invites WHERE user_id = 'u_mai_anh'") is not None

    # Lần hai — cùng token, cùng thân request.
    r = await app_client.post("/api/v1/invites/accept", json={"token": token, "password": "mat-khau-khac-han"})
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "INVITE_INVALID"

    # Và `GET` cũng phải chết theo — vị từ nằm trong WHERE nên không đường nào bỏ qua nó.
    assert (await app_client.get(f"/api/v1/invites/{token}")).status_code == 404


async def test_cong_8_moi_lai_lam_token_cu_chet(app_client: httpx.AsyncClient, owner_dang_nhap, pool, id_vai_tro):
    """Cổng 8: token cũ 404, token mới 200 — và đúng MỘT hàng invite tồn tại.

    `invites.user_id` UNIQUE + `ON CONFLICT (user_id) DO UPDATE`. Không UNIQUE thì
    mỗi lần bấm Mời lại sinh thêm một token dùng được, và thu hồi thành việc phải
    xoá n hàng mà không ai biết n bằng mấy.
    """
    token_cu = await _tao(owner_dang_nhap, id_vai_tro)

    r = await owner_dang_nhap.post("/api/v1/users/u_mai_anh/invite")
    assert r.status_code == 200, r.text
    token_moi = r.json()["invitePath"].removeprefix("/invite/")
    assert token_moi != token_cu

    assert (await app_client.get(f"/api/v1/invites/{token_cu}")).status_code == 404, "token cũ phải chết"
    assert (await app_client.get(f"/api/v1/invites/{token_moi}")).status_code == 200

    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.invites WHERE user_id = 'u_mai_anh'") == 1


async def test_moi_lai_dat_lai_used_at_ve_null(app_client: httpx.AsyncClient, owner_dang_nhap, pool, id_vai_tro):
    """`DO UPDATE` phải khai `used_at = NULL` TƯỜNG MINH.

    Không khai thì hàng cũ giữ nguyên `used_at`, token mới sinh ra đã ở trạng thái
    đã-dùng, và người nhận bấm link ăn 404 mà không ai hiểu vì sao. Kịch bản thật:
    admin mời -> người kia nhận -> admin bấm Mời lại vì tưởng chưa nhận.

    (Ở đây phải hạ user về `pending` bằng SQL: `moi_lai` cố ý từ chối user `active`.)
    """
    token = await _tao(owner_dang_nhap, id_vai_tro)
    assert (
        await app_client.post("/api/v1/invites/accept", json={"token": token, "password": MAT_KHAU_MOI})
    ).status_code == 204

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE control.users SET lifecycle = 'pending', password_hash = NULL WHERE id = 'u_mai_anh'"
        )

    r = await owner_dang_nhap.post("/api/v1/users/u_mai_anh/invite")
    assert r.status_code == 200, r.text
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT used_at FROM control.invites WHERE user_id = 'u_mai_anh'") is None


async def test_moi_lai_va_xoa_tu_choi_user_da_dat_mat_khau(app_client: httpx.AsyncClient, owner_dang_nhap, id_vai_tro):
    """Sinh thư mời cho người đã có mật khẩu = tạo đường đặt lại mật khẩu không ai yêu cầu.

    Quên mật khẩu là việc của M8, với xác minh danh tính của chính người đó —
    không phải một nút của admin.
    """
    token = await _tao(owner_dang_nhap, id_vai_tro)
    await app_client.post("/api/v1/invites/accept", json={"token": token, "password": MAT_KHAU_MOI})

    r = await owner_dang_nhap.post("/api/v1/users/u_mai_anh/invite")
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "USER_NOT_PENDING"

    r = await owner_dang_nhap.delete("/api/v1/users/u_mai_anh")
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "USER_NOT_PENDING"


async def test_xoa_duoc_user_con_pending_va_cascade_go_loi_moi(owner_dang_nhap: httpx.AsyncClient, pool, id_vai_tro):
    """Thu hồi một lời mời gửi sai địa chỉ — CASCADE gỡ luôn invite và membership."""
    await _tao(owner_dang_nhap, id_vai_tro)

    r = await owner_dang_nhap.delete("/api/v1/users/u_mai_anh")
    assert r.status_code == 204, r.text

    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.users WHERE id = 'u_mai_anh'") == 0
        assert await conn.fetchval("SELECT count(*) FROM control.invites WHERE user_id = 'u_mai_anh'") == 0
        assert await conn.fetchval("SELECT count(*) FROM control.memberships WHERE user_id = 'u_mai_anh'") == 0


@pytest.mark.parametrize(
    "token",
    [
        "khong-ton-tai",
        "a" * 64,  # đúng dạng sha256 nhưng không có trong bảng
        "'; DROP TABLE control.invites; --",  # tham số hoá, không nối chuỗi
        "token co dau cach",
        "x" * 500,  # thân dài — không được thành 500 hay treo
    ],
)
async def test_token_sai_du_hinh_dang_nao_cung_404_cung_mot_ma(app_client: httpx.AsyncClient, token: str):
    """Một mã cho ba tình huống (sai · đã dùng · hết hạn) — xem docstring loi.py.

    Phân biệt hết hạn với không tồn tại cho một máy dò biết token nào đã từng
    có thật.

    ⚠ KHÔNG dùng `../../etc/passwd` làm ca kiểm: httpx chuẩn hoá `..` trong đường
    dẫn TRƯỚC khi gửi, nên request đi tới `/etc/passwd` — một route không tồn tại,
    và 404 nhận được là 404 mặc định của FastAPI (`{"detail": ...}`), không phải
    404 của đường này. Ca đó kiểm httpx, không kiểm code ở đây.

    Mọi giá trị ở đây vẫn phải đi qua `bam_token()` trước khi vào SQL — nên CHECK
    `^[0-9a-f]{64}$` của bảng `invites` không bao giờ bị đụng tới từ đường đọc.
    """
    r = await app_client.get(f"/api/v1/invites/{token}")
    assert r.status_code == 404, (token, r.text)
    assert r.json()["error"]["code"] == "INVITE_INVALID"

    r = await app_client.post("/api/v1/invites/accept", json={"token": token, "password": "mat-khau-du-dai"})
    assert r.status_code == 404, (token, r.text)
    assert r.json()["error"]["code"] == "INVITE_INVALID"


async def test_loi_moi_het_han_thi_404(app_client: httpx.AsyncClient, owner_dang_nhap, pool, id_vai_tro):
    """Hạn nằm trong WHERE của truy vấn, không trong một phép kiểm ở service.

    Ở service thì một ngày có người thêm đường gọi thứ hai và quên phép kiểm đó.
    """
    token = await _tao(owner_dang_nhap, id_vai_tro)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE control.invites SET expires_at = now() - interval '1 second'")

    assert (await app_client.get(f"/api/v1/invites/{token}")).status_code == 404
    r = await app_client.post("/api/v1/invites/accept", json={"token": token, "password": MAT_KHAU_MOI})
    assert r.status_code == 404
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT lifecycle FROM control.users WHERE id = 'u_mai_anh'") == "pending"


async def test_vong_chay_day_du_user_moi_thay_dung_workspace_duoc_cap(
    app_client: httpx.AsyncClient, owner_dang_nhap, pool, id_vai_tro
):
    """§8 định nghĩa "xong": tạo -> nhận mời -> đăng nhập -> thấy ĐÚNG quyền đã cấp.

    Nửa quan trọng nhất là phép phủ định: `cs_sunrise` và `cs_haven` tồn tại và
    admin thấy chúng, nhưng user mới thì KHÔNG. Seed chỉ đúng những workspace user
    thuộc thì mọi bug lọc trông như chạy đúng.
    """
    token = await _tao(owner_dang_nhap, id_vai_tro)
    assert (
        await app_client.post("/api/v1/invites/accept", json={"token": token, "password": MAT_KHAU_MOI})
    ).status_code == 204

    # Phiên mới, không mang cookie của admin.
    app_client.cookies.clear()
    r = await app_client.post("/api/v1/auth/login", json={"email": "mai.anh@anphuland.vn", "password": MAT_KHAU_MOI})
    assert r.status_code == 200, r.text
    phien = r.json()

    assert phien["user"]["name"] == "Lê Mai Anh"
    assert phien["user"]["initials"] == "LA", "suy từ name, không phải cột DB"
    assert "orgRole" not in phien
    assert [w["id"] for w in phien["workspaces"]] == ["cs_anphu"]
    assert phien["currentWorkspaceId"] == "cs_anphu"

    # Không đổi sang workspace chưa được cấp — 403, không phải "không tồn tại".
    r = await app_client.post("/api/v1/me/workspace", json={"workspaceId": "cs_sunrise"})
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "FORBIDDEN"

    # Và không phải owner nên không quản được user.
    r = await app_client.get("/api/v1/users")
    assert r.status_code == 403, r.text


# ═══════════════════════════════════════════════════════════════════════════════
#  2026-08-22 — ba nhánh nhận lời mời
# ═══════════════════════════════════════════════════════════════════════════════


async def test_xem_loi_moi_invite_new_noi_ten_workspace_khong_noi_ten_nguoi(
    client_cf, app_client, role_id_bien_tap, mailer_stub, pool, workspace_cfg
):
    from tests.modules.auth.conftest import THU_DA_GUI

    THU_DA_GUI.clear()
    await client_cf.post("/api/v1/members", json={"emails": ["chuaco@x.vn"], "roleId": role_id_bien_tap})
    token = THU_DA_GUI[-1]["token"]

    res = await app_client.get(f"/api/v1/invites/{token}")
    assert res.status_code == 200, res.text
    b = res.json()
    assert b["kind"] == "invite_new"
    assert b["email"] == "chuaco@x.vn"
    assert b["name"] is None
    ten_ws = await pool.fetchval("SELECT name FROM control.tenants WHERE id = $1", workspace_cfg)
    assert b["workspaceName"] == ten_ws


async def test_nhan_invite_new_tao_user_active_va_membership(
    client_cf, app_client, role_id_bien_tap, mailer_stub, pool, workspace_cfg
):
    from tests.modules.auth.conftest import THU_DA_GUI

    THU_DA_GUI.clear()
    await client_cf.post("/api/v1/members", json={"emails": ["tao@x.vn"], "roleId": role_id_bien_tap})
    token = THU_DA_GUI[-1]["token"]

    res = await app_client.post("/api/v1/invites/accept", json={"token": token, "password": "mk"})
    assert res.status_code == 204, res.text

    u = await pool.fetchrow("SELECT id, lifecycle, password_hash FROM control.users WHERE email = 'tao@x.vn'")
    assert u is not None, "tài khoản ra đời ĐÚNG lúc này, không sớm hơn"
    assert u["lifecycle"] == "active"
    assert u["password_hash"] is not None
    assert (
        await pool.fetchval(
            "SELECT role_id FROM control.memberships WHERE user_id = $1 AND tenant_id = $2", u["id"], workspace_cfg
        )
        == role_id_bien_tap
    )

    lai = await app_client.post("/api/v1/invites/accept", json={"token": token, "password": "mk"})
    assert lai.status_code == 404, "token dùng một lần"


async def test_nhan_invite_existing_chi_them_membership_khong_doi_mat_khau(
    client_cf, app_client, role_id_bien_tap, mailer_stub, pool, workspace_cfg
):
    from tests.modules.auth.conftest import THU_DA_GUI

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_daco', 'daco@x.vn', 'Đã Có', 'active', 'bam-cu')"
        )
    THU_DA_GUI.clear()
    await client_cf.post("/api/v1/members", json={"emails": ["daco@x.vn"], "roleId": role_id_bien_tap})
    token = THU_DA_GUI[-1]["token"]

    res = await app_client.post("/api/v1/invites/accept", json={"token": token})
    assert res.status_code == 204, res.text
    assert (
        await pool.fetchval(
            "SELECT count(*) FROM control.memberships WHERE user_id = 'u_daco' AND tenant_id = $1", workspace_cfg
        )
        == 1
    )
    assert await pool.fetchval("SELECT password_hash FROM control.users WHERE id = 'u_daco'") == "bam-cu"


async def test_invite_existing_khong_dap_de_len_vai_tro_da_co(
    client_cf, app_client, role_id_bien_tap, role_id_nguoi_xem, mailer_stub, pool, workspace_cfg
):
    """Cửa sổ còn hở SAU khi `thanh_vien.moi` đã đóng cửa trước: `moi()` chặn mời
    một người ĐÃ là thành viên (`USER_ALREADY_MEMBER`), nhưng một token
    `invite_existing` PHÁT TRƯỚC KHI họ có membership vẫn còn sống 7 ngày — nếu
    trong lúc đó họ trở thành thành viên qua đường KHÁC (`ws_service.tao()`, hay
    khối `/users` admin) với một vai trò khác, rồi mới bấm link cũ, `nhan_loi_moi`
    KHÔNG được lấy vai trò đã hứa trên token đè lên vai trò họ đang giữ —
    `repo.them_membership` là `ON CONFLICT DO UPDATE SET role_id`, và làm vậy là
    đúng lớp lỗi "vai trò đổi qua đường mời" mà cả đợt 2026-08-22 dựng ra để
    chấm dứt."""
    from tests.modules.auth.conftest import THU_DA_GUI

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_dua_role', 'duarole@x.vn', 'Dua Role', 'active', 'bam-cu')"
        )
    THU_DA_GUI.clear()
    await client_cf.post("/api/v1/members", json={"emails": ["duarole@x.vn"], "roleId": role_id_bien_tap})
    token = THU_DA_GUI[-1]["token"]

    # Ngoài luồng, SAU khi token đã phát: họ đã thành viên với một vai trò KHÁC.
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_dua_role', $1, $2)",
            workspace_cfg,
            role_id_nguoi_xem,
        )

    res = await app_client.post("/api/v1/invites/accept", json={"token": token})
    assert res.status_code == 204, res.text
    assert (
        await pool.fetchval(
            "SELECT role_id FROM control.memberships WHERE user_id = 'u_dua_role' AND tenant_id = $1", workspace_cfg
        )
        == role_id_nguoi_xem
    ), "vai trò đã có KHÔNG được đổi lén bởi một token invite_existing cũ"


async def test_invite_existing_gui_kem_mat_khau_bi_bac(client_cf, app_client, role_id_bien_tap, mailer_stub, pool):
    """KHÔNG bỏ qua im lặng: một `password` thừa nghĩa là FE đang hiện một ô nhập
    vô tác dụng, và người dùng vừa gõ một mật khẩu mới rồi tưởng nó đã đổi."""
    from tests.modules.auth.conftest import THU_DA_GUI

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_thua', 'thua@x.vn', 'Thừa', 'active', 'bam-cu')"
        )
    THU_DA_GUI.clear()
    await client_cf.post("/api/v1/members", json={"emails": ["thua@x.vn"], "roleId": role_id_bien_tap})
    token = THU_DA_GUI[-1]["token"]

    res = await app_client.post("/api/v1/invites/accept", json={"token": token, "password": "mk"})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVITE_PASSWORD_NOT_ALLOWED"


async def test_invite_new_thieu_mat_khau_bi_bac(client_cf, app_client, role_id_bien_tap, mailer_stub):
    from tests.modules.auth.conftest import THU_DA_GUI

    THU_DA_GUI.clear()
    await client_cf.post("/api/v1/members", json={"emails": ["thieu@x.vn"], "roleId": role_id_bien_tap})
    token = THU_DA_GUI[-1]["token"]

    res = await app_client.post("/api/v1/invites/accept", json={"token": token})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVITE_PASSWORD_REQUIRED"


async def test_invite_new_ma_email_vua_co_tai_khoan_thi_409(client_cf, app_client, role_id_bien_tap, mailer_stub, pool):
    """Ca đua spec §5.6. KHÔNG tự nối lời mời vào tài khoản vừa có: đường này công
    khai và không kiểm mật khẩu nào, nên làm thế là cho ai giữ link cấp quyền
    workspace cho một tài khoản không phải của mình."""
    from tests.modules.auth.conftest import THU_DA_GUI

    THU_DA_GUI.clear()
    await client_cf.post("/api/v1/members", json={"emails": ["dua@x.vn"], "roleId": role_id_bien_tap})
    token = THU_DA_GUI[-1]["token"]

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_dua', 'dua@x.vn', 'Đua', 'active', 'x')"
        )

    res = await app_client.post("/api/v1/invites/accept", json={"token": token, "password": "mk"})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "EMAIL_DA_CO_TAI_KHOAN"


async def test_invite_new_ca_dua_that_giua_pre_check_va_insert_thi_409_khong_500(
    client_cf, app_client, role_id_bien_tap, mailer_stub, pool, monkeypatch
):
    """Ca đua THẬT (finding C) — khác bài trên ở đúng chỗ quan trọng.

    Bài `test_invite_new_ma_email_vua_co_tai_khoan_thi_409` chèn hàng `users`
    xung đột XONG rồi mới gọi accept — `repo.email_da_dung` (pre-check) thấy
    đúng sự thật và 409 NGAY, không hề chạm câu INSERT của
    `tao_user_da_kich_hoat`. Cổng đó không chứng minh được gì về khe hở READ
    COMMITTED giữa pre-check và INSERT — chỉ chứng minh nhánh tuần tự.

    Bài này MÔ PHỎNG khe hở đó một cách tất định: patch `repo.email_da_dung`
    trả `False` (như thể lượt SELECT đó chạy TRƯỚC khi một `POST /auth/register`
    khác commit), trong khi hàng `users` xung đột ĐÃ CÓ MẶT thật trong DB trước
    khi accept chạy. Với patch này, 409 chỉ có thể đến từ nhánh `except
    asyncpg.UniqueViolationError` mới thêm quanh `tao_user_da_kich_hoat` — nếu
    ai gỡ nhánh đó, bài này đỏ với `500`, còn bài tuần tự ở trên vẫn xanh (patch
    của nó là 0, nó dừng ở pre-check).
    """
    from portal.modules.auth import repo as auth_repo
    from tests.modules.auth.conftest import THU_DA_GUI

    THU_DA_GUI.clear()
    await client_cf.post("/api/v1/members", json={"emails": ["dua2@x.vn"], "roleId": role_id_bien_tap})
    token = THU_DA_GUI[-1]["token"]

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_dua2', 'dua2@x.vn', 'Đua Hai', 'active', 'x')"
        )

    async def gia_pre_check_chua_thay_gi(conn, email):
        return False

    monkeypatch.setattr(auth_repo, "email_da_dung", gia_pre_check_chua_thay_gi)

    res = await app_client.post("/api/v1/invites/accept", json={"token": token, "password": "mk"})
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "EMAIL_DA_CO_TAI_KHOAN"


async def test_signup_van_chay_nhu_cu(app_client, pool, mailer_stub):
    from tests.modules.auth.conftest import THU_DA_GUI

    THU_DA_GUI.clear()
    r = await app_client.post("/api/v1/auth/register", json={"email": "tudk@x.vn", "name": "Tự ĐK"})
    assert r.status_code in (200, 201), r.text
    token = THU_DA_GUI[-1]["token"]

    xem = await app_client.get(f"/api/v1/invites/{token}")
    assert xem.json()["kind"] == "signup"
    assert xem.json()["workspaceName"] is None

    res = await app_client.post("/api/v1/invites/accept", json={"token": token, "password": "mk"})
    assert res.status_code == 204, res.text
    assert await pool.fetchval("SELECT lifecycle FROM control.users WHERE email = 'tudk@x.vn'") == "active"
