"""API đọc cho cửa hàng (trang danh sách kiểu TGDĐ, trang chi tiết, so sánh). Chỉ đọc, không ghi.

SQL và các khái niệm dùng chung (giá hiện tại, KM/trả góp áp dụng) ở `repo.py`.
"""

from decimal import Decimal
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Query

from portal.api.loi import du_lieu_khong_hop_le, khong_tim_thay
from portal.core.crud import LIMIT_MAC_DINH, Limit, Offset, Trang, ve_out
from portal.core.db.pool import get_pool
from portal.modules.products import repo
from portal.modules.products.contracts import (
    ColorOut,
    CompareItem,
    FaqOut,
    FeatureGroupOut,
    FeatureMini,
    InstallmentPlanOut,
    MediaOut,
    OsName,
    PhoneType,
    PolicyMini,
    ProductCard,
    ProductDetail,
    ProductOut,
    PromotionOut,
    RatingSummary,
    RelatedOut,
    ResolutionClass,
    ServicePackageMini,
    SortKey,
    SpecsOut,
    TagMini,
    VariantDetail,
)

ROUTER = APIRouter(prefix="/catalog")
Pool = Annotated[asyncpg.Pool, Depends(get_pool)]
SO_SANH_TOI_DA = 4


def _dk_bool(loc: repo.BoLoc, cot: str, v: bool | None) -> None:
    """`true` ⇒ phải có; `false` ⇒ không có HOẶC chưa khai (NULL) — máy thiếu thông số không lọt vào 'có'."""
    if v is True:
        loc.trong.append(f"{cot} IS TRUE")
    elif v is False:
        loc.trong.append(f"{cot} IS NOT TRUE")


