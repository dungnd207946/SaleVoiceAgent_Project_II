"""Chính sách + gói dịch vụ: CRUD · CHECK price_vnd XOR price_percent · báo giá gói theo SKU."""

import asyncpg
import httpx

from tests.modules.promotions.seed import tao_hang, tao_nganh, tao_sp

API = "/api/v1"


async def test_crud_va_loc_chinh_sach(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    b = await tao_hang(admin_pool, "apple")
    base = {"policyType": "warranty", "contentMd": "Nội dung"}
    r = await client.post(f"{API}/policies", json=base | {"slug": "bh-apple", "title": "BH Apple", "brandId": b})
    assert r.status_code == 201, r.text
    assert r.json()["effectiveFrom"] is not None, "bỏ trống ⇒ DEFAULT current_date"
    await client.post(
        f"{API}/policies", json=base | {"slug": "doi-tra", "title": "Hư gì đổi nấy", "policyType": "return_exchange"}
    )
    await client.post(
        f"{API}/policies",
        json=base | {"slug": "cu", "title": "Cũ", "effectiveFrom": "2025-01-01", "effectiveTo": "2025-06-30"},
    )

    lay = lambda r: sorted(x["slug"] for x in r.json()["items"])  # noqa: E731
    assert lay(await client.get(f"{API}/policies", params={"brandId": b})) == ["bh-apple"]
    assert lay(await client.get(f"{API}/policies", params={"policyType": "return_exchange"})) == ["doi-tra"]
    assert lay(await client.get(f"{API}/policies", params={"active": "true"})) == ["bh-apple", "doi-tra"]

    r = await client.post(
        f"{API}/policies",
        json=base | {"slug": "sai", "title": "X", "effectiveFrom": "2026-02-01", "effectiveTo": "2026-01-01"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "CHECK_FAILED"


async def test_goi_dich_vu_mot_kieu_gia(client: httpx.AsyncClient) -> None:
    base = {"code": "BH-ROI-VO", "name": "BH rơi vỡ", "serviceType": "drop_damage", "durationMonths": 12}
    assert (
        await client.post(f"{API}/service-packages", json=base | {"priceVnd": 1, "pricePercent": 5})
    ).status_code == 422
    assert (await client.post(f"{API}/service-packages", json=base)).status_code == 422
    r = await client.post(f"{API}/service-packages", json=base | {"priceVnd": 990_000})
    assert r.status_code == 201, r.text
    # PATCH thêm % mà không xoá giá cố định ⇒ CHECK DB chặn
    r = await client.patch(f"{API}/service-packages/{r.json()['id']}", json={"pricePercent": 5})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CHECK_FAILED"
    assert (await client.get(f"{API}/service-packages", params={"serviceType": "drop_damage"})).json()["total"] == 1


async def test_bao_gia_goi_theo_sku(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    apple, samsung = await tao_hang(admin_pool, "apple"), await tao_hang(admin_pool, "samsung")
    c = await tao_nganh(admin_pool, "dien-thoai")
    v = (await tao_sp(admin_pool, "iphone-16", brand_id=apple, category_id=c, gia=[(30_000_000, 28_990_005)]))[
        "variant_ids"
    ][0]

    async def goi(code: str, **kw: object) -> None:
        body = {"code": code, "name": code, "serviceType": "extended_warranty", "durationMonths": 12} | kw
        assert (await client.post(f"{API}/service-packages", json=body)).status_code == 201

    await goi("CO-DINH", priceVnd=990_000)
    await goi("PHAN-TRAM", pricePercent=5.5, brandId=apple, categoryId=c)
    await goi("SAMSUNG", priceVnd=1, brandId=samsung)
    await goi("RE", priceVnd=1, maxProductPriceVnd=10_000_000)
    await goi("TAT", priceVnd=1, isActive=False)

    r = await client.get(f"{API}/service-packages/quote", params={"variantId": v})
    assert r.status_code == 200, r.text
    gia = {g["code"]: g["quotedPriceVnd"] for g in r.json()}
    # 28.990.005 × 5,5% = 1.594.450,275 ⇒ 1.594.450
    assert gia == {"CO-DINH": 990_000, "PHAN-TRAM": 1_594_450}
    assert r.json()[0]["productPriceVnd"] == 28_990_005
    assert (await client.get(f"{API}/service-packages/quote", params={"variantId": 999})).status_code == 404
