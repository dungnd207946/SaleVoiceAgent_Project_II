"""CỔNG 6 — vỏ API không phá cách ly mà M1 đã dựng.

Đường được kiểm: cookie -> phiên -> membership -> tenant_conn(tenant_id) -> RLS.
Nếu bất kỳ khâu nào truyền sai tenant_id thì user của workspace A đọc được hàng B.

Vì sao không test tenant_conn trực tiếp: M1 đã test nó. Cái chưa ai test là đường
từ COOKIE tới tenant_id — tức chính phần M2a thêm vào.
"""

import asyncpg
import httpx
import pytest
from fastapi import Depends, FastAPI

from portal.api.loi import dang_ky_handler_loi
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn
from portal.core.redis import create_redis
from portal.modules.auth.router import ROUTER
from tests.conftest import API_PASSWORD, dsn_as
from tests.modules.auth.conftest import MAT_KHAU

pytestmark = pytest.mark.integration


def _app_co_probe() -> FastAPI:
    """App = router thật của auth + MỘT endpoint đọc tenant_data.

    Endpoint probe dùng ĐÚNG khuôn mà 7 module sẽ dùng:
        p: Principal = require(<action>)  ->  tenant_conn(pool, p.tenant_id)
    Nên nếu khuôn đó sai, cổng này đỏ trước khi có module nào viết theo nó.
    """
    app = FastAPI()
    dang_ky_handler_loi(app)
    app.include_router(ROUTER, prefix="/api/v1")

    @app.get("/api/v1/_probe/du-an")
    async def du_an(
        p: Principal = require(ACTIONS.CATALOG_READ),
        pool: asyncpg.Pool = Depends(lay_pool),
    ) -> list[str]:
        async with tenant_conn(pool, p.tenant_id) as conn:
            # Vị từ tenant viết TAY, y như mọi truy vấn thật trong `src/portal`:
            # `0909_bo_rls_toan_bo` đã dỡ RLS khỏi `tenant_data`, nên `tenant_conn()`
            # chỉ còn ĐẶT biến phiên chứ không tự lọc gì. Probe này mô phỏng một
            # handler thật, nên nó phải lọc y như handler thật — nếu để câu trần thì
            # test đo một endpoint mà không endpoint nào trong repo được phép giống.
            rows = await conn.fetch(
                "SELECT name FROM tenant_data.projects WHERE tenant_id = portal.current_tenant() ORDER BY name"
            )
        return [r["name"] for r in rows]

    return app


@pytest.fixture
async def du_lieu_du_an(pool):
    """Mỗi tenant một dự án.

    ⚠ Phải SET LOCAL app.tenant_id cho TỪNG tenant: `pool` nối bằng portal_migrator
    (owner) nhưng migration 0003 bật FORCE ROW LEVEL SECURITY, và FORCE áp cả với
    chủ bảng. Không set thì WITH CHECK của policy từ chối INSERT.
    ⚠ `project_code` là NOT NULL không default (migration 0400 — M4a viết lại KB
    BĐS đổi tên cột `code` → `project_code`, xem
    `.superpowers/sdd/2026-08-03-kb-real-estate-viet-lai/task-2-report.md`) —
    phải cấp giá trị. Test này của module `auth` (kiểm phạm vi tenant qua
    `tenant_conn`), không phải của KB — chỉ đổi TÊN CỘT cho khớp schema mới,
    không đổi ý nghĩa test.
    """
    async with pool.acquire() as conn:
        for tid, ten in [("cs_anphu", "Dự án A"), ("cs_sunrise", "Dự án S"), ("cs_haven", "Dự án H")]:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tid)
                await conn.execute(
                    "INSERT INTO tenant_data.projects (tenant_id, project_code, name) VALUES ($1,$2,$3)",
                    tid,
                    f"DA_{tid}",
                    ten,
                )
    yield
    async with pool.acquire() as conn:
        for tid in ("cs_anphu", "cs_sunrise", "cs_haven"):
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tid)
                await conn.execute("DELETE FROM tenant_data.projects WHERE tenant_id = $1", tid)


@pytest.fixture
async def client_probe(pg_dsn, redis_url, ba_workspace, du_lieu_du_an):
    app = _app_co_probe()
    app.state.pool = await create_pool(dsn_as(pg_dsn, "portal_api", API_PASSWORD))
    app.state.redis = create_redis(redis_url)
    transport = httpx.ASGITransport(app=app)
    # https, không phải http — cookie phiên là Secure. Xem docstring fixture
    # app_client ở tests/conftest.py.
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as c:
        yield c
    await app.state.pool.close()
    await app.state.redis.aclose()


async def test_chi_doc_du_an_cua_workspace_hien_tai(client_probe):
    await client_probe.post("/api/v1/auth/login", json={"email": "dang@anphuland.vn", "password": MAT_KHAU})

    assert (await client_probe.get("/api/v1/_probe/du-an")).json() == ["Dự án A"]

    await client_probe.post("/api/v1/me/workspace", json={"workspaceId": "cs_sunrise"})
    assert (await client_probe.get("/api/v1/_probe/du-an")).json() == ["Dự án S"]


async def test_khong_bao_gio_thay_du_an_cua_workspace_khong_thuoc(client_probe):
    """`cs_haven` có dự án trong DB. User không thuộc nó, nên KHÔNG có đường nào
    đọc được — kể cả sau khi thử đổi sang nó."""
    await client_probe.post("/api/v1/auth/login", json={"email": "dang@anphuland.vn", "password": MAT_KHAU})
    await client_probe.post("/api/v1/me/workspace", json={"workspaceId": "cs_haven"})  # 403

    ket_qua = (await client_probe.get("/api/v1/_probe/du-an")).json()
    assert "Dự án H" not in ket_qua
