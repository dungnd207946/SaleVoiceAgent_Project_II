"""Mảnh dùng chung của các module bán hàng (promotions · finance · policies · content).

"Đối tượng áp dụng" (SP / SKU / hãng / ngành hàng), giá hiện hành của biến thể, làm tròn
tiền và CRUD có route danh sách tự viết. Ở `core/` để module không import ruột nhau.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Self

import asyncpg
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, model_validator

from portal.api.loi import khong_tim_thay
from portal.core.crud import CamelIn, Trang, ban_sua, chen, lay, sua, ve_out, xoa
from portal.core.db.pool import get_pool
from portal.core.db.session import tx
from portal.core.dto import CamelOut

COT_DOI_TUONG = ("product_id", "variant_id", "brand_id", "category_id")


class TargetIn(CamelIn):
    """Đúng MỘT khoá mỗi mục — DB CHECK `num_nonnulls(...) = 1` cũng chặn, nhưng báo sớm
    ở đây thì FE nhận 422 trỏ đúng phần tử thay vì lỗi ràng buộc chung chung."""

    product_id: int | None = None
    variant_id: int | None = None
    brand_id: int | None = None
    category_id: int | None = None

    @model_validator(mode="after")
    def _dung_mot_khoa(self) -> Self:
        if sum(getattr(self, c) is not None for c in COT_DOI_TUONG) != 1:
            raise ValueError("Mỗi mục phải có đúng một trong productId | variantId | brandId | categoryId")
        return self


class TargetOut(CamelOut):
    id: int
    product_id: int | None
    variant_id: int | None
    brand_id: int | None
    category_id: int | None


async def doc_targets(conn: asyncpg.Connection, bang: str, khoa_cha: str, id_: int) -> list[TargetOut]:
    rows = await conn.fetch(
        f'SELECT id, {", ".join(COT_DOI_TUONG)} FROM shop."{bang}" WHERE "{khoa_cha}" = $1 ORDER BY id', id_
    )
    return [ve_out(TargetOut, r) for r in rows]


async def thay_targets(
    conn: asyncpg.Connection, bang: str, khoa_cha: str, id_: int, muc: list[TargetIn]
) -> list[TargetOut]:
    """Thay TOÀN BỘ đối tượng (PUT): xoá hết rồi chèn lại — gọi trong `tx` để nguyên tử."""
    await conn.execute(f'DELETE FROM shop."{bang}" WHERE "{khoa_cha}" = $1', id_)
    da_co: set[tuple] = set()
    for m in muc:
        khoa = tuple(getattr(m, c) for c in COT_DOI_TUONG)
        if khoa in da_co:  # bảng không có UNIQUE — bỏ trùng để không nhân đôi khi khớp
            continue
        da_co.add(khoa)
        await conn.execute(
            f'INSERT INTO shop."{bang}" ("{khoa_cha}", {", ".join(COT_DOI_TUONG)}) VALUES ($1, $2, $3, $4, $5)',
            id_,
            *khoa,
        )
    return await doc_targets(conn, bang, khoa_cha, id_)


def dk_ap_dung(t: str, variant: str, product: str, brand: str, category: str) -> str:
    """Điều kiện SQL: dòng target `t` khớp SKU/SP/hãng/ngành hàng (tham số là biểu thức SQL)."""
    return (
        f"({t}.variant_id = {variant} OR {t}.product_id = {product} "
        f"OR {t}.brand_id = {brand} OR {t}.category_id = {category})"
    )


async def lay_bien_the(conn: asyncpg.Connection, variant_id: int) -> asyncpg.Record:
    """SKU + khoá SP/hãng/ngành hàng + giá bán hiện tại (`coalesce(sale, list)`)."""
    hang = await conn.fetchrow(
        """
        SELECT v.id AS variant_id, v.product_id, p.brand_id, p.category_id,
               coalesce(v.sale_price_vnd, v.list_price_vnd) AS price_vnd
        FROM shop.product_variants v JOIN shop.products p ON p.id = v.product_id
        WHERE v.id = $1
        """,
        variant_id,
    )
    if hang is None:
        raise khong_tim_thay("biến thể", variant_id)
    return hang


def lam_tron(x: Decimal) -> int:
    """Làm tròn nửa lên (kiểu kế toán) — `round()` của Python là làm tròn chẵn."""
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def trang[T: BaseModel](model: type[T], rows: list[asyncpg.Record], total: int, limit: int, offset: int) -> Trang[T]:
    return Trang[model](items=[ve_out(model, r) for r in rows], total=total, limit=limit, offset=offset)  # type: ignore[valid-type]


def dang_ky_crud_le(
    router: APIRouter,
    *,
    duong_dan: str,
    bang: str,
    ten: str,
    model_in: type[CamelIn],
    model_out: type[CamelOut],
) -> None:
    """get/create/patch/delete như `dang_ky_crud` — dùng khi route danh sách phải tự viết
    (lọc text/boolean/khoảng thời gian mà `loc` số nguyên không diễn đạt được).

    Đăng ký SAU các route tĩnh `/{duong_dan}/xxx` — `{id}` kiểu int sẽ nuốt chúng thành 422.
    """
    model_sua = ban_sua(model_in)
    Pool = Annotated[asyncpg.Pool, Depends(get_pool)]

    async def lay_route(id: int, pool: Pool) -> model_out:  # type: ignore[valid-type]
        async with pool.acquire() as conn:
            hang = await lay(conn, bang, id)
        if hang is None:
            raise khong_tim_thay(ten, id)
        return ve_out(model_out, hang)

    async def tao_route(body: model_in, pool: Pool) -> model_out:  # type: ignore[valid-type]
        # Trường client KHÔNG gửi và đang None ⇒ bỏ khỏi INSERT để DB dùng DEFAULT của cột
        # (vd starts_at DEFAULT now()); `null` gửi tường minh thì vẫn ghi NULL.
        du_lieu = {k: v for k, v in body.model_dump().items() if v is not None or k in body.model_fields_set}
        async with tx(pool) as conn:
            hang = await chen(conn, bang, du_lieu)
        return ve_out(model_out, hang)

    async def sua_route(id: int, body: model_sua, pool: Pool) -> model_out:  # type: ignore[valid-type]
        async with tx(pool) as conn:
            hang = await sua(conn, bang, id, body.model_dump(exclude_unset=True))
        if hang is None:
            raise khong_tim_thay(ten, id)
        return ve_out(model_out, hang)

    async def xoa_route(id: int, pool: Pool) -> Response:
        async with tx(pool) as conn:
            if not await xoa(conn, bang, id):
                raise khong_tim_thay(ten, id)
        return Response(status_code=204)

    router.add_api_route(f"{duong_dan}/{{id}}", lay_route, methods=["GET"], summary=f"Chi tiết {ten}")
    router.add_api_route(duong_dan, tao_route, methods=["POST"], status_code=201, summary=f"Tạo {ten}")
    router.add_api_route(f"{duong_dan}/{{id}}", sua_route, methods=["PATCH"], summary=f"Sửa {ten}")
    router.add_api_route(f"{duong_dan}/{{id}}", xoa_route, methods=["DELETE"], status_code=204, summary=f"Xoá {ten}")


def them_dk(dk: list[str], ts: list[Any], mau: str, gia_tri: Any) -> None:
    """Thêm điều kiện có MỘT tham số: `mau` chứa `{}` thay bằng `$n` kế tiếp."""
    ts.append(gia_tri)
    dk.append(mau.format(f"${len(ts)}"))
