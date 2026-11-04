"""Cửa hàng & tồn kho: PK text của tỉnh, upsert/điều chỉnh tồn, CHECK giữ hàng, gom theo tỉnh."""

import asyncpg
import httpx

API = "/api/v1"


async def tao_bien_the(admin_pool: asyncpg.Pool, sku: str = "IP16-128-DEN") -> int:
    """Seed tối thiểu một SKU (hãng → ngành → sản phẩm → biến thể) bằng quyền owner."""
    async with admin_pool.acquire() as conn:
        cat = await conn.fetchval(
            "INSERT INTO shop.categories (slug, name) VALUES ('dtdd', 'Điện thoại') "
            "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id"
        )
        brand = await conn.fetchval(
            "INSERT INTO shop.brands (slug, name) VALUES ('apple', 'Apple') "
            "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id"
        )
        prod = await conn.fetchval(
            "INSERT INTO shop.products (category_id, brand_id, slug, name) VALUES ($1, $2, 'iphone-16', 'iPhone 16') "
            "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id",
            cat,
            brand,
        )
        return await conn.fetchval(
            "INSERT INTO shop.product_variants (product_id, sku, list_price_vnd, storage_gb) "
            "VALUES ($1, $2, 20000000, $3) RETURNING id",
            prod,
            sku,
            128 + len(sku),
        )


