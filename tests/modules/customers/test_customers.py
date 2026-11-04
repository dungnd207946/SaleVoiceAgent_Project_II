"""Khách hàng (chuẩn hoá SĐT) và giữ hàng: trừ/nhả/tiêu thụ tồn, máy trạng thái, hết hạn."""

import asyncpg
import httpx
import pytest

from portal.modules.customers.contracts import chuan_hoa_sdt

API = "/api/v1"


@pytest.mark.parametrize(
    ("raw", "chuan"),
    [("0912345678", "0912345678"), ("+84 912.345.678", "0912345678"), ("091 234 5678", "0912345678")],
)
def test_chuan_hoa_sdt(raw: str, chuan: str) -> None:
    assert chuan_hoa_sdt(raw) == chuan


@pytest.mark.parametrize("raw", ["912345678", "09123456789", "0012345678", "abc", "+8512345678"])
def test_sdt_sai(raw: str) -> None:
    with pytest.raises(ValueError):
        chuan_hoa_sdt(raw)


async def test_khach_hang_sdt_trung_va_tim(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{API}/customers", json={"phone": "+84 912.345.678", "fullName": "Nguyễn Văn A"})
    assert r.status_code == 201, r.text
    kh = r.json()
    assert kh["phone"] == "0912345678"

    r = await client.post(f"{API}/customers", json={"phone": "0912 345 678"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE", "cùng số, khác cách gõ"
    r = await client.post(f"{API}/customers", json={"phone": "12345"})
    assert r.status_code == 422 and r.json()["error"]["fields"][0]["field"] == "body.phone"
    r = await client.patch(f"{API}/customers/{kh['id']}", json={"phone": "123"})
    assert r.status_code == 422, "PATCH vẫn chuẩn hoá/validate SĐT"

    r = await client.get(f"{API}/customers/by-phone/+84912345678")
    assert r.status_code == 200 and r.json()["id"] == kh["id"]
    assert (await client.get(f"{API}/customers/by-phone/0999999999")).status_code == 404
    assert (await client.get(f"{API}/customers/by-phone/12")).status_code == 422

    await client.post(f"{API}/customers", json={"phone": "0987654321", "fullName": "Trần B", "email": "b@x.vn"})
    assert (await client.get(f"{API}/customers", params={"q": "0912 345"})).json()["total"] == 1
    assert (await client.get(f"{API}/customers", params={"q": "b@x"})).json()["total"] == 1
    assert (await client.get(f"{API}/customers", params={"q": "văn"})).json()["total"] == 1
    assert (await client.get(f"{API}/customers")).json()["total"] == 2


async def _chuan_bi(client: httpx.AsyncClient, admin_pool: asyncpg.Pool, ton: int) -> tuple[int, int, int]:
    """Một khách, một cửa hàng, một SKU có `ton` máy. Trả (customer_id, store_id, variant_id)."""
    async with admin_pool.acquire() as conn:
        await conn.execute("INSERT INTO shop.provinces (code, name) VALUES ('HCM', 'TP. Hồ Chí Minh')")
        cat = await conn.fetchval("INSERT INTO shop.categories (slug, name) VALUES ('dtdd', 'Điện thoại') RETURNING id")
        brand = await conn.fetchval("INSERT INTO shop.brands (slug, name) VALUES ('apple', 'Apple') RETURNING id")
        prod = await conn.fetchval(
            "INSERT INTO shop.products (category_id, brand_id, slug, name) "
            "VALUES ($1, $2, 'ip16', 'iPhone 16') RETURNING id",
            cat,
            brand,
        )
        v = await conn.fetchval(
            "INSERT INTO shop.product_variants (product_id, sku, list_price_vnd) "
            "VALUES ($1, 'IP16', 20000000) RETURNING id",
            prod,
        )
        st = await conn.fetchval(
            "INSERT INTO shop.stores (code, name, address, province_code) VALUES ('Q1', 'Q1', 'a', 'HCM') RETURNING id"
        )
        await conn.execute(
            "INSERT INTO shop.inventory (store_id, variant_id, quantity) VALUES ($1, $2, $3)", st, v, ton
        )
    kh = (await client.post(f"{API}/customers", json={"phone": "0912345678"})).json()["id"]
    return kh, st, v


async def _ton(admin_pool: asyncpg.Pool) -> tuple[int, int]:
    async with admin_pool.acquire() as conn:
        r = await conn.fetchrow("SELECT quantity, reserved_qty FROM shop.inventory")
    return r["quantity"], r["reserved_qty"]


async def _giu(client: httpx.AsyncClient, kh: int, st: int, v: int, sl: int = 1) -> httpx.Response:
    return await client.post(
        f"{API}/reservations",
        json={"customerId": kh, "reservationType": "hold_stock", "storeId": st, "variantId": v, "quantity": sl},
    )


async def test_giu_hang_tru_kha_dung_va_het_hang(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    kh, st, v = await _chuan_bi(client, admin_pool, ton=3)
    r = await _giu(client, kh, st, v, 2)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["status"] == "pending" and p["expiresAt"] is not None, "hold_stock mặc định hết hạn sau 24h"
    assert await _ton(admin_pool) == (3, 2)

    r = await client.get(f"{API}/inventory", params={"variantId": v})
    assert r.json()["items"][0]["qtyAvailable"] == 1

    r = await _giu(client, kh, st, v, 2)
    assert r.status_code == 409 and r.json()["error"]["code"] == "OUT_OF_STOCK"
    assert await _ton(admin_pool) == (3, 2), "giữ hụt không được trừ gì"
    assert (await client.get(f"{API}/reservations")).json()["total"] == 1

    r = await client.post(f"{API}/reservations", json={"customerId": kh, "reservationType": "hold_stock"})
    assert r.status_code == 422, "hold_stock thiếu store/variant → CHECK của DB"

    r = await client.post(f"{API}/reservations", json={"customerId": kh, "reservationType": "callback"})
    assert r.status_code == 201 and r.json()["expiresAt"] is None
    assert (await client.get(f"{API}/reservations", params={"type": "callback"})).json()["total"] == 1
    assert (await client.get(f"{API}/reservations", params={"storeId": st})).json()["total"] == 1

    r = await client.delete(f"{API}/customers/{kh}")
    assert r.status_code == 409, "còn phiếu giữ hàng thì không xoá khách (sẽ treo reserved_qty)"


async def test_huy_nha_hoan_thanh_tieu_thu(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    kh, st, v = await _chuan_bi(client, admin_pool, ton=5)
    a = (await _giu(client, kh, st, v, 2)).json()["id"]
    b = (await _giu(client, kh, st, v, 1)).json()["id"]
    assert await _ton(admin_pool) == (5, 3)

    r = await client.patch(f"{API}/reservations/{a}", json={"status": "cancelled", "note": "khách đổi ý"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["note"] == "khách đổi ý"
    assert await _ton(admin_pool) == (5, 1)

    assert (await client.patch(f"{API}/reservations/{b}", json={"status": "confirmed"})).status_code == 200
    assert await _ton(admin_pool) == (5, 1), "xác nhận không đổi tồn"
    assert (await client.patch(f"{API}/reservations/{b}", json={"status": "confirmed"})).status_code == 200
    assert (await client.patch(f"{API}/reservations/{b}", json={"status": "completed"})).status_code == 200
    assert await _ton(admin_pool) == (4, 0), "bán xong: trừ cả tồn thật lẫn số giữ"


@pytest.mark.parametrize(
    ("duong", "dich"),
    [([], "completed"), (["cancelled"], "confirmed"), (["confirmed", "completed"], "cancelled"), ([], "pending")],
)
async def test_chuyen_trang_thai_sai(
    client: httpx.AsyncClient, admin_pool: asyncpg.Pool, duong: list[str], dich: str
) -> None:
    kh, st, v = await _chuan_bi(client, admin_pool, ton=2)
    pid = (await _giu(client, kh, st, v)).json()["id"]
    for s in duong:
        assert (await client.patch(f"{API}/reservations/{pid}", json={"status": s})).status_code == 200
    truoc = await _ton(admin_pool)
    r = await client.patch(f"{API}/reservations/{pid}", json={"status": dich})
    if dich == "pending" and not duong:
        assert r.status_code == 200, "trạng thái hiện tại gửi lại = không đổi"
    else:
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_TRANSITION"
    assert await _ton(admin_pool) == truoc


async def test_het_han_nha_ton(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    kh, st, v = await _chuan_bi(client, admin_pool, ton=5)
    qua_han = (await _giu(client, kh, st, v, 2)).json()["id"]
    con_han = (await _giu(client, kh, st, v, 1)).json()["id"]
    xac_nhan = (await _giu(client, kh, st, v, 1)).json()["id"]
    await client.patch(f"{API}/reservations/{xac_nhan}", json={"status": "confirmed"})
    async with admin_pool.acquire() as conn:
        await conn.execute(
            "UPDATE shop.reservations SET expires_at = now() - interval '1 minute' WHERE id = ANY($1::bigint[])",
            [qua_han, xac_nhan],
        )
    assert await _ton(admin_pool) == (5, 4)

    r = await client.post(f"{API}/reservations/expire-due")
    assert r.status_code == 200 and r.json() == {"expired": 2}
    assert await _ton(admin_pool) == (5, 1)
    assert (await client.get(f"{API}/reservations/{qua_han}")).json()["status"] == "expired"
    assert (await client.get(f"{API}/reservations/{con_han}")).json()["status"] == "pending"

    assert (await client.post(f"{API}/reservations/expire-due")).json() == {"expired": 0}
