"""Endpoint tạo workspace.

`ROUTER` không mang `/api/v1` — `create_app()` thêm tiền tố đó lúc
`include_router`. Khai lại thành `/api/v1/api/v1/workspaces`, và triệu chứng là
404 ở mọi route.

Gắn vào app qua `api/app.py::ROUTERS`. Thiếu dòng ở đó thì endpoint không lên.

⚠ ĐƯỜNG NÀY KHAI `require(None, ly_do=...)` — CÔNG KHAI SAU PHIÊN, CÓ CHỦ Ý.

13 action của PQ_01 đều là quyền TRONG một workspace, mà tạo workspace mới thì
CHƯA CÓ workspace nào để xét quyền trong đó — không action nào diễn tả đúng nó.
Trước 2026-08-15 chỗ này khai `WORKSPACE_ADMIN` cho có, còn cửa thật nằm ở
`service.tao()` kiểm `users.org_role = 'owner'`. Tầng tổ chức đã bỏ và cùng với
nó là cửa đó: ai đăng nhập được cũng tạo được workspace, và người tạo trở thành
"Quản trị" của chính nó (spec bo-organization §5.2).

Khai `WORKSPACE_ADMIN` tiếp sẽ là một lời nói dối có hậu quả: `require()` đã
cưỡng chế action thật, nên người vừa đăng ký (0 workspace, 0 action) sẽ ăn 403 ở
đúng đường duy nhất đưa họ ra khỏi trạng thái đó.

Vì vậy route đọc `user_id` từ bản ghi phiên qua `lay_ban_ghi_phien`, không qua
`Principal` — `Principal` chỉ dựng được khi đã có workspace.

GIAO DỊCH MỞ Ở TẦNG NÀY, không trong service — khuôn `repo.py` ("caller quyết
định giao dịch") và khuôn `POST /users`. `service.tao()` gọi 5 hàm repo, và cả 5
phải cùng sống hoặc cùng chết: một workspace có hàng `tenants` mà thiếu
`tenant_verticals` là một workspace không ai biết nó thuộc lĩnh vực gì.
"""

import asyncpg
from fastapi import APIRouter, Depends
from redis.asyncio import Redis

from portal.api import loi as loi_chung
from portal.core.auth import session as ss
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_ban_ghi_phien, lay_pool, lay_redis, require
from portal.modules.workspace import service
from portal.modules.workspace.contracts import (
    SuaWorkspaceIn,
    TaoWorkspaceIn,
    WorkspaceSuaRaOut,
    WorkspaceTaoRaOut,
)

ROUTER = APIRouter(tags=["workspace"])


@ROUTER.post("/workspaces", response_model=WorkspaceTaoRaOut, status_code=201)
async def tao_workspace(
    vao: TaoWorkspaceIn,
    _: None = require(None, ly_do="tạo workspace mới — chưa có workspace nào để xét quyền trong đó"),
    phien: tuple[str, ss.BanGhiPhien] = Depends(lay_ban_ghi_phien),
    pool: asyncpg.Pool = Depends(lay_pool),
    r: Redis = Depends(lay_redis),
) -> WorkspaceTaoRaOut:
    """201 chứ không 200: có một tài nguyên mới, và FE chèn nó thẳng vào switcher.

    KHÔNG cấp phát hạ tầng ở đây (role Postgres · khoá kho tệp · collection
    Qdrant) — xem docstring `service.tao`. Workspace trả về ở trạng thái
    `provisioning`, và đó là trạng thái ĐÚNG, không phải trạng thái lỗi.

    PHIÊN CHƯA CÓ WORKSPACE THÌ TRỎ NÓ VÀO CÁI VỪA TẠO — xem khối dưới.
    """
    sid, ban_ghi = phien
    async with pool.acquire() as conn, conn.transaction():
        ra = await service.tao(conn, ban_ghi.user_id, vao)

    # ─────────────────────────────────────────────────────────────────────────
    # CHỈ khi phiên chưa trỏ vào workspace nào. Đây là ca người vừa tự đăng ký:
    # `tenant_id` của họ là NULL (spec bo-organization §5.0), và `dung_session_out`
    # trả `currentWorkspaceId` NGUYÊN từ bản ghi phiên — không suy từ danh sách
    # workspace. Nên nếu không cập nhật ở đây thì `GET /me` sau khi tạo vẫn trả
    # `currentWorkspaceId: null` trong khi `workspaces` đã có một phần tử, và
    # guard của FE (`currentWorkspaceId === null` ⇒ đi tới màn tạo workspace) đá
    # người dùng về đúng màn họ vừa hoàn thành. Vòng lặp kín, không có lối ra.
    #
    # KHÔNG đổi khi phiên ĐÃ có workspace: đường đó là dialog trong app
    # (`WorkspaceSwitcher` → `TaoWorkspaceDialog`), và nó TỰ gọi `switchWorkspace`
    # sau khi tạo — nó cần chuyển cache và remount nội dung màn theo đúng thứ tự
    # riêng của nó. Chuyển hộ ở đây là đổi hành vi một luồng đang chạy đúng, và
    # đổi theo cách nó không thấy được.
    #
    # SAU commit, ngoài giao dịch: Redis không nằm trong giao dịch Postgres, nên
    # đặt trước commit là hứa một workspace có thể bị rollback.
    if ban_ghi.tenant_id is None:
        await ss.doi_workspace(r, sid, ra.id)

    return ra


