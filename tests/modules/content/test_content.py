"""Bài viết: CRUD · lọc đã đăng/loại/từ khoá · liên kết sản phẩm (thay toàn bộ)."""

import asyncpg
import httpx

from tests.modules.promotions.seed import tao_hang, tao_nganh, tao_sp

API = "/api/v1"


def bai(slug: str, **kw: object) -> dict:
    return {"kind": "review", "slug": slug, "title": slug, "contentMd": "..."} | kw


async def test_crud_va_loc(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{API}/articles", json=bai("danh-gia-iphone-16", publishedAt="2026-01-01T00:00:00Z"))
    assert r.status_code == 201, r.text
    id_ = r.json()["id"]
    await client.post(f"{API}/articles", json=bai("nhap", kind="news"))
    await client.post(f"{API}/articles", json=bai("hen-gio", publishedAt="2099-01-01T00:00:00Z"))
    assert (await client.post(f"{API}/articles", json=bai("x", kind="sai"))).status_code == 422
    assert (await client.post(f"{API}/articles", json=bai("nhap"))).status_code == 409

    slug = lambda r: sorted(x["slug"] for x in r.json()["items"])  # noqa: E731
    assert slug(await client.get(f"{API}/articles", params={"published": "true"})) == ["danh-gia-iphone-16"]
    assert slug(await client.get(f"{API}/articles", params={"published": "false"})) == ["hen-gio", "nhap"]
    assert slug(await client.get(f"{API}/articles", params={"kind": "news"})) == ["nhap"]
    assert slug(await client.get(f"{API}/articles", params={"q": "IPHONE"})) == ["danh-gia-iphone-16"]

    r = await client.patch(f"{API}/articles/{id_}", json={"publishedAt": None})
    assert r.status_code == 200 and r.json()["publishedAt"] is None, "null tường minh = gỡ đăng"
    assert (await client.delete(f"{API}/articles/{id_}")).status_code == 204


async def test_lien_ket_san_pham(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    b, c = await tao_hang(admin_pool, "apple"), await tao_nganh(admin_pool, "dien-thoai")
    p1 = (await tao_sp(admin_pool, "iphone-16", brand_id=b, category_id=c))["product_id"]
    p2 = (await tao_sp(admin_pool, "iphone-16-pro", brand_id=b, category_id=c))["product_id"]
    a = (await client.post(f"{API}/articles", json=bai("so-sanh"))).json()["id"]
    khac = (await client.post(f"{API}/articles", json=bai("khac"))).json()["id"]

    r = await client.put(f"{API}/articles/{a}/products", json={"productIds": [p2, p1, p1]})
    assert r.status_code == 200, r.text
    assert [x["productId"] for x in r.json()] == [p1, p2] and r.json()[0]["slug"] == "iphone-16"

    r = await client.put(f"{API}/articles/{a}/products", json={"productIds": [p2]})
    assert [x["productId"] for x in (await client.get(f"{API}/articles/{a}/products")).json()] == [p2]
    await client.put(f"{API}/articles/{khac}/products", json={"productIds": [p1]})

    ids = lambda r: [x["id"] for x in r.json()["items"]]  # noqa: E731
    assert ids(await client.get(f"{API}/articles", params={"productId": p2})) == [a]
    assert ids(await client.get(f"{API}/articles", params={"productId": p1})) == [khac]

    r = await client.put(f"{API}/articles/{a}/products", json={"productIds": [99999]})
    assert r.status_code == 409
    assert len((await client.get(f"{API}/articles/{a}/products")).json()) == 1, "lỗi FK ⇒ rollback, giữ liên kết cũ"
    assert (await client.put(f"{API}/articles/{a}/products", json={"productIds": []})).json() == []
    assert (await client.get(f"{API}/articles/999/products")).status_code == 404
