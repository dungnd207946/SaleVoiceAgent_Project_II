"""Khách hàng & giữ hàng/hẹn lịch.

Giữ hàng (`hold_stock`) chạm `inventory.reserved_qty` — mọi thay đổi trạng thái kèm cộng/trừ
tồn nằm trong MỘT giao dịch với `SELECT ... FOR UPDATE` trên hàng tồn, để hai khách giữ
cùng máy cuối cùng không cùng thành công. Thứ tự khoá luôn reservation → inventory.
"""

from datetime import timedelta
from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, Query, Response

from portal.api.loi import LoiPortal, du_lieu_khong_hop_le, khong_tim_thay
from portal.core.crud import (
    LIMIT_MAC_DINH,
    Limit,
    Offset,
    Trang,
    ban_sua,
    chen,
    lay,
    liet_ke,
    sua,
    ve_out,
    xoa,
)
from portal.core.db.pool import get_pool
from portal.core.db.session import tx
from portal.modules.customers.contracts import (
    CHUYEN_HOP_LE,
    CustomerIn,
    CustomerOut,
    ExpireOut,
    ReservationIn,
    ReservationOut,
    ReservationPatch,
    ReservationStatus,
    ReservationType,
    chuan_hoa_sdt,
)

ROUTER = APIRouter()
Pool = Annotated[asyncpg.Pool, Depends(get_pool)]
CustomerPatch = ban_sua(CustomerIn)
GIU_HANG_MAC_DINH = timedelta(hours=24)


# ------------------------------------------------------------------ khách hàng


@ROUTER.get("/customers", summary="Danh sách khách hàng")
async def liet_ke_khach(
    pool: Pool,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    q: str | None = None,
    province_code: Annotated[str | None, Query(alias="provinceCode")] = None,
) -> Trang[CustomerOut]:
    dk: list[str] = []
    ts: list[Any] = []
    if province_code is not None:
        ts.append(province_code)
        dk.append(f"province_code = ${len(ts)}")
    if q:
        # SĐT lưu dạng chuẩn hoá (không dấu cách/chấm) → bỏ chúng khỏi q khi so với phone.
        ts.append(f"%{q}%")
        ts.append("%" + q.replace(" ", "").replace(".", "") + "%")
        a, b = len(ts) - 1, len(ts)
        dk.append(f"(full_name ILIKE ${a} OR email ILIKE ${a} OR phone ILIKE ${b})")
    async with pool.acquire() as conn:
        rows, total = await liet_ke(
            conn, "customers", dieu_kien=dk, tham_so=ts, sap_xep="id DESC", limit=limit, offset=offset
        )
    return Trang[CustomerOut](items=[ve_out(CustomerOut, r) for r in rows], total=total, limit=limit, offset=offset)


@ROUTER.get("/customers/by-phone/{phone}", summary="Tìm khách theo SĐT")
async def lay_khach_theo_sdt(phone: str, pool: Pool) -> CustomerOut:
    try:
        sdt = chuan_hoa_sdt(phone)
    except ValueError as e:
        raise du_lieu_khong_hop_le(str(e)) from None
    async with pool.acquire() as conn:
        hang = await conn.fetchrow("SELECT * FROM shop.customers WHERE phone = $1", sdt)
    if hang is None:
        raise khong_tim_thay("khách hàng SĐT", sdt)
    return ve_out(CustomerOut, hang)


@ROUTER.get("/customers/{id}", summary="Chi tiết khách hàng")
async def lay_khach(id: int, pool: Pool) -> CustomerOut:
    async with pool.acquire() as conn:
        hang = await lay(conn, "customers", id)
    if hang is None:
        raise khong_tim_thay("khách hàng", id)
    return ve_out(CustomerOut, hang)


@ROUTER.post("/customers", status_code=201, summary="Tạo khách hàng")
async def tao_khach(body: CustomerIn, pool: Pool) -> CustomerOut:
    async with tx(pool) as conn:
        hang = await chen(conn, "customers", body.model_dump())
    return ve_out(CustomerOut, hang)


