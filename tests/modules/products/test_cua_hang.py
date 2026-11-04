"""API cửa hàng: thẻ danh sách + bộ lọc, trang chi tiết gom đủ KM/trả góp/chính sách/tồn kho, so sánh.

Dữ liệu cấu hình bán hàng (KM, trả góp, cửa hàng, review) seed bằng SQL owner — module này chỉ đọc chúng.
"""

from dataclasses import dataclass

import asyncpg
import httpx
import pytest

API = "/api/v1"


@dataclass
class Bo:
    apple: int
    samsung: int
    xiaomi: int
    cat: int
    a: int  # iPhone 16 — 18tr (giảm 10%), 5G, NFC, face 3D, IP68, có OIS + sạc không dây
    b: int  # Galaxy S25 — 17,6tr (giảm 20%), 5G, RAM 12
    c: int  # Redmi Note — 6tr (SKU 5tr hết hàng bị bỏ qua), 4G
    d: int  # nháp — không bao giờ hiện
    sku_a: list[int]


async def _sp(client: httpx.AsyncClient, brand: int, cat: int, slug: str, ten: str, **them: object) -> int:
    r = await client.post(
        f"{API}/products",
        json={"brandId": brand, "categoryId": cat, "slug": slug, "name": ten, "status": "selling", **them},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _sku(client: httpx.AsyncClient, sp: int, sku: str, ram: float, rom: int, gia: int, **them: object) -> int:
    body = {"sku": sku, "ramGb": ram, "storageGb": rom, "listPriceVnd": gia, **them}
    r = await client.post(f"{API}/products/{sp}/variants", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
async def bo(client: httpx.AsyncClient) -> Bo:
    async def brand(slug: str, ten: str) -> int:
        return (await client.post(f"{API}/brands", json={"slug": slug, "name": ten})).json()["id"]

    apple, samsung, xiaomi = (
        await brand("apple", "Apple"),
        await brand("samsung", "Samsung"),
        await brand("xiaomi", "Xiaomi"),
    )
    cat = (await client.post(f"{API}/categories", json={"slug": "dtdd", "name": "Điện thoại"})).json()["id"]

    a = await _sp(client, apple, cat, "iphone-16", "iPhone 16", isFeatured=True, releaseDate="2024-09-01")
    b = await _sp(client, samsung, cat, "galaxy-s25", "Điện thoại Galaxy S25", releaseDate="2025-02-01")
    c = await _sp(client, xiaomi, cat, "redmi-note", "Redmi Note 14", releaseDate="2025-01-01")
    d = await _sp(client, samsung, cat, "nhap", "Bản nháp", status="draft")

    sku_a = [
        await _sku(client, a, "A-128", 8, 128, 20_000_000, salePriceVnd=18_000_000, isDefault=True),
        await _sku(client, a, "A-256", 8, 256, 23_000_000),
    ]
    await _sku(client, b, "B-256", 12, 256, 22_000_000, salePriceVnd=17_600_000)
    await _sku(client, c, "C-128", 6, 128, 5_000_000, saleStatus="out_of_stock")
    await _sku(client, c, "C-256", 8, 256, 6_000_000)
    await _sku(client, d, "D-1", 8, 128, 1_000_000)

    specs = {
        a: {"osName": "iOS", "networkGen": "5G", "hasNfc": True, "hasFace3d": True, "ipRating": "IP68",
            "refreshRateHz": 60, "maxChargeW": 20, "screenSizeInch": 6.1, "resolutionClass": "Retina"},
        b: {"osName": "Android", "networkGen": "5G", "hasNfc": True, "refreshRateHz": 120, "maxChargeW": 45,
            "resolutionClass": "Full HD+"},
        c: {"osName": "Android", "networkGen": "4G", "refreshRateHz": 120, "maxChargeW": 33},
    }  # fmt: skip
    for sp, s in specs.items():
        assert (await client.put(f"{API}/products/{sp}/specs", json=s)).status_code == 200

    async def tinh_nang(slug: str) -> int:
        body = {"featureGroup": "special", "name": slug, "slug": slug}
        return (await client.post(f"{API}/features", json=body)).json()["id"]

    ois, wl = await tinh_nang("ois"), await tinh_nang("sac-khong-day")
    await client.put(f"{API}/products/{a}/features", json={"featureIds": [ois, wl]})
    await client.put(f"{API}/products/{b}/features", json={"featureIds": [ois]})
    await client.put(f"{API}/products/{c}/features", json={"featureIds": [wl]})

    tag = (await client.post(f"{API}/tags", json={"kind": "need", "slug": "chup-anh", "name": "Chụp ảnh"})).json()
    await client.put(f"{API}/products/{a}/tags", json={"tagIds": [tag["id"]]})
    await client.post(f"{API}/products/{a}/media", json={"mediaType": "image", "url": "/a-1.jpg", "sortOrder": 0})
    await client.post(
        f"{API}/products/{a}/media", json={"mediaType": "thumbnail", "url": "/a-thumb.jpg", "sortOrder": 5}
    )
    return Bo(apple, samsung, xiaomi, cat, a, b, c, d, sku_a)


async def _slugs(client: httpx.AsyncClient, **params: object) -> list[str]:
    r = await client.get(f"{API}/catalog/products", params=params)
    assert r.status_code == 200, r.text
    return [p["slug"] for p in r.json()["items"]]


async def test_the_san_pham(client: httpx.AsyncClient, bo: Bo) -> None:
    trang = (await client.get(f"{API}/catalog/products")).json()
    assert trang["total"] == 3, "SP nháp không lên danh sách"
    a = trang["items"][0]
    assert a["slug"] == "iphone-16", "mặc định: nổi bật lên đầu"
    assert a["brand"] == {"id": bo.apple, "name": "Apple", "slug": "apple"}
    assert (a["priceVnd"], a["listPriceVnd"], a["discountPercent"]) == (18_000_000, 20_000_000, 10)
    assert a["ramOptions"] == [8.0] and a["storageOptions"] == [128.0, 256.0]
    assert a["thumbnail"] == "/a-thumb.jpg" and a["tags"] == ["Chụp ảnh"] and a["screenSizeInch"] == 6.1
    assert a["hasInstallment0"] is False and a["giftValueVnd"] is None

    c = next(p for p in trang["items"] if p["slug"] == "redmi-note")
    assert c["priceVnd"] == 6_000_000, "SKU hết hàng rẻ hơn không làm giá thẻ"


async def test_bo_loc(client: httpx.AsyncClient, bo: Bo) -> None:
    assert set(await _slugs(client, brandId=[bo.apple, bo.samsung])) == {"iphone-16", "galaxy-s25"}
    assert set(await _slugs(client, priceMin=10_000_000, priceMax=18_000_000)) == {"iphone-16", "galaxy-s25"}
    assert await _slugs(client, priceMax=17_999_999, priceMin=7_000_000) == ["galaxy-s25"]
    assert await _slugs(client, ramGb=12) == ["galaxy-s25"]
    assert set(await _slugs(client, ramGb=[6, 12])) == {"galaxy-s25", "redmi-note"}
    assert await _slugs(client, storageGb=128, os="iOS") == ["iphone-16"]
    assert await _slugs(client, feature=["ois", "sac-khong-day"]) == ["iphone-16"], "feature: phải có ĐỦ"
    assert set(await _slugs(client, feature="ois")) == {"iphone-16", "galaxy-s25"}
    assert set(await _slugs(client, has5g="true")) == {"iphone-16", "galaxy-s25"}
    assert await _slugs(client, has5g="false") == ["redmi-note"]
    assert await _slugs(client, hasFace3d="true", waterResistant="true") == ["iphone-16"]
    assert set(await _slugs(client, refreshRateMin=120)) == {"galaxy-s25", "redmi-note"}
    assert await _slugs(client, chargeWMin=40) == ["galaxy-s25"]
    assert await _slugs(client, tag="chup-anh") == ["iphone-16"]
    assert await _slugs(client, resolutionClass="Full HD+") == ["galaxy-s25"]
    assert await _slugs(client, q="dien thoai galaxy") == ["galaxy-s25"], "tìm không dấu"
    assert await _slugs(client, q="samsung") == ["galaxy-s25"], "tìm theo tên hãng"
    assert await _slugs(client, q="100%") == []

    r = await client.get(f"{API}/catalog/products", params={"phoneType": "dien-thoai"})
    assert r.status_code == 422


async def test_sap_xep_va_phan_trang(client: httpx.AsyncClient, bo: Bo) -> None:
    assert await _slugs(client, sort="price_asc") == ["redmi-note", "galaxy-s25", "iphone-16"]
    assert await _slugs(client, sort="price_desc") == ["iphone-16", "galaxy-s25", "redmi-note"]
    assert await _slugs(client, sort="discount") == ["galaxy-s25", "iphone-16", "redmi-note"]
    assert await _slugs(client, sort="newest") == ["galaxy-s25", "redmi-note", "iphone-16"]
    r = (await client.get(f"{API}/catalog/products", params={"sort": "price_asc", "limit": 1, "offset": 1})).json()
    assert r["total"] == 3 and [p["slug"] for p in r["items"]] == ["galaxy-s25"]
    r = (await client.get(f"{API}/catalog/products", params={"offset": 10})).json()
    assert r["total"] == 3 and r["items"] == []


async def _seed_ban_hang(pool: asyncpg.Pool, bo: Bo) -> None:
    """KM · trả góp · chính sách · gói DV · kho · review — đủ ca áp dụng / không áp dụng."""
    async with pool.acquire() as conn:
        km = """INSERT INTO shop.promotions (name, promo_type, discount_vnd, voucher_value_vnd, gift_product_id,
                  choice_group, starts_at, ends_at, is_active)
                VALUES ($1, $2, $3, $4, $5, $6, now() + $7::text::interval, now() + $8::text::interval, $9)
                RETURNING id"""
        hang = await conn.fetchval(
            km, "Giảm 1 triệu", "discount_amount", 1_000_000, None, None, None, "-1 day", "7 days", True
        )
        sku = await conn.fetchval(km, "Phiếu 500k", "voucher", None, 500_000, None, "qua", "-1 day", None, True)
        qua = await conn.fetchval(km, "Tặng Redmi", "gift_product", None, None, bo.c, "qua", "-1 day", None, True)
        het = await conn.fetchval(
            km, "Hết hạn", "discount_amount", 9_000_000, None, None, None, "-9 days", "-1 day", True
        )
        tat = await conn.fetchval(km, "Đã tắt", "discount_amount", 9_000_000, None, None, None, "-1 day", None, False)
        khac = await conn.fetchval(
            km, "Của Samsung", "discount_amount", 9_000_000, None, None, None, "-1 day", None, True
        )
        await conn.executemany(
            "INSERT INTO shop.promotion_targets (promotion_id, product_id, variant_id, brand_id) "
            "VALUES ($1, $2, $3, $4)",
            [(hang, None, None, bo.apple), (sku, None, bo.sku_a[1], None), (qua, bo.a, None, None),
             (het, bo.a, None, None), (tat, bo.a, None, None), (khac, None, None, bo.samsung)],
        )  # fmt: skip

        doi_tac = await conn.fetchval(
            "INSERT INTO shop.finance_partners (code, name, partner_type) "
            "VALUES ('HC', 'Home Credit', 'finance_company') RETURNING id"
        )
        goi = """INSERT INTO shop.installment_plans (partner_id, name, tenor_months, interest_rate_monthly, starts_at)
                 VALUES ($1, $2, $3, $4, now() - interval '1 day') RETURNING id"""
        g0 = await conn.fetchval(goi, doi_tac, "Trả chậm 0% 6 tháng", 6, 0)
        g1 = await conn.fetchval(goi, doi_tac, "Trả góp 1,5% 12 tháng", 12, 1.5)
        await conn.executemany(
            "INSERT INTO shop.installment_plan_targets (plan_id, category_id, product_id) VALUES ($1, $2, $3)",
            [(g0, None, bo.a), (g1, bo.cat, None)],
        )

        cs = "INSERT INTO shop.policies (policy_type, slug, title, content_md, brand_id) VALUES ($1, $2, $3, 'x', $4)"
        await conn.execute(cs, "return_exchange", "doi-tra", "Hư gì đổi nấy", None)
        await conn.execute(cs, "warranty", "bh-apple", "BH Apple", bo.apple)
        await conn.execute(cs, "warranty", "bh-samsung", "BH Samsung", bo.samsung)
        gdv = """INSERT INTO shop.service_packages (code, name, service_type, duration_months, price_vnd,
                   min_product_price_vnd, max_product_price_vnd) VALUES ($1, $2, 'drop_damage', 12, 500000, $3, $4)"""
        await conn.execute(gdv, "RV-CAO", "Rơi vỡ máy cao cấp", 15_000_000, None)
        await conn.execute(gdv, "RV-RE", "Rơi vỡ máy rẻ", None, 10_000_000)

        await conn.execute("INSERT INTO shop.provinces (code, name) VALUES ('79', 'TP.HCM')")
        ch = """INSERT INTO shop.stores (code, name, address, province_code, is_active)
                VALUES ($1, $1, 'x', '79', $2) RETURNING id"""
        mo, dong = await conn.fetchval(ch, "Q1", True), await conn.fetchval(ch, "Q2", False)
        await conn.executemany(
            "INSERT INTO shop.inventory (store_id, variant_id, quantity, reserved_qty) VALUES ($1, $2, $3, $4)",
            [(mo, bo.sku_a[0], 5, 1), (dong, bo.sku_a[0], 10, 0)],
        )
        await conn.executemany(
            "INSERT INTO shop.product_reviews (product_id, author_name, rating, status) VALUES ($1, 'k', $2, $3)",
            [(bo.a, 5, "published"), (bo.a, 4, "published"), (bo.a, 1, "hidden")],
        )


async def test_chi_tiet_gom_du(client: httpx.AsyncClient, admin_pool: asyncpg.Pool, bo: Bo) -> None:
    await _seed_ban_hang(admin_pool, bo)
    await client.post(f"{API}/products/{bo.a}/faqs", json={"question": "Có sạc?", "answer": "Không"})
    await client.post(f"{API}/faqs", json={"question": "Đổi trả?", "answer": "30 ngày"})
    await client.put(
        f"{API}/products/{bo.a}/relations",
        json=[
            {"relatedProductId": bo.b, "relationType": "similar"},
            {"relatedProductId": bo.d, "relationType": "similar"},
        ],
    )

    r = await client.get(f"{API}/catalog/products/iphone-16")
    assert r.status_code == 200, r.text
    ct = r.json()
    assert ct["product"]["id"] == bo.a and ct["brand"]["slug"] == "apple" and ct["category"]["slug"] == "dtdd"
    assert ct["priceVnd"] == 18_000_000 and ct["hasInstallment0"] is True and ct["giftValueVnd"] == 1_000_000

    sku = {v["sku"]: v for v in ct["variants"]}
    assert sku["A-128"]["qtyAvailable"] == 4, "tồn - giữ, bỏ cửa hàng đã đóng"
    assert sku["A-256"]["qtyAvailable"] == 0 and sku["A-128"]["discountPercent"] == 10

    km = {k["name"]: k for k in ct["promotions"]}
    assert set(km) == {"Giảm 1 triệu", "Phiếu 500k", "Tặng Redmi"}, "bỏ KM hết hạn/đã tắt/của hãng khác"
    assert km["Phiếu 500k"]["appliesToAllVariants"] is False and km["Phiếu 500k"]["variantIds"] == [bo.sku_a[1]]
    assert km["Giảm 1 triệu"]["appliesToAllVariants"] is True
    assert km["Tặng Redmi"]["giftProductName"] == "Redmi Note 14" and km["Tặng Redmi"]["choiceGroup"] == "qua"

    assert [(g["tenorMonths"], g["partner"]["name"]) for g in ct["installmentPlans"]] == [
        (6, "Home Credit"),
        (12, "Home Credit"),
    ]
    assert {p["slug"] for p in ct["policies"]} == {"doi-tra", "bh-apple"}
    assert [g["code"] for g in ct["servicePackages"]] == ["RV-CAO"]
    assert ct["specs"]["has5g"] is True
    assert [(g["group"], len(g["items"])) for g in ct["features"]] == [("special", 2)]
    assert [f["question"] for f in ct["faqs"]] == ["Có sạc?", "Đổi trả?"], "FAQ của SP trước, FAQ chung sau"
    assert [x["product"]["slug"] for x in ct["related"]] == ["galaxy-s25"], "SP nháp không lộ qua liên quan"
    assert ct["rating"] == {"avg": 4.5, "count": 2, "distribution": {"1": 0, "2": 0, "3": 0, "4": 1, "5": 1}}
    assert ct["media"][0]["url"] == "/a-1.jpg" and ct["tags"][0]["slug"] == "chup-anh"

    the = (await client.get(f"{API}/catalog/products", params={"brandId": bo.apple})).json()["items"][0]
    assert the["hasInstallment0"] is True and the["giftValueVnd"] == 1_000_000, "thẻ và chi tiết cùng một nguồn"

    assert (await client.get(f"{API}/catalog/products/nhap")).status_code == 404
    assert (await client.get(f"{API}/catalog/products/khong-co")).status_code == 404


async def test_so_sanh(client: httpx.AsyncClient, bo: Bo) -> None:
    r = await client.get(f"{API}/catalog/compare", params={"ids": [bo.c, bo.a, bo.d, 999]})
    assert r.status_code == 200
    ds = r.json()
    assert [x["product"]["slug"] for x in ds] == ["redmi-note", "iphone-16"], "giữ thứ tự, bỏ nháp/không có"
    assert ds[0]["specs"]["networkGen"] == "4G" and ds[1]["product"]["priceVnd"] == 18_000_000

    r = await client.get(f"{API}/catalog/compare", params={"ids": [1, 2, 3, 4, 5]})
    assert r.status_code == 422
