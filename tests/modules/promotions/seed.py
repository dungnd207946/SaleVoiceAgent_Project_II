"""Seed tối thiểu hãng → ngành hàng → sản phẩm → SKU bằng `admin_pool`.

Module products chưa có route, nên test promotions/finance/policies/content seed thẳng DB.
"""

from typing import Any

import asyncpg


async def tao_hang(pool: asyncpg.Pool, slug: str) -> int:
    return await pool.fetchval("INSERT INTO shop.brands (slug, name) VALUES ($1, $1) RETURNING id", slug)


async def tao_nganh(pool: asyncpg.Pool, slug: str) -> int:
    return await pool.fetchval("INSERT INTO shop.categories (slug, name) VALUES ($1, $1) RETURNING id", slug)


async def tao_sp(
    pool: asyncpg.Pool,
    slug: str,
    *,
    brand_id: int,
    category_id: int,
    gia: list[tuple[int, int | None]] = [(30_000_000, 28_990_000)],  # noqa: B006 — chỉ đọc
) -> dict[str, Any]:
    """Một sản phẩm + mỗi phần tử `gia` (niêm yết, bán) là một SKU."""
    pid = await pool.fetchval(
        "INSERT INTO shop.products (category_id, brand_id, slug, name) VALUES ($1, $2, $3, $3) RETURNING id",
        category_id,
        brand_id,
        slug,
    )
    vids = [
        await pool.fetchval(
            "INSERT INTO shop.product_variants (product_id, sku, list_price_vnd, sale_price_vnd, storage_gb)"
            " VALUES ($1, $2, $3, $4, $5) RETURNING id",
            pid,
            f"{slug}-{i}",
            niem_yet,
            ban,
            128 * (i + 1),
        )
        for i, (niem_yet, ban) in enumerate(gia)
    ]
    return {"product_id": pid, "variant_ids": vids, "brand_id": brand_id, "category_id": category_id}
