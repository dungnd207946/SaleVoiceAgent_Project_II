"""Tầng repo của cửa Google. Không HTTP, không router — chỉ SQL."""

import pytest

from portal.modules.auth import repo


@pytest.fixture
async def don_sach(pool):
    yield
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM control.users WHERE id LIKE 'u_ri_%'")


async def test_tim_identity_khong_co_tra_none(pool, don_sach):
    async with pool.acquire() as conn:
        assert await repo.tim_identity(conn, provider="google", subject="khong-ton-tai") is None


async def test_tao_user_tu_google_ra_active_khong_mat_khau(pool, don_sach):
    async with pool.acquire() as conn:
        u = await repo.tao_user_tu_google(conn, user_id="u_ri_a", email="a@thu.vn", name="Nguyễn A")
        assert u.id == "u_ri_a"
        assert u.email == "a@thu.vn"
        assert u.lifecycle == "active"
        # `active` NGAY, khác `tao_user_tu_dang_ky` (ra `pending` rồi chờ bấm link).
        # Cái link đặt mật khẩu tồn tại để chứng minh hộp thư có thật. Google vừa
        # chứng minh xong điều đó (`email_verified`), nên bắt đi lại một vòng nữa là
        # thu phí một lời hứa đã được trả.
        assert u.password_hash is None


async def test_ghi_roi_tim_lai_duoc(pool, don_sach):
    async with pool.acquire() as conn:
        await repo.tao_user_tu_google(conn, user_id="u_ri_b", email="b@thu.vn", name="B")
        await repo.ghi_identity(
            conn,
            provider="google",
            subject="s-b",
            user_id="u_ri_b",
            email_tai_provider="b@thu.vn",
        )
        hang = await repo.tim_identity(conn, provider="google", subject="s-b")
        assert hang is not None
        assert hang.user_id == "u_ri_b"
        assert hang.email_tai_provider == "b@thu.vn"


async def test_cham_dang_nhap_cap_nhat_email_hien_thi(pool, don_sach):
    """Người đổi email tài khoản Google: `sub` không đổi nên vẫn là nhánh 1, và
    cột email hiển thị phải theo kịp — nếu không, audit đọc ra một email đã chết."""
    async with pool.acquire() as conn:
        await repo.tao_user_tu_google(conn, user_id="u_ri_c", email="c@thu.vn", name="C")
        await repo.ghi_identity(
            conn,
            provider="google",
            subject="s-c",
            user_id="u_ri_c",
            email_tai_provider="cu@thu.vn",
        )
        await repo.cham_dang_nhap_identity(
            conn,
            provider="google",
            subject="s-c",
            email_tai_provider="moi@thu.vn",
        )
        hang = await repo.tim_identity(conn, provider="google", subject="s-c")
        assert hang is not None
        assert hang.email_tai_provider == "moi@thu.vn"
        assert await conn.fetchval("SELECT last_login_at IS NOT NULL FROM control.identities WHERE subject = 's-c'")


async def test_kich_hoat_pending_va_xoa_loi_moi(pool, don_sach):
    """Nhánh a của spec §7: người được mời vào bằng Google. Thư mời đang sống
    phải chết — một link đặt mật khẩu còn hiệu lực sau khi người ta đã vào được
    là một cửa thừa không ai theo dõi."""
    async with pool.acquire() as conn:
        # Tạo user pending với thư mời sử dụng SQL thô (không dùng repo function)
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
            "VALUES ($1, $2, NULL, $3, 'pending')",
            "u_ri_d",
            "d@thu.vn",
            "D",
        )
        # Tạo thư mời
        await conn.execute(
            "INSERT INTO control.invites "
            "(token_hash, user_id, email, tenant_id, expires_at, created_by) "
            "VALUES ($1, $2, $3, NULL, now() + interval '7 days', $2)",
            "d" * 64,
            "u_ri_d",
            "d@thu.vn",
        )

        # Kiểm tra thư mời tồn tại TRƯỚC khi gọi hàm
        assert await conn.fetchval("SELECT count(*) FROM control.invites WHERE user_id = 'u_ri_d'") == 1

        # Kích hoạt user
        await repo.kich_hoat_user_pending(conn, user_id="u_ri_d")

        # Xoá thư mời
        await repo.xoa_loi_moi_cua_user(conn, user_id="u_ri_d")

        assert await conn.fetchval("SELECT lifecycle FROM control.users WHERE id = 'u_ri_d'") == "active"
        assert await conn.fetchval("SELECT count(*) FROM control.invites WHERE user_id = 'u_ri_d'") == 0
