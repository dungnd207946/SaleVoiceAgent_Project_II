"""Seam `/members` GHI — mời · đổi vai trò · gỡ · mời lại (task-5/6-brief.md).

Không dùng `@pytest.mark.anyio`: `pyproject.toml` cấu hình `asyncio_mode = "auto"`
(pytest-asyncio), không phải plugin `anyio` — cùng quy ước với `test_repo.py` /
`test_repo_thanh_vien.py` (mark `integration` ở CẤP MODULE, không mark từng hàm).

Không dùng `client_cfg`: fixture đó khai ở `tests/modules/config/conftest.py`,
NGOÀI phạm vi `tests/modules/auth/` — dùng nó ở đây là "fixture not found". Thay
vào đó, `client_cf` (khai cục bộ, dưới đây) log-in `u_dang` qua `dang_nhap_san`
rồi CHUYỂN workspace hiện tại sang `workspace_cfg` (`cf_tv`): `Principal.tenant_id`
seam này luôn suy từ workspace hiện tại của phiên, nên client phải đang MỞ đúng
workspace test sẽ assert vào — nếu không test kiểm nhầm tenant.
"""

import asyncpg
import httpx
import pytest

from portal.modules.auth import repo

pytestmark = pytest.mark.integration


@pytest.fixture
async def client_cf(pool, dang_nhap_san, workspace_cfg):
    """`u_dang` (đã đăng nhập, mở ở `cs_anphu` qua `dang_nhap_san`) được cấp
    Quản trị ở `workspace_cfg` rồi CHUYỂN sang đó làm workspace hiện tại.

    Vai trò đọc từ DB mỗi request (BR-Q04) nên cấp SAU khi đăng nhập là đủ,
    không cần seed lại từ đầu — cùng lối `owner_dang_nhap`/`client_viewer` đã làm.
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


# ═══════════════════════════════════════════════════════════════════════════════
#  Task 5 — POST /members, ba nhánh theo trạng thái email
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
#  2026-08-22 — MỜI = HỎI, KHÔNG PHẢI LÀM
# ═══════════════════════════════════════════════════════════════════════════════
#
# Hai bài cũ ở chỗ này canh đúng hai hành vi vừa bị bỏ: "mời email mới ⇒ tạo user
# pending" và "mời người active ⇒ chỉ thêm membership". Chúng KHÔNG được sửa cho
# xanh — chúng được thay, vì thứ chúng canh đã thôi là hành vi đúng.


async def test_moi_email_moi_khong_tao_user_nao(client_cf, pool, workspace_cfg, role_id_bien_tap, mailer_stub):
    """Trái tim của thay đổi: mời xong, hệ thống chưa biết người đó là ai."""
    from tests.modules.auth.conftest import THU_DA_GUI

    res = await client_cf.post("/api/v1/members", json={"emails": ["moi1@x.vn"], "roleId": role_id_bien_tap})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["loi"] == []
    assert body["invites"][0]["daCo"] is False
    assert body["invites"][0]["userId"] is None, "chưa có tài khoản nào để trỏ tới"

    assert await pool.fetchval("SELECT count(*) FROM control.users WHERE email = 'moi1@x.vn'") == 0
    assert await pool.fetchval("SELECT count(*) FROM control.memberships WHERE tenant_id = $1", workspace_cfg) >= 1

    r = await pool.fetchrow("SELECT user_id, tenant_id, role_id FROM control.invites WHERE email = 'moi1@x.vn'")
    assert r["user_id"] is None
    assert r["tenant_id"] == workspace_cfg
    assert r["role_id"] == role_id_bien_tap, "vai trò đã hứa phải nằm trên chính lời mời"

    # `thu_loi_moi_moi` và `thu_loi_moi_da_co` chia CÙNG một tieu_de — chỉ thân
    # thư phân biệt được. Email chưa có tài khoản phải nhận thư "tạo tài khoản",
    # KHÔNG phải thư "mật khẩu không đổi" của người đã có tài khoản.
    thu_gui = THU_DA_GUI[-1]
    assert thu_gui["tieu_de"] == "Lời mời tham gia workspace CF Thanh Vien trên NobleX Agent Portal"
    assert "tạo tài khoản cho địa chỉ moi1@x.vn" in thu_gui["than_text"]
    assert "không thay đổi" not in thu_gui["than_text"]


async def test_moi_nguoi_da_active_khong_them_membership_ma_phat_token(
    client_cf, pool, workspace_cfg, role_id_bien_tap, mailer_stub
):
    """Trước 2026-08-22 nhánh này thêm thẳng, không thư. Nghĩa là một Quản trị kéo
    được người lạ vào workspace của mình mà họ chỉ biết khi thấy nó trong switcher."""
    from tests.modules.auth.conftest import THU_DA_GUI

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_sanco', 'sanco@x.vn', 'Sẵn Có', 'active', 'x')"
        )
    res = await client_cf.post("/api/v1/members", json={"emails": ["sanco@x.vn"], "roleId": role_id_bien_tap})
    assert res.status_code == 201, res.text
    k = res.json()["invites"][0]
    assert k["daCo"] is True
    assert k["userId"] == "u_sanco"

    assert (
        await pool.fetchval(
            "SELECT count(*) FROM control.memberships WHERE user_id = 'u_sanco' AND tenant_id = $1", workspace_cfg
        )
        == 0
    ), "KHÔNG được thêm thẳng — phải chờ họ xác nhận"
    r = await pool.fetchrow("SELECT user_id, role_id FROM control.invites WHERE email = 'sanco@x.vn'")
    assert r["user_id"] == "u_sanco"
    assert r["role_id"] == role_id_bien_tap

    # Cùng lý do trên: một tài khoản ĐÃ CÓ phải nhận thư "mật khẩu không đổi",
    # không phải thư "tạo tài khoản" của một email chưa từng có ai.
    thu_gui = THU_DA_GUI[-1]
    assert thu_gui["tieu_de"] == "Lời mời tham gia workspace CF Thanh Vien trên NobleX Agent Portal"
    assert "Mật khẩu của bạn không thay đổi" in thu_gui["than_text"]
    assert "tạo tài khoản cho địa chỉ" not in thu_gui["than_text"]


async def test_moi_nguoi_da_la_thanh_vien_tra_loi_tung_dong(
    client_cf, pool, workspace_cfg, role_id_bien_tap, role_id_nguoi_xem
):
    """Trước đây ca này UPSERT im lặng thành công — mời lại người đã ở trong nhà
    cũng trả `daCo=true`. Nay nó sẽ gửi cho họ một lá thư mời vào chỗ họ đã ở."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_trongnha', 'trongnha@x.vn', 'Trong Nhà', 'active', 'x')"
        )
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_trongnha', $1, $2)",
            workspace_cfg,
            role_id_nguoi_xem,
        )
    res = await client_cf.post("/api/v1/members", json={"emails": ["trongnha@x.vn"], "roleId": role_id_bien_tap})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["invites"] == []
    assert body["loi"] == [{"email": "trongnha@x.vn", "ma": "USER_ALREADY_MEMBER"}]
    assert (
        await pool.fetchval(
            "SELECT role_id FROM control.memberships WHERE user_id = 'u_trongnha' AND tenant_id = $1", workspace_cfg
        )
        == role_id_nguoi_xem
    ), "vai trò cũ KHÔNG được đổi lén qua đường mời"


