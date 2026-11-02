"""0952 — `invites` sống được KHÔNG cần một hàng `users`.

Bài này canh HÌNH DẠNG của bảng, không canh nghiệp vụ: nghiệp vụ ở
`tests/modules/auth/`. Ba hình dạng hàng hợp lệ (spec §4) và hình dạng thứ tư
phải bị CHECK bác — nếu không, một lời mời không vai trò sẽ ngồi im trong DB rồi
nổ ở lúc nhận, xa chỗ sinh ra nó.
"""

import asyncpg
import pytest

pytestmark = pytest.mark.integration


async def _don(pool) -> None:
    await pool.execute("DELETE FROM control.invites WHERE email LIKE '%@mig0952.test'")


@pytest.fixture
async def ws_mig(pool):
    await pool.execute(
        "INSERT INTO control.tenants (id, name, created_by) VALUES ('cs_mig0952', 'Mig 0952', 'u_seed_test')"
    )
    yield "cs_mig0952"
    await _don(pool)
    await pool.execute("DELETE FROM control.tenants WHERE id = 'cs_mig0952'")


@pytest.fixture
async def role_mig(pool):
    return await pool.fetchval("SELECT id FROM control.roles WHERE name = 'Biên tập'")


_H = "a" * 64


async def test_loi_moi_khong_co_user_id_ghi_duoc(pool, ws_mig, role_mig):
    """Đây là toàn bộ lý do 0952 tồn tại: `user_id` NULL phải ghi được."""
    await pool.execute(
        """INSERT INTO control.invites (token_hash, email, user_id, tenant_id, role_id, expires_at, created_by)
           VALUES ($1, 'a@mig0952.test', NULL, $2, $3, now() + interval '7 days', 'u_seed_test')""",
        _H,
        ws_mig,
        role_mig,
    )
    r = await pool.fetchrow("SELECT user_id, email, role_id FROM control.invites WHERE token_hash = $1", _H)
    assert r["user_id"] is None
    assert r["email"] == "a@mig0952.test"
    assert r["role_id"] == role_mig
    await _don(pool)


async def test_moi_workspace_khong_vai_tro_bi_bac(pool, ws_mig):
    """`tenant_id` có mà `role_id` NULL = một lời mời không hứa gì. CHECK bác."""
    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute(
            """INSERT INTO control.invites (token_hash, email, user_id, tenant_id, role_id, expires_at, created_by)
               VALUES ($1, 'b@mig0952.test', NULL, $2, NULL, now() + interval '7 days', 'u_seed_test')""",
            "b" * 64,
            ws_mig,
        )


async def test_token_dang_ky_khong_user_bi_bac(pool):
    """`tenant_id` NULL (token đăng ký) mà không `user_id` = một token trỏ vào hư không."""
    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute(
            """INSERT INTO control.invites (token_hash, email, user_id, tenant_id, role_id, expires_at, created_by)
               VALUES ($1, 'c@mig0952.test', NULL, NULL, NULL, now() + interval '7 days', 'u_seed_test')""",
            "c" * 64,
        )


async def test_hai_loi_moi_cung_email_cung_workspace_bi_bac(pool, ws_mig, role_mig):
    await pool.execute(
        """INSERT INTO control.invites (token_hash, email, user_id, tenant_id, role_id, expires_at, created_by)
           VALUES ($1, 'd@mig0952.test', NULL, $2, $3, now() + interval '7 days', 'u_seed_test')""",
        "d" * 64,
        ws_mig,
        role_mig,
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await pool.execute(
            """INSERT INTO control.invites (token_hash, email, user_id, tenant_id, role_id, expires_at, created_by)
               VALUES ($1, 'd@mig0952.test', NULL, $2, $3, now() + interval '7 days', 'u_seed_test')""",
            "e" * 64,
            ws_mig,
            role_mig,
        )
    await _don(pool)


async def test_hai_token_dang_ky_cung_email_bi_bac(pool):
    """Chỉ mục BỘ PHẬN thứ hai giữ lời hứa mà `user_id UNIQUE` cũ từng giữ.

    Một chỉ mục `UNIQUE (email, tenant_id)` duy nhất KHÔNG chặn được ca này:
    Postgres coi hai NULL là khác nhau, nên hai hàng `tenant_id IS NULL` cùng
    email đều lọt. Bài này là thứ đỏ nếu ai đó gộp hai chỉ mục làm một.
    """
    await pool.execute(
        "INSERT INTO control.users (id, email, name, lifecycle, password_hash) "
        "VALUES ('u_mig0952', 'f@mig0952.test', 'F', 'pending', NULL)"
    )
    try:
        await pool.execute(
            """INSERT INTO control.invites (token_hash, email, user_id, tenant_id, role_id, expires_at, created_by)
               VALUES ($1, 'f@mig0952.test', 'u_mig0952', NULL, NULL, now() + interval '7 days', 'u_seed_test')""",
            "f" * 64,
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await pool.execute(
                """INSERT INTO control.invites (token_hash, email, user_id, tenant_id, role_id, expires_at, created_by)
                   VALUES ($1, 'f@mig0952.test', 'u_mig0952', NULL, NULL, now() + interval '7 days', 'u_seed_test')""",
                "0" * 64,
            )
    finally:
        await _don(pool)
        await pool.execute("DELETE FROM control.users WHERE id = 'u_mig0952'")


async def test_email_phai_thuong(pool, ws_mig, role_mig):
    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute(
            """INSERT INTO control.invites (token_hash, email, user_id, tenant_id, role_id, expires_at, created_by)
               VALUES ($1, 'G@mig0952.test', NULL, $2, $3, now() + interval '7 days', 'u_seed_test')""",
            "9" * 64,
            ws_mig,
            role_mig,
        )
