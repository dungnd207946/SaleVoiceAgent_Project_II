"""Đánh giá & hỏi đáp sản phẩm.

`products.rating_avg/rating_count` là cache — chỉ tính trên đánh giá `published`, và được
tính lại trong CÙNG giao dịch với mọi thay đổi đánh giá (`tinh_lai_diem`), nên không bao giờ
lệch khỏi dữ liệu gốc lâu hơn một commit.
"""

from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, Query, Response

from portal.api.loi import khong_tim_thay
from portal.core.crud import LIMIT_MAC_DINH, Limit, Offset, Trang, chen, lay, liet_ke, sua, ve_out
from portal.core.db.pool import get_pool
from portal.core.db.session import tx
from portal.modules.reviews.contracts import (
    QuestionIn,
    QuestionOut,
    QuestionPatch,
    ReviewIn,
    ReviewOut,
    ReviewPatch,
    TrangThai,
)

ROUTER = APIRouter()
Pool = Annotated[asyncpg.Pool, Depends(get_pool)]


async def tinh_lai_diem(conn: asyncpg.Connection, product_id: int) -> None:
    """Tính lại điểm TB (1 chữ số thập phân) + số đánh giá published của một sản phẩm.

    Khoá hàng sản phẩm trước khi đếm: hai giao dịch cùng duyệt đánh giá của một máy sẽ
    xếp hàng, và câu đếm của giao dịch sau (READ COMMITTED, snapshot mới) thấy cả hai.
    """
    await conn.execute("SELECT 1 FROM shop.products WHERE id = $1 FOR UPDATE", product_id)
    await conn.execute(
        """
        UPDATE shop.products p
        SET rating_avg = s.tb, rating_count = s.so
        FROM (SELECT round(avg(rating), 1) AS tb, count(*) AS so
              FROM shop.product_reviews WHERE product_id = $1 AND status = 'published') s
        WHERE p.id = $1
        """,
        product_id,
    )


def _loc(**cot_gia_tri: Any) -> tuple[list[str], list[Any]]:
    dk: list[str] = []
    ts: list[Any] = []
    for cot, v in cot_gia_tri.items():
        if v is not None:
            ts.append(v)
            dk.append(f"{cot} = ${len(ts)}")
    return dk, ts


# ------------------------------------------------------------------ đánh giá


@ROUTER.get("/reviews", summary="Danh sách đánh giá")
async def liet_ke_danh_gia(
    pool: Pool,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    product_id: Annotated[int | None, Query(alias="productId")] = None,
    status: TrangThai | None = None,
    rating: Annotated[int | None, Query(ge=1, le=5)] = None,
) -> Trang[ReviewOut]:
    dk, ts = _loc(product_id=product_id, status=status, rating=rating)
    async with pool.acquire() as conn:
        rows, total = await liet_ke(
            conn,
            "product_reviews",
            dieu_kien=dk,
            tham_so=ts,
            sap_xep="created_at DESC, id DESC",
            limit=limit,
            offset=offset,
        )
    return Trang[ReviewOut](items=[ve_out(ReviewOut, r) for r in rows], total=total, limit=limit, offset=offset)


@ROUTER.get("/reviews/{id}", summary="Chi tiết đánh giá")
async def lay_danh_gia(id: int, pool: Pool) -> ReviewOut:
    async with pool.acquire() as conn:
        hang = await lay(conn, "product_reviews", id)
    if hang is None:
        raise khong_tim_thay("đánh giá", id)
    return ve_out(ReviewOut, hang)


@ROUTER.post("/reviews", status_code=201, summary="Tạo đánh giá")
async def tao_danh_gia(body: ReviewIn, pool: Pool) -> ReviewOut:
    async with tx(pool) as conn:
        hang = await chen(conn, "product_reviews", body.model_dump())
        await tinh_lai_diem(conn, hang["product_id"])
    return ve_out(ReviewOut, hang)


