"""Cổng 10–11 của spec M2b §7 — `PATCH /api/v1/users/{id}`.

Cổng 10 (thay thế toàn bộ, không cộng dồn) là test dễ viết sai nhất trong repo:
nếu nó chỉ kiểm "membership mới có mặt" thì một `dat_lai_membership` thiếu lệnh
DELETE vẫn xanh. Nên nó kiểm CẢ hai chiều — có cái mới VÀ mất cái cũ.
"""

import httpx

MAT_KHAU_MOI = "mat-khau-cua-mai-anh"


def _tao_than(id_vai_tro: dict[str, str]) -> dict:
    """`cs_anphu` lấy Quản trị — không phải vì test cần đủ 13 quyền cho một
    mục đích cụ thể, mà vì `test_dinh_chi_user_thi_ho_bi_day_ra_o_request_ke_tiep`
    dùng phiên này để gọi `GET /members` (require WORKSPACE_ADMIN) làm PHÉP THỬ
    "còn vào được không", không phải để kiểm ma trận — nên nó cần một vai trò làm
    được việc đó (cùng lý lẽ M2b §"fixture cấp Quản trị", không phải nới require()).
    `cs_sunrise` giữ Người xem để phân biệt hai workspace vẫn có membership khác
    nhau, đúng ý gốc trước migration 0104."""
    return {
        "email": "mai.anh@anphuland.vn",
        "name": "Lê Mai Anh",
        "memberships": [
            {"workspaceId": "cs_anphu", "roleId": id_vai_tro["Quản trị"]},
            {"workspaceId": "cs_sunrise", "roleId": id_vai_tro["Người xem"]},
        ],
    }


async def _tao_va_kich_hoat(client: httpx.AsyncClient, id_vai_tro: dict[str, str]) -> None:
    """Tạo `u_mai_anh` rồi cho họ nhận mời — cần `active` để test đổi lifecycle."""
    r = await client.post("/api/v1/users", json=_tao_than(id_vai_tro))
    assert r.status_code == 201, r.text
    token = r.json()["invitePath"].removeprefix("/invite/")
    r = await client.post("/api/v1/invites/accept", json={"token": token, "password": MAT_KHAU_MOI})
    assert r.status_code == 204, r.text


async def test_cong_10_membership_la_THAY_THE_TOAN_BO_khong_cong_don(
    owner_dang_nhap: httpx.AsyncClient, pool, id_vai_tro
):
    """Cổng 10: gửi [cs_haven] lên một user đang có [cs_anphu, cs_sunrise].

    Kết quả phải là ĐÚNG [cs_haven] — không phải ba dòng. Danh sách gửi lên là
    trạng thái mong muốn cuối cùng (spec §4.4), không phải một danh sách để thêm.
    """
    await _tao_va_kich_hoat(owner_dang_nhap, id_vai_tro)

    r = await owner_dang_nhap.patch(
        "/api/v1/users/u_mai_anh",
        json={
            "name": "Lê Mai Anh",
            "memberships": [{"workspaceId": "cs_haven", "roleId": id_vai_tro["Quản trị"]}],
        },
    )
    assert r.status_code == 200, r.text

    assert [m["workspaceId"] for m in r.json()["memberships"]] == ["cs_haven"]
    async with pool.acquire() as conn:
        con_lai = [
            r["tenant_id"]
            for r in await conn.fetch(
                "SELECT tenant_id FROM control.memberships WHERE user_id = 'u_mai_anh' ORDER BY 1"
            )
        ]
    assert con_lai == ["cs_haven"], "hai dòng cũ phải MẤT, không phải nằm cạnh dòng mới"


