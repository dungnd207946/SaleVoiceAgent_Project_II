"""Ba nhánh khớp danh tính + ba ca biên (spec §7).

Gọi THẲNG service với claims dựng tay — không dựng OAuth giả, không đi qua HTTP.
Đó là lý do `oauth_google.py` và file này là hai module: hai bộ test không phải
kéo nhau.
"""

import pytest

from portal.core.auth import oauth_google as og
from portal.core.auth import session as ss
from portal.modules.auth import dang_nhap_google as dng
from portal.modules.auth import repo


def _claims(**ghi_de) -> og.ClaimsGoogle:
    m = {"sub": "104287", "email": "ai.do@noblex.vn", "email_verified": True, "name": "Ai Đó"}
    m.update(ghi_de)
    return og.ClaimsGoogle(**m)


@pytest.fixture
async def don_sach(pool):
    yield
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM control.users WHERE id LIKE 'u_gg_%' OR email LIKE '%@gg.vn'")


async def _goi(conn, redis_client, claims, *, cho_dang_ky_moi=True):
    return await dng.dang_nhap(conn, redis_client, claims=claims, cho_dang_ky_moi=cho_dang_ky_moi)


async def test_nhanh_3_tao_user_moi_va_identity(pool, redis_client, don_sach):
    """Người hoàn toàn mới: 2 hàng, cùng giao dịch, 0 workspace."""
    async with pool.acquire() as conn, conn.transaction():
        sid, tenant_id = await _goi(conn, redis_client, _claims(email="moi@gg.vn"))
        assert tenant_id is None, "chưa thuộc workspace nào — FE đẩy tới màn tạo workspace"

        u = await repo.tim_user_theo_email(conn, "moi@gg.vn")
        assert u is not None
        assert u.lifecycle == "active"
        assert u.password_hash is None
        assert (await repo.tim_identity(conn, provider="google", subject="104287")).user_id == u.id

    ban_ghi = await ss.doc(redis_client, sid)
    assert ban_ghi is not None and ban_ghi.tenant_id is None


async def test_nhanh_1_lan_hai_khong_tao_them_gi(pool, redis_client, don_sach):
    async with pool.acquire() as conn, conn.transaction():
        await _goi(conn, redis_client, _claims(email="lai@gg.vn"))
    async with pool.acquire() as conn, conn.transaction():
        await _goi(conn, redis_client, _claims(email="lai@gg.vn"))
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.users WHERE email = 'lai@gg.vn'") == 1
        assert await conn.fetchval("SELECT count(*) FROM control.identities WHERE subject = '104287'") == 1


async def test_nhanh_1_doi_email_google_van_vao_dung_tai_khoan(pool, redis_client, don_sach):
    """Cái bẫy chính của cả tính năng. `sub` không đổi ⇒ vẫn là người cũ, dù
    email đã khác hẳn. Tra email trước thì đây thành nhánh 3 và họ mất sạch."""
    async with pool.acquire() as conn, conn.transaction():
        await _goi(conn, redis_client, _claims(email="cu@gg.vn"))
    async with pool.acquire() as conn:
        u_cu = await repo.tim_user_theo_email(conn, "cu@gg.vn")

    async with pool.acquire() as conn, conn.transaction():
        sid, _ = await _goi(conn, redis_client, _claims(email="hoan.toan.moi@gg.vn"))

    ban_ghi = await ss.doc(redis_client, sid)
    assert ban_ghi.user_id == u_cu.id, "phải là user CŨ, không phải một user thứ hai"
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.users WHERE email LIKE '%@gg.vn'") == 1


async def test_nhanh_2_email_trung_thi_lien_ket_khong_tao_user(pool, redis_client, don_sach):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
            "VALUES ('u_gg_co_mk', 'co.mk@gg.vn', 'argon2-gia', 'Có Mật Khẩu', 'active')"
        )
    async with pool.acquire() as conn, conn.transaction():
        sid, _ = await _goi(conn, redis_client, _claims(email="co.mk@gg.vn"))

    assert (await ss.doc(redis_client, sid)).user_id == "u_gg_co_mk"
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.users WHERE email = 'co.mk@gg.vn'") == 1
        assert await conn.fetchval("SELECT password_hash FROM control.users WHERE id = 'u_gg_co_mk'") == "argon2-gia", (
            "liên kết KHÔNG được đụng vào mật khẩu sẵn có"
        )


