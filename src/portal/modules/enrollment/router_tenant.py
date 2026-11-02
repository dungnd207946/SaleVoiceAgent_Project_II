"""Ba endpoint tenant-scoped của M10 — CỔNG THỨ BA của module.

    /agent/runtime-credentials  → Bearer api_key            (pod agent gọi)
    /agent/admin/*    → X-Platform-Admin-Token    (admin nền tảng gọi)
    /agent/keys       → phiên + WORKSPACE_ADMIN   (owner workspace gọi)  ← file này

VÌ SAO FILE RIÊNG CHỨ KHÔNG THÊM VÀO router.py: ba cổng xác thực khác nhau nằm
chung một file thì lần sau người đọc không còn thấy ranh giới, và ranh giới đó
chính là thứ router.py:11 cảnh báo phải giữ.

⚠️ NHƯNG `api/app.py::ROUTERS` CHỈ gắn biến `ROUTER` của `modules/<tên>/router.py`.
File này tự nó VÔ HÌNH — endpoint sẽ không lên và KHÔNG có lỗi nào
nổ. Nó sống được nhờ đúng một dòng `ROUTER.include_router(ROUTER_TENANT)` ở cuối
router.py. Đừng xoá dòng đó.

VÌ SAO ĐƯỜNG NÀY KHÔNG PHẠM CẢNH BÁO CỦA router.py:11 ("trộn hai đường xác thực
là mở một đường lấy credential hạ tầng bằng phiên"): nó KHÔNG trả credential hạ
tầng. Nó trả `api_key` — thứ chỉ dùng để ĐỔI lấy credential ở `/runtime-credentials`,
và việc đổi đó vẫn đi qua cổng Bearer như cũ. api_key nói "tôi là ai"; credential
nói "tôi được làm gì" (service.py:3).

TENANT KHÔNG ĐẾN TỪ REQUEST. Nó là `p.tenant_id` — đã xác thực qua một hàng
`control.memberships` còn hiệu lực (core/auth/principal.py:7). Đây là chỗ DUY NHẤT
cưỡng chế cách ly cho đường này: repo.py:6 đã cảnh báo ba bảng `control` không có
RLS đỡ phía sau.
"""

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Query, status

from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.config import get_settings
from portal.modules.enrollment import contracts, service
from portal.modules.enrollment.endpoint import KIND_CHAT, KIND_VOICE, url_endpoint_agent
from portal.modules.enrollment.ha_tang import HaTang, lay_ha_tang

ROUTER_TENANT = APIRouter()
"""KHÔNG khai `prefix`: `ROUTER` của router.py đã có `prefix="/agent"`, và
`include_router` cộng dồn tiền tố. Khai thêm ở đây ra `/agent/agent/keys`."""


def _endpoint_url(tenant_id: str, kind: str) -> str:
    """Đọc hằng số nền tảng rồi giao cho hàm thuần suy URL.

    Chỗ DUY NHẤT trong module đọc `gateway_base_domain`. `url_endpoint_agent` cố ý
    nhận domain làm tham số để test được không cần config — xem endpoint.py.
    """
    return url_endpoint_agent(tenant_id, get_settings().gateway_base_domain, kind)