async def test_sua_ho_so_va_expires_at(owner_dang_nhap: httpx.AsyncClient, id_vai_tro):
    """Vé hỗ trợ có hạn (BR-Q08) đi qua `memberships.expires_at`.

    `owner` không có hạn — nên bất cứ quyền có thời hạn đều buộc là một membership.
    """
    await _tao_va_kich_hoat(owner_dang_nhap, id_vai_tro)

    r = await owner_dang_nhap.patch(
        "/api/v1/users/u_mai_anh",
        json={
            "name": "Lê Mai Anh (đã đổi)",
            "phone": "0901234567",
            "jobTitle": "Giám đốc KD",
            "memberships": [
                {"workspaceId": "cs_anphu", "roleId": id_vai_tro["Quản trị"], "expiresAt": "2030-01-01T00:00:00Z"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    ra = r.json()
    assert ra["name"] == "Lê Mai Anh (đã đổi)"
    assert ra["phone"] == "0901234567"
    assert ra["jobTitle"] == "Giám đốc KD"
    assert ra["email"] == "mai.anh@anphuland.vn", "PATCH không sửa được email"
    assert ra["memberships"][0]["role"] == "Quản trị"
    assert ra["memberships"][0]["roleId"] == id_vai_tro["Quản trị"], "tên để hiện, id để neo — phải có cả hai"
    assert ra["memberships"][0]["expiresAt"].startswith("2030-01-01")


async def test_role_id_tra_ve_trung_role_id_da_gui_len(owner_dang_nhap: httpx.AsyncClient, id_vai_tro):
    """Vòng tròn ghi-rồi-đọc: id gửi lên là id nhận về, ở CẢ hai đường POST và PATCH.

    Đây là bất biến mà `MembershipOut.roleId` sinh ra để bảo đảm. Trước nó, đường
    ĐỌC chỉ trả TÊN vai trò, nên FE buộc dò ngược tên -> id trên danh sách
    `/api/v1/roles`. Tên là khoá ĐỔI ĐƯỢC (đó là điểm của 0104): đổi tên một vai
    trò, hoặc có hai vai trò trùng tên, thì phép dò khớp SANG vai trò khác và
    <select> hiện một quyền không ai cấp — không lỗi, không cảnh báo.

    Test kiểm theo ÁNH XẠ workspaceId -> roleId chứ không theo chỉ số mảng: thứ tự
    trả về là `ORDER BY t.name`, không phải thứ tự gửi lên, nên so theo vị trí sẽ
    xanh/đỏ vì lý do không liên quan đến điều đang đo.
    """
    gui_luc_tao = {m["workspaceId"]: m["roleId"] for m in _tao_than(id_vai_tro)["memberships"]}
    await _tao_va_kich_hoat(owner_dang_nhap, id_vai_tro)

    r = await owner_dang_nhap.get("/api/v1/users/u_mai_anh")
    assert r.status_code == 200, r.text
    assert {m["workspaceId"]: m["roleId"] for m in r.json()["memberships"]} == gui_luc_tao

    # Đường sửa: đổi sang một vai trò KHÁC hai vai trò lúc tạo, để test đỏ nếu
    # `roleId` bị trả cứng theo giá trị cũ thay vì đọc lại từ hàng vừa ghi.
    gui_luc_sua = {"cs_anphu": id_vai_tro["CSKH"]}
    r = await owner_dang_nhap.patch(
        "/api/v1/users/u_mai_anh",
        json={
            "name": "Lê Mai Anh",
            "memberships": [{"workspaceId": k, "roleId": v} for k, v in gui_luc_sua.items()],
        },
    )
    assert r.status_code == 200, r.text
    assert {m["workspaceId"]: m["roleId"] for m in r.json()["memberships"]} == gui_luc_sua


async def test_membership_het_han_van_hien_tren_man_admin(owner_dang_nhap: httpx.AsyncClient, pool, id_vai_tro):
    """`liet_ke_membership` CỐ Ý không dùng vị từ `_CON_HIEU_LUC`.

    Ẩn dòng đã hết hạn thì hàng biến mất khỏi form, và admin cấp lại một dòng thứ
    hai đúng như dòng đang có — trong khi thứ họ cần biết là "vé đã hết hạn".
    """
    await _tao_va_kich_hoat(owner_dang_nhap, id_vai_tro)
    async with pool.acquire() as conn:
        # ⚠ PHẢI lọc theo `user_id`. Bản cũ đẩy quá hạn MỌI dòng ở `cs_anphu`,
        # kể cả của chính admin đang gọi — và nó vẫn xanh vì admin là
        # `org_role='owner'`, có đủ 13 action mà không cần membership. Nhánh owner
        # đã bỏ 2026-08-15, nên câu UPDATE không lọc sẽ tự khoá cửa admin và mọi
        # request sau đó ăn 403.
        await conn.execute(
            "UPDATE control.memberships SET expires_at = now() - interval '1 day'"
            " WHERE tenant_id = 'cs_anphu' AND user_id = 'u_mai_anh'"
        )

    r = await owner_dang_nhap.get("/api/v1/users/u_mai_anh")
    assert r.status_code == 200, r.text
    assert "cs_anphu" in [m["workspaceId"] for m in r.json()["memberships"]]

    # Nhưng SỐ workspace trên danh sách thì đếm dòng CÒN HIỆU LỰC — hai câu hỏi khác nhau.
    r = await owner_dang_nhap.get("/api/v1/users")
    # `workspaceCount` ĐẾM DÒNG CÒN HIỆU LỰC: user có hai membership, một vừa bị
    # đẩy quá hạn ở trên ⇒ còn 1. `_CON_HIEU_LUC` áp cho con số này nhưng KHÔNG áp
    # cho danh sách `memberships` ở trên — màn admin phải thấy cả dòng hết hạn để
    # biết vì sao người đó mất quyền. Hai phát biểu, một test.
    assert next(u for u in r.json() if u["id"] == "u_mai_anh")["workspaceCount"] == 1


async def test_dinh_chi_user_thi_ho_bi_day_ra_o_request_ke_tiep(owner_dang_nhap: httpx.AsyncClient, pool, id_vai_tro):
    """BR-Q04 chạy thật: đình chỉ có hiệu lực ở REQUEST KẾ TIẾP, không chờ hết phiên.

    Đây là lý do `require()` đọc `lifecycle` từ Postgres mỗi request thay vì tin
    vào bản ghi Redis. CMS cũ nhét vai trò vào phiếu 15 phút, nên "sa thải một
    người xong, 15 phút nữa họ vẫn sửa được dữ liệu".

    HAI PHIÊN TRÊN MỘT CLIENT: cất cookie của admin ra, đăng nhập thành user, rồi
    trả cookie admin về. Dựng client thứ hai đòi chạm `_transport` — API riêng của
    httpx, và một fixture vỡ vì httpx đổi tên trường nội bộ là loại đỏ tệ nhất.
    """
    await _tao_va_kich_hoat(owner_dang_nhap, id_vai_tro)
    cookie_admin = dict(owner_dang_nhap.cookies)

    # --- phiên của user vừa tạo ---
    owner_dang_nhap.cookies.clear()
    r = await owner_dang_nhap.post(
        "/api/v1/auth/login", json={"email": "mai.anh@anphuland.vn", "password": MAT_KHAU_MOI}
    )
    assert r.status_code == 200, r.text
    assert (await owner_dang_nhap.get("/api/v1/members")).status_code == 200, "trước khi đình chỉ thì vào được"
    cookie_user = dict(owner_dang_nhap.cookies)

    # --- admin đình chỉ họ ---
    owner_dang_nhap.cookies.clear()
    owner_dang_nhap.cookies.update(cookie_admin)
    r = await owner_dang_nhap.patch(
        "/api/v1/users/u_mai_anh",
        json={
            "name": "Lê Mai Anh",
            "lifecycle": "suspended",
            "memberships": [{"workspaceId": "cs_anphu", "roleId": id_vai_tro["Biên tập"]}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["lifecycle"] == "suspended"

    # --- phiên CŨ của user, không đăng nhập lại: phải bị chặn NGAY ---
    owner_dang_nhap.cookies.clear()
    owner_dang_nhap.cookies.update(cookie_user)
    r = await owner_dang_nhap.get("/api/v1/members")
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "NO_SESSION", "đình chỉ là chuyện DANH TÍNH -> 401, không 403"

    # Và không đăng nhập lại được — cùng mã với sai mật khẩu.
    owner_dang_nhap.cookies.clear()
    r = await owner_dang_nhap.post(
        "/api/v1/auth/login", json={"email": "mai.anh@anphuland.vn", "password": MAT_KHAU_MOI}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS", "không tiết lộ 'tài khoản bị đình chỉ'"


# `test_cong_11_khong_tu_ha_quyen_chu_to_chuc_cua_minh` XOÁ 2026-08-15: luật
# "không tự bỏ quyền chủ tổ chức" mất cùng `orgRole`. Luật anh em của nó —
# "không tự đình chỉ tài khoản của mình" — KHÔNG liên quan tới tổ chức nên
# giữ nguyên, và `test_cong_12_khong_tu_dinh_chi_minh` vẫn canh nó.
async def test_cong_11b_khong_tu_dinh_chi_minh(owner_dang_nhap: httpx.AsyncClient, pool):
    """Cổng 11b: tự đình chỉ = tự đăng xuất vĩnh viễn, không đường quay lại."""
    r = await owner_dang_nhap.patch(
        "/api/v1/users/u_dang",
        json={"name": "Trần Hải Đăng", "lifecycle": "suspended", "memberships": []},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "SELF_LOCKOUT"

    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT lifecycle FROM control.users WHERE id = 'u_dang'") == "active"


async def test_owner_van_sua_duoc_ho_so_cua_chinh_minh(owner_dang_nhap: httpx.AsyncClient):
    """Nửa còn lại của hai cổng trên: chúng chặn ĐÚNG hai việc, không chặn cả form.

    Không có test này thì một `if la_chinh_minh: raise` quá tay vẫn xanh — và
    owner không sửa được số điện thoại của chính họ.
    """
    r = await owner_dang_nhap.patch(
        "/api/v1/users/u_dang",
        json={
            "name": "Trần Hải Đăng",
            "phone": "0987654321",
            "jobTitle": "Tổng giám đốc",
            "memberships": [],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["phone"] == "0987654321"
    assert "orgRole" not in r.json()


async def test_khong_doi_duoc_lifecycle_cua_user_con_pending(owner_dang_nhap: httpx.AsyncClient, id_vai_tro):
    """CHECK song điều kiện của 0103 nói lại bằng tiếng Việt.

    User chưa có mật khẩu không tồn tại ở trạng thái `active`/`suspended` nào. Để
    UPDATE nổ thì thành 500; kiểm ở service thì thành 409 có câu giải thích.
    """
    r = await owner_dang_nhap.post("/api/v1/users", json=_tao_than(id_vai_tro))
    assert r.status_code == 201, r.text

    r = await owner_dang_nhap.patch(
        "/api/v1/users/u_mai_anh",
        json={
            "name": "Lê Mai Anh",
            "lifecycle": "suspended",
            "memberships": [{"workspaceId": "cs_anphu", "roleId": id_vai_tro["Biên tập"]}],
        },
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "USER_PENDING"


# `test_member_khong_sua_duoc_ai` XOÁ 2026-08-15: cổng nó neo là `org_role`
# trong `_lay_owner()`. Khối `/users*` giờ đóng bằng cờ `USERS_ADMIN_ENABLED`
# — `test_co_dong_cong.py` canh.
