"""Cổng nạp dữ liệu ngoài — HAI cổng xác thực, cố ý không dùng chung.

    POST …/events            → Bearer token nạp        (hệ thống bên KHÁCH gọi)
    POST …/manifest          → Bearer token nạp        (job đối soát bên KHÁCH gọi)
    GET  …/whoami            → Bearer token nạp        (adapter kiểm ĐÍCH của token)
    GET|POST|DELETE …/keys   → phiên + WORKSPACE_ADMIN  (quản trị workspace gọi)
    GET  …/tong-quan · …/loi → phiên + WORKSPACE_ADMIN

Ba endpoint control-plane sống ở `router_tenant.py` — xem docstring file đó để
biết vì sao tách.

`POST …/events` khai `require(None, ly_do=…)` để qua cổng
`tests/api/test_moi_route_khai_action.py`: nó cố ý KHÔNG dùng 13 action của
PQ_01, vì 13 nhóm đó là quyền của một NGƯỜI trong workspace, còn đây là một hệ
thống bên thứ ba. Quyền của nó là hằng số, gắn vào chính token — xem `0927`.

⚠️ `POST …/events` KHÔNG nhận cookie phiên. Trộn hai đường xác thực là mở một
đường ghi vào `tenant_data` bằng phiên của một người dùng đang mở portal ở tab
khác — đúng lớp lỗi CSRF mà cookie `SameSite` chỉ chặn được một phần.
"""

from functools import lru_cache
from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, Header, Query
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRoute
from redis.asyncio import Redis

from portal.api.loi import LoiPortal
from portal.core.auth.require import lay_pool, lay_redis, require
from portal.core.config import get_settings
from portal.modules.ingest import contracts, nhip, service, tai_lieu
from portal.modules.ingest.router_tenant import ROUTER_TENANT

ROUTER = APIRouter(prefix=f"/ingest/{contracts.LINH_VUC}/{contracts.PHIEN_BAN}", tags=["ingest"])
"""KHÔNG có `/api/v1` ở đây — `create_app()` gắn tiền tố đó lúc `include_router`.

Lĩnh vực và phiên bản NẰM TRÊN ĐƯỜNG DẪN, không trong thân request:
  · Lĩnh vực — đường dẫn ĐẶT TÊN lời hứa «token của BĐS không với sang lĩnh vực
    khác»; thứ THI HÀNH nó là `vertical=` truyền vào `service.xac_thuc`. Hai việc
    khác nhau, và bản đầu của file này nhầm chúng làm một: đường dẫn mang tên
    lĩnh vực nhưng không handler nào so nó với `ingest_tokens.vertical` (vá
    2026-08-14). Thêm một router lĩnh vực khác ⇒ nhớ truyền ĐÚNG lĩnh vực của nó.
  · Phiên bản — hợp đồng cố định nghĩa là N adapter ngoài kia đang code vào nó.
    `/v2/` sau này sống song song `/v1/` thay vì làm gãy tất cả cùng lúc.
"""

ROUTER.include_router(ROUTER_TENANT)

_LY_DO = "xác thực bằng token nạp của hệ thống bên khách, không phải phiên người dùng"


def _token_khong_hop_le() -> LoiPortal:
    """MỘT mã cho cả «thiếu header» lẫn «token sai».

    Phân biệt chúng là cho không một máy dò biết chuỗi nào tồn tại — cùng lý lẽ
    `sai_dang_nhap()` của `api/loi.py`.
    """
    return LoiPortal("INVALID_INGEST_TOKEN", 401, "Token nạp dữ liệu không hợp lệ hoặc đã bị xoá")


@ROUTER.post(
    "/events",
    summary="Đẩy một lô bản ghi",
    response_model=contracts.LoNapOut,
    description=tai_lieu.mo_ta_events(),
    openapi_extra=tai_lieu.vi_du_events(),
)
async def nap(
    lo: contracts.LoNapIn,
    authorization: Annotated[str, Header()] = "",
    dryRun: Annotated[bool, Query()] = False,  # noqa: N803 — tên query param của hợp đồng, không phải biến Python
    _: None = require(None, ly_do=_LY_DO),
    pool: asyncpg.Pool = Depends(lay_pool),
    redis: Redis = Depends(lay_redis),
) -> contracts.LoNapOut:
    """Nhận một lô. Trả `200` kèm kết quả TỪNG bản ghi.

    KHÔNG trả `4xx` khi có bản ghi hỏng: một bản ghi sai trong lô 500 không phải
    là «request hỏng», và trả `422` cho cả lô buộc bên khách phải đoán cái nào.
    Mã HTTP nói về REQUEST; `results` nói về từng bản ghi.

    `?dryRun=true` — validate và trả cùng hình dạng `results`, không ghi gì. Xem
    `service.nap_lo`. Nó VẪN kiểm token: dryRun không phải cửa sau cho request
    không xác thực.
    """
    hang = await service.xac_thuc(
        pool,
        authorization,
        vertical=contracts.LINH_VUC,
        redis=redis,
        cua=nhip.CUA_EVENTS,
        so_lan=get_settings().ingest_nhip_events_moi_phut,
        giay=60,
    )
    if hang is None:
        raise _token_khong_hop_le()
    return await service.nap_lo(pool, tenant_id=hang["tenant_id"], lo=lo, dry_run=dryRun)


