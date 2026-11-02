"""Migration 0108 — bảng identities và bất biến mật khẩu đã nới.

Sáu cổng ở đây neo những thứ CHỈ DB giữ được (cộng cổng 7, xem dưới). Cổng 5 là
ngoại lệ: nó neo một lời hứa mà CHECK không giữ nổi (phải nhìn sang bảng
khác), nên test này là chỗ DUY NHẤT giữ nó — xem spec §4.2.
"""

import asyncpg
import pytest

from portal.core.auth.oauth_google import ClaimsGoogle
from portal.modules.auth import dang_nhap_google


class _Rollback(Exception):
    """Ném để `conn.transaction()` cuộn lại — test này chỉ cần biết INSERT đi qua
    được CHECK, không cần để lại hàng nào."""


async def _tao_user_google(conn, user_id: str, email: str) -> None:
    """User của nhánh 3: active, KHÔNG mật khẩu."""
    await conn.execute(
        "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
        "VALUES ($1, $2, NULL, 'Người Thử', 'active')",
        user_id,
        email,
    )


async def test_cong_1_user_active_khong_mat_khau_insert_duoc(pool):
    """Chính ca mà CHECK song điều kiện của 0103 chặn. Không nới thì test này đỏ."""
    with pytest.raises(_Rollback):
        async with pool.acquire() as conn, conn.transaction():
            await _tao_user_google(conn, "u_g_cong1", "cong1@thu.vn")
            assert await conn.fetchval("SELECT password_hash IS NULL FROM control.users WHERE id = 'u_g_cong1'")
            raise _Rollback


async def test_cong_2_pending_van_khong_duoc_co_mat_khau(pool):
    """Lời hứa ① của 0103 phải còn nguyên sau khi nới."""
    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
                "VALUES ('u_g_cong2', 'cong2@thu.vn', 'hash-gia', 'X', 'pending')"
            )


async def test_cong_3_hai_user_khong_the_chiem_cung_mot_tai_khoan_google(pool):
    """PRIMARY KEY (provider, subject) — đây LÀ danh tính của hàng, không phải
    một UNIQUE thêm cho vui."""
    async with pool.acquire() as conn:
        try:
            await _tao_user_google(conn, "u_g_a", "a@thu.vn")
            await _tao_user_google(conn, "u_g_b", "b@thu.vn")
            await conn.execute(
                "INSERT INTO control.identities (provider, subject, user_id, email_tai_provider) "
                "VALUES ('google', '104287', 'u_g_a', 'a@thu.vn')"
            )
            with pytest.raises(asyncpg.exceptions.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO control.identities (provider, subject, user_id, email_tai_provider) "
                    "VALUES ('google', '104287', 'u_g_b', 'b@thu.vn')"
                )
        finally:
            await conn.execute("DELETE FROM control.users WHERE id IN ('u_g_a', 'u_g_b')")


async def test_cong_4_mot_user_khong_gan_duoc_hai_tai_khoan_google(pool):
    async with pool.acquire() as conn:
        try:
            await _tao_user_google(conn, "u_g_c", "c@thu.vn")
            await conn.execute(
                "INSERT INTO control.identities (provider, subject, user_id, email_tai_provider) "
                "VALUES ('google', '111', 'u_g_c', 'c@thu.vn')"
            )
            with pytest.raises(asyncpg.exceptions.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO control.identities (provider, subject, user_id, email_tai_provider) "
                    "VALUES ('google', '222', 'u_g_c', 'c@thu.vn')"
                )
        finally:
            await conn.execute("DELETE FROM control.users WHERE id = 'u_g_c'")


