"""Repo của seam `/members` GHI (mời · đổi vai trò · gỡ) — task-4-brief.md.

Không dùng `@pytest.mark.anyio`: `pyproject.toml` cấu hình `asyncio_mode = "auto"`
(pytest-asyncio), không phải plugin `anyio` — cùng quy ước với `test_repo.py`
(mark `integration` ở CẤP MODULE, không mark từng hàm).
"""

from datetime import UTC, datetime, timedelta

import pytest

from portal.core.avatar import avatar_data_uri
from portal.modules.auth import repo

pytestmark = pytest.mark.integration


async def test_them_roi_doc_lai_thanh_vien(pool, workspace_cfg, role_id_bien_tap):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id,email,name,lifecycle) VALUES ('u_tv','tv@x.vn','TV','pending')"
        )
        await repo.them_membership(conn, user_id="u_tv", tenant_id=workspace_cfg, role_id=role_id_bien_tap)

        m = await repo.doc_thanh_vien(conn, tenant_id=workspace_cfg, user_id="u_tv")
        assert m is not None
        assert m.userId == "u_tv"
        assert m.roleId == role_id_bien_tap


async def test_doi_vai_tro_chi_cham_MOT_workspace(pool, workspace_cfg, role_id_bien_tap, role_id_nguoi_xem):
    """Neo bug mất dữ liệu 2026-08-06: `dat_lai_membership` THAY THẾ TOÀN BỘ, nên
    dùng nó cho đường này là xoá sạch vai trò của người đó ở workspace khác."""
    async with pool.acquire() as conn, conn.transaction():
        # Trước migration 0108, CHECK song điều kiện `users_password_theo_lifecycle_check`
        # (0103) buộc `lifecycle='active'` đi cùng `password_hash NOT NULL`. 0108 đổi tên
        # CHECK thành `users_co_duong_dang_nhap_check` và bỏ đúng chiều đó (user Google-only
        # là `active` mà không mật khẩu) — giá trị dưới đây không còn BẮT BUỘC bởi CHECK,
        # nhưng vẫn đặt để mô phỏng một user có mật khẩu thật; không cần băm thật, chỉ cần
        # khác NULL.
        await conn.execute(
            "INSERT INTO control.users (id,email,name,lifecycle,password_hash)"
            " VALUES ('u_hai','hai@x.vn','Hai','active','x')"
        )
        await conn.execute("INSERT INTO control.tenants (id,name,created_by) VALUES ('t_khac','Khác','u_hai')")
        await repo.them_membership(conn, user_id="u_hai", tenant_id=workspace_cfg, role_id=role_id_bien_tap)
        await repo.them_membership(conn, user_id="u_hai", tenant_id="t_khac", role_id=role_id_bien_tap)

        ok = await repo.doi_vai_tro_thanh_vien(
            conn, user_id="u_hai", tenant_id=workspace_cfg, role_id=role_id_nguoi_xem
        )
        assert ok is True

        con = await repo.doc_thanh_vien(conn, tenant_id="t_khac", user_id="u_hai")
        assert con is not None and con.roleId == role_id_bien_tap, "workspace khác bị đụng"


async def test_go_thanh_vien_giu_nguyen_tai_khoan(pool, workspace_cfg, role_id_bien_tap):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id,email,name,lifecycle,password_hash)"
            " VALUES ('u_go','go@x.vn','Go','active','x')"
        )
        await repo.them_membership(conn, user_id="u_go", tenant_id=workspace_cfg, role_id=role_id_bien_tap)

        assert await repo.go_thanh_vien(conn, user_id="u_go", tenant_id=workspace_cfg) is True
        assert await repo.doc_thanh_vien(conn, tenant_id=workspace_cfg, user_id="u_go") is None
        assert await conn.fetchval("SELECT 1 FROM control.users WHERE id='u_go'") == 1


