"""Chín endpoint của M10. BA cổng xác thực khác nhau, cố ý không dùng chung:

    /agent/runtime-credentials  → Bearer api_key của workspace     (máy gọi)
    /agent/admin/*    → header X-Platform-Admin-Token      (người gọi)
    /agent/keys       → phiên + WORKSPACE_ADMIN            (owner workspace gọi)

Sáu endpoint Ở FILE NÀY khai `require(None, ly_do=...)` để qua cổng
test_moi_route_khai_action.py của M2a. Chúng cố ý KHÔNG dùng 13 action của PQ_01,
vì 13 nhóm đó là quyền TRONG một workspace còn hai vai này ở ngoài workspace —
xem core/auth/quan_tri_nen_tang.py.

Ba endpoint `/agent/keys` thì NGƯỢC LẠI — chúng ở trong một workspace, nên chúng
dùng action thứ 13 (`workspace.admin`, nhãn PQ_01: "Khoá API · Thành viên · Cài
đặt workspace"). Chúng sống ở `router_tenant.py`; xem docstring file đó.

`/agent/runtime-credentials` KHÔNG nhận cookie phiên. Trộn hai đường xác thực là
mở một đường lấy credential hạ tầng bằng phiên của một người dùng workspace.
"""

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Header, Path, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from redis.asyncio import Redis

from portal.core.auth.quan_tri_nen_tang import ACTOR_QUAN_TRI, require_quan_tri_nen_tang
from portal.core.auth.require import lay_pool, lay_redis, require
from portal.core.config import get_settings
from portal.modules.enrollment import contracts, gateway_docs, loi, service
from portal.modules.enrollment.ha_tang import HaTang, lay_ha_tang
from portal.modules.enrollment.router_tenant import ROUTER_TENANT

ROUTER = APIRouter(prefix="/agent", tags=["agent"])
"""KHÔNG có `/api/v1` ở đây — create_app() gắn tiền tố đó lúc include_router."""

ROUTER.include_router(ROUTER_TENANT)
"""⚠️ ĐỪNG XOÁ. `api/app.py::ROUTERS` chỉ gắn biến `ROUTER` của `router.py`,
nên `router_tenant.py` tự nó vô hình: ba endpoint `/agent/keys` sẽ
không lên và KHÔNG có lỗi nào nổ — chỉ là 404 ở chỗ không ai ngờ."""

_LY_DO_AGENT = "xác thực bằng api_key của workspace, không phải phiên người dùng"
_LY_DO_ADMIN = "xác thực bằng token quản trị nền tảng, không phải phiên workspace"

# `lay_ha_tang` chuyển sang `ha_tang.py` để router_tenant.py dùng chung mà không
# tạo vòng import. Vẫn tái xuất ở đây vì chỗ khác có thể đang import từ router.
__all__ = ["ROUTER", "lay_ha_tang"]


@ROUTER.post("/runtime-credentials", response_model=contracts.RuntimeCredentialsOut)
async def lay_runtime_credentials(
    authorization: Annotated[str, Header()] = "",
    _: None = require(None, ly_do=_LY_DO_AGENT),
    pool: asyncpg.Pool = Depends(lay_pool),
    redis: Redis = Depends(lay_redis),
    ha_tang: HaTang = Depends(lay_ha_tang),
) -> contracts.RuntimeCredentialsOut:
    """⚠️ Response CHỨA MẬT KHẨU. Không log, không trace, không APM span (G-10)."""
    if not authorization.startswith("Bearer "):
        raise loi.khoa_khong_hop_le()
    return await service.lay_runtime_credentials(pool, redis, ha_tang, authorization.removeprefix("Bearer ").strip())