def _q_like(q: str) -> str:
    """Thoát ký tự đại diện của LIKE — khách gõ '%' là tìm chữ '%', không phải 'mọi thứ'."""
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@ROUTER.get("/products", summary="Danh sách thẻ sản phẩm (bộ lọc kiểu TGDĐ)")
async def danh_sach(
    pool: Pool,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    sort: SortKey = "featured",
    brand_id: Annotated[list[int] | None, Query(alias="brandId")] = None,
    category_id: Annotated[int | None, Query(alias="categoryId")] = None,
    price_min: Annotated[int | None, Query(alias="priceMin", ge=0)] = None,
    price_max: Annotated[int | None, Query(alias="priceMax", ge=0)] = None,
    phone_type: Annotated[list[PhoneType] | None, Query(alias="phoneType")] = None,
    os: Annotated[list[OsName] | None, Query()] = None,
    ram_gb: Annotated[list[Decimal] | None, Query(alias="ramGb")] = None,
    storage_gb: Annotated[list[Decimal] | None, Query(alias="storageGb")] = None,
    tag: Annotated[list[str] | None, Query()] = None,
    feature: Annotated[list[str] | None, Query()] = None,
    resolution_class: Annotated[list[ResolutionClass] | None, Query(alias="resolutionClass")] = None,
    refresh_rate_min: Annotated[int | None, Query(alias="refreshRateMin", gt=0)] = None,
    charge_w_min: Annotated[int | None, Query(alias="chargeWMin", gt=0)] = None,
    has_5g: Annotated[bool | None, Query(alias="has5g")] = None,
    has_nfc: Annotated[bool | None, Query(alias="hasNfc")] = None,
    has_face_3d: Annotated[bool | None, Query(alias="hasFace3d")] = None,
    water_resistant: Annotated[bool | None, Query(alias="waterResistant")] = None,
    q: str | None = None,
) -> Trang[ProductCard]:
    """Một thẻ / SẢN PHẨM. Mọi bộ lọc tuỳ chọn và kết hợp AND; bộ lọc nhiều giá trị là OR trong
    nhóm (`brandId=1&brandId=2`), riêng `feature` là AND (SP phải có ĐỦ mọi tính năng chọn).
    `priceMin/priceMax` so với giá thẻ (SKU rẻ nhất còn bán). `chargeWMin` 20 = sạc nhanh, 60 = siêu nhanh."""
    loc = repo.BoLoc()
    loc.trong.append("p.status IN ('selling', 'coming_soon')")
    if brand_id:
        loc.trong.append(f"p.brand_id = ANY({loc.ts_moi(brand_id)}::bigint[])")
    if category_id is not None:
        loc.trong.append(f"p.category_id = {loc.ts_moi(category_id)}")
    if phone_type:
        loc.trong.append(f"p.phone_type = ANY({loc.ts_moi(phone_type)}::text[])")
    if os:
        loc.trong.append(f"sp.os_name = ANY({loc.ts_moi(os)}::text[])")
    if ram_gb:
        loc.trong.append(
            "EXISTS (SELECT 1 FROM shop.product_variants v WHERE v.product_id = p.id "
            f"AND v.ram_gb = ANY({loc.ts_moi(ram_gb)}::numeric[]))"
        )
    if storage_gb:
        loc.trong.append(
            "EXISTS (SELECT 1 FROM shop.product_variants v WHERE v.product_id = p.id "
            f"AND v.storage_gb = ANY({loc.ts_moi(storage_gb)}::numeric[]))"
        )
    if tag:
        loc.trong.append(
            "EXISTS (SELECT 1 FROM shop.product_tags pt JOIN shop.tags t ON t.id = pt.tag_id "
            f"WHERE pt.product_id = p.id AND t.slug = ANY({loc.ts_moi(tag)}::text[]))"
        )
    if feature:
        # slug chỉ duy nhất TRONG một feature_group ⇒ đếm slug khác nhau, không đếm hàng.
        slugs = list(dict.fromkeys(feature))
        loc.trong.append(
            "(SELECT count(DISTINCT f.slug) FROM shop.product_features pf JOIN shop.features f ON f.id = pf.feature_id "
            f"WHERE pf.product_id = p.id AND f.slug = ANY({loc.ts_moi(slugs)}::text[])) = {loc.ts_moi(len(slugs))}"
        )
    if resolution_class:
        loc.trong.append(f"sp.resolution_class = ANY({loc.ts_moi(resolution_class)}::text[])")
    if refresh_rate_min is not None:
        loc.trong.append(f"sp.refresh_rate_hz >= {loc.ts_moi(refresh_rate_min)}")
    if charge_w_min is not None:
        loc.trong.append(f"sp.max_charge_w >= {loc.ts_moi(charge_w_min)}")
    _dk_bool(loc, "sp.has_5g", has_5g)
    _dk_bool(loc, "sp.has_nfc", has_nfc)
    _dk_bool(loc, "sp.has_face_3d", has_face_3d)
    _dk_bool(loc, "(sp.ip_rating IS NOT NULL)", water_resistant)
    if q and q.strip():
        loc.trong.append(f"unaccent(lower(p.name || ' ' || b.name)) ILIKE unaccent(lower({loc.ts_moi(_q_like(q))}))")
    if price_min is not None:
        loc.ngoai.append(f"price_vnd >= {loc.ts_moi(price_min)}")
    if price_max is not None:
        loc.ngoai.append(f"price_vnd <= {loc.ts_moi(price_max)}")

    async with pool.acquire() as conn:
        rows, total = await repo.liet_ke_the(conn, loc, sort, limit, offset)
    return Trang[ProductCard](
        items=[ProductCard.model_validate(repo.ve_the(r)) for r in rows], total=total, limit=limit, offset=offset
    )


@ROUTER.get("/compare", summary="So sánh tối đa 4 sản phẩm")
async def so_sanh(pool: Pool, ids: Annotated[list[int], Query()]) -> list[CompareItem]:
    """Giữ thứ tự client gửi (cột so sánh theo thứ tự khách chọn); id không có/nháp bị bỏ qua."""
    ids = list(dict.fromkeys(ids))
    if len(ids) > SO_SANH_TOI_DA:
        raise du_lieu_khong_hop_le(f"Chỉ so sánh tối đa {SO_SANH_TOI_DA} sản phẩm")
    async with pool.acquire() as conn:
        the = await repo.the_theo_id(conn, ids)
        specs = {
            r["product_id"]: r
            for r in await conn.fetch("SELECT * FROM shop.phone_specs WHERE product_id = ANY($1::bigint[])", ids)
        }
    return [
        CompareItem(
            product=ProductCard.model_validate(repo.ve_the(the[i])),
            specs=ve_out(SpecsOut, specs[i]) if i in specs else None,
        )
        for i in ids
        if i in the
    ]


