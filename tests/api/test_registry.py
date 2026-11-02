"""`liet_ke_route` — nền của các cổng quét route."""

from fastapi import APIRouter, FastAPI

from tests.conftest import liet_ke_route

# ─── liet_ke_route ──────────────────────────────────────────────────────────
# Hai test dưới đây là nền của Cổng 1 (T11). Chúng neo lại đúng hai điều mà một
# phép quét ngây thơ làm sai — xem docstring của liet_ke_route(). Đã xác minh trên
# FastAPI 0.141.1: `app.routes` chứa `_IncludedRouter` KHÔNG có thuộc tính `path`,
# nên `{r.path for r in app.routes}` không thấy route nào của module. Cổng 1 dựng
# trên phép quét đó sẽ xanh vĩnh viễn.


def _app_hai_tang() -> FastAPI:
    """App có: route trực tiếp · router lồng · route ẩn khỏi /docs."""
    trong = APIRouter()

    @trong.get("/long")
    async def _long(): ...

    ngoai = APIRouter()

    @ngoai.get("/hien")
    async def _hien(): ...

    @ngoai.get("/an", include_in_schema=False)
    async def _an(): ...

    ngoai.include_router(trong, prefix="/nest")

    app = FastAPI()

    @app.get("/healthz")
    async def _healthz(): ...

    app.include_router(ngoai, prefix="/api/v1")
    return app


def test_liet_ke_route_duoi_phang_router_long_nhau():
    duong = {p for p, _ in liet_ke_route(_app_hai_tang())}

    assert duong == {"/healthz", "/api/v1/hien", "/api/v1/an", "/api/v1/nest/long"}


def test_liet_ke_route_khong_bo_route_an_khoi_docs():
    """`include_in_schema=False` là "ẩn khỏi /docs", KHÔNG phải "miễn kiểm quyền".

    Dùng app.openapi()["paths"] cho Cổng 1 thì route ẩn biến mất khỏi tầm quét —
    tức là một đường lách quyền chỉ cần thêm một tham số.
    """
    app = _app_hai_tang()
    duong = {p for p, _ in liet_ke_route(app)}

    assert "/api/v1/an" in duong
    assert "/api/v1/an" not in app.openapi()["paths"]
