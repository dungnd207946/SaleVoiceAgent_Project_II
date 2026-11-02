"""`LoiPortal` mang được header HTTP — thứ `Retry-After` của 429 cần.

Trước bản này `nhip.py` phải ghi số giây vào CÂU CHỮ tiếng Việt vì «LoiPortal
chưa mang được header» — và backoff logic của adapter bên khách phải regex một
câu tiếng Việt để lấy con số. Header là hợp đồng máy đọc; câu chữ là cho người.
"""

import httpx
from fastapi import FastAPI

from portal.api.loi import LoiPortal, dang_ky_handler_loi


def _app() -> FastAPI:
    app = FastAPI()
    dang_ky_handler_loi(app)

    @app.get("/co-header")
    async def co_header() -> None:
        raise LoiPortal("RATE_LIMITED", 429, "chậm lại", headers={"Retry-After": "17"})

    @app.get("/khong-header")
    async def khong_header() -> None:
        raise LoiPortal("FORBIDDEN", 403, "không được")

    return app


async def _goi(duong: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(duong)


async def test_header_khai_trong_loi_di_ra_response():
    r = await _goi("/co-header")
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "17"
    assert r.json()["error"]["code"] == "RATE_LIMITED", "thân lỗi giữ nguyên khuôn — header là phần THÊM"


async def test_khong_khai_header_thi_nhu_cu():
    """Mọi LoiPortal hiện có trong repo không khai header — hành vi của chúng
    không được đổi một ly."""
    r = await _goi("/khong-header")
    assert r.status_code == 403
    assert "Retry-After" not in r.headers
    assert r.json()["error"]["code"] == "FORBIDDEN"
