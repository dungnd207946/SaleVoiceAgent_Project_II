"""Endpoint màn «Quản lý lĩnh vực» (/domains của FE) — 2 route.

HỢP ĐỒNG DO FE ĐỊNH TRƯỚC (2026-08-08, `features/agent/linhVuc.ts`, fake MSW
chạy từ đó tới nay): GET trả MẢNG TRẦN đúng thứ tự sổ; PATCH trả MỘT object.
Đổi hình dạng ở đây là vỡ màn đang chạy — sửa FE trước rồi mới tới đây.

`tenant_id` LUÔN lấy từ `Principal` (đã xác thực qua membership), KHÔNG từ
path/body — `control.tenant_verticals` không có RLS đỡ phía sau, lấy sai chỗ
là bật/tắt lĩnh vực của workspace khác không lỗi nào.

Quyền: GET `AGENT_CONFIG_READ` (khớp `requiredActions` nav FE), PATCH
`AGENT_CONFIG_WRITE` — bật/tắt lĩnh vực là sửa hành vi agent, cùng hạng sửa
bản nháp cấu hình. KHÔNG side effect sang agent: gating kỹ năng vẫn ở FE lúc
«Lưu và áp dụng» (`locKyNangTheoLinhVuc`), backend chỉ là sổ trạng thái.
Cổng nạp (ingest) cũng KHÔNG đọc bảng này — tắt lĩnh vực không chặn nạp dữ
liệu, cố ý (xem spec §7).
"""

import asyncpg
from fastapi import APIRouter, Depends

from portal.api import loi
from portal.core import nhat_ky
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.db.session import tenant_conn
from portal.modules.linh_vuc import repo, so
from portal.modules.linh_vuc.contracts import DatLinhVucIn, LinhVucOut

ROUTER = APIRouter(prefix="/linh-vuc", tags=["linh-vuc"])
"""KHÔNG có `/api/v1` ở đây — `create_app()` thêm tiền tố lúc include_router."""


def _khong_ton_tai(ma: str) -> loi.LoiPortal:
    return loi.LoiPortal("LINH_VUC_KHONG_TON_TAI", 404, f"Không có lĩnh vực {ma!r}")


async def _dung_out(pool: asyncpg.Pool, tenant_id: str, lv: so.LinhVuc, dang_bat: set[str]) -> LinhVucOut:
    """Một chỗ dựng LinhVucOut — GET và PATCH trả cùng hình dạng từ cùng phép tính."""
    if lv.ma == "bds":
        async with tenant_conn(pool, tenant_id) as conn:
            co_du_lieu = await repo.co_du_lieu_bds(conn)
    else:
        # taichinh chưa có bảng dữ liệu nào — hằng False, không mở giao dịch vô ích
        co_du_lieu = False
    return LinhVucOut(
        ma=lv.ma,
        ten=lv.ten,
        bat=lv.vertical in dang_bat,
        soKyNang=so.so_ky_nang(lv),
        coDuLieu=co_du_lieu,
    )


@ROUTER.get("", response_model=list[LinhVucOut])
async def liet_ke(
    p: Principal = require(ACTIONS.AGENT_CONFIG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[LinhVucOut]:
    async with pool.acquire() as conn:
        dang_bat = await repo.doc_verticals(conn, p.tenant_id)
    return [await _dung_out(pool, p.tenant_id, lv, dang_bat) for lv in so.SO_LINH_VUC]


@ROUTER.patch("/{ma}", response_model=LinhVucOut)
async def dat(
    ma: str,
    body: DatLinhVucIn,
    p: Principal = require(ACTIONS.AGENT_CONFIG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> LinhVucOut:
    lv = so.theo_ma(ma)
    if lv is None:
        raise _khong_ton_tai(ma)
    async with pool.acquire() as conn, conn.transaction():
        if body.bat:
            await repo.bat(conn, p.tenant_id, lv.vertical)
        else:
            await repo.tat(conn, p.tenant_id, lv.vertical)
        # Nhật ký CÙNG transaction — công tắc đổi mà không có vết (hoặc ngược
        # lại) thì người đọc nhật ký tin vào cái sai.
        await nhat_ky.ghi(conn, p.tenant_id, "linh_vuc.bat" if body.bat else "linh_vuc.tat", p.user_id, {"ma": ma})
    # Đọc lại từ DB thay vì suy từ body — rẻ, và không bao giờ lệch trạng thái thật.
    async with pool.acquire() as conn:
        dang_bat = await repo.doc_verticals(conn, p.tenant_id)
    return await _dung_out(pool, p.tenant_id, lv, dang_bat)
