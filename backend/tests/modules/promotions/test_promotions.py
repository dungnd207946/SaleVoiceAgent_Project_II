"""Khuyến mãi: CRUD theo CHECK promo_type · thay đối tượng · KM áp cho SP qua hãng/SKU."""

import asyncpg
import httpx

from tests.modules.promotions.seed import tao_hang, tao_nganh, tao_sp

API = "/api/v1"
BAT_DAU = "2026-01-01T00:00:00Z"


def km(**kw: object) -> dict:
    return {"name": "Giảm 1 triệu", "promoType": "discount_amount", "discountVnd": 1_000_000, "startsAt": BAT_DAU} | kw


async def test_crud_va_rang_buoc_promo_type(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{API}/promotions", json=km(discountVnd=None))
    assert r.status_code == 422, "discount_amount thiếu discountVnd phải bị chặn ở Pydantic"

    r = await client.post(f"{API}/promotions", json=km())
    assert r.status_code == 201, r.text
    hang = r.json()
    assert hang["discountVnd"] == 1_000_000 and hang["channel"] == "all" and hang["isActive"] is True

    # PATCH không mang validator của POST — CHECK DB là chốt chặn.
    r = await client.patch(f"{API}/promotions/{hang['id']}", json={"promoType": "voucher"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CHECK_FAILED"

    r = await client.patch(
        f"{API}/promotions/{hang['id']}", json={"promoType": "discount_percent", "discountPercent": 5}
    )
    assert r.status_code == 200 and r.json()["discountPercent"] == 5.0

    assert (await client.delete(f"{API}/promotions/{hang['id']}")).status_code == 204
    assert (await client.get(f"{API}/promotions/{hang['id']}")).status_code == 404


async def test_loc_danh_sach(client: httpx.AsyncClient) -> None:
    await client.post(f"{API}/promotions", json=km(name="Giảm sốc"))
    await client.post(f"{API}/promotions", json=km(name="Hết hạn", endsAt="2026-02-01T00:00:00Z"))
    await client.post(f"{API}/promotions", json=km(name="Tắt", isActive=False))
    await client.post(f"{API}/promotions", json=km(name="Quà", promoType="other", discountVnd=None))

    ten = lambda r: sorted(x["name"] for x in r.json()["items"])  # noqa: E731
    assert ten(await client.get(f"{API}/promotions", params={"active": "true"})) == ["Giảm sốc", "Quà"]
    assert ten(await client.get(f"{API}/promotions", params={"promoType": "other"})) == ["Quà"]
    assert ten(await client.get(f"{API}/promotions", params={"q": "hạn"})) == ["Hết hạn"]


async def test_thay_doi_tuong(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    b = await tao_hang(admin_pool, "apple")
    c = await tao_nganh(admin_pool, "dien-thoai")
    sp = await tao_sp(admin_pool, "iphone-16", brand_id=b, category_id=c)
    pid = (await client.post(f"{API}/promotions", json=km())).json()["id"]

    r = await client.put(f"{API}/promotions/{pid}/targets", json=[{"brandId": b}, {"productId": sp["product_id"]}])
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2

    r = await client.put(f"{API}/promotions/{pid}/targets", json=[{"categoryId": c}, {"categoryId": c}])
    assert [t["categoryId"] for t in r.json()] == [c], "PUT thay TOÀN BỘ, trùng thì gộp"
    assert len((await client.get(f"{API}/promotions/{pid}/targets")).json()) == 1

    for sai in ([{"brandId": b, "productId": sp["product_id"]}], [{}], [{"tenSai": 1}]):
        r = await client.put(f"{API}/promotions/{pid}/targets", json=sai)
        assert r.status_code == 422, sai
    r = await client.put(f"{API}/promotions/{pid}/targets", json=[{"brandId": 99999}])
    assert r.status_code == 409 and r.json()["error"]["code"] == "REFERENCE_ERROR"
    assert len((await client.get(f"{API}/promotions/{pid}/targets")).json()) == 1, "lỗi giữa chừng phải rollback"
    assert (await client.get(f"{API}/promotions/999/targets")).status_code == 404


async def test_km_ap_dung_qua_hang_sku_va_nhom_chon(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    apple, samsung = await tao_hang(admin_pool, "apple"), await tao_hang(admin_pool, "samsung")
    c = await tao_nganh(admin_pool, "dien-thoai")
    ip = await tao_sp(
        admin_pool, "iphone-16", brand_id=apple, category_id=c, gia=[(30_000_000, None), (35_000_000, None)]
    )
    await tao_sp(admin_pool, "galaxy-s25", brand_id=samsung, category_id=c)
    v128, v256 = ip["variant_ids"]

    async def tao(dt: list[dict], **kw: object) -> int:
        id_ = (await client.post(f"{API}/promotions", json=km(**kw))).json()["id"]
        assert (await client.put(f"{API}/promotions/{id_}/targets", json=dt)).status_code == 200
        return id_

    hang = await tao([{"brandId": apple}], name="Hãng Apple", choiceGroup="qua", priority=5)
    tai_nghe = await tao([{"productId": ip["product_id"]}], name="Tai nghe", choiceGroup="qua")
    chi_256 = await tao([{"variantId": v256}], name="Chỉ bản 256")
    await tao([{"brandId": samsung}], name="Của Samsung")
    await tao([{"brandId": apple}], name="Hết hạn", endsAt="2026-02-01T00:00:00Z")

    r = await client.get(f"{API}/promotions/applicable", params={"productId": ip["product_id"]})
    assert r.status_code == 200, r.text
    ds = {p["id"]: p for p in r.json()["promotions"]}
    assert list(ds) == [hang, tai_nghe, chi_256], "sắp theo priority giảm dần, rồi id"
    assert ds[hang]["appliesVia"] == ["brand"] and ds[hang]["variantIds"] is None
    assert ds[chi_256]["variantIds"] == [v256]
    assert r.json()["choiceGroups"] == [{"choiceGroup": "qua", "promotionIds": [hang, tai_nghe]}]

    r = await client.get(f"{API}/promotions/applicable", params={"variantId": v128})
    assert [p["id"] for p in r.json()["promotions"]] == [hang, tai_nghe], "KM của SKU khác không lọt vào"

    assert (await client.get(f"{API}/promotions/applicable")).status_code == 422
    assert (await client.get(f"{API}/promotions/applicable", params={"productId": 999})).status_code == 404
