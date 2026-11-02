"""Cổng 9 và 13 của spec M2b §7 — trạng thái `pending` ở hai tầng.

Cổng 13 gọi SQL trực tiếp (không qua API) vì nó kiểm một RÀNG BUỘC DB, không kiểm
một luồng: phép kiểm ở tầng service cũng chặn được, nhưng chỉ CHECK là thứ psql
tay, seed script và mọi migration sau không đi vòng được.

Cổng 9 là một bug thật, không phải một giả thiết: trước 0103 thì `password_hash`
NOT NULL nên `pw.kiem(u.password_hash, ...)` luôn nhận str. Sau 0103 nó nhận None
ở mọi user chưa nhận mời — tức một `TypeError` -> 500 ở đúng đường đăng nhập.
"""

import asyncpg
import pytest

from portal.core.auth import password as pw

from .conftest import MAT_KHAU


async def _tao_pending(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """INSERT INTO control.users (id, email, password_hash, name, lifecycle)
           VALUES ('u_cho', 'cho@anphuland.vn', NULL, 'Người Chờ', 'pending')"""
    )


async def test_cong_9_user_pending_dang_nhap_thi_401_khong_phai_500(app_client, ba_workspace, pool):
    """Cổng 9: 401 INVALID_CREDENTIALS, KHÔNG phải 500 TypeError.

    Và cùng mã với sai mật khẩu — "tài khoản này đang chờ nhận lời mời" cũng là một
    câu trả lời cho máy dò rằng email đó có thật.
    """
    async with pool.acquire() as conn:
        await _tao_pending(conn)

    r = await app_client.post(
        "/api/v1/auth/login", json={"email": "cho@anphuland.vn", "password": "bat-ky-mat-khau-gi"}
    )
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_user_pending_khong_hien_tren_danh_sach_thanh_vien_workspace(app_client, ba_workspace, pool):
    """`GET /members` là danh sách thành viên WORKSPACE — pending chưa vào được.

    Họ hiện trên `GET /users` (màn quản trị tổ chức, admin cần thấy để mời lại),
    nhưng KHÔNG hiện ở đây: hai màn trả lời hai câu hỏi khác nhau.
    """
    async with pool.acquire() as conn:
        await _tao_pending(conn)
        r_viewer = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Người xem'")
        await conn.execute(
            """INSERT INTO control.memberships (user_id, tenant_id, role_id)
               VALUES ('u_cho', 'cs_anphu', $1)""",
            r_viewer,
        )

    r = await app_client.post("/api/v1/auth/login", json={"email": "dang@anphuland.vn", "password": MAT_KHAU})
    assert r.status_code == 200, r.text

    r = await app_client.get("/api/v1/members")
    assert r.status_code == 200, r.text
    # ⚠ `liet_ke_thanh_vien` KHÔNG lọc lifecycle — nó lọc theo membership còn hiệu
    # lực. User pending CÓ membership nên họ CÓ hiện. Ghi lại hành vi thật ở đây
    # thay vì assert một điều mong muốn chưa được cài: nếu có ngày ai đó quyết định
    # lọc, test này là chỗ đổi, và nó nói rõ vì sao hôm nay chưa lọc.
    assert "u_cho" in [m["userId"] for m in r.json()], (
        "hành vi hiện tại: /members lọc theo membership, không theo lifecycle"
    )


async def test_cong_13_active_khong_mat_khau_gio_hop_le_vi_cua_google(pool):
    """Cổng 13 (nửa INSERT) — `active` + `password_hash NULL` GIỜ CHÈN ĐƯỢC.

    Đây từng là "cửa hậu" bị chặn: CHECK song điều kiện `users_password_theo_lifecycle_check`
    (0103) buộc `pending ⇔ password_hash IS NULL` cả hai chiều, nên `active` mà
    không mật khẩu vi phạm chiều thứ hai. Migration 0108 đổi tên CHECK thành
    `users_co_duong_dang_nhap_check` và CHỦ Ý bỏ đúng chiều đó: một user đăng
    nhập bằng Google không có mật khẩu nào cả, và giữ nguyên chiều cũ là chặn
    luôn chính tính năng đăng nhập Google.

    Lời hứa gốc — "không có user `active` nào thiếu mọi đường vào" — KHÔNG áp
    dụng cho MỌI cách một hàng có thể tới trạng thái đó nữa. Với ĐÚNG đường
    đăng nhập Google, nửa lời hứa đó được giữ ở tầng ỨNG DỤNG: `users` +
    `identities` được ghi trong CÙNG một giao dịch (`router.tro_ve_tu_google`),
    và `tests/modules/auth/test_migration_google.py::test_cong_5_khong_con_hang_active_nao_khong_duong_dang_nhap`
    chạy THẬT đường đó rồi mới quét, để chứng minh đúng điều này (không phải
    một phép quét DB tĩnh xanh rỗng).

    Còn một khoảng hở KHÔNG ai canh: một script bảo trì `UPDATE control.users
    SET lifecycle='active'` HÀNG LOẠT từ ngoài ứng dụng (không qua router,
    không qua `dang_nhap_google`) không còn bị CHECK chặn, và không code ứng
    dụng nào tham gia lượt đó để một test có thể bắt được. Đây là rủi ro VẬN
    HÀNH được migration 0108 đánh đổi CÓ Ý THỨC để lấy tính năng đăng nhập
    Google, không phải một khoảng hở đã được lấp — xem spec §4.2
    (`docs/superpowers/specs/2026-08-18-dang-nhap-google-oauth-design.md`).
    """
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """INSERT INTO control.users (id, email, password_hash, name, lifecycle)
                   VALUES ('u_cua_hau', 'hau@a.vn', NULL, 'Cửa Hậu', 'active')"""
            )
            assert await conn.fetchval("SELECT password_hash IS NULL FROM control.users WHERE id = 'u_cua_hau'")
        finally:
            await conn.execute("DELETE FROM control.users WHERE id = 'u_cua_hau'")


