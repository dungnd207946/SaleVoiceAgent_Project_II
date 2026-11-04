"""Chính sách (bảo hành, đổi trả, giao hàng…) và gói dịch vụ bán thêm (BH rơi vỡ, 1 đổi 1…)."""

from decimal import Decimal
from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, Query

from portal.core.ban_hang import dang_ky_crud_le, lam_tron, lay_bien_the, them_dk, trang
from portal.core.crud import LIMIT_MAC_DINH, Limit, Offset, Trang, liet_ke
from portal.core.db.pool import get_pool
from portal.modules.policies.contracts import (
    BaoGiaGoiDichVuOut,
    PolicyIn,
    PolicyOut,
    PolicyType,
    ServicePackageIn,
    ServicePackageOut,
    ServiceType,
)

ROUTER = APIRouter()
Pool = Annotated[asyncpg.Pool, Depends(get_pool)]

# Chính sách "đang hiệu lực" theo NGÀY (cột date), khác KM theo thời điểm.
CS_HIEU_LUC = (
    "(is_active AND current_date >= effective_from AND (effective_to IS NULL OR current_date <= effective_to))"
)


@ROUTER.get("/policies", summary="Danh sách chính sách")
async def liet_ke_cs(
    pool: Pool,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    q: str | None = None,
    policy_type: Annotated[PolicyType | None, Query(alias="policyType")] = None,
    brand_id: Annotated[int | None, Query(alias="brandId")] = None,
    category_id: Annotated[int | None, Query(alias="categoryId")] = None,
    active: bool | None = None,
) -> Trang[PolicyOut]:
    """`brandId`/`categoryId` lọc ĐÚNG giá trị cột — chính sách chung (NULL) không tự kèm vào;
    FE trang sản phẩm muốn cả chính sách chung thì gọi thêm không có bộ lọc."""
    dk: list[str] = []
    ts: list[Any] = []
    if q:
        them_dk(dk, ts, "title ILIKE {}", f"%{q}%")
    if policy_type:
        them_dk(dk, ts, "policy_type = {}", policy_type)
    if brand_id is not None:
        them_dk(dk, ts, "brand_id = {}", brand_id)
    if category_id is not None:
        them_dk(dk, ts, "category_id = {}", category_id)
    if active is not None:
        dk.append(CS_HIEU_LUC if active else f"NOT {CS_HIEU_LUC}")
    async with pool.acquire() as conn:
        rows, total = await liet_ke(
            conn, "policies", dieu_kien=dk, tham_so=ts, sap_xep="policy_type, id", limit=limit, offset=offset
        )
    return trang(PolicyOut, rows, total, limit, offset)


dang_ky_crud_le(
    ROUTER, duong_dan="/policies", bang="policies", ten="chính sách", model_in=PolicyIn, model_out=PolicyOut
)


@ROUTER.get("/service-packages", summary="Danh sách gói dịch vụ")
async def liet_ke_goi(
    pool: Pool,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    q: str | None = None,
    service_type: Annotated[ServiceType | None, Query(alias="serviceType")] = None,
    active: bool | None = None,
) -> Trang[ServicePackageOut]:
    dk: list[str] = []
    ts: list[Any] = []
    if q:
        them_dk(dk, ts, "name ILIKE {}", f"%{q}%")
    if service_type:
        them_dk(dk, ts, "service_type = {}", service_type)
    if active is not None:
        them_dk(dk, ts, "is_active = {}", active)
    async with pool.acquire() as conn:
        rows, total = await liet_ke(
            conn, "service_packages", dieu_kien=dk, tham_so=ts, sap_xep="service_type, id", limit=limit, offset=offset
        )
    return trang(ServicePackageOut, rows, total, limit, offset)


@ROUTER.get("/service-packages/quote", summary="Giá các gói dịch vụ mua kèm được cho một SKU")
async def bao_gia_goi(pool: Pool, variant_id: Annotated[int, Query(alias="variantId")]) -> list[BaoGiaGoiDichVuOut]:
    """Gói đang bật, khớp hãng/ngành hàng (NULL = mọi), giá máy trong [min, max] của gói.
    Giá gói = `price_vnd` cố định, hoặc round(giá máy × `price_percent` / 100) — làm tròn nửa lên."""
    async with pool.acquire() as conn:
        bt = await lay_bien_the(conn, variant_id)
        rows = await conn.fetch(
            """
            SELECT * FROM shop.service_packages
            WHERE is_active
              AND (brand_id IS NULL OR brand_id = $1)
              AND (category_id IS NULL OR category_id = $2)
              AND (min_product_price_vnd IS NULL OR $3 >= min_product_price_vnd)
              AND (max_product_price_vnd IS NULL OR $3 <= max_product_price_vnd)
            ORDER BY service_type, id
            """,
            bt["brand_id"],
            bt["category_id"],
            bt["price_vnd"],
        )
    gia = int(bt["price_vnd"])
    ket_qua = []
    for r in rows:
        gia_goi = r["price_vnd"] if r["price_vnd"] is not None else lam_tron(Decimal(gia) * r["price_percent"] / 100)
        ket_qua.append(
            BaoGiaGoiDichVuOut.model_validate({**dict(r), "product_price_vnd": gia, "quoted_price_vnd": gia_goi})
        )
    return ket_qua


dang_ky_crud_le(
    ROUTER,
    duong_dan="/service-packages",
    bang="service_packages",
    ten="gói dịch vụ",
    model_in=ServicePackageIn,
    model_out=ServicePackageOut,
)