@ROUTER.get("/products/{slug}", summary="Trang chi tiết sản phẩm")
async def chi_tiet(slug: str, pool: Pool) -> ProductDetail:
    """Gom mọi thứ trang chi tiết cần trong một lượt: số câu SQL cố định (~14), không phụ thuộc
    số SKU/KM. SP nháp coi như không tồn tại (404)."""
    async with pool.acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
        sp = await conn.fetchrow(repo.SQL_SP, slug)
        if sp is None:
            raise khong_tim_thay("sản phẩm", slug)
        pid = sp["id"]
        the = (await repo.the_theo_id(conn, [pid]))[pid]
        mau = await conn.fetch("SELECT * FROM shop.product_colors WHERE product_id = $1 ORDER BY sort_order, id", pid)
        sku = await conn.fetch(repo.SQL_SKU, pid)
        thong_so = await conn.fetchrow("SELECT * FROM shop.phone_specs WHERE product_id = $1", pid)
        tinh_nang = await conn.fetch(repo.SQL_TINH_NANG, pid)
        nhan = await conn.fetch(repo.SQL_NHAN, pid)
        media = await conn.fetch("SELECT * FROM shop.product_media WHERE product_id = $1 ORDER BY sort_order, id", pid)
        faq = await conn.fetch(repo.SQL_FAQ, pid)
        km = await conn.fetch(repo.SQL_KM, pid)
        tra_gop = await conn.fetch(repo.SQL_TRA_GOP, pid)
        chinh_sach = await conn.fetch(repo.SQL_CHINH_SACH, sp["brand_id"], sp["category_id"])
        goi_dv = await conn.fetch(repo.SQL_GOI_DV, sp["brand_id"], sp["category_id"], the["price_vnd"])
        lien_quan = await conn.fetch(repo.SQL_LIEN_QUAN, pid)
        the_lq = await repo.the_theo_id(conn, [r["related_product_id"] for r in lien_quan])
        danh_gia = await conn.fetch(repo.SQL_DANH_GIA, pid)

    nhom: dict[str, list[FeatureMini]] = {}
    for r in tinh_nang:
        nhom.setdefault(r["feature_group"], []).append(ve_out(FeatureMini, r))

    phan_bo = {str(s): 0 for s in range(1, 6)}
    for r in danh_gia:
        phan_bo[str(r["rating"])] = r["n"]
    dem = sum(phan_bo.values())
    tb = round(sum(int(s) * n for s, n in phan_bo.items()) / dem, 1) if dem else None

    return ProductDetail(
        product=ve_out(ProductOut, sp),
        brand={"id": sp["brand_id"], "name": sp["b_name"], "slug": sp["b_slug"]},
        category={"id": sp["category_id"], "name": sp["c_name"], "slug": sp["c_slug"]},
        series={"id": sp["s_id"], "name": sp["s_name"], "slug": sp["s_slug"]} if sp["s_id"] else None,
        price_vnd=the["price_vnd"],
        list_price_vnd=the["list_price_vnd"],
        discount_percent=the["discount_percent"],
        has_installment_0=the["has_installment_0"],
        gift_value_vnd=the["gift_value_vnd"],
        colors=[ve_out(ColorOut, r) for r in mau],
        variants=[ve_out(VariantDetail, r) for r in sku],
        specs=ve_out(SpecsOut, thong_so) if thong_so else None,
        features=[FeatureGroupOut(group=g, items=ds) for g, ds in nhom.items()],
        tags=[ve_out(TagMini, r) for r in nhan],
        media=[ve_out(MediaOut, r) for r in media],
        faqs=[ve_out(FaqOut, r) for r in faq],
        promotions=[ve_out(PromotionOut, r) for r in km],
        installment_plans=[
            InstallmentPlanOut.model_validate(
                {
                    **dict(r),
                    "partner": {
                        "id": r["partner_id"],
                        "code": r["fp_code"],
                        "name": r["fp_name"],
                        "partner_type": r["fp_type"],
                    },
                }
            )
            for r in tra_gop
        ],  # fmt: skip
        policies=[ve_out(PolicyMini, r) for r in chinh_sach],
        service_packages=[ve_out(ServicePackageMini, r) for r in goi_dv],
        related=[
            RelatedOut(
                relation_type=r["relation_type"],
                sort_order=r["sort_order"],
                product=ProductCard.model_validate(repo.ve_the(the_lq[r["related_product_id"]])),
            )
            for r in lien_quan
            if r["related_product_id"] in the_lq
        ],
        rating=RatingSummary(avg=tb, count=dem, distribution=phan_bo),
    )
