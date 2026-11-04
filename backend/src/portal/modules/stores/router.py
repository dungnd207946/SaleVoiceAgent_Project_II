"""Cửa hàng & tồn kho: tỉnh/thành · cửa hàng · tồn theo (cửa hàng, SKU) · "còn hàng tại cửa hàng".

`provinces` có PK text (`code`) nên không dùng được `dang_ky_crud` (giả định id số) — viết tay.
`reserved_qty` chỉ do module customers (giữ hàng) đổi; ở đây chỉ đổi `quantity`, và CHECK
`reserved_qty <= quantity` của DB chặn việc kiểm kê xuống dưới số đang giữ (→ 422).
"""

from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, Query, Response

from portal.api.loi import khong_tim_thay
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
from portal.modules.stores.contracts import (
    AvailabilityOut,
    InventoryAdjust,
    InventoryOut,
    InventorySet,
    ProvinceIn,
    ProvinceOut,
    ProvincePatch,
    ProvinceStock,
    StoreIn,
    StoreOut,
    StoreStock,
    StoreType,
)

ROUTER = APIRouter()
Pool = Annotated[asyncpg.Pool, Depends(get_pool)]
StorePatch = ban_sua(StoreIn)


# ------------------------------------------------------------------ tỉnh/thành


@ROUTER.get("/provinces", summary="Danh sách tỉnh/thành")
async def liet_ke_tinh(pool: Pool, q: str | None = None) -> list[ProvinceOut]:
    # Chỉ ~34 tỉnh/thành — trả trọn, không phân trang.
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT code, name FROM shop.provinces WHERE $1::text IS NULL OR name ILIKE '%' || $1 || '%' ORDER BY name",
            q,
        )
    return [ProvinceOut.model_validate(dict(r)) for r in rows]


@ROUTER.post("/provinces", status_code=201, summary="Tạo tỉnh/thành")
async def tao_tinh(body: ProvinceIn, pool: Pool) -> ProvinceOut:
    async with tx(pool) as conn:
        hang = await chen(conn, "provinces", body.model_dump())
    return ProvinceOut.model_validate(dict(hang))


@ROUTER.patch("/provinces/{code}", summary="Sửa tỉnh/thành")
async def sua_tinh(code: str, body: ProvincePatch, pool: Pool) -> ProvinceOut:
    async with tx(pool) as conn:
        hang = await sua(conn, "provinces", code, body.model_dump(exclude_unset=True), khoa="code")  # type: ignore[arg-type]
    if hang is None:
        raise khong_tim_thay("tỉnh/thành", code)
    return ProvinceOut.model_validate(dict(hang))


@ROUTER.delete("/provinces/{code}", status_code=204, summary="Xoá tỉnh/thành")
async def xoa_tinh(code: str, pool: Pool) -> Response:
    # Còn cửa hàng/khách tham chiếu → FK nổ → 409, đúng ý: không xoá ngầm.
    async with tx(pool) as conn:
        if not await xoa(conn, "provinces", code, khoa="code"):  # type: ignore[arg-type]
            raise khong_tim_thay("tỉnh/thành", code)
    return Response(status_code=204)


# ------------------------------------------------------------------ cửa hàng


@ROUTER.get("/stores", summary="Danh sách cửa hàng")
async def liet_ke_cua_hang(
    pool: Pool,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    q: str | None = None,
    province_code: Annotated[str | None, Query(alias="provinceCode")] = None,
    store_type: Annotated[StoreType | None, Query(alias="storeType")] = None,
    active: bool | None = None,
) -> Trang[StoreOut]:
    dk: list[str] = []
    ts: list[Any] = []
    for cot, v in (("province_code", province_code), ("store_type", store_type), ("is_active", active)):
        if v is not None:
            ts.append(v)
            dk.append(f"{cot} = ${len(ts)}")
    if q:
        ts.append(f"%{q}%")
        dk.append(f"(name ILIKE ${len(ts)} OR address ILIKE ${len(ts)})")
    async with pool.acquire() as conn:
        rows, total = await liet_ke(conn, "stores", dieu_kien=dk, tham_so=ts, limit=limit, offset=offset)
    return Trang[StoreOut](items=[ve_out(StoreOut, r) for r in rows], total=total, limit=limit, offset=offset)


@ROUTER.get("/stores/{id}", summary="Chi tiết cửa hàng")
async def lay_cua_hang(id: int, pool: Pool) -> StoreOut:
    async with pool.acquire() as conn:
        hang = await lay(conn, "stores", id)
    if hang is None:
        raise khong_tim_thay("cửa hàng", id)
    return ve_out(StoreOut, hang)


@ROUTER.post("/stores", status_code=201, summary="Tạo cửa hàng")
async def tao_cua_hang(body: StoreIn, pool: Pool) -> StoreOut:
    async with tx(pool) as conn:
        hang = await chen(conn, "stores", body.model_dump())
    return ve_out(StoreOut, hang)


@ROUTER.patch("/stores/{id}", summary="Sửa cửa hàng")
async def sua_cua_hang(id: int, body: StorePatch, pool: Pool) -> StoreOut:  # type: ignore[valid-type]
    async with tx(pool) as conn:
        hang = await sua(conn, "stores", id, body.model_dump(exclude_unset=True))  # type: ignore[attr-defined]
    if hang is None:
        raise khong_tim_thay("cửa hàng", id)
    return ve_out(StoreOut, hang)


@ROUTER.delete("/stores/{id}", status_code=204, summary="Xoá cửa hàng")
async def xoa_cua_hang(id: int, pool: Pool) -> Response:
    async with tx(pool) as conn:
        if not await xoa(conn, "stores", id):
            raise khong_tim_thay("cửa hàng", id)
    return Response(status_code=204)


