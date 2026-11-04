"""Trả góp: CRUD đối tác/gói · đối tượng áp dụng · báo giá ước tính (số tiền chính xác)."""

import asyncpg
import httpx

from tests.modules.promotions.seed import tao_hang, tao_nganh, tao_sp

API = "/api/v1"


async def _doi_tac(client: httpx.AsyncClient, code: str = "HOME_CREDIT") -> int:
    r = await client.post(
        f"{API}/finance-partners", json={"code": code, "name": code, "partnerType": "finance_company"}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _goi(client: httpx.AsyncClient, partner: int, targets: list[dict], **kw: object) -> int:
    body = {"partnerId": partner, "name": "Gói", "tenorMonths": 6} | kw
    r = await client.post(f"{API}/installment-plans", json=body)
    assert r.status_code == 201, r.text
    id_ = r.json()["id"]
    assert (await client.put(f"{API}/installment-plans/{id_}/targets", json=targets)).status_code == 200
    return id_


async def test_crud_doi_tac_va_goi(client: httpx.AsyncClient) -> None:
    p = await _doi_tac(client)
    assert (await client.get(f"{API}/finance-partners", params={"q": "home"})).json()["total"] == 1
    assert (
        await client.post(f"{API}/finance-partners", json={"code": "HOME_CREDIT", "name": "X", "partnerType": "bnpl"})
    ).status_code == 409

    r = await client.post(f"{API}/installment-plans", json={"partnerId": p, "name": "0% 6 tháng", "tenorMonths": 6})
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["interestRateMonthly"] == 0.0 and g["startsAt"] is not None, "bỏ trống startsAt ⇒ DEFAULT now()"
    await client.post(
        f"{API}/installment-plans", json={"partnerId": p, "name": "Tắt", "tenorMonths": 12, "isActive": False}
    )
    assert (await client.get(f"{API}/installment-plans", params={"partnerId": p})).json()["total"] == 2
    assert [
        x["id"] for x in (await client.get(f"{API}/installment-plans", params={"active": "true"})).json()["items"]
    ] == [g["id"]]

    r = await client.patch(f"{API}/installment-plans/{g['id']}", json={"interestRateMonthly": 1.5})
    assert r.status_code == 200 and r.json()["interestRateMonthly"] == 1.5
    assert (
        await client.put(f"{API}/installment-plans/{g['id']}/targets", json=[{"variantId": 1, "brandId": 1}])
    ).status_code == 422
    assert (await client.delete(f"{API}/finance-partners/{p}")).status_code == 409, "đối tác đang có gói ⇒ RESTRICT"


async def test_bao_gia_vi_du_tinh_tay(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    b, c = await tao_hang(admin_pool, "apple"), await tao_nganh(admin_pool, "dien-thoai")
    sp = await tao_sp(admin_pool, "iphone-16", brand_id=b, category_id=c)  # giá bán 28.990.000
    v = sp["variant_ids"][0]
    p = await _doi_tac(client)
    goi = await _goi(
        client,
        p,
        [{"brandId": b}],
        tenorMonths=6,
        interestRateMonthly=1.5,
        minDownPaymentPercent=30,
        fixedFeeVnd=500_000,
    )

    r = await client.get(f"{API}/installment-plans/quote", params={"variantId": v, "planId": goi})
    assert r.status_code == 200, r.text
    q = r.json()
    # trả trước = round(28.990.000 × 30%) = 8.697.000 ; vay = 20.293.000
    # góp = ceil(20.293.000/6 + 20.293.000 × 1,5%) = ceil(3.382.166,67 + 304.395) = 3.686.562
    # tổng = 8.697.000 + 3.686.562 × 6 + 500.000 = 31.316.372 ; chênh = 2.326.372
    assert q["priceVnd"] == 28_990_000 and q["downPaymentPercent"] == 30.0
    assert q["downPaymentVnd"] == 8_697_000 and q["loanVnd"] == 20_293_000
    assert q["monthlyPaymentVnd"] == 3_686_562
    assert q["totalPaymentVnd"] == 31_316_372 and q["extraCostVnd"] == 2_326_372

    r = await client.get(
        f"{API}/installment-plans/quote", params={"variantId": v, "planId": goi, "downPaymentPercent": 50}
    )
    q = r.json()
    # trả trước 14.495.000 ; vay 14.495.000 ; góp = ceil(2.415.833,33 + 217.425) = 2.633.259
    assert q["downPaymentVnd"] == 14_495_000 and q["monthlyPaymentVnd"] == 2_633_259
    assert q["totalPaymentVnd"] == 14_495_000 + 2_633_259 * 6 + 500_000


async def test_bao_gia_bi_tu_choi(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    apple, samsung = await tao_hang(admin_pool, "apple"), await tao_hang(admin_pool, "samsung")
    c = await tao_nganh(admin_pool, "dien-thoai")
    v = (await tao_sp(admin_pool, "iphone-16", brand_id=apple, category_id=c))["variant_ids"][0]
    p = await _doi_tac(client)

    async def loi(params: dict) -> str:
        r = await client.get(f"{API}/installment-plans/quote", params={"variantId": v} | params)
        assert r.status_code == 422, r.text
        return r.json()["error"]["message"]

    khac_hang = await _goi(client, p, [{"brandId": samsung}])
    assert "không áp dụng" in await loi({"planId": khac_hang})
    re = await _goi(client, p, [{"brandId": apple}], maxPriceVnd=10_000_000)
    assert "ngoài khoảng giá" in await loi({"planId": re})
    toi_thieu = await _goi(client, p, [{"categoryId": c}], minDownPaymentPercent=30)
    assert "tối thiểu" in await loi({"planId": toi_thieu, "downPaymentPercent": 20})
    tat = await _goi(client, p, [{"variantId": v}], isActive=False)
    assert "hiệu lực" in await loi({"planId": tat})

    assert (
        await client.get(f"{API}/installment-plans/quote", params={"variantId": v, "planId": 999})
    ).status_code == 404
    assert (
        await client.get(f"{API}/installment-plans/quote", params={"variantId": 999, "planId": re})
    ).status_code == 404


async def test_bao_gia_moi_goi_sap_theo_gop_thang(client: httpx.AsyncClient, admin_pool: asyncpg.Pool) -> None:
    b, c = await tao_hang(admin_pool, "apple"), await tao_nganh(admin_pool, "dien-thoai")
    sp = await tao_sp(admin_pool, "iphone-16", brand_id=b, category_id=c)
    v = sp["variant_ids"][0]
    p = await _doi_tac(client)
    sau = await _goi(client, p, [{"productId": sp["product_id"]}], tenorMonths=6)
    muoi_hai = await _goi(client, p, [{"brandId": b}], tenorMonths=12, minDownPaymentPercent=20)
    await _goi(client, p, [{"brandId": b}], tenorMonths=24, maxPriceVnd=1_000_000)  # ngoài khoảng giá

    r = await client.get(f"{API}/installment-plans/quotes", params={"variantId": v})
    assert r.status_code == 200, r.text
    ds = r.json()
    assert [q["planId"] for q in ds] == [muoi_hai, sau]
    # 12 tháng, 0%, trả trước 20%: vay 23.192.000 ⇒ ceil(1.932.666,67) = 1.932.667
    assert ds[0]["monthlyPaymentVnd"] == 1_932_667 and ds[0]["extraCostVnd"] == 4