@ROUTER.patch("/reviews/{id}", summary="Duyệt/ẩn, trả lời đánh giá")
async def sua_danh_gia(id: int, body: ReviewPatch, pool: Pool) -> ReviewOut:
    du_lieu = body.model_dump(exclude_unset=True)
    if du_lieu.get("status", "") is None:
        du_lieu.pop("status")  # NOT NULL — null tường minh coi như không đổi
    async with tx(pool) as conn:
        if "staff_reply" in du_lieu:
            du_lieu["replied_at"] = None if du_lieu["staff_reply"] is None else await conn.fetchval("SELECT now()")
        hang = await sua(conn, "product_reviews", id, du_lieu)
        if hang is None:
            raise khong_tim_thay("đánh giá", id)
        await tinh_lai_diem(conn, hang["product_id"])
    return ve_out(ReviewOut, hang)


@ROUTER.delete("/reviews/{id}", status_code=204, summary="Xoá đánh giá")
async def xoa_danh_gia(id: int, pool: Pool) -> Response:
    async with tx(pool) as conn:
        product_id = await conn.fetchval("DELETE FROM shop.product_reviews WHERE id = $1 RETURNING product_id", id)
        if product_id is None:
            raise khong_tim_thay("đánh giá", id)
        await tinh_lai_diem(conn, product_id)
    return Response(status_code=204)


@ROUTER.post("/reviews/{id}/helpful", summary="Đánh dấu 'hữu ích'")
async def huu_ich(id: int, pool: Pool) -> ReviewOut:
    # Cộng dồn trong SQL — đọc-rồi-ghi sẽ mất lượt khi nhiều người bấm cùng lúc.
    async with tx(pool) as conn:
        hang = await conn.fetchrow(
            "UPDATE shop.product_reviews SET helpful_count = helpful_count + 1 WHERE id = $1 RETURNING *", id
        )
    if hang is None:
        raise khong_tim_thay("đánh giá", id)
    return ve_out(ReviewOut, hang)


# ------------------------------------------------------------------ hỏi đáp


@ROUTER.get("/questions", summary="Danh sách hỏi đáp")
async def liet_ke_hoi_dap(
    pool: Pool,
    limit: Limit = LIMIT_MAC_DINH,
    offset: Offset = 0,
    product_id: Annotated[int | None, Query(alias="productId")] = None,
    status: TrangThai | None = None,
) -> Trang[QuestionOut]:
    dk, ts = _loc(product_id=product_id, status=status)
    async with pool.acquire() as conn:
        rows, total = await liet_ke(
            conn,
            "product_questions",
            dieu_kien=dk,
            tham_so=ts,
            sap_xep="created_at DESC, id DESC",
            limit=limit,
            offset=offset,
        )
    return Trang[QuestionOut](items=[ve_out(QuestionOut, r) for r in rows], total=total, limit=limit, offset=offset)


@ROUTER.get("/questions/{id}", summary="Chi tiết hỏi đáp")
async def lay_hoi_dap(id: int, pool: Pool) -> QuestionOut:
    async with pool.acquire() as conn:
        hang = await lay(conn, "product_questions", id)
    if hang is None:
        raise khong_tim_thay("câu hỏi", id)
    return ve_out(QuestionOut, hang)


@ROUTER.post("/questions", status_code=201, summary="Tạo câu hỏi")
async def tao_hoi_dap(body: QuestionIn, pool: Pool) -> QuestionOut:
    async with tx(pool) as conn:
        hang = await chen(conn, "product_questions", body.model_dump())
    return ve_out(QuestionOut, hang)


@ROUTER.patch("/questions/{id}", summary="Trả lời/duyệt câu hỏi")
async def sua_hoi_dap(id: int, body: QuestionPatch, pool: Pool) -> QuestionOut:
    du_lieu = body.model_dump(exclude_unset=True)
    if du_lieu.get("status", "") is None:
        du_lieu.pop("status")
    async with tx(pool) as conn:
        if "answer" in du_lieu:
            du_lieu["answered_at"] = None if du_lieu["answer"] is None else await conn.fetchval("SELECT now()")
        hang = await sua(conn, "product_questions", id, du_lieu)
    if hang is None:
        raise khong_tim_thay("câu hỏi", id)
    return ve_out(QuestionOut, hang)


@ROUTER.delete("/questions/{id}", status_code=204, summary="Xoá câu hỏi")
async def xoa_hoi_dap(id: int, pool: Pool) -> Response:
    async with tx(pool) as conn:
        if not await conn.fetchval("DELETE FROM shop.product_questions WHERE id = $1 RETURNING true", id):
            raise khong_tim_thay("câu hỏi", id)
    return Response(status_code=204)
