"""App khởi động và trả lời được, KHÔNG cần Postgres/Redis.

Vì sao không cần: create_app() nối pool trong `lifespan`, và test này dùng
ASGITransport gọi thẳng app mà không chạy lifespan. Nhờ vậy cổng "app import
được, route đăng ký đúng" chạy trong test-unit, không phải chờ container.
"""

import httpx
from fastapi import APIRouter

from portal.api.app import TIEN_TO, create_app
from tests.conftest import liet_ke_route

# Route hạ tầng của FastAPI/portal — không thuộc module nào nên không mang tiền tố.
NGOAI_LE = {"/healthz"}


async def test_healthz_tra_200():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/healthz")

    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_moi_route_module_deu_duoi_api_v1():
    """Tiền tố đặt MỘT chỗ (app.py), không để mỗi module tự viết '/api/v1' —
    một module quên là một endpoint nằm ngoài proxy '^/api/' của Vite.

    Quét bằng `liet_ke_route`, KHÔNG bằng `{r.path for r in app.routes}`: phép
    sau không thấy route nào gắn qua include_router() (xem docstring
    liet_ke_route), nên nó xanh kể cả khi một module viết sai tiền tố.
    """
    duong = {p for p, _ in liet_ke_route(create_app())} - NGOAI_LE

    sai = sorted(p for p in duong if not p.startswith(f"{TIEN_TO}/"))
    assert sai == [], f"route không mang tiền tố {TIEN_TO}: {sai}"


def test_app_py_that_su_ap_tien_to_chu_khong_phai_module_tu_viet():
    """Bơm một module giả và xác nhận đường cuối cùng = TIEN_TO + đường module khai.

    Đây là thứ làm cổng trên KHÔNG rỗng tuếch: hôm nay `modules/` trống nên tập
    quét chỉ có /healthz, và một phép assert trên tập rỗng thì luôn đúng.
    """
    gia = APIRouter()

    @gia.get("/toi-la-ai")
    async def _gia(): ...

    app = create_app(routers=[("gia", gia)])
    duong = {p for p, _ in liet_ke_route(app)}

    assert f"{TIEN_TO}/toi-la-ai" in duong


def test_phep_kiem_tien_to_do_duoc():
    """Một cổng không bao giờ đỏ được thì không phải cổng — nó là trang trí.

    Dựng đúng thứ mà cổng tồn tại để chặn — một route KHÔNG mang tiền tố — rồi
    khẳng định phép kiểm bắt được. Nếu ai đó sau này sửa app.py bỏ `prefix=`,
    `test_moi_route_module_deu_duoi_api_v1` sẽ đỏ chứ không im lặng cho qua.
    """
    lac = APIRouter()

    @lac.get("/v2/lac-de")
    async def _lac(): ...

    app = create_app(routers=[])
    app.include_router(lac)  # ← quên prefix, đúng lỗi cần bắt

    duong = {p for p, _ in liet_ke_route(app)} - NGOAI_LE
    sai = sorted(p for p in duong if not p.startswith(f"{TIEN_TO}/"))

    assert sai == ["/v2/lac-de"]
