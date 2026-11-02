"""Tầng repo của lời mời sau 0952 — ba hình dạng token, một hàm đọc.

Đo ở tầng repo chứ không chỉ qua HTTP: vị từ "token nào còn hiệu lực" nằm trong
WHERE (xem docstring `doc_loi_moi_con_hieu_luc`), và một vị từ trong SQL thì chỉ
có SQL đo được. Qua HTTP thì ba nhánh trông giống nhau — cùng 404.
"""

from datetime import UTC, datetime, timedelta

import pytest

from portal.modules.auth import repo

pytestmark = pytest.mark.integration

_HAN = timedelta(days=7)


def _han():
    return datetime.now(UTC) + _HAN


@pytest.fixture
async def nen(pool):
    """1 workspace · 1 user active · 1 user pending. Dọn sạch sau mỗi bài."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('cs_rlm', 'Repo LM', 'u_seed_test')"
        )
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_rlm_act', 'act@rlm.test', 'Người Active', 'active', 'x')"
        )
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
            "VALUES ('u_rlm_pen', 'pen@rlm.test', 'Người Pending', 'pending', NULL)"
        )
    r = await pool.fetchval("SELECT id FROM control.roles WHERE name = 'Biên tập'")
    yield {"ws": "cs_rlm", "role": r}
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.invites WHERE email LIKE '%rlm.test'")
        await conn.execute("DELETE FROM control.memberships WHERE tenant_id = 'cs_rlm'")
        await conn.execute("DELETE FROM control.users WHERE id LIKE 'u\\_rlm%'")
        await conn.execute("DELETE FROM control.tenants WHERE id = 'cs_rlm'")


async def test_doc_loi_moi_invite_new_khong_can_user(pool, nen):
    """Trái tim của cả thay đổi: đọc được một lời mời KHÔNG trỏ vào user nào."""
    async with pool.acquire() as conn:
        await repo.ghi_loi_moi_workspace(
            conn,
            token_hash="1" * 64,
            email="moi@rlm.test",
            user_id=None,
            tenant_id=nen["ws"],
            role_id=nen["role"],
            expires_at=_han(),
            created_by="u_seed_test",
        )
        h = await repo.doc_loi_moi_con_hieu_luc(conn, "1" * 64)
    assert h is not None
    assert h.user_id is None
    assert h.name is None
    assert h.email == "moi@rlm.test"
    assert h.tenant_id == "cs_rlm"
    assert h.role_id == nen["role"]
    assert h.ten_workspace == "Repo LM", "màn nhận mời phải nói được tham gia CÁI GÌ"


async def test_doc_loi_moi_invite_existing_cho_user_active(pool, nen):
    """`u.lifecycle = 'pending'` của vị từ CŨ sẽ loại đúng ca này — đó là bug nó vá."""
    async with pool.acquire() as conn:
        await repo.ghi_loi_moi_workspace(
            conn,
            token_hash="2" * 64,
            email="act@rlm.test",
            user_id="u_rlm_act",
            tenant_id=nen["ws"],
            role_id=nen["role"],
            expires_at=_han(),
            created_by="u_seed_test",
        )
        h = await repo.doc_loi_moi_con_hieu_luc(conn, "2" * 64)
    assert h is not None
    assert h.user_id == "u_rlm_act"
    assert h.name == "Người Active"


async def test_doc_loi_moi_signup_van_doi_pending(pool, nen):
    """Chiều cũ phải giữ: token đăng ký của một user đã `active` KHÔNG được đặt lại
    mật khẩu của họ. Đây là lý lẽ gốc của vị từ, và nó vẫn đúng cho nhánh này."""
    async with pool.acquire() as conn:
        await repo.ghi_loi_moi_dang_ky(
            conn,
            token_hash="3" * 64,
            user_id="u_rlm_pen",
            email="pen@rlm.test",
            expires_at=_han(),
            created_by="u_seed_test",
        )
        assert await repo.doc_loi_moi_con_hieu_luc(conn, "3" * 64) is not None
        await conn.execute("UPDATE control.users SET lifecycle = 'active' WHERE id = 'u_rlm_pen'")
        assert await repo.doc_loi_moi_con_hieu_luc(conn, "3" * 64) is None


async def test_moi_lai_cung_email_cung_ws_giet_token_cu(pool, nen):
    async with pool.acquire() as conn:
        for h in ("4" * 64, "5" * 64):
            await repo.ghi_loi_moi_workspace(
                conn,
                token_hash=h,
                email="moi@rlm.test",
                user_id=None,
                tenant_id=nen["ws"],
                role_id=nen["role"],
                expires_at=_han(),
                created_by="u_seed_test",
            )
        assert await repo.doc_loi_moi_con_hieu_luc(conn, "4" * 64) is None, "token cũ phải chết"
        assert await repo.doc_loi_moi_con_hieu_luc(conn, "5" * 64) is not None


async def test_mot_email_nhan_moi_tu_hai_workspace(pool, nen):
    """`user_id UNIQUE` cũ chặn đúng ca này. Nó phải đi được.

    `cs_rlm2` dọn trong `finally`, không phải một khối trần sau hai `assert`:
    fixture `nen` chỉ biết dọn `cs_rlm`, nên NẾU một `assert` ở đây fail mà
    không có `finally`, hàng `cs_rlm2` (và invite trỏ vào nó) sống sót vĩnh
    viễn — lượt chạy KẾ TIẾP của file này chết ngay ở INSERT với lỗi khoá
    trùng, che mất lỗi gốc và làm cả file đỏ dây chuyền.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('cs_rlm2', 'Repo LM 2', 'u_seed_test')"
        )
    try:
        async with pool.acquire() as conn:
            for h, ws in (("6" * 64, "cs_rlm"), ("7" * 64, "cs_rlm2")):
                await repo.ghi_loi_moi_workspace(
                    conn,
                    token_hash=h,
                    email="act@rlm.test",
                    user_id="u_rlm_act",
                    tenant_id=ws,
                    role_id=nen["role"],
                    expires_at=_han(),
                    created_by="u_seed_test",
                )
            assert await repo.doc_loi_moi_con_hieu_luc(conn, "6" * 64) is not None
            assert await repo.doc_loi_moi_con_hieu_luc(conn, "7" * 64) is not None
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM control.invites WHERE tenant_id = 'cs_rlm2'")
            await conn.execute("DELETE FROM control.tenants WHERE id = 'cs_rlm2'")


