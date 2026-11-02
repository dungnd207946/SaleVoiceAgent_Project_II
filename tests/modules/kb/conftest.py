"""Seed dùng chung cho test của module kb — mỗi hàng chứng minh một nhánh:

  nplb / __ALL__ / draftpj   projects: đường thường · sentinel cấp tenant · anchor nháp
  doc có body                không cần trích PDF
  doc body='' + file_url     nhánh presign + extract_profile
  doc dưới draftpj           cascade cha chặn con

INSERT vào `tenant_data` phải đi qua `tenant_conn()` (RLS FORCE). `control.*` thì không.

CHƯA seed `media`/`zones` — nhưng KHÔNG còn vì thiếu migration: `0400_kb_real_estate`
(M4, vào theo nhánh dungnd) đã dựng cả hai bảng. Đây là khoảng trống test còn nợ, không
phải chặn kỹ thuật: pipeline media (`service.index_media`) và nhánh `section_col="name"`
của zones hiện chưa có test trên dữ liệu thật.
"""

import pytest

from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn

# `client_cfg`/`workspace_cfg` sống ở `tests/modules/config/conftest.py` (module config
# là chỗ dựng chúng) — re-export CÙNG cách `tests/modules/agent_seam/conftest.py` đã làm,
# để `test_endpoint_sync.py` không phải dựng bản thứ hai của "một workspace đã đăng nhập".
from tests.modules.config.conftest import client_cfg, workspace_cfg  # noqa: F401

TENANT = "kb_acme"
OTHER_TENANT = "kb_other"

_PROJECTS = [
    ("nplb", "Noble Palace Long Biên", "published"),
    ("__ALL__", "Chung / toàn tenant", "published"),
    ("draftpj", "Dự án chưa công bố", "draft"),
]

_DOCUMENTS = [
    ("nplb", "Chính sách bán hàng Q3", "## Tiến độ thanh toán\n| Đợt | % |", "", "published"),
    ("__ALL__", "Brochure công ty", "", "docs/brochure.pdf", "published"),
    ("draftpj", "Tài liệu của dự án nháp", "nội dung gì đó", "", "published"),
]


@pytest.fixture
async def seed_kb(pool):
    """Hai tenant: seed đúng tenant đang test thì mọi bug cách ly trông như chạy đúng."""
    async with pool.acquire() as conn, conn.transaction():
        for tid, name in [(TENANT, "KB Acme"), (OTHER_TENANT, "KB Other")]:
            # org_id: `0102_organizations` thêm cột NOT NULL và seed sẵn org 'noble'
            # (NobleX vận hành hệ). Cùng nếp mọi conftest khác của repo.
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $2, 'u_seed_test')", tid, name
            )

    for tid in (TENANT, OTHER_TENANT):
        async with tenant_conn(pool, tid) as conn:
            for code, name, status in _PROJECTS:
                await conn.execute(
                    "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) VALUES ($1,$2,$3,$4)",
                    tid,
                    code,
                    name,
                    status,
                )
            for project_code, title, body, file_url, status in _DOCUMENTS:
                await conn.execute(
                    """
                    INSERT INTO tenant_data.documents (tenant_id, project_code, title, body, file_url, status)
                    VALUES ($1,$2,$3,$4,$5,$6)
                    """,
                    tid,
                    project_code,
                    title,
                    body,
                    file_url,
                    status,
                )
    yield
    # ON DELETE CASCADE của FK tenant_id dọn sạch tenant_data — cascade chạy ở tầng
    # hệ thống nên nó không bị RLS chặn.
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id LIKE 'kb\\_%'")


@pytest.fixture
async def api_pool(api_dsn):
    """Pool runtime (`portal_api`) — worker thật nối bằng role này.

    ⚠ Đừng dùng `pool` để test ingest: nó là `portal_migrator` = superuser trong
    container, và superuser bỏ qua RLS kể cả FORCE. `pool` chỉ để seed và quét catalog.
    """
    p = await create_pool(api_dsn, min_size=1, max_size=4)
    yield p
    await p.close()


@pytest.fixture
async def doc_ids(pool, seed_kb) -> dict[str, int]:
    """{project_code: documents.id} của tenant TENANT — test cần id thật để gọi service."""
    async with tenant_conn(pool, TENANT) as conn:
        rows = await conn.fetch(
            "SELECT project_code, id FROM tenant_data.documents WHERE tenant_id = $1 ORDER BY id",
            TENANT,
        )
    return {r["project_code"]: r["id"] for r in rows}


@pytest.fixture
async def tenant_co_du_an_va_phan_khu(pool):
    """Một tenant với 1 dự án + 2 phân khu. Trả `(tenant_id, project_code, project_id, zone_id)`."""
    tenant_id = "kb_childblock"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')", tenant_id
        )
    async with tenant_conn(pool, tenant_id) as conn:
        project_id = await conn.fetchval(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
            "VALUES (portal.current_tenant(), 'P1', 'Dự án 1', 'published') RETURNING id"
        )
        zone_id = await conn.fetchval(
            "INSERT INTO tenant_data.zones (tenant_id, project_code, zone_code, name, status) "
            "VALUES (portal.current_tenant(), 'P1', 'Z1', 'Phân khu 1', 'published') RETURNING id"
        )
        await conn.execute(
            "INSERT INTO tenant_data.zones (tenant_id, project_code, zone_code, name, status) "
            "VALUES (portal.current_tenant(), 'P1', 'Z2', 'Phân khu 2', 'published')"
        )
    yield tenant_id, "P1", project_id, zone_id
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.jobs WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM control.tenants WHERE id = $1", tenant_id)
