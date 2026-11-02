"""CỔNG 1 — MỌI route đã đăng ký phải khai `action`. Thiếu ⇒ CI đỏ.

Spec tổng §3.5: nếu M2a ship endpoint không có chỗ khai quyền thì M2b thành "rà
toàn bộ endpoint và thêm kiểm tra" — kiểu retrofit đau nhất, và bỏ sót một
endpoint là một lỗ hổng không ai thấy.

CHỖ DỄ LÀM CỔNG NÀY THÀNH TRANG TRÍ: nếu route công khai chỉ đơn giản KHÔNG có
dependency thì cổng không phân biệt được "công khai có chủ ý" với "quên khai", và
mọi endpoint quên khai đều lọt. Vì vậy `require(None, ly_do=...)` cũng gắn marker.
"""

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from portal.api.app import create_app
from portal.core.auth.actions import ACTIONS
from portal.core.auth.require import KhaiQuyen, require
from tests.conftest import liet_ke_route

MIEN = {"/healthz", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def _khai_quyen_cua(route: APIRoute) -> KhaiQuyen | None:
    """Duyệt cây dependency của route, tìm marker do require() gắn."""
    con = list(route.dependant.dependencies)
    while con:
        d = con.pop()
        khai = getattr(d.call, "khai_quyen", None)
        if khai is not None:
            return khai
        con.extend(d.dependencies)
    return None


def _route_can_khai(app: FastAPI) -> list[tuple[str, APIRoute]]:
    """Dùng `liet_ke_route()` của tests/conftest.py — KHÔNG tự quét `app.routes`.

    Vì sao (xác minh trên FastAPI 0.141.1): `app.include_router()` KHÔNG duỗi
    phẳng route vào `app.routes` — nó đặt một `_IncludedRouter` không có thuộc
    tính `path`. Nên `[r for r in app.routes if isinstance(r, APIRoute)]` chỉ thấy
    route khai TRỰC TIẾP trên app, và **mọi route của 7 module đều vô hình**. Cổng
    này sẽ xanh vĩnh viễn — đúng loại "cổng trang trí" mà plan cấm.
    """
    return [(duong, rt) for duong, rt in liet_ke_route(app) if duong not in MIEN]


def test_moi_route_deu_khai_action():
    thieu = [
        f"{sorted(rt.methods)} {duong}" for duong, rt in _route_can_khai(create_app()) if _khai_quyen_cua(rt) is None
    ]
    assert not thieu, (
        "Route chưa khai quyền. Thêm `p: Principal = require(ACTIONS.X)` hoặc "
        "`_: None = require(None, ly_do='...')` vào chữ ký:\n  " + "\n  ".join(thieu)
    )


def test_cong_1_that_su_co_route_de_quet():
    """Cổng trên đúng một cách rỗng tuếch nếu app không có route nào ngoài MIEN.

    Hôm nay có 5 endpoint của module auth. Nếu con số này về 0 thì
    `test_moi_route_deu_khai_action` xanh mà không kiểm gì — và không ai biết.
    """
    assert len(_route_can_khai(create_app())) >= 5


def test_route_cong_khai_deu_co_ly_do():
    """Khai `None` mà không nói vì sao thì người rà M2b không đọc được ý định."""
    thieu_ly_do = []
    for duong, rt in _route_can_khai(create_app()):
        khai = _khai_quyen_cua(rt)
        if khai is not None and khai.action is None and not khai.ly_do:
            thieu_ly_do.append(f"{sorted(rt.methods)} {duong}")
    assert not thieu_ly_do, thieu_ly_do


def test_cong_1_bat_duoc_route_quen_khai_QUA_include_router():
    """Chứng minh cổng ĐỎ ĐƯỢC — và đỏ trên route gắn QUA `include_router()`.

    Đường `include_router` mới là đường thật: 7 module đều đi qua nó. Test synthetic
    khai route trực tiếp trên app sẽ xanh cả khi phép liệt kê bỏ sót router included,
    tức chứng minh sai điều cần chứng minh. Xem docstring `_route_can_khai`.
    """
    r = APIRouter()

    @r.get("/quen")
    async def quen() -> dict[str, bool]:
        return {"ok": True}

    app = FastAPI()
    app.include_router(r, prefix="/api/v1")

    thieu = [duong for duong, rt in _route_can_khai(app) if _khai_quyen_cua(rt) is None]
    assert thieu == ["/api/v1/quen"]


def test_cong_1_thay_ca_route_an_khoi_docs():
    """`include_in_schema=False` KHÔNG được là đường lách cổng.

    Đây là lý do phép liệt kê không dùng `app.openapi()["paths"]`: openapi duỗi
    phẳng router nhưng bỏ hẳn route ẩn, nên một endpoint ẩn quên khai quyền sẽ lọt.
    """
    r = APIRouter()

    @r.get("/an", include_in_schema=False)
    async def an() -> dict[str, bool]:
        return {"ok": True}

    app = FastAPI()
    app.include_router(r, prefix="/api/v1")

    assert [duong for duong, rt in _route_can_khai(app) if _khai_quyen_cua(rt) is None] == ["/api/v1/an"]


def test_cong_1_thay_ca_router_long_hai_tang():
    """Module có thể gom router con (ví dụ /du-an và /du-an/{id} ở hai file). Phép
    liệt kê phải xuống hết, không dừng ở tầng một."""
    trong = APIRouter()

    @trong.get("/sau")
    async def sau() -> dict[str, bool]:
        return {"ok": True}

    ngoai = APIRouter()
    ngoai.include_router(trong, prefix="/trong")

    app = FastAPI()
    app.include_router(ngoai, prefix="/api/v1")

    assert [duong for duong, rt in _route_can_khai(app) if _khai_quyen_cua(rt) is None] == ["/api/v1/trong/sau"]


def test_cong_1_khong_bao_sai_route_da_khai():
    r = APIRouter()

    @r.get("/da-khai")
    async def da_khai(p=require(ACTIONS.CATALOG_READ)) -> dict[str, bool]:
        return {"ok": True}

    app = FastAPI()
    app.include_router(r, prefix="/api/v1")

    assert [duong for duong, rt in _route_can_khai(app) if _khai_quyen_cua(rt) is None] == []


def test_cong_1_khong_bao_sai_route_cong_khai_co_chu_y():
    """Nửa còn lại của phép phân biệt: khai công khai KHÔNG được tính là quên khai."""
    r = APIRouter()

    @r.get("/mo")
    async def mo(_=require(None, ly_do="có lý do đàng hoàng")) -> dict[str, bool]:
        return {"ok": True}

    app = FastAPI()
    app.include_router(r, prefix="/api/v1")

    assert [duong for duong, rt in _route_can_khai(app) if _khai_quyen_cua(rt) is None] == []
