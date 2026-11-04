"""CRUD danh mục — cũng là bài canh cho `core/crud.py` (dùng chung mọi bảng phẳng)."""

import httpx

API = "/api/v1"


async def test_tao_doc_sua_xoa_hang(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{API}/brands", json={"slug": "apple", "name": "iPhone (Apple)", "sortOrder": 1})
    assert r.status_code == 201, r.text
    hang = r.json()
    assert hang["slug"] == "apple" and hang["isActive"] is True and hang["sortOrder"] == 1

    r = await client.patch(f"{API}/brands/{hang['id']}", json={"country": "Mỹ"})
    assert r.status_code == 200 and r.json()["country"] == "Mỹ" and r.json()["name"] == "iPhone (Apple)"

    r = await client.get(f"{API}/brands/{hang['id']}")
    assert r.json()["country"] == "Mỹ"

    assert (await client.delete(f"{API}/brands/{hang['id']}")).status_code == 204
    r = await client.get(f"{API}/brands/{hang['id']}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


async def test_liet_ke_loc_tim_va_phan_trang(client: httpx.AsyncClient) -> None:
    for i, (slug, ten) in enumerate([("apple", "Apple"), ("samsung", "Samsung"), ("oppo", "OPPO")]):
        await client.post(f"{API}/brands", json={"slug": slug, "name": ten, "sortOrder": i})
    r = await client.get(f"{API}/brands", params={"limit": 2})
    trang = r.json()
    assert trang["total"] == 3 and len(trang["items"]) == 2 and trang["items"][0]["slug"] == "apple"

    r = await client.get(f"{API}/brands", params={"q": "sam"})
    assert [b["slug"] for b in r.json()["items"]] == ["samsung"]

    apple = (await client.get(f"{API}/brands", params={"q": "apple"})).json()["items"][0]["id"]
    await client.post(f"{API}/series", json={"brandId": apple, "slug": "iphone-16", "name": "iPhone 16 series"})
    r = await client.get(f"{API}/series", params={"brandId": apple})
    assert r.json()["total"] == 1
    r = await client.get(f"{API}/series", params={"brandId": apple + 999})
    assert r.json()["total"] == 0


async def test_rang_buoc_db_thanh_loi_http(client: httpx.AsyncClient) -> None:
    await client.post(f"{API}/brands", json={"slug": "apple", "name": "Apple"})
    r = await client.post(f"{API}/brands", json={"slug": "apple", "name": "Apple 2"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE"

    r = await client.post(f"{API}/series", json={"brandId": 999, "slug": "x", "name": "X"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "REFERENCE_ERROR"


async def test_validate_dau_vao(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{API}/brands", json={"slug": "Có Dấu", "name": "X"})
    assert r.status_code == 422 and r.json()["error"]["fields"][0]["field"] == "body.slug"

    r = await client.post(f"{API}/brands", json={"slug": "x", "name": "X", "tenSai": 1})
    assert r.status_code == 422, "trường lạ phải bị từ chối, không âm thầm bỏ qua"

    hang = (await client.post(f"{API}/brands", json={"slug": "x", "name": "X"})).json()
    r = await client.patch(f"{API}/brands/{hang['id']}", json={"slug": "Sai Slug"})
    assert r.status_code == 422, "PATCH phải giữ ràng buộc của model gốc"

    r = await client.post(f"{API}/tags", json={"kind": "khong-co", "slug": "a", "name": "A"})
    assert r.status_code == 422