async def test_mot_dong_hong_khong_keo_ca_lo(client_cf, pool, workspace_cfg, role_id_bien_tap):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_dinhchi', 'dinhchi@x.vn', 'Đình Chỉ', 'suspended', 'x')"
        )
    res = await client_cf.post(
        "/api/v1/members",
        json={"emails": ["ok1@x.vn", "dinhchi@x.vn", "ok2@x.vn"], "roleId": role_id_bien_tap},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert {i["email"] for i in body["invites"]} == {"ok1@x.vn", "ok2@x.vn"}
    assert body["loi"] == [{"email": "dinhchi@x.vn", "ma": "USER_SUSPENDED"}]


async def test_get_members_tra_ca_hang_loi_moi(client_cf, role_id_bien_tap):
    await client_cf.post("/api/v1/members", json={"emails": ["treo@x.vn"], "roleId": role_id_bien_tap})
    res = await client_cf.get("/api/v1/members")
    assert res.status_code == 200, res.text
    theo_email = {m["email"]: m for m in res.json()}
    h = theo_email["treo@x.vn"]
    assert h["kind"] == "invite"
    assert h["userId"] is None
    assert h["name"] is None
    assert h["lifecycle"] is None
    assert h["expiresAt"] is not None


async def test_thu_hoi_loi_moi(client_cf, role_id_bien_tap):
    await client_cf.post("/api/v1/members", json={"emails": ["huy@x.vn"], "roleId": role_id_bien_tap})
    res = await client_cf.delete("/api/v1/members/invites/huy%40x.vn")
    assert res.status_code == 204, res.text
    assert "huy@x.vn" not in {m["email"] for m in (await client_cf.get("/api/v1/members")).json()}

    lai = await client_cf.delete("/api/v1/members/invites/huy%40x.vn")
    assert lai.status_code == 404
    assert lai.json()["error"]["code"] == "INVITE_NOT_FOUND"


async def test_gui_lai_loi_moi_giet_token_cu(client_cf, pool, role_id_bien_tap, mailer_stub):
    from tests.modules.auth.conftest import THU_DA_GUI

    THU_DA_GUI.clear()
    await client_cf.post("/api/v1/members", json={"emails": ["lai@x.vn"], "roleId": role_id_bien_tap})
    token_cu = THU_DA_GUI[-1]["token"]

    res = await client_cf.post("/api/v1/members/invites/lai%40x.vn/resend")
    assert res.status_code == 200, res.text
    token_moi = THU_DA_GUI[-1]["token"]
    assert token_moi != token_cu

    assert (await client_cf.get(f"/api/v1/invites/{token_cu}")).status_code == 404
    assert (await client_cf.get(f"/api/v1/invites/{token_moi}")).status_code == 200


async def test_gui_lai_loi_moi_email_da_active_thi_token_moi_accept_duoc(
    client_cf, app_client: httpx.AsyncClient, pool, role_id_bien_tap, mailer_stub
):
    """Finding F — race đã sửa: lời mời gốc phát khi email CHƯA có tài khoản
    (`invite_new`, `user_id=NULL`), rồi CHÍNH email đó tự đăng ký và trở thành
    `active` TRƯỚC khi admin bấm «Gửi lại». Token cũ, nếu bị mint lại nguyên
    `user_id=NULL`, sẽ mãi mãi 409 `EMAIL_DA_CO_TAI_KHOAN` ở accept — đây là
    "permanently unacceptable token" mà report mô tả. Token MỚI phải re-resolve
    ra `invite_existing` và accept được (204).
    """
    from tests.modules.auth.conftest import THU_DA_GUI

    THU_DA_GUI.clear()
    await client_cf.post("/api/v1/members", json={"emails": ["dagn@x.vn"], "roleId": role_id_bien_tap})

    # Email tự đăng ký VÀ kích hoạt xong (giả bằng SQL thẳng — luồng thật là
    # `POST /auth/register` + đặt mật khẩu qua chính lời mời SIGNUP của nó,
    # không liên quan gì tới lời mời workspace đang treo ở trên).
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_dagn', 'dagn@x.vn', 'Đã Có Tài Khoản', 'active', 'x')"
        )

    THU_DA_GUI.clear()
    res = await client_cf.post("/api/v1/members/invites/dagn%40x.vn/resend")
    assert res.status_code == 200, res.text
    token_moi = THU_DA_GUI[-1]["token"]

    # Trước bản sửa F: token này vẫn mang `user_id=NULL` (invite_new) và ăn 409
    # `EMAIL_DA_CO_TAI_KHOAN` VĨNH VIỄN ở đây — không cách nào accept được.
    xem = await app_client.get(f"/api/v1/invites/{token_moi}")
    assert xem.status_code == 200, xem.text
    assert xem.json()["kind"] == "invite_existing", (
        "token gửi lại phải re-resolve theo trạng thái HIỆN TẠI của email, không mang hình invite_new cũ"
    )

    accept = await app_client.post("/api/v1/invites/accept", json={"token": token_moi})
    assert accept.status_code == 204, accept.text
    assert await pool.fetchval("SELECT count(*) FROM control.memberships WHERE user_id = 'u_dagn'") == 1


