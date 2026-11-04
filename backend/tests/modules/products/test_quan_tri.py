"""Quản trị sản phẩm: CRUD, ràng buộc màu-thuộc-SP, lịch sử giá, thông số, tập tính năng/nhãn, liên quan."""

import asyncpg
import httpx

API = "/api/v1"


async def _nen(client: httpx.AsyncClient) -> tuple[int, int]:
    brand = (await client.post(f"{API}/brands", json={"slug": "apple", "name": "Apple"})).json()["id"]
    cat = (await client.post(f"{API}/categories", json={"slug": "dtdd", "name": "Điện thoại"})).json()["id"]
    return brand, cat


async def _sp(client: httpx.AsyncClient, brand: int, cat: int, slug: str, **them: object) -> dict:
    r = await client.post(
        f"{API}/products", json={"brandId": brand, "categoryId": cat, "slug": slug, "name": slug.upper(), **them}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_crud_san_pham_va_loc(client: httpx.AsyncClient) -> None:
    brand, cat = await _nen(client)
    sp = await _sp(client, brand, cat, "iphone-16", modelCode="A3287", phoneType="smartphone")
    assert sp["status"] == "draft" and sp["warrantyMonths"] == 12 and sp["ratingAvg"] is None
    await _sp(client, brand, cat, "iphone-15", status="selling")

    r = await client.patch(f"{API}/products/{sp['id']}", json={"name": "iPhone 16", "status": "selling"})
    assert r.status_code == 200 and r.json()["name"] == "iPhone 16" and r.json()["modelCode"] == "A3287"

    trang = (await client.get(f"{API}/products", params={"brandId": brand, "status": "selling"})).json()
    assert trang["total"] == 2
    trang = (await client.get(f"{API}/products", params={"q": "a3287"})).json()
    assert [p["slug"] for p in trang["items"]] == ["iphone-16"]
    assert (await client.get(f"{API}/products", params={"brandId": brand + 99})).json()["total"] == 0

    r = await client.post(
        f"{API}/products", json={"brandId": brand, "categoryId": cat, "slug": "iphone-16", "name": "X"}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE"
    r = await client.post(f"{API}/products", json={"brandId": 999, "categoryId": cat, "slug": "x", "name": "X"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "REFERENCE_ERROR"
    r = await client.patch(f"{API}/products/{sp['id']}", json={"status": "dang-ban"})
    assert r.status_code == 422

    assert (await client.delete(f"{API}/products/{sp['id']}")).status_code == 204
    r = await client.get(f"{API}/products/{sp['id']}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    assert (await client.get(f"{API}/products/{sp['id']}/colors")).status_code == 404


async def test_mau_cua_sp_khac_bi_tu_choi(client: httpx.AsyncClient) -> None:
    brand, cat = await _nen(client)
    a = await _sp(client, brand, cat, "a")
    b = await _sp(client, brand, cat, "b")
    mau_a = (await client.post(f"{API}/products/{a['id']}/colors", json={"name": "Đen", "hexCode": "#000000"})).json()
    mau_b = (await client.post(f"{API}/products/{b['id']}/colors", json={"name": "Trắng"})).json()

    sku = {"sku": "A-8-128", "ramGb": 8, "storageGb": 128, "listPriceVnd": 20_000_000}
    r = await client.post(f"{API}/products/{a['id']}/variants", json={**sku, "colorId": mau_b["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_DATA"

    r = await client.post(f"{API}/products/{a['id']}/variants", json={**sku, "colorId": mau_a["id"]})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["ramGb"] == 8.0 and v["colorId"] == mau_a["id"]

    r = await client.patch(f"{API}/variants/{v['id']}", json={"colorId": mau_b["id"]})
    assert r.status_code == 422
    r = await client.post(
        f"{API}/products/{a['id']}/media", json={"mediaType": "image", "url": "x", "colorId": mau_b["id"]}
    )
    assert r.status_code == 422

    # Màu đang có SKU dùng ⇒ không xoá được (FK), không âm thầm mồ côi SKU.
    r = await client.delete(f"{API}/product-colors/{mau_a['id']}")
    assert r.status_code == 409
    assert [c["name"] for c in (await client.get(f"{API}/products/{a['id']}/colors")).json()] == ["Đen"]


async def test_doi_gia_ghi_lich_su(client: httpx.AsyncClient) -> None:
    brand, cat = await _nen(client)
    a = await _sp(client, brand, cat, "a")
    v = (await client.post(f"{API}/products/{a['id']}/variants", json={"sku": "S1", "listPriceVnd": 10_000_000})).json()
    await client.patch(f"{API}/variants/{v['id']}", json={"salePriceVnd": 9_000_000})
    await client.patch(f"{API}/variants/{v['id']}", json={"sortOrder": 3})  # không đổi giá ⇒ không ghi

    ls = (await client.get(f"{API}/variants/{v['id']}/price-history")).json()
    assert [(h["listPriceVnd"], h["salePriceVnd"]) for h in ls] == [(10_000_000, 9_000_000), (10_000_000, None)]

    r = await client.patch(f"{API}/variants/{v['id']}", json={"salePriceVnd": 11_000_000})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CHECK_FAILED"
    assert (await client.get(f"{API}/variants/999/price-history")).status_code == 404

    r = await client.post(f"{API}/products/{a['id']}/variants", json={"sku": "S1", "listPriceVnd": 1})
    assert r.status_code == 409


async def test_thong_so_upsert_thay_tron(client: httpx.AsyncClient) -> None:
    brand, cat = await _nen(client)
    a = await _sp(client, brand, cat, "a")
    assert (await client.get(f"{API}/products/{a['id']}/specs")).status_code == 404

    r = await client.put(
        f"{API}/products/{a['id']}/specs",
        json={"osName": "iOS", "chipset": "A18", "networkGen": "5G", "screenSizeInch": 6.1, "hasNfc": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["has5g"] is True and r.json()["screenSizeInch"] == 6.1

    r = await client.put(f"{API}/products/{a['id']}/specs", json={"chipset": "A18 Pro", "networkGen": "4G"})
    s = r.json()
    assert s["chipset"] == "A18 Pro" and s["has5g"] is False and s["osName"] is None, "PUT là thay trọn"
    assert (await client.get(f"{API}/products/{a['id']}/specs")).json()["chipset"] == "A18 Pro"

    r = await client.put(f"{API}/products/{a['id']}/specs", json={"has5g": True})
    assert r.status_code == 422, "has5g là cột sinh — không được ghi"
    assert (await client.put(f"{API}/products/999/specs", json={})).status_code == 404


async def test_thay_tap_tinh_nang_va_nhan(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    brand, cat = await _nen(client)
    a = await _sp(client, brand, cat, "a")
    f = [
        (await client.post(f"{API}/features", json={"featureGroup": "special", "name": n, "slug": n})).json()["id"]
        for n in ("ois", "khang-nuoc", "sac-khong-day")
    ]
    r = await client.put(f"{API}/products/{a['id']}/features", json={"featureIds": [f[0], f[1]]})
    assert {x["id"] for x in r.json()} == {f[0], f[1]}
    r = await client.put(f"{API}/products/{a['id']}/features", json={"featureIds": [f[1], f[2], f[2]]})
    assert {x["id"] for x in r.json()} == {f[1], f[2]}

    r = await client.put(f"{API}/products/{a['id']}/features", json={"featureIds": [f[0], 9999]})
    assert r.status_code == 409
    con = await admin_pool.fetchval("SELECT array_agg(feature_id ORDER BY feature_id) FROM shop.product_features")
    assert con == [f[1], f[2]], "id lạ ⇒ cả lượt thay lùi lại"

    t = (await client.post(f"{API}/tags", json={"kind": "need", "slug": "choi-game", "name": "Chơi game"})).json()
    r = await client.put(f"{API}/products/{a['id']}/tags", json={"tagIds": [t["id"]]})
    assert [x["slug"] for x in r.json()] == ["choi-game"]
    assert (await client.put(f"{API}/products/{a['id']}/tags", json={"tagIds": []})).json() == []


async def test_media_faq_va_lien_quan(client: httpx.AsyncClient) -> None:
    brand, cat = await _nen(client)
    a = await _sp(client, brand, cat, "a")
    b = await _sp(client, brand, cat, "b")

    m = (await client.post(f"{API}/products/{a['id']}/media", json={"mediaType": "thumbnail", "url": "/a.jpg"})).json()
    r = await client.patch(f"{API}/product-media/{m['id']}", json={"altText": "Ảnh A"})
    assert r.json()["altText"] == "Ảnh A"
    assert (
        await client.post(f"{API}/products/{a['id']}/media", json={"mediaType": "gif", "url": "x"})
    ).status_code == 422

    await client.post(f"{API}/products/{a['id']}/faqs", json={"question": "Có sạc?", "answer": "Không"})
    r = await client.post(f"{API}/faqs", json={"question": "Đổi trả?", "answer": "30 ngày"})
    assert r.status_code == 201 and r.json()["productId"] is None
    assert (await client.get(f"{API}/faqs", params={"general": "true"})).json()["total"] == 1
    assert (await client.get(f"{API}/faqs", params={"productId": a["id"]})).json()["total"] == 1
    assert (await client.get(f"{API}/faqs")).json()["total"] == 2

    lq = [{"relatedProductId": b["id"], "relationType": "similar"}]
    r = await client.put(f"{API}/products/{a['id']}/relations", json=lq)
    assert r.status_code == 200 and r.json()[0]["slug"] == "b"
    r = await client.put(
        f"{API}/products/{a['id']}/relations", json=[{"relatedProductId": a["id"], "relationType": "similar"}]
    )
    assert r.status_code == 422, "SP không liên quan tới chính nó (CHECK)"
    assert len((await client.get(f"{API}/products/{a['id']}/relations")).json()) == 1, "lỗi ⇒ giữ nguyên bản cũ"
    assert (await client.put(f"{API}/products/{a['id']}/relations", json=[])).json() == []