@ROUTER.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def ghi_feedback(
    body: contracts.FeedbackIn,
    authorization: Annotated[str, Header()] = "",
    _: None = require(None, ly_do=_LY_DO_AGENT),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> Response:
    """BE của agent pod gọi bằng CHÍNH `AGENT_API_KEY` nó đã có từ `/runtime-credentials`
    — không phải một khoá riêng cho feedback. Tenant suy từ khoá, `body` không có
    trường `tenant_id` (xem `contracts.FeedbackIn`)."""
    if not authorization.startswith("Bearer "):
        raise loi.khoa_khong_hop_le()
    await service.ghi_feedback(pool, authorization.removeprefix("Bearer ").strip(), body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@ROUTER.post(
    "/admin/tenants/{tenant_id}/provision",
    response_model=contracts.KhoaMoiOut,
    status_code=status.HTTP_201_CREATED,
)
async def cap_phat_workspace(
    tenant_id: Annotated[str, Path(pattern=contracts.TENANT_ID_PATTERN)],
    _: None = require(None, ly_do=_LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
    pool: asyncpg.Pool = Depends(lay_pool),
    ha_tang: HaTang = Depends(lay_ha_tang),
) -> contracts.KhoaMoiOut:
    """Khoá thô trả về ĐÚNG MỘT LẦN, ở đây. Không endpoint nào đọc lại được.

    ĐỔI Ở `0941` từ `POST /admin/deployments` (tenant_id trong body): endpoint không
    còn tạo hàng deployment nào — bảng đã bỏ — nên tên cũ nói sai việc nó làm. Cùng
    khuôn `/admin/tenants/{id}/keys` và `/admin/tenants/{id}/rotate-secrets` đã có.
    """
    return await service.cap_phat(pool, ha_tang, tenant_id, "", ACTOR_QUAN_TRI)


@ROUTER.get("/admin/tenants", response_model=list[contracts.TenantVanHanhOut])
async def liet_ke_tenant_van_hanh(
    _: None = require(None, ly_do=_LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[contracts.TenantVanHanhOut]:
    """Màn vận hành xuyên tenant. ĐỔI Ở `0941` từ `GET /admin/deployments` — nguồn hàng
    chuyển từ `control.deployments` (đã bỏ) sang `control.tenants`."""
    return await service.liet_ke_tenant_van_hanh(pool)


@ROUTER.post(
    "/admin/tenants/{tenant_id}/keys",
    response_model=contracts.KhoaMoiOut,
    status_code=status.HTTP_201_CREATED,
)
async def phat_khoa(
    tenant_id: Annotated[str, Path(pattern=contracts.TENANT_ID_PATTERN)],
    _: None = require(None, ly_do=_LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> contracts.KhoaMoiOut:
    """Xoay khoá không gián đoạn: phát mới → nạp vào pod → thu hồi cũ.

    ĐƯỜNG DẪN ĐỔI Ở `0940` (`/admin/deployments/{id}/keys` → đây): khoá treo thẳng
    vào tenant, nên `deployment_id` không còn định danh được thứ cần phát khoá cho.
    Frontend không gọi endpoint `/admin/*` nào (`features/platform/api.ts:53` chỉ
    dùng `/agent/keys`), nên đổi URL ở đây không phá màn hình nào.

    `pattern` trên path param: `tenant_id` đi thẳng vào FK, và một chuỗi lạ nên
    dừng ở 422 nói rõ định dạng chứ không ở 404 sau một vòng chạm DB.
    """
    return await service.phat_khoa_them(pool, tenant_id, ACTOR_QUAN_TRI)


@ROUTER.delete("/admin/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def thu_hoi_khoa(
    key_id: int,
    _: None = require(None, ly_do=_LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> Response:
    await service.thu_hoi_khoa(pool, key_id, ACTOR_QUAN_TRI)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@ROUTER.post("/admin/tenants/{tenant_id}/rotate-secrets")
async def xoay_bi_mat(
    tenant_id: str,
    _: None = require(None, ly_do=_LY_DO_ADMIN),
    __: None = require_quan_tri_nen_tang(),
    pool: asyncpg.Pool = Depends(lay_pool),
    ha_tang: HaTang = Depends(lay_ha_tang),
) -> dict[str, int]:
    """Pod tự nhận bí mật mới ở lần làm mới TTL kế tiếp. Kết nối đang mở không đứt."""
    return {"secret_version": await service.xoay_bi_mat(pool, ha_tang, tenant_id, ACTOR_QUAN_TRI)}


# ─── Tài liệu Swagger của gateway WS — công khai ─────────────────────────────

_LY_DO_TAI_LIEU = "tài liệu công khai của gateway — bàn giao cho dev bên khách cùng lúc với khoá"


@ROUTER.get("/gateway/docs", include_in_schema=False)
async def trang_tai_lieu_gateway(_: None = require(None, ly_do=_LY_DO_TAI_LIEU)) -> HTMLResponse:
    """Swagger UI riêng của gateway, KHÔNG dùng `/docs` của cả portal.

    Trang đó liệt kê mọi endpoint nội bộ, và ở dev nó còn không mở được từ origin
    của FE — vite chỉ proxy `^/api/`. Cùng lý lẽ đã ghi ở `ingest/router.py`.
    """
    return HTMLResponse(gateway_docs.trang())


@ROUTER.get("/gateway/openapi.json", include_in_schema=False)
async def spec_gateway(_: None = require(None, ly_do=_LY_DO_TAI_LIEU)) -> JSONResponse:
    """Spec cho trang docs fetch qua đường tương đối, và cũng là đường tải về.

    `charset=utf-8` PHẢI khai tường minh: Starlette chỉ tự thêm nó cho media type
    `text/*`, nên `JSONResponse` gửi `application/json` trần. Bình thường trình
    duyệt vẫn đoán UTF-8 cho JSON, nhưng `Content-Disposition: inline` dưới đây
    đẩy nó sang chế độ hiển thị-tệp và ở đó nó sniff theo locale — spec đầy tiếng
    Việt nên ra mojibake («Giao thá»©c WebSocket»). Đã bị báo lỗi thật trên UAT.
    """
    ten_tep = gateway_docs.ten_tep_spec()
    return JSONResponse(
        gateway_docs.spec(get_settings().gateway_ws_base_url),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{ten_tep}"'},
    )
