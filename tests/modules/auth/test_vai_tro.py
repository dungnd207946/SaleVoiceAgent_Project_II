"""Sáu endpoint vai trò — cổng 5·9·10·11 của spec §7.

Hai fixture đăng nhập ở đây KHÔNG mượn `owner_dang_nhap`/`client_viewer` của
conftest.py (những cái đó gắn với `u_dang`/org 'noble') — chúng đăng nhập
đúng người của `du_lieu_quyen` (org 'org_q'), vì cổng 11 dưới cần MỘT tổ chức
thứ hai để chứng minh cách ly, và trộn seed 'noble' vào đó là hai nguồn thật
đè lên nhau.

`du_lieu_quyen` chèn `password_hash = 'x'` — không phải hash Argon2 hợp lệ,
vì fixture đó dựng để ĐỌC THẲNG CSDL (`tests/test_ma_tran_quyen.py`), không để
đăng nhập qua HTTP. Nên `client_owner` đặt lại mật khẩu bằng `pw.bam()` trước
khi gọi `POST /auth/login`, đúng khuôn `owner_dang_nhap` của conftest.py.
"""

import json

import httpx
import pytest

from portal.core.auth import password as pw
from portal.modules.auth import repo as auth_repo

pytestmark = pytest.mark.integration

_MAT_KHAU = "mat-khau-cua-vai-tro"


@pytest.fixture
async def client_owner(app_client: httpx.AsyncClient, pool, du_lieu_quyen) -> httpx.AsyncClient:
    """`u_q_owner` — Quản trị của `ws_q` (đủ 13 action), đăng nhập thật.

    Cửa thật cũ (`org_role='owner'` qua `_kiem_owner`) đã bỏ 2026-08-15; cổng còn
    lại là `require(WORKSPACE_ADMIN)` + cờ `ROLES_CRUD_ENABLED` (bật ở conftest).
    """
    async with pool.acquire() as conn:
        await conn.execute("UPDATE control.users SET password_hash = $1 WHERE id = 'u_q_owner'", pw.bam(_MAT_KHAU))
    r = await app_client.post("/api/v1/auth/login", json={"email": "u_q_owner@q.vn", "password": _MAT_KHAU})
    assert r.status_code == 200, r.text
    return app_client


@pytest.fixture
async def client_member_quan_tri(app_client: httpx.AsyncClient, pool, du_lieu_quyen) -> httpx.AsyncClient:
    """Một người KHÁC cũng giữ vai trò Quản trị (đủ 13 action) ở `ws_q`.

    Trước 2026-08-15 fixture này chứng minh cổng THỨ HAI (`org_role`) có chạy:
    một `member` đủ 13 action vẫn phải bị chặn. Cổng đó đã bỏ — giờ nó chỉ còn
    chứng minh rằng quyền quản trị vai trò đi theo `WORKSPACE_ADMIN`, không theo
    một danh tính cụ thể nào.
    """
    ten = du_lieu_quyen.tenant_id
    async with pool.acquire() as conn, conn.transaction():
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        assert r_admin is not None, "migration 0104/0105 phải đã seed vai trò mẫu Quản trị"
        await conn.execute(
            """INSERT INTO control.users (id, email, password_hash, name)
                   VALUES ('u_q_member_qt', 'u_q_member_qt@q.vn', $1, 'Member Quan Tri')
               ON CONFLICT (id) DO NOTHING""",
            pw.bam(_MAT_KHAU),
        )
        await conn.execute(
            """INSERT INTO control.memberships (user_id, tenant_id, role_id)
                   VALUES ('u_q_member_qt', $1, $2)
               ON CONFLICT DO NOTHING""",
            ten,
            r_admin,
        )
    r = await app_client.post("/api/v1/auth/login", json={"email": "u_q_member_qt@q.vn", "password": _MAT_KHAU})
    assert r.status_code == 200, r.text
    return app_client


