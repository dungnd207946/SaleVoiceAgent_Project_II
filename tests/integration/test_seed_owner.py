"""`chay()` của vai `seed-owner` — chạm DB thật.

MỌI TEST Ở ĐÂY CHẠY TRONG MỘT GIAO DỊCH RỒI ROLLBACK. Không phải để tiện dọn: DB
test là scope session và dùng chung với mọi module khác, mà phép chặn của
`chay()` đếm user `lifecycle='active'` TOÀN CỤC. Chạy thật rồi dọn sau là để lại
một khoảng thời gian mà một test song song thấy DB ở trạng thái khác — và thứ tự
test thì không ai bảo đảm. Rollback là cách duy nhất phép đếm toàn cục đó test
được mà không dính vào ai.

Cùng lý do, mỗi test tự đưa DB về "chưa ai vào được" bằng `_khong_con_ai_active()`
thay vì giả định nó đã vậy: module khác (tests/modules/workspace/conftest.py) seed
user `active` và không có gì nói ai chạy trước.
"""

import asyncpg
import pytest

from portal.cli.seed_owner import CauHinh, LoiBootstrap, chay
from portal.modules.auth.quan_tri_user import bam_token

pytestmark = pytest.mark.integration

CH = CauHinh(
    email="so_owner@seedtest.vn",
    ten_nguoi="Sờ Owner",
    ten_workspace="WS Đầu",
    goc_url="",
)


async def _khong_con_ai_active(conn: asyncpg.Connection) -> None:
    """Đưa mọi user về `pending`. Hai cột cùng lúc — CHECK của 0103 buộc vậy."""
    await conn.execute(
        "UPDATE control.users SET lifecycle = 'pending', password_hash = NULL WHERE lifecycle = 'active'"
    )