@ROUTER.get(
    "/whoami",
    summary="Token này thuộc workspace nào",
    response_model=contracts.WhoamiOut,
    description=(
        "Token này thuộc workspace nào — gọi để kiểm ĐÍCH trước khi đẩy dữ liệu.\n\n"
        "Token ghim workspace tại lúc tạo; muốn đổ dữ liệu sang workspace khác thì "
        "tạo token MỚI trong workspace đó (kiểm tra bộ chuyển workspace đang đứng "
        "đúng chỗ) rồi thay vào adapter. Adapter nên gọi endpoint này mỗi lượt chạy "
        "và hiện tên workspace cho người vận hành."
    ),
)
async def whoami(
    authorization: Annotated[str, Header()] = "",
    _: None = require(None, ly_do=_LY_DO),
    pool: asyncpg.Pool = Depends(lay_pool),
    redis: Redis = Depends(lay_redis),
) -> contracts.WhoamiOut:
    """Dùng CHUNG cửa nhịp với `/events` (một lượt whoami trừ một suất events):
    lời gọi hợp lệ là 1–2 lần mỗi lượt sync + vài lần mở trang CMS — không đáng
    một cửa sổ riêng, và kẻ quay whoami để dò token thì bị chính cửa events chặn.
    """
    hang = await service.xac_thuc(
        pool,
        authorization,
        vertical=contracts.LINH_VUC,
        redis=redis,
        cua=nhip.CUA_EVENTS,
        so_lan=get_settings().ingest_nhip_events_moi_phut,
        giay=60,
    )
    if hang is None:
        raise _token_khong_hop_le()
    return await service.toi_la_ai(pool, hang["tenant_id"])


@ROUTER.post(
    "/manifest",
    summary="Đối soát bằng bản kê",
    response_model=contracts.DoiSoatOut,
    description=tai_lieu.mo_ta_manifest(),
)
async def doi_soat(
    ban_ke: contracts.BanKeIn,
    authorization: Annotated[str, Header()] = "",
    dryRun: Annotated[bool, Query()] = False,  # noqa: N803 — tên query param của hợp đồng, không phải biến Python
    _: None = require(None, ly_do=_LY_DO),
    pool: asyncpg.Pool = Depends(lay_pool),
    redis: Redis = Depends(lay_redis),
) -> contracts.DoiSoatOut:
    """Bản kê đối soát của MỘT thực thể — nửa còn lại của «đẩy khi có thay đổi».

    Không có nó, một sự kiện `delete` bị rơi là im lặng VĨNH VIỄN, và nó im theo
    hướng nguy hiểm nhất: căn đã bán ở lại «còn hàng» và agent nói với khách là
    còn. Đúng bug `NT2-1408`.

    Response CHÍNH LÀ yêu cầu đẩy lại: `externalIdLech` là danh sách bên khách cần
    gửi lại. Không có webhook gọi ngược — họ đang đứng chờ response này.

    ⚠️ Bản kê phải ĐẦY ĐỦ cho thực thể đó. Gửi một nửa sẽ làm phần còn lại bị đánh
    dấu nghi mất tích, nên lô quá trần bị từ chối thẳng thay vì nhận một phần.
    """
    hang = await service.xac_thuc(
        pool,
        authorization,
        vertical=contracts.LINH_VUC,
        redis=redis,
        cua=nhip.CUA_MANIFEST,
        so_lan=get_settings().ingest_nhip_manifest_moi_gio,
        giay=3600,
    )
    if hang is None:
        raise _token_khong_hop_le()
    try:
        return await service.doi_soat_ban_ke(
            pool, tenant_id=hang["tenant_id"], ban_ke=ban_ke, token_id=hang["id"], dry_run=dryRun
        )
    except service.BanKeKhongHopLe as e:
        raise LoiPortal("BAN_KE_KHONG_HOP_LE", 422, str(e)) from e


# ─── Tài liệu của CHÍNH cổng nạp — Swagger riêng + spec tải được ─────────────

_LY_DO_TAI_LIEU = "tài liệu công khai của cổng nạp — bàn giao cho dev bên khách trước cả khi họ có token"

_ROUTE_HOP_DONG = ("nap", "whoami", "doi_soat")
"""Ba route thuộc HỢP ĐỒNG với hệ thống bên khách. Các route control-plane
(`router_tenant.py`) cố ý đứng NGOÀI spec này: nó vào tay dev bên thứ ba, bày
`/keys`/`/tong-quan`/`/loi` ra đó là mô tả một bề mặt họ không gọi được. Đây
cũng là lý do `docsUrl` thôi trỏ vào `/docs` của CẢ portal (trước 2026-08-21):
trang đó liệt kê mọi endpoint nội bộ, và ở dev nó còn không mở được từ origin
của FE — vite chỉ proxy `^/api/`, còn `/docs` trần rơi vào SPA."""