async def test_owner_tao_va_doc_lai_vai_tro(client_owner):
    r = await client_owner.post(
        "/api/v1/roles",
        json={"name": "Trưởng nhóm CSKH", "description": "Thử", "actions": ["convos.read"]},
    )
    assert r.status_code == 201
    rid = r.json()["id"]

    r2 = await client_owner.get(f"/api/v1/roles/{rid}")
    assert r2.status_code == 200
    assert r2.json()["actions"] == ["convos.read"]


async def test_ai_co_workspace_admin_cung_tao_duoc(client_member_quan_tri):
    """ĐẢO NGƯỢC bản cũ (`test_member_du_13_quyen_van_khong_tao_duoc`).

    Bản cũ neo cổng THỨ HAI: một `org_role='member'` mang vai trò Quản trị (đủ 13
    action) vẫn phải ăn 403, vì `_kiem_owner` chặn ở tầng service. Cổng đó bỏ cùng
    tầng tổ chức 2026-08-15, nên quyền quản trị vai trò giờ đi theo ĐÚNG
    `WORKSPACE_ADMIN` và không theo danh tính nào khác.

    ⚠ Đây chính là rủi ro mà cờ `ROLES_CRUD_ENABLED` tồn tại để chặn: vai trò đã
    TOÀN CỤC (0105), nên "ai có WORKSPACE_ADMIN ở một workspace bất kỳ" nghĩa là
    họ sửa được vai trò của MỌI workspace. Test này khẳng định hành vi khi cờ BẬT;
    `test_co_dong_cong.py` khẳng định mặc định nó TẮT.
    """
    r = await client_member_quan_tri.post(
        "/api/v1/roles", json={"name": "Bởi Thành Viên", "description": None, "actions": []}
    )
    assert r.status_code == 201, r.text


async def test_trung_ten_tra_409(client_owner):
    await client_owner.post("/api/v1/roles", json={"name": "Trùng", "actions": []})
    r = await client_owner.post("/api/v1/roles", json={"name": "Trùng", "actions": []})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ROLE_NAME_TAKEN"


async def test_action_la_tra_422_va_khong_de_lai_hang_nao(client_owner, pool):
    """Cổng 9 §7 — phép kiểm transaction. Thứ duy nhất phân biệt có
    conn.transaction() với trông như có."""
    r = await client_owner.post("/api/v1/roles", json={"name": "Hỏng", "actions": ["catalog.read", "khong.co.that"]})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNKNOWN_ACTION"

    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT count(*) FROM control.roles WHERE name = 'Hỏng'")
    assert n == 0


async def test_patch_thay_the_toan_bo_khong_cong_don(client_owner):
    """Cổng 7 §7."""
    rid = (
        await client_owner.post(
            "/api/v1/roles",
            json={"name": "Thay thế", "actions": ["convos.read", "appts.read"]},
        )
    ).json()["id"]

    await client_owner.patch(f"/api/v1/roles/{rid}", json={"name": "Thay thế", "actions": ["catalog.read"]})
    r = await client_owner.get(f"/api/v1/roles/{rid}")
    assert r.json()["actions"] == ["catalog.read"]


