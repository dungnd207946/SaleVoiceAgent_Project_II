"""Fixture dùng chung cho test của M4a.

Cùng nếp `tests/modules/kb/conftest.py`: một workspace thật, một user thật, và
client đã đăng nhập. Không mock — `tenant_conn()` là seam của cách ly, và mock
nó thì test xanh cho cả một RLS đã tắt.
"""

import asyncpg
import httpx
import pytest

MAT_KHAU = "MatKhauDaiVaManh!1"
TENANT = "rew"


@pytest.fixture
async def workspace_re(pool: asyncpg.Pool):
    from portal.core.auth.password import bam

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, 'RE Workspace', 'u_seed_test')", TENANT
        )
        await conn.execute(
            "INSERT INTO control.users (id, name, email, password_hash) VALUES ($1, $2, $3, $4)",
            "u_re",
            "Đăng",
            "dang@re.vn",
            bam(MAT_KHAU),
        )
        # migration 0104: `role` (4 mã cố định) → `role_id` (vai trò do tổ chức
        # tự định nghĩa). Session này cần LÀM VIỆC THẬT (CRUD catalog), nên cấp
        # Quản trị (đủ danh mục action) — không phải widen require(), fixture chỉ
        # tra id vai trò mẫu mà trigger của 0104 đã seed cho org 'noble'.
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_re', $1, $2)",
            TENANT,
            r_admin,
        )
    yield TENANT
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id = $1", TENANT)
        await conn.execute("DELETE FROM control.users WHERE id = 'u_re'")


@pytest.fixture
async def conn_re(pool: asyncpg.Pool, workspace_re: str):
    """Kết nối đã đặt `app.tenant_id` — RLS có hiệu lực, đúng như production.

    Dùng `tenant_conn` thật chứ không tự `set_config`: nếu `tenant_conn` đổi
    cách đặt biến thì test phải đỏ, không phải im lặng chạy đường cũ.
    """
    from portal.core.db.session import tenant_conn

    async with tenant_conn(pool, workspace_re) as conn:
        yield conn


@pytest.fixture
async def client_re(app_client: httpx.AsyncClient, workspace_re, kho_tep) -> httpx.AsyncClient:
    """Client đã đăng nhập vào workspace `rew`, kho tệp rỗng.

    Nhận `kho_tep` để BUỘC THỨ TỰ: nó dọn bucket lúc setup, nên test nào upload
    trước rồi mới dựng nó sẽ mất file vừa ghi.
    """
    r = await app_client.post("/api/v1/auth/login", json={"email": "dang@re.vn", "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    return app_client


@pytest.fixture
def nap_du_an(client_re):
    """Tạo `n` dự án, trả list `project_code` theo ĐÚNG thứ tự danh sách sẽ trả
    (`ORDER BY id DESC` ⇒ mã tạo sau đứng trước)."""

    async def _nap(n: int, *, region: str = "Hà Nội") -> list[str]:
        ma = []
        for i in range(n):
            code = f"PT{region[:2]}{i:02d}"
            r = await client_re.post(
                "/api/v1/projects",
                json={"projectCode": code, "name": f"Dự án {code}", "region": region},
            )
            assert r.status_code == 201, r.text
            ma.append(code)
        return list(reversed(ma))

    return _nap


@pytest.fixture
def nap_phan_khu(client_re):
    async def _nap(project_code: str, n: int) -> list[str]:
        ma = []
        for i in range(n):
            code = f"PK{i:02d}"
            r = await client_re.post(
                f"/api/v1/projects/{project_code}/zones",
                json={"zoneCode": code, "name": f"Phân khu {code}", "category": "chung_cu"},
            )
            assert r.status_code == 201, r.text
            ma.append(code)
        return list(reversed(ma))

    return _nap


@pytest.fixture
def nap_can(client_re):
    """`units.zone_code` mang FK thật tới `zones` (migration 0400) — cần một
    zone có sẵn trước khi tạo căn, khác `nap_du_an`/`nap_tai_lieu`/`nap_media`.
    Zone dùng chung một mã cố định; lần gọi thứ hai (test gọi `nap_can` hai lần
    trên cùng dự án) trùng mã zone và nhận 409 — bỏ qua, đó không phải lỗi."""

    async def _nap(project_code: str, n: int, *, product_type: str = "chung_cu") -> None:
        r = await client_re.post(
            f"/api/v1/projects/{project_code}/zones",
            json={"zoneCode": "PKMD", "name": "Phân khu mặc định", "category": "chung_cu"},
        )
        assert r.status_code in (201, 409), r.text
        for i in range(n):
            r = await client_re.post(
                f"/api/v1/projects/{project_code}/units",
                json={
                    "zoneCode": "PKMD",
                    "unitCode": f"{product_type[:2].upper()}-{i:03d}",
                    "productType": product_type,
                },
            )
            assert r.status_code == 201, r.text

    return _nap


@pytest.fixture
def nap_tai_lieu(client_re):
    async def _nap(project_code: str, n: int) -> None:
        for i in range(n):
            r = await client_re.post(
                f"/api/v1/projects/{project_code}/documents",
                json={"title": f"Tài liệu {i}", "loai": "khac"},
            )
            assert r.status_code == 201, r.text

    return _nap


@pytest.fixture
def nap_media(client_re):
    async def _nap(project_code: str, n: int, *, category: str = "ngoai_that") -> None:
        for i in range(n):
            r = await client_re.post(
                f"/api/v1/projects/{project_code}/media",
                json={
                    "category": category,
                    "contentType": "image",
                    "mediaUrl": f"tenants/t/kb-bds/{category}{i}/a.webp",
                    "contentHash": f"{category}{i}",
                },
            )
            assert r.status_code == 201, r.text

    return _nap
