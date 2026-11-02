"""create_app() — chỗ duy nhất dựng FastAPI app.

Pool và Redis client sống theo `lifespan` của app, không phải module-level
singleton: test cần dựng nhiều app trong một tiến trình, và một singleton
module-level làm hai app dùng chung pool đã đóng.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from portal.api.loi import dang_ky_handler_loi
from portal.core.config import get_settings
from portal.core.db.pool import create_pool
from portal.core.redis import create_redis
from portal.modules.audit.router import ROUTER as audit
from portal.modules.auth.router import ROUTER as auth
from portal.modules.billing.router import ROUTER as billing
from portal.modules.config.router import ROUTER as config
from portal.modules.enrollment.router import ROUTER as enrollment
from portal.modules.ingest.router import ROUTER as ingest
from portal.modules.kb.router import ROUTER as kb
from portal.modules.linh_vuc.router import ROUTER as linh_vuc
from portal.modules.nhan_vat.router import ROUTER as nhan_vat
from portal.modules.ops.router import ROUTER as ops
from portal.modules.playbook.router import ROUTER as playbook
from portal.modules.realestate.router import ROUTER as realestate
from portal.modules.workspace.router import ROUTER as workspace

TIEN_TO = "/api/v1"
"""Tiền tố đặt ĐÚNG MỘT CHỖ. Module khai đường tương đối ('/me'), app.py gắn tiền
tố. Để mỗi module tự viết '/api/v1' thì một module viết sai là một endpoint nằm
ngoài proxy '^/api/' của Vite — và nó chỉ lộ ra lúc bấm vào màn đó trên trình duyệt."""

ROUTERS: list[tuple[str, APIRouter]] = [
    ("audit", audit),
    ("auth", auth),
    ("billing", billing),
    ("config", config),
    ("enrollment", enrollment),
    ("ingest", ingest),
    ("kb", kb),
    ("linh_vuc", linh_vuc),
    ("nhan_vat", nhan_vat),
    ("ops", ops),
    ("playbook", playbook),
    ("realestate", realestate),
    ("workspace", workspace),
]
"""Thêm một module có endpoint = thêm một dòng import + một dòng ở đây. Tên là tag OpenAPI."""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cai_dat = get_settings()
    app.state.pool = await create_pool(cai_dat.database_url)
    app.state.redis = create_redis(cai_dat.redis_url)
    try:
        yield
    finally:
        await app.state.pool.close()
        await app.state.redis.aclose()


def create_app(routers: list[tuple[str, APIRouter]] | None = None) -> FastAPI:
    """Dựng app. `routers=None` (mặc định, và là cách uvicorn gọi) = `ROUTERS`.

    Tham số `routers` là seam để test dựng app với module giả: một cổng chỉ có nghĩa
    khi nó đỏ được.
    """
    app = FastAPI(title="Odyssey Portal API", version="0.1.0", lifespan=lifespan)
    dang_ky_handler_loi(app)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    for ten, router in ROUTERS if routers is None else routers:
        app.include_router(router, prefix=TIEN_TO, tags=[ten])

    return app