@ROUTER.patch("/customers/{id}", summary="Sửa khách hàng")
async def sua_khach(id: int, body: CustomerPatch, pool: Pool) -> CustomerOut:  # type: ignore[valid-type]
    async with tx(pool) as conn:
        hang = await sua(conn, "customers", id, body.model_dump(exclude_unset=True))  # type: ignore[attr-defined]
    if hang is None:
        raise khong_tim_thay("khách hàng", id)
    return ve_out(CustomerOut, hang)


@ROUTER.delete("/customers/{id}", status_code=204, summary="Xoá khách hàng")
async def xoa_khach(id: int, pool: Pool) -> Response:
    # Cascade xoá reservations của khách. Hàng đang giữ phải huỷ trước — xoá thẳng sẽ để
    # reserved_qty treo, nên chặn ở đây thay vì âm thầm rò tồn.
    async with tx(pool) as conn:
        dang_giu = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM shop.reservations WHERE customer_id = $1 "
            "AND reservation_type = 'hold_stock' AND status IN ('pending','confirmed'))",
            id,
        )
        if dang_giu:
            raise LoiPortal("HAS_ACTIVE_HOLD", 409, "Khách còn phiếu giữ hàng đang hiệu lực — huỷ trước khi xoá")
        if not await xoa(conn, "customers", id):
            raise khong_tim_thay("khách hàng", id)
    return Response(status_code=204)


# ------------------------------------------------------------------ giữ hàng / hẹn


async def _giu_ton(conn: asyncpg.Connection, store_id: int, variant_id: int, so_luong: int) -> None:
    ton = await conn.fetchrow(
        "SELECT quantity, reserved_qty FROM shop.inventory WHERE store_id = $1 AND variant_id = $2 FOR UPDATE",
        store_id,
        variant_id,
    )
    if ton is None or ton["quantity"] - ton["reserved_qty"] < so_luong:
        con = 0 if ton is None else ton["quantity"] - ton["reserved_qty"]
        raise LoiPortal("OUT_OF_STOCK", 409, f"Cửa hàng chỉ còn {con} máy có thể giữ, cần {so_luong}")
    await conn.execute(
        "UPDATE shop.inventory SET reserved_qty = reserved_qty + $3 WHERE store_id = $1 AND variant_id = $2",
        store_id,
        variant_id,
        so_luong,
    )


async def _tra_ton(conn: asyncpg.Connection, phieu: asyncpg.Record, *, ban: bool) -> None:
    """Nhả số đang giữ; `ban=True` (completed) thì trừ luôn tồn thật — máy đã giao cho khách."""
    if phieu["reservation_type"] != "hold_stock" or phieu["store_id"] is None or phieu["variant_id"] is None:
        return  # cửa hàng/SKU đã bị xoá (SET NULL) → hàng tồn cũng đã cascade đi, không còn gì để trả
    await conn.execute(
        "SELECT 1 FROM shop.inventory WHERE store_id = $1 AND variant_id = $2 FOR UPDATE",
        phieu["store_id"],
        phieu["variant_id"],
    )
    await conn.execute(
        "UPDATE shop.inventory SET reserved_qty = reserved_qty - $3, "
        "quantity = quantity - CASE WHEN $4 THEN $3 ELSE 0 END "
        "WHERE store_id = $1 AND variant_id = $2",
        phieu["store_id"],
        phieu["variant_id"],
        phieu["quantity"],
        ban,
    )


async def _doi_trang_thai(conn: asyncpg.Connection, phieu: asyncpg.Record, moi: str) -> None:
    """Kiểm máy trạng thái + cộng/trừ tồn. Gọi trong giao dịch, `phieu` đã khoá FOR UPDATE."""
    cu = phieu["status"]
    if moi not in CHUYEN_HOP_LE.get(cu, frozenset()):
        raise LoiPortal("INVALID_TRANSITION", 422, f"Không chuyển được từ '{cu}' sang '{moi}'")
    if moi in ("cancelled", "expired"):
        await _tra_ton(conn, phieu, ban=False)
    elif moi == "completed":
        await _tra_ton(conn, phieu, ban=True)