async def test_token_het_han_va_da_dung_deu_tra_none(pool, nen):
    async with pool.acquire() as conn:
        await repo.ghi_loi_moi_workspace(
            conn,
            token_hash="8" * 64,
            email="moi@rlm.test",
            user_id=None,
            tenant_id=nen["ws"],
            role_id=nen["role"],
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            created_by="u_seed_test",
        )
        assert await repo.doc_loi_moi_con_hieu_luc(conn, "8" * 64) is None

        await repo.ghi_loi_moi_workspace(
            conn,
            token_hash="9" * 64,
            email="hai@rlm.test",
            user_id=None,
            tenant_id=nen["ws"],
            role_id=nen["role"],
            expires_at=_han(),
            created_by="u_seed_test",
        )
        await repo.danh_dau_da_dung(conn, token_hash="9" * 64)
        assert await repo.doc_loi_moi_con_hieu_luc(conn, "9" * 64) is None


async def test_tao_user_da_kich_hoat_ra_doi_active_co_mat_khau(pool, nen):
    """`pending` nghĩa "chưa đặt mật khẩu". Nhánh `invite_new` có mật khẩu trong
    CÙNG lệnh, nên cho nó đi qua `pending` là nói sai một trạng thái."""
    async with pool.acquire() as conn:
        await repo.tao_user_da_kich_hoat(
            conn, user_id="u_rlm_new", email="new@rlm.test", name="new", password_hash="bam"
        )
        u = await repo.tim_user_theo_id(conn, "u_rlm_new")
    assert u is not None and u.lifecycle == "active"


async def test_liet_ke_thanh_vien_tra_ca_hang_loi_moi(pool, nen):
    async with pool.acquire() as conn:
        await repo.them_membership(conn, user_id="u_rlm_act", tenant_id="cs_rlm", role_id=nen["role"])
        await repo.ghi_loi_moi_workspace(
            conn,
            token_hash="a" * 64,
            email="cho@rlm.test",
            user_id=None,
            tenant_id="cs_rlm",
            role_id=nen["role"],
            expires_at=_han(),
            created_by="u_seed_test",
        )
        rows = await repo.liet_ke_thanh_vien(conn, "cs_rlm")

    theo_email = {r.email: r for r in rows}
    assert theo_email["act@rlm.test"].kind == "member"
    cho = theo_email["cho@rlm.test"]
    assert cho.kind == "invite"
    assert cho.userId is None
    assert cho.name is None
    assert cho.lifecycle is None
    assert cho.roleId == nen["role"]
    assert cho.expiresAt is not None


async def test_liet_ke_thanh_vien_bo_qua_loi_moi_da_dung(pool, nen):
    async with pool.acquire() as conn:
        await repo.ghi_loi_moi_workspace(
            conn,
            token_hash="b" * 64,
            email="xong@rlm.test",
            user_id=None,
            tenant_id="cs_rlm",
            role_id=nen["role"],
            expires_at=_han(),
            created_by="u_seed_test",
        )
        await repo.danh_dau_da_dung(conn, token_hash="b" * 64)
        rows = await repo.liet_ke_thanh_vien(conn, "cs_rlm")
    assert "xong@rlm.test" not in {r.email for r in rows}


async def test_thu_hoi_loi_moi(pool, nen):
    async with pool.acquire() as conn:
        await repo.ghi_loi_moi_workspace(
            conn,
            token_hash="c" * 64,
            email="thuhoi@rlm.test",
            user_id=None,
            tenant_id="cs_rlm",
            role_id=nen["role"],
            expires_at=_han(),
            created_by="u_seed_test",
        )
        assert await repo.thu_hoi_loi_moi(conn, tenant_id="cs_rlm", email="thuhoi@rlm.test") is True
        assert await repo.doc_loi_moi_con_hieu_luc(conn, "c" * 64) is None
        assert await repo.thu_hoi_loi_moi(conn, tenant_id="cs_rlm", email="thuhoi@rlm.test") is False


async def test_la_thanh_vien(pool, nen):
    async with pool.acquire() as conn:
        assert await repo.la_thanh_vien(conn, user_id="u_rlm_act", tenant_id="cs_rlm") is False
        await repo.them_membership(conn, user_id="u_rlm_act", tenant_id="cs_rlm", role_id=nen["role"])
        assert await repo.la_thanh_vien(conn, user_id="u_rlm_act", tenant_id="cs_rlm") is True


async def test_doc_ten_workspace(pool, nen):
    async with pool.acquire() as conn:
        assert await repo.doc_ten_workspace(conn, "cs_rlm") == "Repo LM"
        assert await repo.doc_ten_workspace(conn, "cs_khong_co") is None
