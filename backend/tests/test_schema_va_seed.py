"""Bài canh cấp repo: seed dev chạy được trên schema hiện hành, trigger KB của danh mục.

Seed là SQL chép tay, schema đổi mà quên seed thì `make up` gãy ở bước cuối — chỉ lộ
ra trên máy người khác. Bài này chạy đúng tệp mà `make seed-shop` chạy.
"""

from pathlib import Path

import asyncpg

SEED = Path(__file__).resolve().parent.parent / "scripts" / "seed_shop.sql"


async def _seed(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(SEED.read_text(encoding="utf-8"))


async def test_seed_chay_duoc_va_view_agent_doc_ra_gia(admin_pool: asyncpg.Pool) -> None:
    await _seed(admin_pool)
    async with admin_pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM shop.product_variants") == 12
        hang = await conn.fetchrow(
            "SELECT price_vnd, discount_percent, has_installment_0 FROM shop.agent_products_v "
            "WHERE variant_name = 'iPhone 16 Pro Max 8GB/256GB Titan sa mạc'"
        )
        assert hang["price_vnd"] == 31_590_000 and hang["discount_percent"] == 7 and hang["has_installment_0"]
        # Seed đi qua trigger KB như mọi lần ghi khác ⇒ có việc index chờ worker.
        assert await conn.fetchval("SELECT count(*) FROM shop.jobs WHERE kind = 'kb_index'") > 0


async def test_doi_ten_hang_xep_index_lai_san_pham(admin_pool: asyncpg.Pool) -> None:
    await _seed(admin_pool)
    async with admin_pool.acquire() as conn:
        await conn.execute("DELETE FROM shop.jobs")
        await conn.execute("UPDATE shop.brands SET sort_order = 99 WHERE slug = 'apple'")
        assert await conn.fetchval("SELECT count(*) FROM shop.jobs") == 0, "không đổi tên thì không index lại"

        await conn.execute("UPDATE shop.brands SET name = 'Apple' WHERE slug = 'apple'")
        payload = await conn.fetchval("SELECT payload FROM shop.jobs WHERE kind = 'kb_index'")
        san_pham = await conn.fetchval("SELECT id FROM shop.products WHERE slug = 'iphone-16-pro-max'")
        assert payload is not None and f'"id": {san_pham}' in payload
