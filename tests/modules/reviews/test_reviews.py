"""Đánh giá: điểm TB/số lượng của sản phẩm chỉ tính bản published, tính lại ở mọi thay đổi. Hỏi đáp."""

import asyncpg
import httpx

API = "/api/v1"


async def tao_san_pham(admin_pool: asyncpg.Pool) -> int:
    async with admin_pool.acquire() as conn:
        cat = await conn.fetchval("INSERT INTO shop.categories (slug, name) VALUES ('dtdd', 'Điện thoại') RETURNING id")
        brand = await conn.fetchval("INSERT INTO shop.brands (slug, name) VALUES ('apple', 'Apple') RETURNING id")
        return await conn.fetchval(
            "INSERT INTO shop.products (category_id, brand_id, slug, name) "
            "VALUES ($1, $2, 'ip16', 'iPhone 16') RETURNING id",
            cat,
            brand,
        )


async def _diem(admin_pool: asyncpg.Pool, pid: int) -> tuple[float | None, int]:
    async with admin_pool.acquire() as conn:
        r = await conn.fetchrow("SELECT rating_avg, rating_count FROM shop.products WHERE id = $1", pid)
    return (None if r["rating_avg"] is None else float(r["rating_avg"])), r["rating_count"]


async def _danh_gia(client: httpx.AsyncClient, pid: int, rating: int, **them: object) -> int:
    r = await client.post(f"{API}/reviews", json={"productId": pid, "authorName": "Khách", "rating": rating, **them})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_diem_chi_tinh_ban_published(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    pid = await tao_san_pham(admin_pool)
    a = await _danh_gia(client, pid, 5)
    assert (await client.get(f"{API}/reviews/{a}")).json()["status"] == "pending"
    assert await _diem(admin_pool, pid) == (None, 0), "pending không tính"

    assert (await client.patch(f"{API}/reviews/{a}", json={"status": "published"})).status_code == 200
    assert await _diem(admin_pool, pid) == (5.0, 1)

    b = await _danh_gia(client, pid, 4, status="published")
    c = await _danh_gia(client, pid, 4, status="published")
    assert await _diem(admin_pool, pid) == (4.3, 3), "13/3 = 4.333 → làm tròn 1 chữ số"

    await client.patch(f"{API}/reviews/{b}", json={"status": "hidden"})
    assert await _diem(admin_pool, pid) == (4.5, 2)

    assert (await client.delete(f"{API}/reviews/{a}")).status_code == 204
    assert await _diem(admin_pool, pid) == (4.0, 1)
    await client.delete(f"{API}/reviews/{c}")
    assert await _diem(admin_pool, pid) == (None, 0)
    assert (await client.delete(f"{API}/reviews/{c}")).status_code == 404


async def test_tra_loi_huu_ich_va_loc(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    pid = await tao_san_pham(admin_pool)
    a = await _danh_gia(client, pid, 2, content="Pin yếu")
    await _danh_gia(client, pid, 5, status="published")

    r = await client.patch(f"{API}/reviews/{a}", json={"staffReply": "Bộ phận bảo hành đã liên hệ"})
    assert r.json()["staffReply"] and r.json()["repliedAt"] is not None
    r = await client.patch(f"{API}/reviews/{a}", json={"staffReply": None})
    assert r.json()["repliedAt"] is None

    for _ in range(3):
        r = await client.post(f"{API}/reviews/{a}/helpful")
    assert r.status_code == 200 and r.json()["helpfulCount"] == 3
    assert (await client.post(f"{API}/reviews/999/helpful")).status_code == 404

    assert (await client.get(f"{API}/reviews", params={"productId": pid})).json()["total"] == 2
    assert (await client.get(f"{API}/reviews", params={"rating": 2})).json()["items"][0]["id"] == a
    assert (await client.get(f"{API}/reviews", params={"status": "published"})).json()["total"] == 1
    assert (
        await client.post(f"{API}/reviews", json={"productId": pid, "authorName": "X", "rating": 6})
    ).status_code == 422
    r = await client.post(f"{API}/reviews", json={"productId": pid + 9, "authorName": "X", "rating": 3})
    assert r.status_code == 409


async def test_hoi_dap(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    pid = await tao_san_pham(admin_pool)
    r = await client.post(
        f"{API}/questions", json={"productId": pid, "authorName": "Lan", "question": "Có eSIM không?"}
    )
    assert r.status_code == 201
    q = r.json()
    assert q["status"] == "pending" and q["answeredAt"] is None

    r = await client.patch(f"{API}/questions/{q['id']}", json={"answer": "Có ạ"})
    assert r.json()["answeredAt"] is not None and r.json()["status"] == "pending", "trả lời không tự duyệt"
    r = await client.patch(f"{API}/questions/{q['id']}", json={"status": "published"})
    assert r.json()["status"] == "published" and r.json()["answer"] == "Có ạ"

    assert (await client.get(f"{API}/questions", params={"productId": pid, "status": "published"})).json()["total"] == 1
    assert (await client.get(f"{API}/questions", params={"status": "hidden"})).json()["total"] == 0
    assert (await client.delete(f"{API}/questions/{q['id']}")).status_code == 204
    assert (await client.get(f"{API}/questions/{q['id']}")).status_code == 404
