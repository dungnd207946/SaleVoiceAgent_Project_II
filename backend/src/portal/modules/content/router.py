"""Bài viết dài (giới thiệu, đánh giá, tin, tư vấn mua) và liên kết bài ↔ sản phẩm."""

from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, Query

from portal.api.loi import khong_tim_thay
from portal.core.ban_hang import dang_ky_crud_le, them_dk, trang
from portal.core.crud import LIMIT_MAC_DINH, Limit, Offset, Trang, lay, liet_ke
from portal.core.db.pool import get_pool
from portal.core.db.session import tx
from portal.modules.content.contracts import (
    ArticleIn,
    ArticleKind,
    ArticleOut,
    ArticleProductOut,
    ArticleProductsIn,
)

ROUTER = APIRouter()
Pool = Annotated[asyncpg.Pool, Depends(get_pool)]

TEN = "bài viết"
DA_DANG = "(published_at IS NOT NULL AND published_at <= now())"


@ROUTER.get("/articles", summary="Danh sách bài viết")
async def liet_ke_bai(
    pool: Pool,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    q: str | None = None,
    kind: ArticleKind | None = None,
    published: bool | None = None,
    product_id: Annotated[int | None, Query(alias="productId")] = None,
) -> Trang[ArticleOut]:
    """`published=true` = đã tới giờ đăng (bài hẹn giờ tương lai coi là chưa đăng)."""
    dk: list[str] = []
    ts: list[Any] = []
    if q:
        them_dk(dk, ts, "title ILIKE {}", f"%{q}%")
    if kind:
        them_dk(dk, ts, "kind = {}", kind)
    if published is not None:
        dk.append(DA_DANG if published else f"NOT {DA_DANG}")
    if product_id is not None:
        them_dk(
            dk,
            ts,
            "EXISTS (SELECT 1 FROM shop.article_products ap WHERE ap.article_id = articles.id AND ap.product_id = {})",
            product_id,
        )
    async with pool.acquire() as conn:
        rows, total = await liet_ke(
            conn,
            "articles",
            dieu_kien=dk,
            tham_so=ts,
            sap_xep="published_at DESC NULLS LAST, id DESC",
            limit=limit,
            offset=offset,
        )
    return trang(ArticleOut, rows, total, limit, offset)


async def _san_pham_cua_bai(conn: asyncpg.Connection, id_: int) -> list[ArticleProductOut]:
    rows = await conn.fetch(
        """
        SELECT p.id AS product_id, p.name, p.slug
        FROM shop.article_products ap JOIN shop.products p ON p.id = ap.product_id
        WHERE ap.article_id = $1 ORDER BY p.id
        """,
        id_,
    )
    return [ArticleProductOut.model_validate(dict(r)) for r in rows]


async def _phai_co(conn: asyncpg.Connection, id_: int) -> None:
    if await lay(conn, "articles", id_) is None:
        raise khong_tim_thay(TEN, id_)


@ROUTER.get("/articles/{id}/products", summary="Sản phẩm gắn với bài viết")
async def doc_sp(id: int, pool: Pool) -> list[ArticleProductOut]:
    async with pool.acquire() as conn:
        await _phai_co(conn, id)
        return await _san_pham_cua_bai(conn, id)


@ROUTER.put("/articles/{id}/products", summary="Thay toàn bộ sản phẩm gắn với bài viết")
async def thay_sp(id: int, body: ArticleProductsIn, pool: Pool) -> list[ArticleProductOut]:
    """Xoá hết rồi chèn lại trong một giao dịch; id trùng tự gộp. Sản phẩm không tồn tại ⇒ 409 (FK)."""
    async with tx(pool) as conn:
        await _phai_co(conn, id)
        await conn.execute("DELETE FROM shop.article_products WHERE article_id = $1", id)
        await conn.execute(
            "INSERT INTO shop.article_products (article_id, product_id) SELECT $1, unnest($2::bigint[])",
            id,
            sorted(set(body.product_ids)),
        )
        return await _san_pham_cua_bai(conn, id)


dang_ky_crud_le(ROUTER, duong_dan="/articles", bang="articles", ten=TEN, model_in=ArticleIn, model_out=ArticleOut)