async def test_gui_lai_loi_moi_email_dang_tu_dang_ky_thi_tu_choi(client_cf, pool, role_id_bien_tap, mailer_stub):
    """Finding F — nhánh `pending`: KHÔNG phát token mới. Mang `user_id` của một
    user `pending` đi cùng `tenant_id` là dựng một hình `doc_loi_moi_con_hieu_luc`
    không nhận nhánh nào (chết cả ở GET) — tệ hơn 409 hiện tại. Cùng lý lẽ
    `USER_PENDING_SIGNUP` ở `thanh_vien.moi`.
    """
    from tests.modules.auth.conftest import THU_DA_GUI

    THU_DA_GUI.clear()
    await client_cf.post("/api/v1/members", json={"emails": ["dangpending@x.vn"], "roleId": role_id_bien_tap})

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle) "
            "VALUES ('u_dp', 'dangpending@x.vn', 'Đang Đăng Ký', 'pending')"
        )

    res = await client_cf.post("/api/v1/members/invites/dangpending%40x.vn/resend")
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "USER_PENDING_SIGNUP"


async def test_gui_lai_loi_moi_email_bi_dinh_chi_thi_tu_choi(client_cf, pool, role_id_bien_tap, mailer_stub):
    """Finding F — nhánh `suspended`, cùng lý lẽ `USER_SUSPENDED` ở `thanh_vien.moi`."""
    from tests.modules.auth.conftest import THU_DA_GUI

    THU_DA_GUI.clear()
    await client_cf.post("/api/v1/members", json={"emails": ["dinhchilai@x.vn"], "roleId": role_id_bien_tap})

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_dcl', 'dinhchilai@x.vn', 'Đình Chỉ Lại', 'suspended', 'x')"
        )

    res = await client_cf.post("/api/v1/members/invites/dinhchilai%40x.vn/resend")
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "USER_SUSPENDED"