def _phai_la_workspace_dang_mo(p: Principal, tenant_id: str) -> None:
    """CỔNG THẬT của hai đường dưới đây — đọc kỹ trước khi sửa.

    `require(WORKSPACE_ADMIN)` tra ma trận quyền cho `Principal.tenant_id`: workspace
    mà PHIÊN đang mở. Nó KHÔNG biết gì về `{tenant_id}` trong đường dẫn. Bỏ phép đối
    chiếu này thì một Quản trị của workspace A gọi `DELETE /workspaces/B` sẽ đi qua
    đúng cổng quyền của A — cổng xanh, quyền được kiểm, chỉ là kiểm nhầm workspace —
    rồi đóng B. Đây là lớp lỗi mà `require()` KHÔNG che được, vì `require()` không
    đọc đường dẫn.

    403 chứ không 404: phân biệt "workspace không tồn tại" với "có nhưng không phải
    của bạn" là cho không một máy dò danh sách khách hàng — cùng lý lẽ
    `doi_workspace` ở `modules/auth/router.py` đã ghi.

    VÌ SAO ĐƯỜNG DẪN VẪN MANG `{tenant_id}` DÙ NÓ LUÔN PHẢI BẰNG `p.tenant_id`:
    `DELETE /workspaces` trần là một lời mời hiểu nhầm — người đọc log thấy một
    request xoá mà không thấy xoá cái gì, và một cú bấm nhầm tab không có gì để
    đối chiếu. Id trong đường dẫn biến "tôi định xoá cái này" thành thứ server
    kiểm được.
    """
    if tenant_id != p.tenant_id:
        raise loi_chung.khong_du_quyen()


@ROUTER.patch("/workspaces/{tenant_id}", response_model=WorkspaceSuaRaOut)
async def sua_workspace(
    tenant_id: str,
    vao: SuaWorkspaceIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> WorkspaceSuaRaOut:
    """Đổi tên. Mã workspace KHÔNG đổi — xem `service.sua`."""
    _phai_la_workspace_dang_mo(p, tenant_id)
    async with pool.acquire() as conn, conn.transaction():
        return await service.sua(conn, p.user_id, tenant_id, vao)


@ROUTER.delete("/workspaces/{tenant_id}", status_code=204)
async def xoa_workspace(
    tenant_id: str,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    phien: tuple[str, ss.BanGhiPhien] = Depends(lay_ban_ghi_phien),
    pool: asyncpg.Pool = Depends(lay_pool),
    r: Redis = Depends(lay_redis),
) -> None:
    """XOÁ CỨNG workspace, dời con trỏ phiên, rồi dọn ba kho NGOÀI Postgres-thuần.

    BA VIỆC, ĐÚNG THỨ TỰ NÀY, và mỗi lần đảo là một chế độ hỏng khác:

    ① `DELETE FROM control.tenants` trong giao dịch — cuốn theo 31 bảng qua
       `ON DELETE CASCADE`. Xem `service.xoa`.
    ② Dời con trỏ phiên. KHÔNG phải tiện nghi: `liet_ke_workspace()` thôi trả
       workspace vừa xoá, nên phiên còn trỏ vào nó thì `GET /me` trả một
       `currentWorkspaceId` không có trong `workspaces`, và `require()` đáp 403 cho
       mọi request sau. Người vừa bấm Xoá thấy màn hỏng vì chính cú bấm của họ.
    ③ Dọn collection Qdrant · kho tệp · role Postgres. SAU CÙNG, và KHÔNG ném —
       xem `service.don_ha_tang_ngoai`.

    Cùng khuôn `tao_workspace` ở trên: Redis KHÔNG nằm trong giao dịch Postgres nên
    ② đứng sau commit. Đảo lại là hứa một workspace có thể bị rollback.

    ③ đứng sau ② chứ không xen vào giữa: dọn hạ tầng là thao tác chậm nhất của cả
    request (liệt kê rồi xoá cả tiền tố trên kho tệp), và để nó chặn ② nghĩa là một
    MinIO chậm làm phiên người dùng nằm ở workspace đã biến mất lâu hơn cần thiết.

    `lay_ban_ghi_phien` chứ không `Principal`: `Principal` không mang `session_id`,
    mà `ss.doi_workspace` cần đúng cái đó. Hai dependency cùng đọc một bản ghi
    phiên là một roundtrip Redis thừa — cái giá của việc `require()` cố ý không trả
    sid ra ngoài.
    """
    _phai_la_workspace_dang_mo(p, tenant_id)
    sid, _ = phien

    async with pool.acquire() as conn, conn.transaction():
        ke_tiep = await service.xoa(conn, p.user_id, tenant_id)

    await ss.doi_workspace(r, sid, ke_tiep)
    await service.don_ha_tang_ngoai(pool, tenant_id)