async def test_go_nguoi_khong_phai_thanh_vien_tra_false(pool, workspace_cfg):
    async with pool.acquire() as conn, conn.transaction():
        assert await repo.go_thanh_vien(conn, user_id="u_khong_co", tenant_id=workspace_cfg) is False


# ─── Avatar trên hàng thành viên (2026-08-25) ─────────────────────────────────
# Bảng «Thành viên» phía FE phải hiện ĐÚNG avatar người dùng đã set ở «Hồ sơ &
# tuỳ chọn» — trước đó nó tự vẽ chữ cái nên avatar trên bảng LỆCH với avatar ở
# chân sidebar của chính người đó. Cùng công thức với `/me`
# (`auth/service.py`: `avatar_data_uri(u.avatar_seed or u.name)`).


async def test_thanh_vien_mang_avatar_suy_tu_ten(pool, workspace_cfg, role_id_bien_tap):
    """Chưa chọn avatar (`avatar_seed` NULL) ⇒ avatar mặc định suy từ TÊN —
    trùng từng byte với avatar mà `/me` trả cho chính người đó."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id,email,name,lifecycle,password_hash)"
            " VALUES ('u_av_ten','av.ten@x.vn','Trần Hải Đăng','active','x')"
        )
        await repo.them_membership(conn, user_id="u_av_ten", tenant_id=workspace_cfg, role_id=role_id_bien_tap)

        rows = await repo.liet_ke_thanh_vien(conn, workspace_cfg)
        m = await repo.doc_thanh_vien(conn, tenant_id=workspace_cfg, user_id="u_av_ten")

    hang = next(r for r in rows if r.userId == "u_av_ten")
    assert hang.avatar == avatar_data_uri("Trần Hải Đăng")
    assert hang.avatar is not None and hang.avatar.startswith("data:image/svg+xml")
    # `doc_thanh_vien` phục vụ response của PATCH — PHẢI cùng tập giá trị với
    # danh sách, nếu không hàng vừa đổi vai trò mất ảnh trong khi hàng khác còn.
    assert m is not None and m.avatar == hang.avatar


async def test_thanh_vien_avatar_theo_seed_da_chon(pool, workspace_cfg, role_id_bien_tap):
    """Đã chọn avatar ở «Đổi avatar» (`avatar_seed` có giá trị) ⇒ seed thắng tên."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id,email,name,lifecycle,password_hash,avatar_seed)"
            " VALUES ('u_av_seed','av.seed@x.vn','Người Có Seed','active','x','bottts:xyz')"
        )
        await repo.them_membership(conn, user_id="u_av_seed", tenant_id=workspace_cfg, role_id=role_id_bien_tap)

        rows = await repo.liet_ke_thanh_vien(conn, workspace_cfg)

    hang = next(r for r in rows if r.userId == "u_av_seed")
    assert hang.avatar == avatar_data_uri("bottts:xyz")
    assert hang.avatar != avatar_data_uri("Người Có Seed"), "seed đã chọn phải thắng tên"


async def test_hang_loi_moi_khong_avatar(pool, workspace_cfg, role_id_bien_tap):
    """Hàng `kind='invite'` không mang avatar — FE hiện phong bì cho hàng đó,
    một data URI ở đây là bytes không ai đọc trên mọi lượt tải bảng."""
    async with pool.acquire() as conn, conn.transaction():
        await repo.ghi_loi_moi_workspace(
            conn,
            token_hash="c" * 64,
            email="moi.avatar@x.vn",
            user_id=None,
            tenant_id=workspace_cfg,
            role_id=role_id_bien_tap,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            created_by="u_seed_test",
        )
        rows = await repo.liet_ke_thanh_vien(conn, workspace_cfg)
        await conn.execute("DELETE FROM control.invites WHERE email = 'moi.avatar@x.vn'")

    cho = next(r for r in rows if r.email == "moi.avatar@x.vn")
    assert cho.kind == "invite"
    assert cho.avatar is None