async def test_loi_giua_delete_va_insert_khong_lam_mat_action_cua_vai_tro(client_owner, pool, monkeypatch):
    """Phép kiểm `conn.transaction()` THẬT ở route PATCH /roles/{id} — thứ mà
    `test_action_la_tra_422...` và `test_xoa_vai_tro_dang_dung...` KHÔNG chứng
    minh được: cả hai raise ở bước KIỂM TRƯỚC GHI, trước khi `DELETE` nào chạy,
    nên xoá `conn.transaction()` khỏi route vẫn để cả hai xanh (xem docstring
    `repo.dat_action_cua_vai_tro`).

    Test này ép lỗi xảy ra SAU khi `DELETE FROM control.role_actions` đã THẬT
    SỰ chạy — đúng khe hở docstring cảnh báo: xoá xong mà insert hỏng thì vai
    trò mất sạch quyền, im lặng, TRỪ KHI có `conn.transaction()` bọc ngoài để
    cuộn lại DELETE cùng với INSERT hỏng.

    Không patch từng câu SQL của `dat_action_cua_vai_tro` (patch càng chi tiết
    thì phép kiểm càng phụ thuộc cách hàm đó VIẾT, không phải cách nó phải HÀNH
    XỬ) — patch cả hàm bằng một bản chạy ĐÚNG câu DELETE thật rồi raise ngay
    trước INSERT. Route không hề đổi; đây là cách duy nhất bắt được lỗi ở khe
    hở giữa hai câu SQL mà không cần một cột "hãm insert" giả trong production.
    """
    rid = (
        await client_owner.post(
            "/api/v1/roles",
            json={"name": "Sẽ hỏng giữa đường", "actions": ["convos.read", "appts.read"]},
        )
    ).json()["id"]

    async def vo_giua_duong(conn, role_id, codes):
        await conn.execute(
            """DELETE FROM control.role_actions ra
                 USING control.roles r
                WHERE ra.role_id = r.id AND r.id = $1""",
            role_id,
        )
        raise RuntimeError("hỏng ngay sau DELETE, trước khi INSERT chạy")

    monkeypatch.setattr(auth_repo, "dat_action_cua_vai_tro", vo_giua_duong)

    with pytest.raises(RuntimeError):
        await client_owner.patch(
            f"/api/v1/roles/{rid}", json={"name": "Sẽ hỏng giữa đường", "actions": ["catalog.read"]}
        )

    async with pool.acquire() as conn:
        con_lai = await conn.fetch("SELECT action_code FROM control.role_actions WHERE role_id = $1", rid)
    assert {r["action_code"] for r in con_lai} == {"convos.read", "appts.read"}, (
        "conn.transaction() ở route phải cuộn lại DELETE khi INSERT sau nó hỏng — "
        "nếu tập action rỗng hoặc khác tập gốc, route đang chạy không có transaction thật"
    )


async def test_xoa_vai_tro_dang_dung_tra_409_va_khong_xoa(client_owner, pool, du_lieu_quyen):
    """Cổng 5 §7."""
    r = await client_owner.delete(f"/api/v1/roles/{du_lieu_quyen.role_viewer_id}")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ROLE_IN_USE"
    assert "1" in r.json()["error"]["message"]

    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT count(*) FROM control.roles WHERE id = $1", du_lieu_quyen.role_viewer_id)
    assert n == 1