async def test_moi_nguoi_dang_cho_dang_ky_bi_tu_choi_rieng_dong_do(client_cf, pool, role_id_bien_tap):
    """Phát token cho họ sẽ giết token đăng ký của chính họ."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id,email,name,lifecycle) VALUES ('u_pen','pen@x.vn','Pen','pending')"
        )
        await conn.execute(
            """INSERT INTO control.invites (token_hash,user_id,email,tenant_id,expires_at,created_by)
               VALUES (repeat('b',64),'u_pen','pen@x.vn',NULL, now() + interval '7 day','u_pen')"""
        )
    res = await client_cf.post(
        "/api/v1/members", json={"emails": ["pen@x.vn", "khac@x.vn"], "roleId": role_id_bien_tap}
    )
    assert res.status_code == 201
    body = res.json()
    assert body["loi"] == [{"email": "pen@x.vn", "ma": "USER_PENDING_SIGNUP"}]
    assert [i["email"] for i in body["invites"]] == ["khac@x.vn"], "39 người kia phải vào được"
    assert await pool.fetchval("SELECT token_hash FROM control.invites WHERE user_id='u_pen'") == "b" * 64, (
        "email pending bị từ chối TRƯỚC khi phát token mới — token đăng ký cũ của họ phải CÒN SỐNG, không bị đụng"
    )


async def test_moi_nguoi_suspended_bi_tu_choi_khong_them_membership(client_cf, pool, workspace_cfg, role_id_bien_tap):
    """⑤c: user `suspended` KHÔNG được nối vào workspace — đình chỉ nghĩa là thu
    hồi quyền, cấp membership mới ở đây là hoàn tác chính việc đó."""
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO control.users (id,email,name,password_hash,lifecycle)
               VALUES ('u_sus','sus@x.vn','Sus','$argon2id$fake','suspended')"""
        )
    res = await client_cf.post("/api/v1/members", json={"emails": ["sus@x.vn"], "roleId": role_id_bien_tap})
    assert res.status_code == 201
    body = res.json()
    assert body["loi"] == [{"email": "sus@x.vn", "ma": "USER_SUSPENDED"}]
    assert body["invites"] == []
    assert (
        await pool.fetchval(
            "SELECT count(*) FROM control.memberships WHERE user_id='u_sus' AND tenant_id=$1",
            workspace_cfg,
        )
        == 0
    ), "user đình chỉ KHÔNG được cấp membership"


