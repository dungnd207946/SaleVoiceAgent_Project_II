"""`GET /audit` — màn «Nhật ký» đọc `control.audit_log`. Một route, chỉ đọc.

Quyền: `ACTIONS.AUDIT_READ` (0956, cấp cho «Quản trị»). Phạm vi = workspace của
`Principal`; hàng `tenant_id IS NULL` (đăng ký, đổi mật khẩu…) không thuộc
workspace nào nên không bao giờ lọt — spec §2 #6.

KHÔNG có `/api/v1` ở đây — `create_app()` thêm tiền tố lúc include_router.
"""

import json
import re
from datetime import date

import asyncpg
from fastapi import APIRouter, Depends, Query

from portal.api import loi
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.db.session import tenant_conn
from portal.modules.audit import repo
from portal.modules.audit.contracts import (
    GIOI_HAN_TRANG,
    SO_NHOM_TOI_DA,
    TRANG_MAC_DINH,
    DongNhatKyOut,
    LoiConTro,
    TrangNhatKyOut,
    doc_con_tro,
    ma_con_tro,
)

ROUTER = APIRouter(tags=["audit"])

_LIMIT_Q = Query(TRANG_MAC_DINH, ge=1, le=GIOI_HAN_TRANG)
"""Singleton mức module — `Query(...)` trong default là B008 (ruff)."""

_NHOM_RE = re.compile(r"^[a-z_]{1,32}$")


def _con_tro_khong_hop_le() -> loi.LoiPortal:
    return loi.LoiPortal("CURSOR_KHONG_HOP_LE", 400, "Con trỏ phân trang không hợp lệ")


def _tach_nhom(nhom: str | None) -> list[str] | None:
    """`?nhom=thanh_vien,user` → `["thanh_vien", "user"]`. Rỗng/None → None (không lọc)."""
    if not nhom:
        return None
    ds = [x.strip() for x in nhom.split(",") if x.strip()]
    if not ds or len(ds) > SO_NHOM_TOI_DA or any(not _NHOM_RE.fullmatch(x) for x in ds):
        raise loi.LoiPortal(
            "NHOM_KHONG_HOP_LE", 422, f"`nhom` là tối đa {SO_NHOM_TOI_DA} tiền tố [a-z_], cách nhau dấu phẩy"
        )
    return ds


def _xin_du_phong(lim: int) -> int:
    """Xin `lim + 1` để biết còn trang sau — trừ khi đã chạm trần."""
    return min(lim + 1, GIOI_HAN_TRANG)


def _trang(hang: list[asyncpg.Record], lim: int, xin: int) -> tuple[list[asyncpg.Record], str | None]:
    """`hang` là kết quả repo trả cho `LIMIT xin`. `len(hang) >= xin` (nhận ĐỦ số
    đã xin — không thể nhiều hơn, SQL `LIMIT xin` đảm bảo) ⇒ có thể còn trang
    sau: cắt về đúng `lim` phần tử, `nextCursor` mã hoá từ `(luc, id)` của phần
    tử thứ `lim` (0-index `lim - 1`) — cùng một công thức đúng cho cả hai trường
    hợp `xin == lim + 1` (chính xác tuyệt đối) lẫn `xin == lim == GIOI_HAN_TRANG`
    (bảo thủ: ở `limit=200` không còn chỗ xin dư 1 vì `_xin_du_phong` đã kẹp về
    đúng trần — nên một trang cuối ĐẦY ĐỦ 200 hàng, dù không còn hàng nào sau nó,
    vẫn trả `nextCursor`; FE bấm «Tải thêm» thêm một lần nữa và nhận `items: []`
    — không phải lỗi, xem `docs/contracts/audit.md`)."""
    if len(hang) >= xin:
        cuoi = hang[lim - 1]
        return list(hang[:lim]), ma_con_tro(cuoi["luc"], cuoi["id"])
    return list(hang), None


def _ra_dong(r: asyncpg.Record) -> DongNhatKyOut:
    return DongNhatKyOut(
        id=r["id"],
        luc=r["luc"],
        hanhDong=r["hanh_dong"],
        actorId=r["actor"],
        actorTen=r["actor_ten"],
        actorEmail=r["actor_email"],
        chiTiet=json.loads(r["chi_tiet"]),
    )


@ROUTER.get("/audit", response_model=TrangNhatKyOut)
async def liet_ke_nhat_ky(
    limit: int = _LIMIT_Q,
    cursor: str | None = None,
    nhom: str | None = None,
    tu: date | None = Query(None, alias="from"),
    den: date | None = Query(None, alias="to"),
    may: bool = False,
    p: Principal = require(ACTIONS.AUDIT_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TrangNhatKyOut:
    """Trang nhật ký của workspace hiện tại, mới nhất trước.

    `to` là cận TRÊN MỞ (`< to`) — cùng nghĩa `_khoang()` của billing; FE gửi
    `ngày chọn + 1` cho ô «đến hết ngày». KHÔNG có khoảng mặc định: thiếu cả hai
    là «mới nhất trước», cuộn tới đâu tuỳ người xem.
    `may=false` (mặc định) ẩn `actor = 'agent'` — xem `contracts.MA_ACTOR_MAY`.

    `cursor=""` coi như không có cursor (như `nhom=""` ở `_tach_nhom`) — cả hai
    kiểm `if cursor`/`if not nhom` trước khi đụng tới hàm đọc; còn `doc_con_tro("")`
    gọi TRỰC TIẾP thì ném `LoiConTro` (chuỗi rỗng không phải base64 hợp lệ). Hai
    hợp đồng khác nhau CÓ CHỦ Ý: ở biên route, chuỗi rỗng là "FE không gửi gì" —
    thân thiện; còn `doc_con_tro` tự nó là hàm giải mã, một cursor rác kể cả rỗng
    phải ném, không được âm thầm coi là "trang đầu".
    """
    if tu is not None and den is not None and tu >= den:
        raise loi.LoiPortal("KHOANG_KHONG_HOP_LE", 422, "`from` phải trước `to`")
    ds_nhom = _tach_nhom(nhom)
    try:
        con_tro = doc_con_tro(cursor) if cursor else None
    except LoiConTro as e:
        raise _con_tro_khong_hop_le() from e

    xin = _xin_du_phong(limit)
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.liet_ke(conn, limit=xin, con_tro=con_tro, nhom=ds_nhom, tu=tu, den=den, may=may)
    items, ke_tiep = _trang(hang, limit, xin)
    return TrangNhatKyOut(items=[_ra_dong(r) for r in items], nextCursor=ke_tiep)