async def test_cong_5_khong_con_hang_active_nao_khong_duong_dang_nhap(pool, redis_client):
    """Lời hứa ② mà CHECK không giữ nổi (nó phải nhìn sang bảng khác — spec §4.2).

    RUỘT của test là chạy THẬT nhánh 3 của `dang_nhap_google.dang_nhap` (người
    hoàn toàn mới, tự đăng ký qua Google) — đúng đường mà migration 0108 mở ra
    — rồi MỚI quét. Trước bản sửa này, test chỉ quét một DB tĩnh: xanh MỘT
    CÁCH RỖNG trên DB sạch (không chạy qua đường code nào) và chỉ đỏ nếu một
    test KHÁC lỡ để sót rác — mà nay mọi test đều tự dọn, nên phép quét gần như
    không còn cơ hội đỏ. Chạy hành vi thật ở đây chứng minh điều CÓ THẬT: hai
    INSERT (`users` + `identities`) nằm trong CÙNG một giao dịch (ở
    `router.tro_ve_tu_google`, mô phỏng lại đúng thứ tự ở đây), nên đăng nhập
    Google không bao giờ để lại một user `active` không mật khẩu mà thiếu
    identity — dù nửa sau có nổ, giao dịch cuộn lại cả hai.

    Quét toàn bảng ở cuối vẫn giữ làm LƯỚI AN TOÀN (bắt được rác từ NGUỒN KHÁC,
    không riêng đường này) — nhưng nó không còn là ruột của test.

    ⚠ KHÔNG CANH: một script bảo trì chạy `UPDATE control.users SET
    lifecycle='active'` HÀNG LOẠT từ ngoài ứng dụng. CHECK đã nới (0108) không
    chặn câu đó, không code ứng dụng nào tham gia để test này (hay bất kỳ CI
    nào) nhìn thấy — đây là một rủi ro VẬN HÀNH có thật mà 0108 đánh đổi có ý
    thức để lấy tính năng đăng nhập Google, không phải một khoảng hở đã được
    test này lấp. Xem spec §4.2.
    """
    claims = ClaimsGoogle(sub="cong5-sub", email="cong5@thu.vn", email_verified=True, name="Cổng Năm")
    try:
        async with pool.acquire() as conn, conn.transaction():
            await dang_nhap_google.dang_nhap(conn, redis_client, claims=claims, cho_dang_ky_moi=True)

        async with pool.acquire() as conn:
            rac = await conn.fetch(
                "SELECT u.id FROM control.users u "
                "LEFT JOIN control.identities i ON i.user_id = u.id "
                "WHERE u.lifecycle = 'active' AND u.password_hash IS NULL AND i.user_id IS NULL"
            )
        assert rac == [], f"user `active` không mật khẩu và không identity — không đường nào vào: {rac}"
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM control.users WHERE email = 'cong5@thu.vn'")


async def test_cong_6_xoa_user_thi_identity_di_theo(pool):
    async with pool.acquire() as conn:
        await _tao_user_google(conn, "u_g_d", "d@thu.vn")
        await conn.execute(
            "INSERT INTO control.identities (provider, subject, user_id, email_tai_provider) "
            "VALUES ('google', '333', 'u_g_d', 'd@thu.vn')"
        )
        await conn.execute("DELETE FROM control.users WHERE id = 'u_g_d'")
        assert await conn.fetchval("SELECT count(*) FROM control.identities WHERE subject = '333'") == 0


async def test_cong_7_user_google_bi_dinh_chi_van_la_trang_thai_hop_le(pool):
    """`suspended` + không mật khẩu = user Google-only bị admin đình chỉ.

    Ràng buộc mới CỐ Ý cho phép trạng thái này. Chặn nó là chặn luôn việc đình
    chỉ người đăng nhập bằng Google — tức vô hiệu hoá cổng bảo mật của spec §7b.
    Test này cũng là lý do `downgrade()` lọc `lifecycle <> 'pending'`.
    """
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
                "VALUES ('u_g_dc', 'dc@thu.vn', NULL, 'Đình Chỉ', 'suspended')"
            )
            assert await conn.fetchval("SELECT lifecycle FROM control.users WHERE id = 'u_g_dc'") == "suspended"
        finally:
            await conn.execute("DELETE FROM control.users WHERE id = 'u_g_dc'")