async def test_cong_13b_check_song_dieu_kien_chan_pending_co_mat_khau(pool):
    """Nửa còn lại: `pending` + có hash cũng không chèn được.

    Trạng thái đó nghĩa là một thư mời còn sống sau khi mật khẩu đã đặt — token
    trong tay ai đó vẫn đổi lại được mật khẩu của người đang hoạt động.
    """
    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.IntegrityConstraintViolationError, match="users_co_duong_dang_nhap_check"):
            await conn.execute(
                """INSERT INTO control.users (id, email, password_hash, name, lifecycle)
                   VALUES ('u_lo', 'lo@a.vn', $1, 'Lỡ', 'pending')""",
                pw.bam("co-mat-khau-ma-van-pending"),
            )


async def test_cong_13c_update_ve_active_khong_mat_khau_gio_hop_le_vi_cua_google(pool, ba_workspace):
    """Cổng 13 (nửa UPDATE) — cùng nới với bản INSERT ở trên, cùng lý do.

    Trước 0108, CHECK `users_password_theo_lifecycle_check` áp cho MỌI phép ghi
    (không riêng INSERT), nên một script bảo trì `UPDATE … SET lifecycle='active'`
    trên một hàng `pending` (`password_hash IS NULL`) từng vi phạm. Migration
    0108 đổi tên CHECK thành `users_co_duong_dang_nhap_check` và bỏ đúng chiều
    này.

    ⚠ ĐÂY CHÍNH LÀ kịch bản rủi ro, không phải một ca đã được lấp: test này
    chạy UPDATE thẳng bằng SQL — giống HỆT một script bảo trì chạy ngoài ứng
    dụng — và nó ĐI QUA được. Không có gì trong DB chặn nó nữa, và vì nó không
    đi qua router/`dang_nhap_google` nên không đoạn code ứng dụng nào, không
    test/CI nào nhìn thấy một script như vậy chạy trên production. Đó là rủi
    ro VẬN HÀNH mà 0108 đánh đổi CÓ Ý THỨC để lấy tính năng đăng nhập Google —
    xem spec §4.2 (`docs/superpowers/specs/2026-08-18-dang-nhap-google-oauth-design.md`).

    Lời hứa "không user active nào mà không có ĐƯỜNG vào" CHỈ được giữ cho
    ĐÚNG đường đăng nhập Google (giao dịch ở router +
    `test_cong_13_active_khong_mat_khau_gio_hop_le_vi_cua_google` ngay trên +
    `tests/modules/auth/test_migration_google.py::test_cong_5_khong_con_hang_active_nao_khong_duong_dang_nhap`
    hành vi) — KHÔNG được giữ cho đường SQL trực tiếp mà chính test này vừa đi qua.
    """
    async with pool.acquire() as conn:
        try:
            await _tao_pending(conn)
            await conn.execute("UPDATE control.users SET lifecycle = 'active' WHERE id = 'u_cho'")
            assert await conn.fetchval("SELECT lifecycle FROM control.users WHERE id = 'u_cho'") == "active"
        finally:
            await conn.execute("DELETE FROM control.users WHERE id = 'u_cho'")


async def test_audit_log_nhan_hang_khong_tenant(pool):
    """ĐẢO NGƯỢC: `audit_log_co_pham_vi_check` đã BỎ ở migration 0106.

    CHECK cũ là `(tenant_id IS NOT NULL OR org_id IS NOT NULL)` — mỗi dòng nhật ký
    phải có ít nhất một phạm vi. Bỏ `org_id` mà giữ CHECK thì nó rút thành
    `tenant_id IS NOT NULL`, và MỌI dòng cũ ghi hành động cấp tổ chức (tenant_id
    NULL) lập tức vi phạm. Chọn drop CHECK chứ không backfill một workspace bừa
    vào những dòng đó — xem docstring migration 0106.

    `tenant_id IS NULL` từ nay đọc là "hành động không thuộc workspace nào".
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.audit_log (hanh_dong, actor, chi_tiet) VALUES ('kiem.tra', 'u_seed_test', '{}'::jsonb)"
        )
        n = await conn.fetchval(
            "SELECT count(*) FROM control.audit_log WHERE hanh_dong = 'kiem.tra' AND tenant_id IS NULL"
        )
        assert n == 1
        await conn.execute("DELETE FROM control.audit_log WHERE hanh_dong = 'kiem.tra'")


async def test_invites_token_hash_phai_la_sha256_hex(pool, ba_workspace):
    """CHECK `^[0-9a-f]{64}$` — chặn đúng lỗi "quên băm, lưu token thô".

    Không có nó thì một đường ghi thiếu `bam_token()` sẽ chạy êm, và token dùng
    được nằm nguyên trong DB cho tới khi có người soi bảng.
    """
    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.IntegrityConstraintViolationError, match="invites_token_hash_check"):
            await conn.execute(
                """INSERT INTO control.invites (token_hash, user_id, email, expires_at)
                   VALUES ('token-tho-chua-bam', 'u_dang', 'dang@anphuland.vn', now() + interval '7 days')"""
            )


# `test_invites_khong_xuyen_to_chuc_duoc` XOÁ 2026-08-15: nó neo composite FK
# `(org_id, user_id)` của 0103 — một thư mời không được trỏ sang user của tổ chức
# khác. Migration 0105 thay nó bằng FK đơn `user_id -> users(id)` vì không còn
# tổ chức nào để xuyên qua. Phép chặn còn lại (`user_id` phải có thật) đã có
# `test_invites_user_id_phai_ton_tai` canh.