async def tao_cua_hang(client: httpx.AsyncClient, code: str, tinh: str = "HCM", **them: object) -> int:
    r = await client.post(
        f"{API}/stores",
        json={"code": code, "name": f"Cửa hàng {code}", "address": f"{code} Nguyễn Huệ", "provinceCode": tinh, **them},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_tinh_thanh_pk_text(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{API}/provinces", json={"code": "HCM", "name": "TP. Hồ Chí Minh"})
    assert r.status_code == 201 and r.json() == {"code": "HCM", "name": "TP. Hồ Chí Minh"}
    r = await client.post(f"{API}/provinces", json={"code": "HCM", "name": "Khác"})
    assert r.status_code == 409

    r = await client.patch(f"{API}/provinces/HCM", json={"name": "Thành phố Hồ Chí Minh"})
    assert r.status_code == 200 and r.json()["name"] == "Thành phố Hồ Chí Minh"
    assert (await client.patch(f"{API}/provinces/XX", json={"name": "A"})).status_code == 404

    await client.post(f"{API}/provinces", json={"code": "HN", "name": "Hà Nội"})
    r = await client.get(f"{API}/provinces")
    assert [p["code"] for p in r.json()] == ["HN", "HCM"]

    await tao_cua_hang(client, "Q1")
    r = await client.delete(f"{API}/provinces/HCM")
    assert r.status_code == 409, "còn cửa hàng tham chiếu thì không xoá được"
    assert (await client.delete(f"{API}/provinces/HN")).status_code == 204
    assert (await client.delete(f"{API}/provinces/HN")).status_code == 404


async def test_cua_hang_crud_va_loc(client: httpx.AsyncClient) -> None:
    await client.post(f"{API}/provinces", json={"code": "HCM", "name": "TP. Hồ Chí Minh"})
    await client.post(f"{API}/provinces", json={"code": "HN", "name": "Hà Nội"})
    a = await tao_cua_hang(client, "Q1", openTime="08:00:00", latitude=10.776)
    await tao_cua_hang(client, "HK", tinh="HN")
    await tao_cua_hang(client, "KHO", storeType="warehouse", isActive=False)

    r = await client.get(f"{API}/stores/{a}")
    assert r.json()["openTime"] == "08:00:00" and r.json()["latitude"] == 10.776

    assert (await client.get(f"{API}/stores", params={"provinceCode": "HN"})).json()["total"] == 1
    assert (await client.get(f"{API}/stores", params={"storeType": "warehouse"})).json()["total"] == 1
    assert (await client.get(f"{API}/stores", params={"active": "true"})).json()["total"] == 2
    assert (await client.get(f"{API}/stores", params={"q": "hk nguyễn"})).json()["total"] == 1

    r = await client.patch(f"{API}/stores/{a}", json={"isActive": False})
    assert r.status_code == 200 and r.json()["isActive"] is False
    assert (
        await client.post(f"{API}/stores", json={"code": "X", "name": "X", "address": "a", "provinceCode": "ZZ"})
    ).status_code == 409
    assert (await client.delete(f"{API}/stores/{a}")).status_code == 204


async def test_ton_kho_upsert_dieu_chinh_va_check(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    await client.post(f"{API}/provinces", json={"code": "HCM", "name": "TP. Hồ Chí Minh"})
    ch = await tao_cua_hang(client, "Q1")
    v = await tao_bien_the(admin_pool)

    r = await client.put(f"{API}/inventory", json={"storeId": ch, "variantId": v, "quantity": 5})
    assert r.status_code == 200, r.text
    ton = r.json()
    assert ton["quantity"] == 5 and ton["qtyAvailable"] == 5 and ton["sku"] == "IP16-128-DEN"
    assert ton["productName"] == "iPhone 16" and ton["storeName"] == "Cửa hàng Q1"

    r = await client.put(f"{API}/inventory", json={"storeId": ch, "variantId": v, "quantity": 3})
    assert r.json()["quantity"] == 3

    r = await client.post(f"{API}/inventory/adjust", json={"storeId": ch, "variantId": v, "delta": 4})
    assert r.json()["quantity"] == 7
    r = await client.post(f"{API}/inventory/adjust", json={"storeId": ch, "variantId": v, "delta": -2})
    assert r.json()["quantity"] == 5

    # Đang giữ 4 máy → không kiểm kê/xuất xuống dưới 4.
    async with admin_pool.acquire() as conn:
        await conn.execute("UPDATE shop.inventory SET reserved_qty = 4")
    r = await client.put(f"{API}/inventory", json={"storeId": ch, "variantId": v, "quantity": 3})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CHECK_FAILED"
    r = await client.post(f"{API}/inventory/adjust", json={"storeId": ch, "variantId": v, "delta": -2})
    assert r.status_code == 422
    r = await client.get(f"{API}/inventory", params={"variantId": v})
    item = r.json()["items"][0]
    assert item["quantity"] == 5 and item["reservedQty"] == 4 and item["qtyAvailable"] == 1, "lỗi phải rollback"

    # Điều chỉnh âm trên hàng chưa tồn tại → CHECK (không tạo hàng rác).
    v2 = await tao_bien_the(admin_pool, "IP16-256-TRANG")
    r = await client.post(f"{API}/inventory/adjust", json={"storeId": ch, "variantId": v2, "delta": -1})
    assert r.status_code == 422
    assert (await client.get(f"{API}/inventory")).json()["total"] == 1

    r = await client.put(f"{API}/inventory", json={"storeId": ch, "variantId": v2, "quantity": 0})
    assert (await client.get(f"{API}/inventory", params={"inStockOnly": "true"})).json()["total"] == 1
    assert (await client.get(f"{API}/inventory", params={"provinceCode": "HN"})).json()["total"] == 0


async def test_con_hang_gom_theo_tinh(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    await client.post(f"{API}/provinces", json={"code": "HCM", "name": "TP. Hồ Chí Minh"})
    await client.post(f"{API}/provinces", json={"code": "HN", "name": "Hà Nội"})
    q1 = await tao_cua_hang(client, "Q1")
    q3 = await tao_cua_hang(client, "Q3")
    hk = await tao_cua_hang(client, "HK", tinh="HN")
    het = await tao_cua_hang(client, "HET", tinh="HN")
    kho = await tao_cua_hang(client, "KHO", storeType="warehouse")
    dong = await tao_cua_hang(client, "DONG", isActive=False)
    v = await tao_bien_the(admin_pool)
    for ch, sl in ((q1, 2), (q3, 1), (hk, 5), (het, 1), (kho, 100), (dong, 3)):
        await client.put(f"{API}/inventory", json={"storeId": ch, "variantId": v, "quantity": sl})
    async with admin_pool.acquire() as conn:
        await conn.execute("UPDATE shop.inventory SET reserved_qty = 1 WHERE store_id = $1", het)

    r = await client.get(f"{API}/variants/{v}/availability")
    assert r.status_code == 200
    kq = r.json()
    assert kq["qtyAvailable"] == 8, "bỏ kho online, cửa hàng đóng, và cửa hàng hết (đã giữ hết)"
    assert [(p["provinceCode"], p["qtyAvailable"]) for p in kq["provinces"]] == [("HN", 5), ("HCM", 3)]
    assert [s["storeId"] for s in kq["provinces"][1]["stores"]] == [q1, q3]

    r = await client.get(f"{API}/variants/{v + 99}/availability")
    assert r.json() == {"variantId": v + 99, "qtyAvailable": 0, "provinces": []}
