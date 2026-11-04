"""create_app() — chỗ duy nhất dựng FastAPI app.

Pool sống theo `lifespan` của app, không phải singleton module-level: test dựng nhiều
app trong một tiến trình, singleton làm hai app dùng chung pool đã đóng.

⚠️ CHƯA CÓ ĐĂNG NHẬP: mọi route quản trị đang MỞ — chỉ chạy ở dev, không expose ra
Internet. Auth admin là việc làm sau (spec 2026-11-02 §7).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from portal.api.loi import dang_ky_handler_loi
from portal.core.config import get_settings
from portal.core.db.pool import create_pool
from portal.modules.catalog.router import ROUTER as catalog
from portal.modules.content.router import ROUTER as content
from portal.modules.customers.router import ROUTER as customers
from portal.modules.finance.router import ROUTER as finance
from portal.modules.kb.router import ROUTER as kb
from portal.modules.policies.router import ROUTER as policies
from portal.modules.products.router import ROUTER as products
from portal.modules.promotions.router import ROUTER as promotions
from portal.modules.reviews.router import ROUTER as reviews
from portal.modules.stores.router import ROUTER as stores

TIEN_TO = "/api/v1"
"""Tiền tố đặt ĐÚNG MỘT CHỖ. Module khai đường tương đối, app.py gắn tiền tố."""

ROUTERS: list[tuple[str, APIRouter]] = [
    ("catalog", catalog),
    ("products", products),
    ("promotions", promotions),
    ("finance", finance),
    ("policies", policies),
    ("content", content),
    ("stores", stores),
    ("customers", customers),
    ("reviews", reviews),
    ("kb", kb),
]
"""Thêm một module có endpoint = thêm một dòng import + một dòng ở đây. Tên là tag OpenAPI."""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.pool = await create_pool(get_settings().database_url)
    try:
        yield
    finally:
        await app.state.pool.close()


def create_app(routers: list[tuple[str, APIRouter]] | None = None) -> FastAPI:
    """Dựng app. `routers=None` (mặc định, và là cách uvicorn gọi) = `ROUTERS`."""
    app = FastAPI(title="Phone Shop API", version="0.2.0", lifespan=lifespan)
    dang_ky_handler_loi(app)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    for ten, router in ROUTERS if routers is None else routers:
        app.include_router(router, prefix=TIEN_TO, tags=[ten])

    return app
