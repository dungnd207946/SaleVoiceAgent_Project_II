"""Bốn endpoint control-plane của cổng nạp — phiên + `WORKSPACE_ADMIN`.

VÌ SAO FILE RIÊNG: hai cổng xác thực khác nhau nằm chung một file thì lần sau
người đọc không còn thấy ranh giới, và ranh giới đó chính là thứ `router.py` cảnh
báo phải giữ. Cùng khuôn `enrollment/router_tenant.py`.

⚠️ File này tự nó VÔ HÌNH với `api/app.py::ROUTERS` (nó chỉ gắn biến `ROUTER`
của `router.py`). Nó sống nhờ đúng một dòng `ROUTER.include_router(ROUTER_TENANT)`
ở `router.py`. Đừng xoá dòng đó.

TENANT KHÔNG ĐẾN TỪ REQUEST. Nó là `p.tenant_id` — đã xác thực qua một hàng
`control.memberships` còn hiệu lực. `control.ingest_tokens` không có RLS đỡ phía
sau (schema `control` chưa từng có), nên đây là chỗ DUY NHẤT cưỡng chế cách ly cho
đường này.

Cả bốn dùng action thứ 13 (`workspace.admin`), nhãn PQ_01: «Khoá API · Thành viên
· Cài đặt workspace». Token nạp là một loại khoá API — cùng vai, cùng quyền.
"""

import asyncpg
from fastapi import APIRouter, Depends, Response, status

from portal.api.loi import LoiPortal
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.config import get_settings
from portal.modules.ingest import contracts, service

ROUTER_TENANT = APIRouter()


def _goc() -> str:
    """Gốc URL công khai của portal.

    Dùng lại `public_base_url` (đã có sẵn cho link ảnh agent) chứ không thêm một
    biến cấu hình thứ hai chỉ vào cùng một host: hai biến cho một giá trị là hai
    chỗ để đặt lệch nhau, và lệch ở đây nghĩa là bàn giao nhầm môi trường.

    RỖNG ⇒ trả đường TƯƠNG ĐỐI. Nó vẫn đúng khi mở từ chính portal, và nó nói
    thật rằng chưa ai cấu hình host công khai — khác hẳn việc bịa `localhost`,
    thứ chạy được trên máy dev rồi đi vào email gửi cho khách.
    """
    return get_settings().public_base_url.rstrip("/")


def _diem_nap() -> str:
    """URL đầy đủ khách POST vào — thứ bàn giao cho đội kỹ thuật bên kia."""
    return f"{_goc()}/api/v1/ingest/{contracts.LINH_VUC}/{contracts.PHIEN_BAN}/events"


def _docs_url() -> str:
    """Swagger của RIÊNG cổng nạp — `router.py` phục vụ tại `…/{v}/docs`.

    Trước 2026-08-21 nó trỏ `{goc}/docs#/ingest/nap` — Swagger của CẢ portal,
    neo hash vào operation. Hai lỗi một lúc: ① với `public_base_url` rỗng (dev)
    URL thành `/docs` tương đối, mở từ origin của FE thì vite chỉ proxy
    `^/api/` nên nó rơi vào SPA — «màn tài liệu API chưa có gì» đúng nghĩa đen;
    ② trang đó bày MỌI endpoint nội bộ của portal cho dev bên thứ ba. Trang
    scoped nằm DƯỚI `/api/v1` nên đi qua proxy dev lẫn reverse-proxy prod,
    và chỉ chứa ba route hợp đồng.
    """
    return f"{_goc()}/api/v1/ingest/{contracts.LINH_VUC}/{contracts.PHIEN_BAN}/docs"


@ROUTER_TENANT.get("/tong-quan", response_model=contracts.TongQuanOut)
async def tong_quan(
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> contracts.TongQuanOut:
    """Điểm nạp · ba con số 24 giờ · danh sách token.

    Trả về kể cả khi chưa có token nào — màn hình phải bàn giao được điểm nạp
    trước khi có token, cùng lý lẽ `DanhSachKhoaOut` của M10.
    """
    return await service.tong_quan(pool, p.tenant_id, diem_nap=_diem_nap(), docs_url=_docs_url())


@ROUTER_TENANT.post("/keys", response_model=contracts.TokenOut, status_code=status.HTTP_201_CREATED)
async def tao_token(
    than: contracts.TaoTokenIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> contracts.TokenOut:
    """Trả LUÔN chuỗi thô. Không có bước «chỉ hiện một lần» như khoá agent —
    token này xem lại được bất cứ lúc nào ngay trong bảng.

    `created_by` là `user_id`, KHÔNG phải email: `Principal` không mang email, và
    kéo nó vào chỉ để ghi một cột không ai đọc trên giao diện (bảng token có đúng
    hai cột) là thêm một lượt truy vấn cho không ai cả."""
    try:
        return await service.tao_token(pool, p.tenant_id, than.label, p.user_id)
    except asyncpg.UniqueViolationError as e:
        raise LoiPortal("TEN_TRUNG", 409, f"Đã có token tên «{than.label}»") from e


@ROUTER_TENANT.delete("/keys/{id_}", status_code=status.HTTP_204_NO_CONTENT)
async def xoa_token(
    id_: int,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> Response:
    """XOÁ HẲN, không có trạng thái vô hiệu.

    Một hàng «đã thu hồi» hoặc còn giữ chuỗi thô (bí mật vô dụng nằm chờ rò) hoặc
    không giữ (hàng rỗng không trả lời câu hỏi nào). Ai xoá token nào là việc của
    Nhật ký, không phải của bảng này — và từ 2026-08-15 câu đó là THẬT: `service`
    ghi `ingest.token_xoa` vào `control.audit_log`. Trước đó nó chỉ là một lời hứa
    trong docstring, cùng lời hứa mà `contracts.TokenOut` cũng viện dẫn.
    """
    if not await service.xoa_token(pool, p.tenant_id, id_, p.user_id):
        raise LoiPortal("TOKEN_NOT_FOUND", 404, "Không tìm thấy token")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@ROUTER_TENANT.get("/loi", response_model=contracts.TrangLoiOut)
async def liet_ke_loi(
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> contracts.TrangLoiOut:
    """Bản ghi bị từ chối — đường phản hồi cho dev BÊN KHÁCH.

    Dưới schema cố định, sai một tên trường là bản ghi bị từ chối; đây là chỗ duy
    nhất họ thấy được cái gì sai. Nên `lyDo` phải đủ để tự sửa, không phải một mã
    HTTP — xem `hop_dong._enum`.
    """
    return await service.liet_ke_loi(pool, p.tenant_id)
