"""CỔNG ĐẦU-CUỐI: dữ liệu `tenant_data` ghi qua portal ⇒ agent đọc DB thấy ngay.

Trước `0917` file này còn kiểm chuỗi "bấm Lưu và áp dụng ⇒ agent đọc config qua
Postgres" (view `agent_api.agent_published_config`) — đường đó đã bỏ, agent giờ chỉ
đọc config qua bundle trên kho tệp, không qua Postgres nữa (xem
`docs/contracts/dau-noi-agent.md`). Bốn test đo chuyện đó đã xoá.

Còn lại đúng một câu hỏi, khác loại dữ liệu: `tenant_data` không có bước "áp dụng" —
ghi là có hiệu lực ngay — và agent đọc bằng `odyssey_agent` (MỘT credential cho MỌI
tenant, hợp đồng §0), KHÔNG dùng fixture `pool` (là `portal_migrator`, superuser
trong container test, nên đọc được kể cả khi GRANT bị gỡ — một cổng "agent đọc được"
chạy bằng superuser là cổng không bao giờ đỏ).
"""

import uuid

import pytest

from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn
from tests.conftest import ODYSSEY_AGENT_PASSWORD, dsn_as

pytestmark = pytest.mark.integration


@pytest.fixture
async def agent_pool(pg_dsn: str):
    """Pool nối bằng `odyssey_agent` — ĐÚNG credential của pod agent (hợp đồng §0)."""
    p = await create_pool(dsn_as(pg_dsn, "odyssey_agent", ODYSSEY_AGENT_PASSWORD), min_size=1, max_size=2)
    yield p
    await p.close()


async def test_agent_doc_duoc_thay_doi_tenant_data(agent_pool, pool, workspace_cfg):
    """Không có bước "áp dụng": dữ liệu nghiệp vụ có hiệu lực ngay khi ghi, đó là
    thiết kế đúng cho nó. Từ `0917`: đọc thẳng `tenant_data.projects`, không qua view
    `agent_api.projects` nữa — cách ly còn lại hoàn toàn dựa vào RLS FORCE (`0913`).
    """
    code = f"P{uuid.uuid4().hex[:6]}"
    async with tenant_conn(pool, workspace_cfg) as conn:
        await conn.execute(
            """INSERT INTO tenant_data.projects
                   (tenant_id, project_code, name, category, sale_phase, status)
               VALUES ($1, $2, $2, ARRAY['chung_cu'], 'dang_ban', 'published')""",
            workspace_cfg,
            code,
        )

    async with tenant_conn(agent_pool, workspace_cfg) as conn:
        ds = await conn.fetch("SELECT project_code FROM tenant_data.projects")
    assert code in [r["project_code"] for r in ds], "agent không đọc được project vừa thêm"