@ROUTER.get("/reservations", summary="Danh sách giữ hàng/hẹn")
async def liet_ke_phieu(
    pool: Pool,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    customer_id: Annotated[int | None, Query(alias="customerId")] = None,
    status: ReservationStatus | None = None,
    store_id: Annotated[int | None, Query(alias="storeId")] = None,
    type: ReservationType | None = None,
) -> Trang[ReservationOut]:
    dk: list[str] = []
    ts: list[Any] = []
    for cot, v in (
        ("customer_id", customer_id),
        ("status", status),
        ("store_id", store_id),
        ("reservation_type", type),
    ):
        if v is not None:
            ts.append(v)
            dk.append(f"{cot} = ${len(ts)}")
    async with pool.acquire() as conn:
        rows, total = await liet_ke(
            conn,
            "reservations",
            dieu_kien=dk,
            tham_so=ts,
            sap_xep="created_at DESC, id DESC",
            limit=limit,
            offset=offset,
        )
    return Trang[ReservationOut](
        items=[ve_out(ReservationOut, r) for r in rows], total=total, limit=limit, offset=offset
    )


@ROUTER.get("/reservations/{id}", summary="Chi tiết giữ hàng/hẹn")
async def lay_phieu(id: int, pool: Pool) -> ReservationOut:
    async with pool.acquire() as conn:
        hang = await lay(conn, "reservations", id)
    if hang is None:
        raise khong_tim_thay("phiếu giữ hàng/hẹn", id)
    return ve_out(ReservationOut, hang)


@ROUTER.post("/reservations", status_code=201, summary="Tạo giữ hàng/hẹn")
async def tao_phieu(body: ReservationIn, pool: Pool) -> ReservationOut:
    du_lieu = body.model_dump()
    async with tx(pool) as conn:
        if body.reservation_type == "hold_stock":
            if du_lieu["expires_at"] is None:
                du_lieu["expires_at"] = await conn.fetchval("SELECT now() + $1::interval", GIU_HANG_MAC_DINH)
            # Thiếu store/variant thì bỏ qua bước giữ — câu INSERT sẽ nổ CHECK của DB (422).
            if body.store_id is not None and body.variant_id is not None:
                await _giu_ton(conn, body.store_id, body.variant_id, body.quantity)
        hang = await chen(conn, "reservations", du_lieu)
    return ve_out(ReservationOut, hang)


@ROUTER.patch("/reservations/{id}", summary="Đổi trạng thái/ghi chú/lịch hẹn")
async def sua_phieu(id: int, body: ReservationPatch, pool: Pool) -> ReservationOut:
    du_lieu = body.model_dump(exclude_unset=True)
    async with tx(pool) as conn:
        phieu = await conn.fetchrow("SELECT * FROM shop.reservations WHERE id = $1 FOR UPDATE", id)
        if phieu is None:
            raise khong_tim_thay("phiếu giữ hàng/hẹn", id)
        moi = du_lieu.get("status")
        if moi is None:
            du_lieu.pop("status", None)  # status NOT NULL — null tường minh coi như không đổi
        elif moi == phieu["status"]:
            du_lieu.pop("status")  # gửi lại trạng thái hiện tại: idempotent, không cộng/trừ tồn lần hai
        else:
            await _doi_trang_thai(conn, phieu, moi)
        hang = await sua(conn, "reservations", id, du_lieu)
    return ve_out(ReservationOut, hang)


@ROUTER.post("/reservations/expire-due", summary="Hết hạn các phiếu giữ hàng quá hạn (cron)")
async def het_han_phieu(pool: Pool) -> ExpireOut:
    async with tx(pool) as conn:
        # SKIP LOCKED: phiếu đang bị người khác sửa thì để lượt cron sau, không chờ.
        phieus = await conn.fetch(
            "SELECT * FROM shop.reservations WHERE reservation_type = 'hold_stock' "
            "AND status IN ('pending','confirmed') AND expires_at < now() ORDER BY id FOR UPDATE SKIP LOCKED"
        )
        for p in phieus:
            await _doi_trang_thai(conn, p, "expired")
        if phieus:
            await conn.execute(
                "UPDATE shop.reservations SET status = 'expired' WHERE id = ANY($1::bigint[])",
                [p["id"] for p in phieus],
            )
    return ExpireOut(expired=len(phieus))