# ------------------------------------------------------------------ tồn kho

_TON_SELECT = """
SELECT i.store_id, st.name AS store_name, st.province_code, i.variant_id, v.sku,
       p.name AS product_name, i.quantity, i.reserved_qty,
       i.quantity - i.reserved_qty AS qty_available, i.updated_at,
       count(*) OVER () AS _total
FROM shop.inventory i
JOIN shop.stores st          ON st.id = i.store_id
JOIN shop.product_variants v ON v.id = i.variant_id
JOIN shop.products p         ON p.id = v.product_id
"""


async def _lay_ton(conn: asyncpg.Connection, store_id: int, variant_id: int) -> InventoryOut:
    hang = await conn.fetchrow(_TON_SELECT + "WHERE i.store_id = $1 AND i.variant_id = $2", store_id, variant_id)
    return ve_out(InventoryOut, hang)


@ROUTER.get("/inventory", summary="Tồn kho theo cửa hàng × SKU")
async def liet_ke_ton(
    pool: Pool,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    variant_id: Annotated[int | None, Query(alias="variantId")] = None,
    store_id: Annotated[int | None, Query(alias="storeId")] = None,
    province_code: Annotated[str | None, Query(alias="provinceCode")] = None,
    in_stock_only: Annotated[bool, Query(alias="inStockOnly")] = False,
) -> Trang[InventoryOut]:
    dk: list[str] = []
    ts: list[Any] = []
    for cot, v in (("i.variant_id", variant_id), ("i.store_id", store_id), ("st.province_code", province_code)):
        if v is not None:
            ts.append(v)
            dk.append(f"{cot} = ${len(ts)}")
    if in_stock_only:
        dk.append("i.quantity > i.reserved_qty")
    where = f"WHERE {' AND '.join(dk)}" if dk else ""
    n = len(ts)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"{_TON_SELECT} {where} ORDER BY i.store_id, i.variant_id LIMIT ${n + 1} OFFSET ${n + 2}",
            *ts,
            limit,
            offset,
        )
        if rows:
            total = int(rows[0]["_total"])
        else:
            total = await conn.fetchval(
                "SELECT count(*) FROM shop.inventory i JOIN shop.stores st ON st.id = i.store_id " + where, *ts
            )
    return Trang[InventoryOut](items=[ve_out(InventoryOut, r) for r in rows], total=total, limit=limit, offset=offset)


@ROUTER.put("/inventory", summary="Đặt số tồn (kiểm kê)")
async def dat_ton(body: InventorySet, pool: Pool) -> InventoryOut:
    async with tx(pool) as conn:
        await conn.execute(
            "INSERT INTO shop.inventory (store_id, variant_id, quantity) VALUES ($1, $2, $3) "
            "ON CONFLICT (store_id, variant_id) DO UPDATE SET quantity = EXCLUDED.quantity",
            body.store_id,
            body.variant_id,
            body.quantity,
        )
        return await _lay_ton(conn, body.store_id, body.variant_id)


@ROUTER.post("/inventory/adjust", summary="Nhập/xuất tương đối")
async def dieu_chinh_ton(body: InventoryAdjust, pool: Pool) -> InventoryOut:
    async with tx(pool) as conn:
        # Bảo đảm có hàng trước (0) rồi cộng dồn bằng MỘT câu UPDATE — không đọc-rồi-ghi.
        # Không dùng INSERT ... ON CONFLICT với quantity = delta: delta âm vi phạm CHECK
        # ngay ở bộ dữ liệu đề xuất, kể cả khi hàng đã tồn tại.
        await conn.execute(
            "INSERT INTO shop.inventory (store_id, variant_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            body.store_id,
            body.variant_id,
        )
        await conn.execute(
            "UPDATE shop.inventory SET quantity = quantity + $3 WHERE store_id = $1 AND variant_id = $2",
            body.store_id,
            body.variant_id,
            body.delta,
        )
        return await _lay_ton(conn, body.store_id, body.variant_id)


@ROUTER.get("/variants/{variant_id}/availability", summary="Còn hàng tại cửa hàng nào")
async def con_hang(variant_id: int, pool: Pool) -> AvailabilityOut:
    # Cùng luật với view agent_stock_v: chỉ cửa hàng đang mở, loại kho online, còn bán được (> giữ).
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT pv.code AS province_code, pv.name AS province_name,
                   st.id AS store_id, st.name AS store_name, st.address, st.ward, st.phone,
                   st.open_time, st.close_time, i.quantity - i.reserved_qty AS qty_available
            FROM shop.inventory i
            JOIN shop.stores st    ON st.id = i.store_id AND st.is_active AND st.store_type = 'store'
            JOIN shop.provinces pv ON pv.code = st.province_code
            WHERE i.variant_id = $1 AND i.quantity > i.reserved_qty
            ORDER BY pv.name, st.name
            """,
            variant_id,
        )
    nhom: dict[str, ProvinceStock] = {}
    for r in rows:
        tinh = nhom.get(r["province_code"])
        if tinh is None:
            tinh = nhom[r["province_code"]] = ProvinceStock(
                province_code=r["province_code"], province_name=r["province_name"], qty_available=0, stores=[]
            )
        ch = StoreStock.model_validate({k: r[k] for k in StoreStock.model_fields})
        tinh.stores.append(ch)
        tinh.qty_available += ch.qty_available
    return AvailabilityOut(
        variant_id=variant_id,
        qty_available=sum(t.qty_available for t in nhom.values()),
        provinces=list(nhom.values()),
    )
