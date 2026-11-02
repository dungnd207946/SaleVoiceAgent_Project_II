"""Fixture dùng chung cho test của module config (M3)."""

import asyncpg
import httpx
import pytest

MAT_KHAU = "MatKhauDaiVaManh!1"

PAYLOAD_HOP_LE = {
    "schema_version": 3,
    "danh_tinh": {"ten_agent": "Mai", "ten_thuong_hieu": "An Phú Land"},
    "pham_vi": {"phong_ban": [{"ten": "CSKH", "khi_nao": "khách hỏi hợp đồng đã ký"}]},
    "tools": {"enabled": ["find_project", "kb_search"]},
}


@pytest.fixture
async def workspace_cfg(pool: asyncpg.Pool):
    """Một user, một workspace, một membership admin. Dọn sau mỗi test.

    Mật khẩu băm bằng đúng hàm production dùng, không phải chuỗi cứng: hash cứng
    trong test là thứ hết hạn im lặng ngày ai đó đổi tham số Argon2.
    """
    from portal.core.auth.password import bam

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('cf_anphu', 'An Phú Land', 'u_seed_test')"
        )
        await conn.execute(
            "INSERT INTO control.users (id, name, email, password_hash) VALUES ($1, $2, $3, $4)",
            "u_cf",
            "Đăng",
            "dang@anphuland.vn",
            bam(MAT_KHAU),
        )
        # migration 0104: `role` (4 mã cố định) → `role_id` (vai trò do tổ chức
        # tự định nghĩa). Session này cần LÀM VIỆC THẬT (đọc/ghi cấu hình agent),
        # nên cấp Quản trị (đủ danh mục action) — không phải widen require(), fixture
        # chỉ tra id vai trò mẫu mà trigger của 0104 đã seed cho org 'noble'.
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_cf', 'cf_anphu', $1)",
            r_admin,
        )
    yield "cf_anphu"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id LIKE 'cf\\_%'")
        await conn.execute("DELETE FROM control.users WHERE id = 'u_cf'")


@pytest.fixture
async def client_cfg(app_client: httpx.AsyncClient, workspace_cfg, kho_tep) -> httpx.AsyncClient:
    """Client đã đăng nhập, workspace `cf_anphu`, kho tệp rỗng.

    Nhận `kho_tep` để BUỘC THỨ TỰ: nó dọn sạch bucket lúc setup, nên test nào
    publish trước rồi mới dựng fixture đó sẽ mất bundle vừa ghi. Cùng lý do
    `app_client` nhận `redis_client` — xem docstring của nó.
    """
    r = await app_client.post("/api/v1/auth/login", json={"email": "dang@anphuland.vn", "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    return app_client