async def test_xoa_vai_tro_dang_duoc_loi_moi_hua_tra_409_khong_500(client_owner, pool, du_lieu_quyen):
    """Finding B — sequence từ report review: mời ai đó một vai trò rồi xoá vai
    trò đó TRƯỚC khi họ nhận. `dem_nguoi_dung_vai_tro` (đếm `memberships`) báo 0
    vì chưa ai NHẬN — cổng cũ chỉ nhìn con số đó và cho `DELETE` đi qua, rồi vỡ ở
    `ForeignKeyViolationError` (`invites.role_id`, migration 0952 không có
    `ON DELETE`) → 500. Cổng sau khi sửa phải hỏi thêm `dem_loi_moi_dang_treo_vai_tro`
    và chặn ở 409 TRƯỚC khi chạm `DELETE`.
    """
    rid = (
        await client_owner.post(
            "/api/v1/roles",
            json={"name": "Đang được hứa qua lời mời", "actions": []},
        )
    ).json()["id"]

    # Không đi qua `/members` (seam đó `require(WORKSPACE_ADMIN)` cho ĐÚNG
    # workspace của phiên, và vai trò TOÀN CỤC không quan tâm tenant nào) — chèn
    # thẳng một hàng `invites` CÒN SỐNG hứa vai trò `rid`, khớp đúng hình dạng
    # `thanh_vien.moi` sinh ra cho một email chưa có tài khoản.
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO control.invites (token_hash, user_id, email, tenant_id, role_id, expires_at, created_by)
               VALUES (repeat('c', 64), NULL, 'hua@x.vn', $1, $2, now() + interval '7 day', 'u_q_owner')""",
            du_lieu_quyen.tenant_id,
            rid,
        )

    r = await client_owner.delete(f"/api/v1/roles/{rid}")
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "ROLE_IN_USE"
    assert "lời mời" in r.json()["error"]["message"]

    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT count(*) FROM control.roles WHERE id = $1", rid)
    assert n == 1, "vai trò không được xoá khi còn lời mời sống hứa nó"


async def test_xoa_vai_tro_khong_ai_dung_thanh_cong(client_owner):
    rid = (await client_owner.post("/api/v1/roles", json={"name": "Bỏ đi", "actions": []})).json()["id"]
    assert (await client_owner.delete(f"/api/v1/roles/{rid}")).status_code == 204


async def test_vai_tro_khong_ton_tai_tra_404(client_owner):
    """404 cho một `role_id` không có thật.

    THAY `test_vai_tro_to_chuc_khac_tra_404_khong_403`: vai trò đã TOÀN CỤC từ
    migration 0105, nên "vai trò của tổ chức khác" không còn là một trạng thái tồn
    tại được. Câu hỏi duy nhất còn lại là "có thật không" — và câu trả lời vẫn
    phải là 404, không phải 403: 403 xác nhận id đó tồn tại, đủ để dò cấu hình
    quyền của hệ thống.
    """
    r = await client_owner.get("/api/v1/roles/r_khong_co_that")
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "ROLE_NOT_FOUND"


async def test_vai_tro_0_quyen_tao_duoc(client_owner):
    """Cổng 10 §7 — đã tạo, chưa cấu hình là trạng thái thật."""
    r = await client_owner.post("/api/v1/roles", json={"name": "Trống", "actions": []})
    assert r.status_code == 201
    assert r.json()["actions"] == []


async def test_danh_muc_action_tra_17_o_co_thu_tu(client_owner):
    """13 nhóm gốc PQ_01 §3.1 + `billing.read` (`0945_billing_action`,
    2026-08-20) + audit.read (0956_audit_action, 2026-08-25)."""
    r = await client_owner.get("/api/v1/actions")
    o = r.json()
    assert len(o) == 17
    assert [x["sortOrder"] for x in o] == list(range(1, 18))
    assert o[0]["labelVi"]


async def test_danh_sach_kem_user_count(client_owner, du_lieu_quyen):
    r = await client_owner.get("/api/v1/roles")
    theo_id = {x["id"]: x for x in r.json()}
    assert theo_id[du_lieu_quyen.role_viewer_id]["userCount"] == 1


async def test_tao_vai_tro_vao_nhat_ky_cap_to_chuc(client_owner, pool):
    """0103 đã nới audit_log.tenant_id thành NULL kèm CHECK phải có ít nhất một
    phạm vi. Vai trò không thuộc workspace nào nên `tenant_id` là NULL."""
    r_tao = await client_owner.post("/api/v1/roles", json={"name": "Có vết", "actions": ["catalog.read"]})
    role_id = r_tao.json()["id"]

    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            """SELECT tenant_id, chi_tiet FROM control.audit_log
                WHERE hanh_dong = 'role.tao' ORDER BY luc DESC LIMIT 1"""
        )
    assert r is not None
    assert r["tenant_id"] is None
    assert r["tenant_id"] is None

    # Không chỉ kiểm PHẠM VI mà còn kiểm PAYLOAD: một hàng đúng phạm vi nhưng
    # chi_tiet rỗng vẫn không cho auditor dựng lại được vai trò nào, tên gì, quyền
    # gì — đúng thứ nhật ký này tồn tại để trả lời.
    chi_tiet = json.loads(r["chi_tiet"])
    assert chi_tiet["role_id"] == role_id
    assert chi_tiet["name"] == "Có vết"
    assert chi_tiet["actions"] == ["catalog.read"]


async def test_sua_vai_tro_vao_nhat_ky_cap_to_chuc(client_owner, pool):
    """`role.sua` là hàng nhật ký giá trị cao nhất của cả tính năng — nó là bản
    ghi DUY NHẤT của một lần CẤP hoặc THU HỒI quyền. Không có test này thì bỏ
    rơi dòng `nhat_ky.ghi_to_chuc(..., "role.sua", ...)` hoặc gõ sai chuỗi
    `hanh_dong` (ví dụ 'role.update') sẽ không ai nhận ra — cùng lý lẽ đã áp
    cho `role.tao` ở test trên, lặp cho `sua` vì đó là thao tác quan trọng hơn."""
    role_id = (
        await client_owner.post(
            "/api/v1/roles",
            json={"name": "Trước khi sửa", "actions": ["catalog.read"]},
        )
    ).json()["id"]

    r_sua = await client_owner.patch(
        f"/api/v1/roles/{role_id}",
        json={"name": "Sau khi sửa", "actions": ["convos.read", "appts.write"]},
    )
    assert r_sua.status_code == 200

    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            """SELECT tenant_id, chi_tiet FROM control.audit_log
                WHERE hanh_dong = 'role.sua' ORDER BY luc DESC LIMIT 1"""
        )
    assert r is not None
    assert r["tenant_id"] is None
    assert r["tenant_id"] is None, "sửa vai trò là việc cấp tổ chức, không thuộc workspace nào"

    chi_tiet = json.loads(r["chi_tiet"])
    assert chi_tiet["role_id"] == role_id
    assert chi_tiet["name"] == "Sau khi sửa"
    assert set(chi_tiet["actions"]) == {"convos.read", "appts.write"}


async def test_xoa_vai_tro_vao_nhat_ky_giu_ten_va_action_cu(client_owner, pool):
    """`quan_tri_vai_tro.xoa` đọc `hien_tai` TRƯỚC khi DELETE — cố ý, để tên và
    tập action cũ còn sống trong nhật ký sau khi hàng `roles` đã mất. Một refactor
    đảo thứ tự (xoá trước, đọc sau) sẽ ghi lại `None`/rỗng một cách im lặng; test
    này canh đúng cái ĐÃ XOÁ vẫn còn tra được trong `chi_tiet`, không chỉ canh
    PHẠM VI như test `role.tao`/`role.sua` ở trên."""
    ten, actions = "Sắp xoá", ["catalog.read", "appts.read"]
    role_id = (await client_owner.post("/api/v1/roles", json={"name": ten, "actions": actions})).json()["id"]

    r_xoa = await client_owner.delete(f"/api/v1/roles/{role_id}")
    assert r_xoa.status_code == 204

    async with pool.acquire() as conn:
        # Vai trò phải THẬT SỰ đã mất — nếu không, "chi_tiet giữ tên/action cũ"
        # không chứng minh được gì: hàng roles vẫn ở đó thì tra ngược ra cùng giá
        # trị bất kể nhật ký ghi trước hay sau DELETE.
        n = await conn.fetchval("SELECT count(*) FROM control.roles WHERE id = $1", role_id)
        r = await conn.fetchrow(
            """SELECT tenant_id, chi_tiet FROM control.audit_log
                WHERE hanh_dong = 'role.xoa' ORDER BY luc DESC LIMIT 1"""
        )
    assert n == 0, "vai trò phải đã bị xoá thật — nếu không, phép kiểm dưới đây rỗng tuếch"
    assert r is not None
    assert r["tenant_id"] is None
    assert r["tenant_id"] is None, "xoá vai trò là việc cấp tổ chức, không thuộc workspace nào"

    chi_tiet = json.loads(r["chi_tiet"])
    assert chi_tiet["role_id"] == role_id
    assert chi_tiet["name"] == ten
    assert set(chi_tiet["actions"]) == set(actions)
