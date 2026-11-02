"""Tạo nhân vật đi QUA FastAPI (multipart thật) — thứ test gọi-thẳng-handler không phủ.

Bug đã gặp (e2e 2026-10-07): ba tham số form dùng chung MỘT `Form(...)` nên FastAPI gắn
kiểu `bool` của `dongY` lên cả `ten` ⇒ mọi lần tạo trả 422 «ten: valid boolean», trong khi
`test_quy_trinh.py` (gọi thẳng `router.tao(...)`) vẫn xanh. Bài này dựng app chỉ gồm ROUTER
của module, thay hai dependency (phiên + pool) — phần còn lại là FastAPI thật.
"""

import httpx
from fastapi import FastAPI

from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool
from portal.modules.nhan_vat import router

from .conftest import TENANT

_P = Principal(user_id="u_seed_test", tenant_id=TENANT, role="Quản trị", actions=frozenset())


def _app(api_pool) -> FastAPI:
    app = FastAPI()
    app.include_router(router.ROUTER, prefix="/api/v1")
    route = next(r for r in router.ROUTER.routes if r.path == "/nhan-vat" and "POST" in r.methods)
    dep_p = next(d for d in route.dependant.dependencies if d.name == "p")
    app.dependency_overrides[dep_p.call] = lambda: _P
    app.dependency_overrides[lay_pool] = lambda: api_pool
    return app


async def test_tao_qua_multipart_that(api_pool, seed_nv, kho_tep, env_nv):
    app = _app(api_pool)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/v1/nhan-vat",
            data={"ten": "Chị Lan", "nguon": "video", "dongY": "true"},
            files={"tep": ("lan.mp4", b"VIDEO", "video/mp4"), "tepTay": ("tay.mp4", b"TAY", "video/mp4")},
        )
    assert r.status_code == 201, r.text
    o = r.json()
    assert (o["ten"], o["nguon"], o["trangThai"]) == ("Chị Lan", "video", "dung")


async def test_khong_gui_tep_tay_van_tao_duoc(api_pool, seed_nv, kho_tep, env_nv):
    app = _app(api_pool)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/v1/nhan-vat",
            data={"ten": "Anh Minh", "nguon": "video", "dongY": "true"},
            files={"tep": ("minh.mp4", b"VIDEO", "video/mp4")},
        )
    assert r.status_code == 201, r.text