async def test_bien_a_pending_thanh_active_va_thu_moi_chet(pool, redis_client, don_sach):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
            "VALUES ('u_gg_pending', 'pd@gg.vn', NULL, 'Chờ', 'pending')"
        )
        await conn.execute(
            "INSERT INTO control.invites (token_hash, user_id, email, tenant_id, expires_at, created_by) "
            "VALUES ($1, 'u_gg_pending', 'pd@gg.vn', NULL, now() + interval '7 days', 'u_gg_pending')",
            "e" * 64,
        )
    async with pool.acquire() as conn, conn.transaction():
        await _goi(conn, redis_client, _claims(email="pd@gg.vn"))
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT lifecycle FROM control.users WHERE id = 'u_gg_pending'") == "active"
        assert await conn.fetchval("SELECT count(*) FROM control.invites WHERE user_id = 'u_gg_pending'") == 0


async def test_bien_b_CUA_HAU_user_dinh_chi_khong_vao_duoc(pool, redis_client, don_sach):
    """TEST QUAN TRỌNG NHẤT CỦA CẢ TÍNH NĂNG.

    Đình chỉ có nghĩa "thu hồi quyền vào". Cửa mật khẩu đã chặn; cửa này mà không
    chặn thì lệnh đình chỉ chỉ còn là một dòng chữ trong DB.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
            "VALUES ('u_gg_dc', 'dc@gg.vn', 'argon2-gia', 'Đình Chỉ', 'suspended')"
        )
    async with pool.acquire() as conn, conn.transaction():
        with pytest.raises(og.LoiGoogle) as e:
            await _goi(conn, redis_client, _claims(email="dc@gg.vn"))
    assert e.value.ma == "TAI_KHOAN_DINH_CHI"
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.identities WHERE subject = '104287'") == 0


async def test_bien_b_identity_da_lien_ket_roi_bi_dinh_chi_sau_do(pool, redis_client, don_sach):
    """Đình chỉ SAU khi đã liên kết — nhánh 1 cũng phải kiểm lifecycle, không chỉ nhánh 2."""
    async with pool.acquire() as conn, conn.transaction():
        await _goi(conn, redis_client, _claims(email="sau@gg.vn"))
    async with pool.acquire() as conn:
        await conn.execute("UPDATE control.users SET lifecycle = 'suspended' WHERE email = 'sau@gg.vn'")
    async with pool.acquire() as conn, conn.transaction():
        with pytest.raises(og.LoiGoogle) as e:
            await _goi(conn, redis_client, _claims(email="sau@gg.vn"))
    assert e.value.ma == "TAI_KHOAN_DINH_CHI"


async def test_bien_c_email_chua_xac_thuc_thi_tu_choi(pool, redis_client, don_sach):
    async with pool.acquire() as conn, conn.transaction():
        with pytest.raises(og.LoiGoogle) as e:
            await _goi(conn, redis_client, _claims(email="chua@gg.vn", email_verified=False))
    assert e.value.ma == "EMAIL_CHUA_XAC_THUC"


def test_lifecycle_khong_ro_cung_bi_chan():
    """`_kiem_vao_duoc` phải là ALLOWLIST (`active`/`pending`), không phải
    denylist (`== "suspended"`) — nếu không, một giá trị `lifecycle` thứ tư sau
    này (`closed`, `archived`, ...) lọt qua cửa Google trong im lặng dù cửa mật
    khẩu (`service.dang_nhap`, allowlist `!= "active"`) đã chặn nó.

    CHECK `users_lifecycle_check` (migration 0103) giới hạn cột trong đúng ba
    giá trị hôm nay, nên KHÔNG chèn được một `lifecycle` thứ tư qua DB để đi hết
    một lượt `dang_nhap()` — gọi trực tiếp hàm thuần `_kiem_vao_duoc` với một
    `repo.HangUser` dựng tay là cách duy nhất neo được ca này trước khi CHECK đó
    nới ra thêm giá trị.
    """
    u = repo.HangUser(
        id="u_gg_khong_ro",
        email="khong-ro@gg.vn",
        password_hash=None,
        name="Không Rõ",
        lifecycle="closed",
        phone=None,
        job_title=None,
        avatar_seed=None,
    )
    with pytest.raises(og.LoiGoogle) as e:
        dng._kiem_vao_duoc(u)
    assert e.value.ma == "TAI_KHOAN_DINH_CHI"


async def test_tat_dang_ky_thi_nguoi_moi_bi_tu_choi_nhung_nguoi_cu_van_vao(pool, redis_client, don_sach):
    async with pool.acquire() as conn, conn.transaction():
        with pytest.raises(og.LoiGoogle) as e:
            await _goi(conn, redis_client, _claims(email="khach@gg.vn"), cho_dang_ky_moi=False)
    assert e.value.ma == "DANG_KY_DANG_TAT"

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
            "VALUES ('u_gg_cu', 'cu2@gg.vn', 'argon2-gia', 'Cũ', 'active')"
        )
    async with pool.acquire() as conn, conn.transaction():
        sid, _ = await _goi(conn, redis_client, _claims(email="cu2@gg.vn"), cho_dang_ky_moi=False)
    assert (await ss.doc(redis_client, sid)).user_id == "u_gg_cu"