@ROUTER_TENANT.get("/keys", response_model=contracts.DanhSachKhoaOut)
async def liet_ke_khoa(
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> contracts.DanhSachKhoaOut:
    """Khoá đang sống của workspace hiện tại.

    CÓ khoá thô (`api_key`, từ `0918`) — `None` cho khoá tạo trước migration đó.
    Xem docstring `contracts.KhoaOut` để biết vì sao và đánh đổi kèm theo.

    Hai endpoint trả về kể cả khi `keys` rỗng — màn hình phải bàn giao được
    endpoint trước khi có khoá nào.
    """
    return contracts.DanhSachKhoaOut(
        endpoint_chat_url=_endpoint_url(p.tenant_id, KIND_CHAT),
        endpoint_voice_url=_endpoint_url(p.tenant_id, KIND_VOICE),
        keys=await service.liet_ke_khoa(pool, p.tenant_id),
    )


@ROUTER_TENANT.post("/keys", response_model=contracts.KhoaDaTaoOut, status_code=status.HTTP_201_CREATED)
async def tao_khoa(
    body: contracts.TaoKhoaIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
    ha_tang: HaTang = Depends(lay_ha_tang),
) -> contracts.KhoaDaTaoOut:
    """⚠️ Response CHỨA KHOÁ THÔ, đúng một lần. Không log, không trace (G-10).

    Một khoá dùng chung cho cả `chat` lẫn `voice` — deployment không còn phân
    biệt theo `kind` (bỏ ở cùng đợt xoá cột `control.deployments.kind`).

    `boi` là `p.user_id` chứ không phải một chuỗi hằng: `agent_keys.created_by`
    là thứ duy nhất trả lời "ai đã phát khoá này" khi cần truy.
    """
    khoa = await service.phat_khoa_cho_tenant(pool, ha_tang, p.tenant_id, body.label, p.user_id)
    return contracts.KhoaDaTaoOut(
        id=khoa.id,
        api_key=khoa.api_key,
        key_prefix=khoa.key_prefix,
        endpoint_chat_url=_endpoint_url(p.tenant_id, KIND_CHAT),
        endpoint_voice_url=_endpoint_url(p.tenant_id, KIND_VOICE),
    )


@ROUTER_TENANT.post("/keys/{key_id}", response_model=contracts.KhoaOut)
async def dat_trang_thai_khoa(
    key_id: int,
    body: contracts.DatTrangThaiKhoaIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> contracts.KhoaOut:
    """Bật/tắt khoá. MỘT endpoint cho cả hai chiều (`status: "active"|"inactive"`)
    — trạng thái là một giá trị, không phải hai hành động (đổi từ `DELETE`
    2026-08-07: `control.agent_keys` chưa từng có câu `DELETE` nào, hàng chỉ
    được đặt/gỡ `revoked_at`, nên `DELETE` là một động từ nói sai việc nó làm).

    404 nếu khoá không tồn tại HOẶC thuộc workspace khác — cùng một câu chữ.

    Pod đang dùng khoá này không đứt ngay khi tắt: credential nó đã lấy vẫn
    sống tới hết TTL. Nó chết ở lần làm mới kế tiếp, khi `/runtime-credentials`
    trả 401.
    """
    return await service.dat_trang_thai_khoa_cua_tenant(pool, key_id, p.tenant_id, body.status, p.user_id)


@ROUTER_TENANT.post("/keys/{key_id}/rotate", response_model=contracts.KhoaDaTaoOut, status_code=status.HTTP_201_CREATED)
async def xoay_khoa(
    key_id: int,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> contracts.KhoaDaTaoOut:
    """Phát khoá mới cùng nhãn + thu hồi khoá cũ, trong một lời gọi.

    ⚠️ Response CHỨA KHOÁ THÔ, đúng một lần — cùng hợp đồng với `tao_khoa()`
    phía trên, và FE hiện nó lại bằng đúng dialog "khoá vừa tạo".

    404 nếu khoá không tồn tại HOẶC thuộc workspace khác — cùng câu chữ với
    `dat_trang_thai_khoa`.

    Khoá cũ KHÔNG biến mất — nó chuyển sang `status: "inactive"` như một lượt
    tắt tay, chủ workspace bật lại được nếu thật sự muốn (không có khái niệm
    "chết vĩnh viễn" nào khác cho khoá ở đây, xem `thu_hoi_khoa`).
    """
    khoa = await service.xoay_khoa_cua_tenant(pool, key_id, p.tenant_id, p.user_id)
    return contracts.KhoaDaTaoOut(
        id=khoa.id,
        api_key=khoa.api_key,
        key_prefix=khoa.key_prefix,
        endpoint_chat_url=_endpoint_url(p.tenant_id, KIND_CHAT),
        endpoint_voice_url=_endpoint_url(p.tenant_id, KIND_VOICE),
    )


@ROUTER_TENANT.get("/feedback", response_model=contracts.DanhSachFeedbackOut)
async def liet_ke_feedback(
    limit: int = Query(default=contracts.FEEDBACK_TRANG_MAC_DINH, gt=0, le=contracts.FEEDBACK_GIOI_HAN_TRANG),
    before_id: int | None = Query(default=None),
    rating: Annotated[list[int] | None, Query()] = None,
    session_id: str | None = Query(default=None),
    p: Principal = require(ACTIONS.CONVOS_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> contracts.DanhSachFeedbackOut:
    """Feedback của workspace hiện tại, mới nhất trước — cùng quyền xem Hội thoại
    (`ACTIONS.CONVOS_READ`, PQ_01 nhóm 2): feedback là một góc nhìn khác của
    cùng dữ liệu hội thoại, không phải một khái niệm quyền riêng.

    `rating` lặp lại được (`?rating=1&rating=2`) — lọc theo TẬP sao. `session_id`
    lọc đúng một phiên — dùng khi FE nhúng feedback vào chi tiết một hội thoại
    (`PhienKhach.tsx`), thay vì cần một endpoint riêng.
    """
    return await service.liet_ke_feedback_cua_tenant(
        pool, p.tenant_id, limit, before_id, ratings=rating, session_id=session_id
    )
