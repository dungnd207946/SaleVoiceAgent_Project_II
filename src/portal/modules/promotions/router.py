"""Khuyến mãi: CRUD · đối tượng áp dụng · KM đang áp cho một sản phẩm/SKU.

Thứ tự đăng ký quan trọng: `/promotions/applicable` phải đứng TRƯỚC `/promotions/{id}`
(id kiểu int sẽ nuốt chữ "applicable" thành 422).
"""

from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, Query

from portal.api.loi import du_lieu_khong_hop_le, khong_tim_thay
from portal.core.ban_hang import (
    TargetIn,
    TargetOut,
    dang_ky_crud_le,
    doc_targets,
    thay_targets,
    them_dk,
    trang,
)
from portal.core.crud import LIMIT_MAC_DINH, Limit, Offset, Trang, lay, liet_ke
from portal.core.db.pool import get_pool
from portal.core.db.session import tx
from portal.modules.promotions.contracts import (
    KhuyenMaiApDungOut,
    NhomChonOut,
    PromotionApDungOut,
    PromotionIn,
    PromotionOut,
    PromoType,
)

ROUTER = APIRouter()
Pool = Annotated[asyncpg.Pool, Depends(get_pool)]

BANG = "promotions"
BANG_DT = "promotion_targets"
TEN = "khuyến mãi"


def dang_chay(a: str = "") -> str:
    """KM đang chạy = bật + now() trong cửa sổ — cùng định nghĩa với view agent_promotions_v."""
    return f"({a}is_active AND now() >= {a}starts_at AND ({a}ends_at IS NULL OR now() < {a}ends_at))"


THU_TU_VIA = ("variant", "product", "brand", "category")


@ROUTER.get("/promotions", summary="Danh sách khuyến mãi")
async def liet_ke_km(
    pool: Pool,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    q: str | None = None,
    promo_type: Annotated[PromoType | None, Query(alias="promoType")] = None,
    active: bool | None = None,
) -> Trang[PromotionOut]:
    dk: list[str] = []
    ts: list[Any] = []
    if q:
        them_dk(dk, ts, "name ILIKE {}", f"%{q}%")
    if promo_type:
        them_dk(dk, ts, "promo_type = {}", promo_type)
    if active is not None:
        dk.append(dang_chay() if active else f"NOT {dang_chay()}")
    async with pool.acquire() as conn:
        rows, total = await liet_ke(
            conn, BANG, dieu_kien=dk, tham_so=ts, sap_xep="priority DESC, id", limit=limit, offset=offset
        )
    return trang(PromotionOut, rows, total, limit, offset)


@ROUTER.get("/promotions/applicable", summary="Khuyến mãi đang áp cho sản phẩm/SKU")
async def km_ap_dung(
    pool: Pool,
    product_id: Annotated[int | None, Query(alias="productId")] = None,
    variant_id: Annotated[int | None, Query(alias="variantId")] = None,
) -> KhuyenMaiApDungOut:
    """KM đang chạy khớp qua SKU, sản phẩm (gồm mọi SKU của nó), hãng hoặc ngành hàng.

    Chỉ `productId` ⇒ gồm cả KM chỉ gắn vài SKU (kèm `variantIds` để FE lọc khi khách chọn
    cấu hình). Có `variantId` ⇒ chỉ KM áp được cho đúng SKU đó.
    """
    if (product_id is None) == (variant_id is None):
        raise du_lieu_khong_hop_le("Cần đúng một trong productId | variantId")
    async with pool.acquire() as conn:
        if variant_id is not None:
            product_id = await conn.fetchval("SELECT product_id FROM shop.product_variants WHERE id = $1", variant_id)
            if product_id is None:
                raise khong_tim_thay("biến thể", variant_id)
        sp = await conn.fetchrow("SELECT brand_id, category_id FROM shop.products WHERE id = $1", product_id)
        if sp is None:
            raise khong_tim_thay("sản phẩm", product_id)
        rows = await conn.fetch(
            f"""
            SELECT pr.*, gp.name AS gift_product_name,
                   array_agg(DISTINCT CASE WHEN t.variant_id IS NOT NULL THEN 'variant'
                                           WHEN t.product_id IS NOT NULL THEN 'product'
                                           WHEN t.brand_id   IS NOT NULL THEN 'brand'
                                           ELSE 'category' END) AS applies_via,
                   bool_or(t.variant_id IS NULL) AS ca_san_pham,
                   array_agg(DISTINCT t.variant_id) FILTER (WHERE t.variant_id IS NOT NULL) AS variant_ids
            FROM shop.promotions pr
            JOIN shop.promotion_targets t ON t.promotion_id = pr.id
            LEFT JOIN shop.products gp ON gp.id = pr.gift_product_id
            WHERE {dang_chay("pr.")}
              AND (t.product_id = $1 OR t.brand_id = $2 OR t.category_id = $3
                   OR t.variant_id = $4::bigint
                   OR ($4::bigint IS NULL AND t.variant_id IN
                         (SELECT id FROM shop.product_variants WHERE product_id = $1)))
            GROUP BY pr.id, gp.name
            ORDER BY pr.priority DESC, pr.id
            """,
            product_id,
            sp["brand_id"],
            sp["category_id"],
            variant_id,
        )
    km: list[PromotionApDungOut] = []
    nhom: dict[str, list[int]] = {}
    for r in rows:
        d = {k: v for k, v in dict(r).items() if k != "ca_san_pham"}
        d["applies_via"] = [v for v in THU_TU_VIA if v in r["applies_via"]]
        d["variant_ids"] = None if r["ca_san_pham"] else sorted(r["variant_ids"])
        km.append(PromotionApDungOut.model_validate(d))
        if r["choice_group"]:
            nhom.setdefault(r["choice_group"], []).append(r["id"])
    return KhuyenMaiApDungOut(
        product_id=product_id,
        variant_id=variant_id,
        promotions=km,
        choice_groups=[NhomChonOut(choice_group=g, promotion_ids=ids) for g, ids in nhom.items()],
    )


async def _phai_co(conn: asyncpg.Connection, id_: int) -> None:
    if await lay(conn, BANG, id_) is None:
        raise khong_tim_thay(TEN, id_)


@ROUTER.get("/promotions/{id}/targets", summary="Đối tượng áp dụng của khuyến mãi")
async def doc_dt(id: int, pool: Pool) -> list[TargetOut]:
    async with pool.acquire() as conn:
        await _phai_co(conn, id)
        return await doc_targets(conn, BANG_DT, "promotion_id", id)


@ROUTER.put("/promotions/{id}/targets", summary="Thay toàn bộ đối tượng áp dụng")
async def thay_dt(id: int, body: list[TargetIn], pool: Pool) -> list[TargetOut]:
    async with tx(pool) as conn:
        await _phai_co(conn, id)
        return await thay_targets(conn, BANG_DT, "promotion_id", id, body)


dang_ky_crud_le(ROUTER, duong_dan="/promotions", bang=BANG, ten=TEN, model_in=PromotionIn, model_out=PromotionOut)