async def test_tao_du_bon_thu_va_token_mo_duoc(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _khong_con_ai_active(conn)
            token = await chay(conn, CH)
            assert token

            # ① tổ chức, ② owner `pending` (mật khẩu NULL — không ai biết nó)
            u = await conn.fetchrow(
                "SELECT id, lifecycle, password_hash FROM control.users WHERE email = $1",
                CH.email,
            )
            assert u["lifecycle"] == "pending"
            assert u["password_hash"] is None

            # Migration 0104 (+0105 dedup) phải đã seed 4 vai trò TOÀN CỤC —
            # không có nó thì owner đăng nhập vào và dropdown vai trò rỗng.
            assert await conn.fetchval("SELECT count(*) FROM control.roles") == 4

            # ③ workspace — thiếu nó thì `dang_nhap()` raise khong_co_workspace()
            # và owner không vào được để tự tạo.
            ws = await conn.fetchrow("SELECT id, name FROM control.tenants")
            assert ws["name"] == CH.ten_workspace
            # `ws_service.tao` còn ghi vertical; một tenant thiếu hàng đó là một
            # workspace không ai biết thuộc lĩnh vực gì.
            assert await conn.fetchval("SELECT count(*) FROM control.tenant_verticals WHERE tenant_id = $1", ws["id"])

            # ④ CHỈ hash vào DB. Token thô là thứ duy nhất mở được link, và nó chỉ
            # tồn tại ở stdout của lệnh deploy.
            inv = await conn.fetchrow(
                "SELECT token_hash, user_id, used_at FROM control.invites WHERE user_id = $1", u["id"]
            )
            assert inv["token_hash"] == bam_token(token)
            assert token not in inv["token_hash"]
            assert inv["used_at"] is None
        finally:
            await tr.rollback()


async def test_co_user_active_thi_tu_choi(pool: asyncpg.Pool):
    """Cửa chính. Có ai đăng nhập được nghĩa là `POST /users` là công cụ đúng."""
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _khong_con_ai_active(conn)
            await chay(conn, CH)
            # Owner vừa nhận lời mời — giờ hệ đã có đường vào.
            await conn.execute(
                "UPDATE control.users SET lifecycle = 'active', password_hash = 'x' WHERE email = $1",
                CH.email,
            )
            with pytest.raises(LoiBootstrap, match="TỪ CHỐI"):
                await chay(conn, CH)
        finally:
            await tr.rollback()


async def test_chay_lai_khi_con_pending_thi_moi_lai_va_giet_token_cu(pool: asyncpg.Pool):
    """Lần chạy trước mất token (log bị cuộn, mạng đứt) — mời lại là việc đúng.

    Và token CŨ phải chết: `ghi_loi_moi` UPSERT theo `user_id`, nên hai link song
    song mở được cùng một tài khoản là điều không xảy ra.
    """
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _khong_con_ai_active(conn)
            cu = await chay(conn, CH)
            moi = await chay(conn, CH)
            assert moi != cu

            uid = await conn.fetchval("SELECT id FROM control.users WHERE email = $1", CH.email)
            hashes = await conn.fetch("SELECT token_hash FROM control.invites WHERE user_id = $1", uid)
            assert [h["token_hash"] for h in hashes] == [bam_token(moi)]
        finally:
            await tr.rollback()


async def test_chay_lai_khong_sinh_them_workspace(pool: asyncpg.Pool):
    """Lần chạy thứ hai, CÙNG email — canh bất biến ② ("không sinh thêm workspace")."""
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _khong_con_ai_active(conn)
            await chay(conn, CH)
            await chay(conn, CH)
            assert await conn.fetchval("SELECT count(*) FROM control.tenants") == 1
        finally:
            await tr.rollback()


CH_B = CauHinh(
    email="so_owner_b@seedtest.vn",
    ten_nguoi="Sờ Owner B",
    ten_workspace="WS Đầu",  # không dùng — nhánh `else` không tạo workspace mới
    goc_url="",
)


async def test_chay_voi_email_khac_khi_da_co_workspace_gan_dung_tenant(pool: asyncpg.Pool):
    """Nhánh `else` (workspace đã có, KHÔNG tạo mới) cho một `user_id` CHƯA TỪNG
    có membership nào — không phải cùng user với lần tạo.

    Đây là kịch bản mà bug thật sự lộ ra (fix round 1, trước 0952): lần 1 tạo
    user A + workspace, `ws_service.tao()` ghi membership cho CHÍNH A. Nếu lần 2
    gọi lại CÙNG email (như `test_chay_lai_khong_sinh_them_workspace` ở trên),
    nhánh `else` tra `tenant_id` qua `memberships` của A vẫn ra đúng kết quả DÙ
    code có bug — vì A đã có sẵn membership từ lần 1. Bug chỉ lộ khi người thứ
    hai (B), không membership nào, đi qua đúng nhánh đó — nên test dùng hai
    `CauHinh` khác email để dựng đúng tình huống đó.

    ⚠️ KHẲNG ĐỊNH ĐÃ ĐẢO CHIỀU SAU 0952 (`invites_khong_can_user`), VÀ ĐẢO CHIỀU
    ĐÚNG — ĐỪNG "KHÔI PHỤC" `tenant_id == ws_id`. Bài gốc (fix round 1) khẳng
    định `invites.tenant_id` của B là workspace thật, không phải NULL — đúng ở
    THỜI ĐIỂM ĐÓ vì `ghi_loi_moi` cũ không phân biệt hình dạng. 0952 định nghĩa
    lại ba hình dạng hợp lệ DUY NHẤT của một hàng `control.invites`: `signup`
    (có `user_id`, KHÔNG `tenant_id`/`role_id`) · `invite_new` (không `user_id`,
    có `tenant_id`+`role_id`) · `invite_existing` (cả ba). Một token mang
    `tenant_id` SET + `user_id` SET rơi vào `invite_existing`, và
    `doc_loi_moi_con_hieu_luc` CHỈ nhận nhánh đó khi `u.lifecycle = 'active'`.

    B ở đây LUÔN `pending`: vòng chặn đầu của `chay()` (`_khong_con_ai_active` +
    kiểm `active` toàn cục) chỉ cho lệnh chạy khi CHƯA có ai `active`, nên A và
    B không thể vừa "qua được vòng chặn" vừa "đã active" cùng lúc — B luôn tới
    bước ④ ở trạng thái `pending`. Viết `tenant_id=ws_id` cho một B `pending` do
    đó sinh ra một token CHẾT NGAY LÚC SINH (rơi vào `invite_existing`, đòi
    `active` mà không có) — tệ hơn hẳn lựa chọn `seed_owner.py` đang dùng.
    `ghi_loi_moi_dang_ky` (nhánh `signup`, `tenant_id` NULL) là lựa chọn SCHEMA-
    KHẢ-THI DUY NHẤT còn lại cho ca B `pending` này — token của B mở được đúng
    nhờ khớp vị từ `(tenant_id IS NULL AND lifecycle = 'pending')`.

    ⚠️ LỖ HỔNG THẬT, CHƯA SỬA, GHI LẠI ĐỂ KHÔNG THẤT LẠC (không thuộc phạm vi
    task vá `repo.py` — xem report Task 4, mục Concerns): nhánh `else` này CHƯA
    BAO GIỜ cấp cho B một hàng `control.memberships`, trước hay sau 0952 đều
    vậy — chỉ A (người đi qua nhánh `if`, tạo workspace) được `ws_service.tao()`
    gắn membership 'Quản trị'. Nghĩa là B đặt mật khẩu xong qua token này sẽ
    `active` với ĐÚNG ZERO quyền vào bất kỳ workspace nào. Đây là hành vi CÓ
    THẬT của `chay()`, không phải giả định, và một task khác cần quyết định có
    sửa hay không (gắn membership cho B, hay đổi hẳn ngữ nghĩa nhánh `else`).
    """
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await _khong_con_ai_active(conn)
            await chay(conn, CH)  # A: tạo user + workspace + membership của A
            await chay(conn, CH_B)  # B: user mới, KHÔNG membership nào, đi nhánh `else`

            assert await conn.fetchval("SELECT count(*) FROM control.tenants") == 1

            uid_b = await conn.fetchval("SELECT id FROM control.users WHERE email = $1", CH_B.email)
            assert await conn.fetchval("SELECT count(*) FROM control.memberships WHERE user_id = $1", uid_b) == 0

            # `tenant_id IS NULL` + `role_id IS NULL`: token của B là
            # `ghi_loi_moi_dang_ky` (nhánh `signup`) — xem docstring trên vì sao
            # đây là hình dạng DUY NHẤT còn mở được cho một B `pending`.
            hang = await conn.fetchrow("SELECT tenant_id, role_id FROM control.invites WHERE user_id = $1", uid_b)
            assert hang["tenant_id"] is None
            assert hang["role_id"] is None
        finally:
            await tr.rollback()


# `test_email_da_o_to_chuc_khac_thi_chan` XOÁ 2026-08-15: nó neo phép kiểm
# "email đã tồn tại ở tổ chức khác thì từ chối", mà `SEED_ORG_ID` và cả tầng tổ
# chức đã bỏ. Email vẫn UNIQUE TOÀN CỤC (migration 0100) nên trường hợp thật sự
# còn lại — "email đã có, user chưa active" — do `test_chay_lai_khi_con_pending...`
# canh.