async def test_role_khong_ton_tai_tra_422(client_cf):
    res = await client_cf.post("/api/v1/members", json={"emails": ["a@x.vn"], "roleId": "r_ma"})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "ROLE_NOT_FOUND"


# ═══════════════════════════════════════════════════════════════════════════════
#  Task 6 — PATCH · DELETE · POST .../invite trên /members
# ═══════════════════════════════════════════════════════════════════════════════


async def test_patch_doi_vai_tro_tra_member_moi(client_cf, pool, workspace_cfg, role_id_bien_tap, role_id_nguoi_xem):
    """Seed trực tiếp qua SQL, không qua `POST /members`: từ 2026-08-22 lời mời
    không còn tạo user/membership nào, nên không còn cách nào lấy một `userId`
    thật từ response của nó — PATCH cần một THÀNH VIÊN đã tồn tại."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_patch', 'patch@x.vn', 'Patch', 'active', 'x')"
        )
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_patch', $1, $2)",
            workspace_cfg,
            role_id_bien_tap,
        )

    r2 = await client_cf.patch("/api/v1/members/u_patch", json={"roleId": role_id_nguoi_xem})
    assert r2.status_code == 200, r2.text
    assert r2.json()["roleId"] == role_id_nguoi_xem


async def test_patch_nguoi_ngoai_workspace_tra_404(client_cf, role_id_nguoi_xem):
    r = await client_cf.patch("/api/v1/members/u_khong_co", json={"roleId": role_id_nguoi_xem})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "USER_NOT_FOUND"


async def test_delete_go_khoi_workspace_ma_tai_khoan_con(client_cf, pool, workspace_cfg, role_id_bien_tap):
    """Seed trực tiếp — cùng lý do với `test_patch_doi_vai_tro_tra_member_moi`."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_del', 'del@x.vn', 'Del', 'active', 'x')"
        )
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_del', $1, $2)",
            workspace_cfg,
            role_id_bien_tap,
        )

    r2 = await client_cf.delete("/api/v1/members/u_del")
    assert r2.status_code == 204
    assert await pool.fetchval("SELECT 1 FROM control.users WHERE id='u_del'") == 1


async def test_delete_tu_go_minh_khoi_workspace_bi_tu_choi(client_cf, pool, workspace_cfg):
    """⑥ Minor đã hoãn, nay bắt buộc trước merge: `thanh_vien.go()` chặn tự-gỡ-mình
    (`user_id == actor_id`) nhưng chưa có bài nào phủ nhánh đó qua HTTP thật.

    `client_cf` đăng nhập là `u_dang`, đang mở ở `workspace_cfg` — actor tự gọi
    DELETE lên chính mình. Đây là nhánh giữ cho một workspace không mất Quản trị
    cuối cùng (không có console Nền tảng nào cứu — 0106 §10.1), nên một regress ở
    đây là hỏng không hoàn tác được, và tới nay không cổng nào bắt được nó.

    Tự kiểm (đã làm thủ công khi viết bài này): tạm bỏ điều kiện `user_id ==
    actor_id` trong `thanh_vien.go()` — bài dưới đỏ (204 thay vì 409), xác nhận
    bài THẬT SỰ phủ nhánh, không phải xanh vì lý do khác."""
    res = await client_cf.delete("/api/v1/members/u_dang")
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "SELF_LOCKOUT"
    assert (
        await pool.fetchval(
            "SELECT count(*) FROM control.memberships WHERE user_id='u_dang' AND tenant_id=$1",
            workspace_cfg,
        )
        == 1
    ), "membership của actor phải CÒN NGUYÊN — DELETE bị từ chối trước khi chạm DB"