@lru_cache(maxsize=1)
def _spec_cong_khai() -> dict[str, Any]:
    """OpenAPI CHỈ của ba route hợp đồng — sinh một lần rồi cache.

    Đường dẫn trong spec ghép tiền tố `/api/v1` TƯỜNG MINH: route ở đây khai
    không tiền tố (`create_app()` gắn lúc `include_router`), nhưng spec là thứ
    bàn giao cho khách nên phải mang URL đầy đủ — cùng lệ `_diem_nap()` của
    `router_tenant.py` (hardcode tiền tố trong CHUỖI HIỂN THỊ thì được, trong
    đăng ký route thì không).

    Ném ngay khi lọc thiếu route: một lần đổi tên hàm handler mà quên sổ
    `_ROUTE_HOP_DONG` là spec âm thầm mất một endpoint — thà 500 to tiếng.
    """
    routes = [r for r in ROUTER.routes if isinstance(r, APIRoute) and r.name in _ROUTE_HOP_DONG]
    if {r.name for r in routes} != set(_ROUTE_HOP_DONG):
        raise RuntimeError(
            f"spec cổng nạp lọc được {sorted(r.name for r in routes)} — "
            f"lệch sổ {sorted(_ROUTE_HOP_DONG)}; ai đó đổi tên handler mà quên sổ?"
        )
    spec = get_openapi(
        title="NobleX Agent Platform — Cổng nạp dữ liệu Bất động sản",
        version=contracts.PHIEN_BAN,
        description=(
            "API cho hệ thống của bạn (CRM/ERP) **đẩy** dữ liệu sang NobleX Agent Platform.\n\n"
            "- Xác thực: `Authorization: Bearer <token>` — token do quản trị workspace phát "
            "ở màn *Kiến thức → Nạp qua API*.\n"
            "- Bắt đầu bằng `GET /whoami` để chắc token đang trỏ đúng workspace.\n"
            "- Đẩy dữ liệu theo lô qua `POST /events`; đối soát định kỳ qua `POST /manifest`.\n"
            "- Schema cố định, trường lạ bỏ qua im lặng; "
            f"mỗi lô tối đa {contracts.TRAN_LO} bản ghi; "
            "cả hai endpoint ghi đều có `?dryRun=true` để diễn tập an toàn."
        ),
        routes=routes,
    )
    spec["paths"] = {f"/api/v1{duong}": muc for duong, muc in spec["paths"].items()}
    return spec


@ROUTER.get("/docs", include_in_schema=False)
async def trang_tai_lieu(_: None = require(None, ly_do=_LY_DO_TAI_LIEU)) -> HTMLResponse:
    """Swagger UI của RIÊNG cổng nạp — đích mới của `docsUrl`.

    `openapi_url` TƯƠNG ĐỐI («openapi.json»): trình duyệt phân giải theo URL
    trang (`…/v1/docs` → `…/v1/openapi.json`), nên hàm này không phải biết
    tiền tố `/api/v1` mà `create_app()` sẽ gắn.
    """
    return get_swagger_ui_html(openapi_url="openapi.json", title="NobleX Agent Platform — Tài liệu API cổng nạp")


@ROUTER.get("/openapi.json", include_in_schema=False)
async def spec_tai_ve(_: None = require(None, ly_do=_LY_DO_TAI_LIEU)) -> JSONResponse:
    """Spec cho Swagger UI đọc — trang `…/docs` fetch nó qua đường tương đối.

    Cũng là đường tải spec cho dev bên khách (link `openapi.json` dưới tiêu đề
    trang docs; import vào Postman/codegen). Từng có nút «Tải OpenAPI» riêng ở
    màn Nạp qua API kèm `TongQuanOut.specUrl` — bỏ cùng ngày thêm (người dùng
    chốt 2026-08-21): hai đường cho cùng một tệp là thừa. `Content-Disposition:
    inline` + `filename` giữ lại — mở trong tab vẫn xem được, «tải về» nhận đúng
    tên tệp thay vì `openapi.json` vô danh.
    """
    # «noblex», không «odyssey»: tệp này rơi vào máy dev bên khách — tên đối
    # ngoại là NobleX Agent Platform, Odyssey chỉ là tên dự án nội bộ.
    # `charset=utf-8` tường minh: Starlette chỉ tự thêm cho media type `text/*`,
    # và `Content-Disposition: inline` ngay dưới đẩy trình duyệt sang chế độ
    # hiển thị-tệp, nơi nó sniff encoding theo locale — spec đầy tiếng Việt nên
    # ra mojibake. Cùng lỗi đã bị báo trên endpoint spec của gateway.
    ten_tep = f"noblex-ingest-{contracts.LINH_VUC}-{contracts.PHIEN_BAN}.openapi.json"
    return JSONResponse(
        _spec_cong_khai(),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{ten_tep}"'},
    )
