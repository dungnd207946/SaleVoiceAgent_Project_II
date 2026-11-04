"""Quản trị sản phẩm: SP → màu → SKU, thông số, tính năng/nhãn, media, FAQ, SP liên quan.

Route đọc cho cửa hàng nằm ở `cua_hang.py`, gắn vào cùng `ROUTER`.
"""

from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, Query, Response

from portal.api.loi import du_lieu_khong_hop_le, khong_tim_thay
from portal.core.crud import (
    LIMIT_MAC_DINH,
    CamelIn,
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
from portal.core.dto import CamelOut
from portal.modules.products.contracts import (
    ColorIn,
    ColorOut,
    FaqIn,
    FaqOut,
    FaqTaoIn,
    FeatureIdsIn,
    FeatureMini,
    MediaIn,
    MediaOut,
    PriceHistoryOut,
    ProductIn,
    ProductOut,
    ProductStatus,
    RelationIn,
    RelationOut,
    SpecsIn,
    SpecsOut,
    TagIdsIn,
    TagMini,
    VariantIn,
    VariantOut,
)
from portal.modules.products.cua_hang import ROUTER as CUA_HANG

ROUTER = APIRouter()
Pool = Annotated[asyncpg.Pool, Depends(get_pool)]


async def _phai_co_sp(conn: asyncpg.Connection, product_id: int) -> None:
    """404 rõ ràng thay vì để FK báo 409 — client gõ sai id SP cần biết là 'không có', không phải 'xung đột'."""
    if not await conn.fetchval("SELECT true FROM shop.products WHERE id = $1", product_id):
        raise khong_tim_thay("sản phẩm", product_id)


async def _kiem_mau(conn: asyncpg.Connection, product_id: int, color_id: int | None) -> None:
    """Màu phải thuộc chính SP. DB có FK ghép (product_id, color_id) nhưng lỗi FK là 409 mơ hồ —
    kiểm ở đây để trả 422 nói đúng trường sai."""
    if color_id is None:
        return
    if not await conn.fetchval(
        "SELECT true FROM shop.product_colors WHERE id = $1 AND product_id = $2", color_id, product_id
    ):
        raise du_lieu_khong_hop_le(f"colorId {color_id} không thuộc sản phẩm #{product_id}")


# ---------------------------------------------------------------------------
# Sản phẩm
# ---------------------------------------------------------------------------
ProductPatch = ban_sua(ProductIn)


@ROUTER.get("/products", summary="Danh sách sản phẩm (quản trị)")
async def liet_ke_sp(
    pool: Pool,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    brand_id: Annotated[int | None, Query(alias="brandId")] = None,
    category_id: Annotated[int | None, Query(alias="categoryId")] = None,
    series_id: Annotated[int | None, Query(alias="seriesId")] = None,
    status: ProductStatus | None = None,
    q: str | None = None,
) -> Trang[ProductOut]:
    dk: list[str] = []
    ts: list[Any] = []
    for cot, v in (("brand_id", brand_id), ("category_id", category_id), ("series_id", series_id), ("status", status)):
        if v is not None:
            ts.append(v)
            dk.append(f"{cot} = ${len(ts)}")
    if q:
        ts.append(f"%{q}%")
        dk.append(f"(name ILIKE ${len(ts)} OR slug ILIKE ${len(ts)} OR model_code ILIKE ${len(ts)})")
    async with pool.acquire() as conn:
        rows, total = await liet_ke(
            conn, "products", dieu_kien=dk, tham_so=ts, sap_xep="id DESC", limit=limit, offset=offset
        )
    return Trang[ProductOut](items=[ve_out(ProductOut, r) for r in rows], total=total, limit=limit, offset=offset)


@ROUTER.get("/products/{id}", summary="Chi tiết sản phẩm (quản trị)")
async def lay_sp(id: int, pool: Pool) -> ProductOut:
    async with pool.acquire() as conn:
        hang = await lay(conn, "products", id)
    if hang is None:
        raise khong_tim_thay("sản phẩm", id)
    return ve_out(ProductOut, hang)


@ROUTER.post("/products", status_code=201, summary="Tạo sản phẩm")
async def tao_sp(body: ProductIn, pool: Pool) -> ProductOut:
    async with tx(pool) as conn:
        hang = await chen(conn, "products", body.model_dump())
    return ve_out(ProductOut, hang)


@ROUTER.patch("/products/{id}", summary="Sửa sản phẩm")
async def sua_sp(id: int, body: ProductPatch, pool: Pool) -> ProductOut:  # type: ignore[valid-type]
    async with tx(pool) as conn:
        hang = await sua(conn, "products", id, body.model_dump(exclude_unset=True))
    if hang is None:
        raise khong_tim_thay("sản phẩm", id)
    return ve_out(ProductOut, hang)


@ROUTER.delete("/products/{id}", status_code=204, summary="Xoá sản phẩm (cascade màu/SKU/media...)")
async def xoa_sp(id: int, pool: Pool) -> Response:
    async with tx(pool) as conn:
        if not await xoa(conn, "products", id):
            raise khong_tim_thay("sản phẩm", id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Bảng con của SP: màu · SKU · media · FAQ — cùng một khuôn 4 route
# ---------------------------------------------------------------------------
def _dang_ky_con(
    *,
    con: str,
    duong_dan_rieng: str,
    bang: str,
    ten: str,
    model_in: type[CamelIn],
    model_out: type[CamelOut],
    sap_xep: str = "sort_order, id",
    kiem_mau: bool = False,
) -> None:
    """`GET/POST /products/{id}/<con>` + `PATCH/DELETE <duong_dan_rieng>/{id}`.

    `kiem_mau`: bảng có `color_id` ⇒ màu phải thuộc cùng SP, cả lúc tạo lẫn lúc sửa.
    """
    model_sua = ban_sua(model_in)

    async def liet_ke_route(id: int, pool: Pool) -> list[model_out]:  # type: ignore[valid-type]
        async with pool.acquire() as conn:
            await _phai_co_sp(conn, id)
            rows = await conn.fetch(f"SELECT * FROM shop.{bang} WHERE product_id = $1 ORDER BY {sap_xep}", id)
        return [ve_out(model_out, r) for r in rows]

    async def tao_route(id: int, body: model_in, pool: Pool) -> model_out:  # type: ignore[valid-type]
        du_lieu = body.model_dump()
        async with tx(pool) as conn:
            await _phai_co_sp(conn, id)
            if kiem_mau:
                await _kiem_mau(conn, id, du_lieu.get("color_id"))
            hang = await chen(conn, bang, {"product_id": id, **du_lieu})
        return ve_out(model_out, hang)

    async def sua_route(id: int, body: model_sua, pool: Pool) -> model_out:  # type: ignore[valid-type]
        du_lieu = body.model_dump(exclude_unset=True)
        async with tx(pool) as conn:
            cu = await lay(conn, bang, id)
            if cu is None:
                raise khong_tim_thay(ten, id)
            if kiem_mau and "color_id" in du_lieu:
                await _kiem_mau(conn, cu["product_id"], du_lieu["color_id"])
            hang = await sua(conn, bang, id, du_lieu)
        return ve_out(model_out, hang)

    async def xoa_route(id: int, pool: Pool) -> Response:
        async with tx(pool) as conn:
            if not await xoa(conn, bang, id):
                raise khong_tim_thay(ten, id)
        return Response(status_code=204)

    ROUTER.add_api_route(f"/products/{{id}}/{con}", liet_ke_route, methods=["GET"], summary=f"Danh sách {ten}")
    ROUTER.add_api_route(f"/products/{{id}}/{con}", tao_route, methods=["POST"], status_code=201, summary=f"Thêm {ten}")
    ROUTER.add_api_route(f"{duong_dan_rieng}/{{id}}", sua_route, methods=["PATCH"], summary=f"Sửa {ten}")
    ROUTER.add_api_route(
        f"{duong_dan_rieng}/{{id}}", xoa_route, methods=["DELETE"], status_code=204, summary=f"Xoá {ten}"
    )


_dang_ky_con(
    con="colors", duong_dan_rieng="/product-colors", bang="product_colors", ten="màu", model_in=ColorIn,
    model_out=ColorOut,
)  # fmt: skip
_dang_ky_con(
    con="variants", duong_dan_rieng="/variants", bang="product_variants", ten="phiên bản", model_in=VariantIn,
    model_out=VariantOut, kiem_mau=True,
)  # fmt: skip
_dang_ky_con(
    con="media", duong_dan_rieng="/product-media", bang="product_media", ten="media", model_in=MediaIn,
    model_out=MediaOut, kiem_mau=True,
)  # fmt: skip
_dang_ky_con(
    con="faqs", duong_dan_rieng="/faqs", bang="faqs", ten="FAQ", model_in=FaqIn, model_out=FaqOut,
)  # fmt: skip


@ROUTER.get("/variants/{id}", summary="Chi tiết phiên bản")
async def lay_sku(id: int, pool: Pool) -> VariantOut:
    async with pool.acquire() as conn:
        hang = await lay(conn, "product_variants", id)
    if hang is None:
        raise khong_tim_thay("phiên bản", id)
    return ve_out(VariantOut, hang)


@ROUTER.get("/variants/{id}/price-history", summary="Lịch sử giá (trigger DB tự ghi mỗi lần đổi giá)")
async def lich_su_gia(id: int, pool: Pool) -> list[PriceHistoryOut]:
    async with pool.acquire() as conn:
        if await lay(conn, "product_variants", id) is None:
            raise khong_tim_thay("phiên bản", id)
        rows = await conn.fetch(
            "SELECT * FROM shop.price_history WHERE variant_id = $1 ORDER BY changed_at DESC, id DESC", id
        )
    return [ve_out(PriceHistoryOut, r) for r in rows]


# ---------------------------------------------------------------------------
# FAQ chung (product_id NULL) — cùng bảng với FAQ theo SP
# ---------------------------------------------------------------------------
@ROUTER.get("/faqs", summary="Danh sách FAQ (lọc theo SP hoặc chỉ FAQ chung)")
async def liet_ke_faq(
    pool: Pool,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    product_id: Annotated[int | None, Query(alias="productId")] = None,
    general: bool = False,
) -> Trang[FaqOut]:
    dk: list[str] = []
    ts: list[Any] = []
    if product_id is not None:
        ts.append(product_id)
        dk.append("product_id = $1")
    elif general:
        dk.append("product_id IS NULL")
    async with pool.acquire() as conn:
        rows, total = await liet_ke(
            conn, "faqs", dieu_kien=dk, tham_so=ts, sap_xep="sort_order, id", limit=limit, offset=offset
        )
    return Trang[FaqOut](items=[ve_out(FaqOut, r) for r in rows], total=total, limit=limit, offset=offset)


@ROUTER.post("/faqs", status_code=201, summary="Tạo FAQ (không productId = FAQ chung)")
async def tao_faq(body: FaqTaoIn, pool: Pool) -> FaqOut:
    async with tx(pool) as conn:
        if body.product_id is not None:
            await _phai_co_sp(conn, body.product_id)
        hang = await chen(conn, "faqs", body.model_dump())
    return ve_out(FaqOut, hang)


# ---------------------------------------------------------------------------
# Thông số (1-1)
# ---------------------------------------------------------------------------
_COT_THONG_SO = list(SpecsIn.model_fields)


@ROUTER.get("/products/{id}/specs", summary="Thông số kỹ thuật")
async def lay_thong_so(id: int, pool: Pool) -> SpecsOut:
    async with pool.acquire() as conn:
        await _phai_co_sp(conn, id)
        hang = await lay(conn, "phone_specs", id, khoa="product_id")
    if hang is None:
        raise khong_tim_thay("thông số của sản phẩm", id)
    return ve_out(SpecsOut, hang)


@ROUTER.put("/products/{id}/specs", summary="Ghi trọn thông số (upsert)")
async def ghi_thong_so(id: int, body: SpecsIn, pool: Pool) -> SpecsOut:
    du_lieu = body.model_dump()
    cot = ", ".join(_COT_THONG_SO)
    gia_tri = ", ".join(f"${i}" for i in range(2, len(_COT_THONG_SO) + 2))
    gan = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COT_THONG_SO)
    async with tx(pool) as conn:
        await _phai_co_sp(conn, id)
        hang = await conn.fetchrow(
            f"INSERT INTO shop.phone_specs (product_id, {cot}) VALUES ($1, {gia_tri}) "
            f"ON CONFLICT (product_id) DO UPDATE SET {gan} RETURNING *",
            id,
            *(du_lieu[c] for c in _COT_THONG_SO),
        )
    return ve_out(SpecsOut, hang)


# ---------------------------------------------------------------------------
# Tập tính năng / nhãn: PUT thay trọn
# ---------------------------------------------------------------------------
async def _thay_tap(conn: asyncpg.Connection, bang: str, cot: str, product_id: int, ids: list[int]) -> None:
    """Xoá phần không còn + thêm phần mới; hàng giữ nguyên không bị đụng (trigger KB không chạy thừa).
    id không tồn tại ⇒ FK nổ ⇒ 409, cả giao dịch lùi."""
    await conn.execute(f"DELETE FROM shop.{bang} WHERE product_id = $1 AND {cot} <> ALL($2::bigint[])", product_id, ids)
    await conn.execute(
        f"INSERT INTO shop.{bang} (product_id, {cot}) SELECT $1, unnest($2::bigint[]) ON CONFLICT DO NOTHING",
        product_id,
        ids,
    )


@ROUTER.put("/products/{id}/features", summary="Thay tập tính năng của SP")
async def ghi_tinh_nang(id: int, body: FeatureIdsIn, pool: Pool) -> list[FeatureMini]:
    async with tx(pool) as conn:
        await _phai_co_sp(conn, id)
        await _thay_tap(conn, "product_features", "feature_id", id, list(dict.fromkeys(body.feature_ids)))
        rows = await conn.fetch(
            "SELECT f.id, f.feature_group, f.name, f.slug FROM shop.product_features pf "
            "JOIN shop.features f ON f.id = pf.feature_id WHERE pf.product_id = $1 "
            "ORDER BY f.feature_group, f.sort_order, f.id",
            id,
        )
    return [ve_out(FeatureMini, r) for r in rows]


@ROUTER.put("/products/{id}/tags", summary="Thay tập nhãn của SP")
async def ghi_nhan(id: int, body: TagIdsIn, pool: Pool) -> list[TagMini]:
    async with tx(pool) as conn:
        await _phai_co_sp(conn, id)
        await _thay_tap(conn, "product_tags", "tag_id", id, list(dict.fromkeys(body.tag_ids)))
        rows = await conn.fetch(
            "SELECT t.id, t.kind, t.slug, t.name FROM shop.product_tags pt JOIN shop.tags t ON t.id = pt.tag_id "
            "WHERE pt.product_id = $1 ORDER BY t.kind, t.name",
            id,
        )
    return [ve_out(TagMini, r) for r in rows]


# ---------------------------------------------------------------------------
# SP liên quan: PUT thay trọn
# ---------------------------------------------------------------------------
_SQL_LIEN_QUAN = """
SELECT r.related_product_id, r.relation_type, r.sort_order, p.slug, p.name, p.status
FROM shop.product_relations r JOIN shop.products p ON p.id = r.related_product_id
WHERE r.product_id = $1 ORDER BY r.relation_type, r.sort_order, r.related_product_id
"""


@ROUTER.get("/products/{id}/relations", summary="SP liên quan")
async def lay_lien_quan(id: int, pool: Pool) -> list[RelationOut]:
    async with pool.acquire() as conn:
        await _phai_co_sp(conn, id)
        rows = await conn.fetch(_SQL_LIEN_QUAN, id)
    return [ve_out(RelationOut, r) for r in rows]


@ROUTER.put("/products/{id}/relations", summary="Thay trọn danh sách SP liên quan")
async def ghi_lien_quan(id: int, body: list[RelationIn], pool: Pool) -> list[RelationOut]:
    async with tx(pool) as conn:
        await _phai_co_sp(conn, id)
        await conn.execute("DELETE FROM shop.product_relations WHERE product_id = $1", id)
        if body:
            await conn.executemany(
                "INSERT INTO shop.product_relations (product_id, related_product_id, relation_type, sort_order) "
                "VALUES ($1, $2, $3, $4)",
                [(id, r.related_product_id, r.relation_type, r.sort_order) for r in body],
            )
        rows = await conn.fetch(_SQL_LIEN_QUAN, id)
    return [ve_out(RelationOut, r) for r in rows]


ROUTER.include_router(CUA_HANG)