async def test_moi_lai_giet_token_cu(client_cf, pool, workspace_cfg, role_id_bien_tap, mailer_stub):
    """`POST /members/{uid}/invite` phục vụ một THÀNH VIÊN đã có membership, chỉ
    thiếu mật khẩu — không còn là hình `POST /members` tạo ra được từ 2026-08-22
    (mời không còn ghi user/membership nào), nên seed trực tiếp qua SQL, đúng
    hình dạng mà `cli/seed_owner.py` / `/users` admin (`quan_tri_user.tao()`) vẫn
    còn tạo ra: một user `pending` với một membership đã có sẵn ở workspace này.

    Token mà đường này phát ra là SIGNUP-SHAPED, không workspace-shaped —
    lý do đầy đủ (ba hình 0952 chấp nhận, vì sao workspace-shaped ở đây sẽ
    KHÔNG BAO GIỜ redeem được) nằm ở docstring `thanh_vien.moi_lai`; đừng chép
    lại nó ở đây, đọc ở đó.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle) "
            "VALUES ('u_moilai', 'moilai@x.vn', 'Moi Lai', 'pending')"
        )
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_moilai', $1, $2)",
            workspace_cfg,
            role_id_bien_tap,
        )
        await conn.execute(
            "INSERT INTO control.invites (token_hash, user_id, email, tenant_id, role_id, expires_at, created_by) "
            "VALUES (repeat('a', 64), 'u_moilai', 'moilai@x.vn', NULL, NULL, now() + interval '7 day', 'u_dang')"
        )
    cu = "a" * 64

    from tests.modules.auth.conftest import THU_DA_GUI

    r2 = await client_cf.post("/api/v1/members/u_moilai/invite")
    assert r2.status_code == 200, r2.text

    r = await pool.fetchrow("SELECT token_hash, tenant_id, role_id FROM control.invites WHERE user_id = 'u_moilai'")
    assert r["token_hash"] != cu, "token cũ phải chết"
    assert r["tenant_id"] is None, "signup-shaped: membership đã có, không phải một lời mời workspace mới"
    assert r["role_id"] is None

    # Ruling 2026-08-22: thư ở ĐÂY phải là thư ĐĂNG KÝ, không phải một trong hai
    # thư MỜI — người này đã ở trong workspace, "bạn được mời tham gia" là sai.
    thu_gui = THU_DA_GUI[-1]
    assert thu_gui["tieu_de"] == "Đặt mật khẩu để hoàn tất đăng ký NobleX Agent Portal"
    assert "được mời tham gia workspace" not in thu_gui["than_text"]


async def test_patch_doi_vai_tro_khong_dung_toi_workspace_khac(
    pool, client_cf, workspace_cfg, role_id_bien_tap, role_id_nguoi_xem
):
    """TỰ KIỂM BẮT BUỘC của task-6-brief.md: PATCH chỉ chạm MỘT workspace.

    Người này có membership ở HAI workspace (`workspace_cfg` + `t_khac_patch`).
    PATCH role ở `workspace_cfg` không được đụng tới hàng ở `t_khac_patch`.

    Đây chính là bài test tái tạo được bug mất dữ liệu 2026-08-06: nếu
    `thanh_vien.doi_vai_tro` bị thay ruột bằng `repo.dat_lai_membership` (hàm đó
    DELETE/INSERT lại TOÀN BỘ hàng của user, không có vị từ `tenant_id`), bài này
    phải ĐỎ — xem báo cáo `task-5-6-report.md` mục tự kiểm.
    """
    # Seed trực tiếp qua SQL: `POST /members` không còn tạo user/membership nào
    # từ 2026-08-22, nên không còn cách nào lấy `userId` thật từ response của nó.
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_haiws', 'hai_ws@x.vn', 'Hai Ws', 'active', 'x')"
        )
        await repo.them_membership(conn, user_id="u_haiws", tenant_id=workspace_cfg, role_id=role_id_bien_tap)
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('t_khac_patch', 'Khác Patch', 'u_dang')"
        )
        await repo.them_membership(conn, user_id="u_haiws", tenant_id="t_khac_patch", role_id=role_id_bien_tap)

    try:
        r2 = await client_cf.patch("/api/v1/members/u_haiws", json={"roleId": role_id_nguoi_xem})
        assert r2.status_code == 200, r2.text
        assert r2.json()["roleId"] == role_id_nguoi_xem

        con = await pool.fetchval(
            "SELECT role_id FROM control.memberships WHERE user_id='u_haiws' AND tenant_id='t_khac_patch'"
        )
        assert con == role_id_bien_tap, "workspace khác bị đụng — dấu hiệu ai đó dùng dat_lai_membership"
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM control.tenants WHERE id = 't_khac_patch'")


async def test_get_members_tra_lifecycle_dung_gia_tri(
    client_cf: httpx.AsyncClient, pool: asyncpg.Pool, workspace_cfg: str, role_id_bien_tap: str
) -> None:
    """BUG 2026-08-09→17: `GET /members` không trả `lifecycle`, FE khai nó BẮT BUỘC.

    `taiThanhVien()` phía FE là `goi<MemberOut[]>()` trần — không chuẩn hoá, không
    giá trị mặc định — nên `undefined` chạy thẳng vào UI. Ba chỗ vỡ, không chỗ nào
    ném lỗi: cột «Trạng thái» hiện pill trống, bộ lọc theo trạng thái trả bảng
    RỖNG, và mục «Gửi lại lời mời» (điều kiện `lifecycle === 'pending'`) KHÔNG BAO
    GIỜ hiện — tức không mời lại được ai.

    Bài này khẳng định GIÁ TRỊ, không chỉ sự có mặt của khoá: một `lifecycle` luôn
    trả `'active'` cứng cũng làm mục «Gửi lại lời mời» tắt vĩnh viễn, và một bài
    chỉ kiểm `'lifecycle' in hang` sẽ xanh với bug đó.

    Seed trực tiếp một THÀNH VIÊN `pending` — `POST /members` không còn tạo ra
    hình dạng đó từ 2026-08-22 (mời không còn ghi user/membership nào), nhưng
    hàng này vẫn tồn tại được qua `cli/seed_owner.py` / `/users` admin, và
    `GET /members` vẫn phải đọc đúng `lifecycle` của nó nếu nó có mặt.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle) "
            "VALUES ('u_lifecycle', 'lifecycle@x.vn', 'Lifecycle', 'pending')"
        )
        await repo.them_membership(conn, user_id="u_lifecycle", tenant_id=workspace_cfg, role_id=role_id_bien_tap)

    hang = next(m for m in (await client_cf.get("/api/v1/members")).json() if m["userId"] == "u_lifecycle")
    assert hang["lifecycle"] == "pending", "người còn pending phải giữ đúng giá trị"

    # Đặt mật khẩu ⇒ `active`. Đọc lại phải thấy đổi — chứng minh giá trị đến từ DB
    # chứ không phải một hằng.
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE control.users SET lifecycle = 'active', password_hash = '$argon2id$x' WHERE id = 'u_lifecycle'"
        )
    hang = next(m for m in (await client_cf.get("/api/v1/members")).json() if m["userId"] == "u_lifecycle")
    assert hang["lifecycle"] == "active"

    # Và PATCH cũng phải trả `lifecycle` — FE thay hàng trong bảng bằng response đó.
    r = await client_cf.patch("/api/v1/members/u_lifecycle", json={"roleId": role_id_bien_tap})
    assert r.status_code == 200, r.text
    assert r.json()["lifecycle"] == "active", "response PATCH thiếu trường ⇒ đúng hàng vừa sửa mất cột"
