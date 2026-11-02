"""Bảng quỹ căn: tìm theo mã · lọc hướng · sắp xếp · danh sách giá trị có thật.

VÌ SAO BỐN THỨ NÀY PHẢI Ở SERVER, không làm ở FE: bảng quỹ căn phân trang bằng
`limit`/`offset`, tức trình duyệt chỉ giữ 20 hàng của trang đang xem. Lọc hay sắp
xếp trên mảng đó cho ra một câu trả lời trông đúng mà sai — "căn đắt nhất" hoá ra
là căn đắt nhất TRONG 20 hàng đầu, và không có gì trên màn hình nói ra điều đó.

`pytestmark` — cùng lý do `test_phan_trang_so.py`: mọi test ở đây cần Postgres thật.
"""

import pytest

pytestmark = pytest.mark.integration


async def _du_an_co_can(client_re, nap_du_an, can: list[dict], *, region: str = "Hà Nội") -> str:
    """Một dự án + một phân khu + đúng danh sách căn truyền vào.

    `region` chỉ để ĐỔI MÃ dự án: `nap_du_an` sinh mã từ region (`PT<2 ký tự>00`),
    nên test cần hai dự án phải gọi với hai region khác nhau — cùng region là 409.
    """
    ma = (await nap_du_an(1, region=region))[0]
    r = await client_re.post(f"/api/v1/projects/{ma}/zones", json={"zoneCode": "Z1", "name": "Z1"})
    assert r.status_code == 201, r.text
    for c in can:
        r = await client_re.post(
            f"/api/v1/projects/{ma}/units", json={"zoneCode": "Z1", "productType": "chung_cu", **c}
        )
        assert r.status_code == 201, r.text
    return ma


@pytest.mark.asyncio
async def test_tim_theo_ma_can_khop_mot_phan_va_khong_phan_biet_hoa_thuong(client_re, nap_du_an):
    ma = await _du_an_co_can(
        client_re,
        nap_du_an,
        [{"unitCode": "ZR-A-1203"}, {"unitCode": "ZR-B-0801"}, {"unitCode": "VP-A-1203"}],
    )

    r = (await client_re.get(f"/api/v1/projects/{ma}/units?unit_code=zr-a&limit=50")).json()

    assert [c["unitCode"] for c in r["items"]] == ["ZR-A-1203"]
    # `total` phải đi theo cùng vị từ — nếu `dem_can` bỏ sót filter mới thì thanh
    # trang nói "3 căn" trong khi bảng có 1 hàng.
    assert r["total"] == 1


@pytest.mark.asyncio
async def test_loc_theo_huong(client_re, nap_du_an):
    ma = await _du_an_co_can(
        client_re,
        nap_du_an,
        [
            {"unitCode": "DN-1", "direction": "dong_nam"},
            {"unitCode": "DN-2", "direction": "dong_nam"},
            {"unitCode": "TB-1", "direction": "tay_bac"},
        ],
    )

    r = (await client_re.get(f"/api/v1/projects/{ma}/units?direction=tay_bac&limit=50")).json()

    assert [c["unitCode"] for c in r["items"]] == ["TB-1"]
    assert r["total"] == 1


@pytest.mark.asyncio
async def test_sap_xep_theo_gia_hai_chieu(client_re, nap_du_an):
    ma = await _du_an_co_can(
        client_re,
        nap_du_an,
        [
            {"unitCode": "RE", "priceVnd": 2_000_000_000},
            {"unitCode": "DAT", "priceVnd": 9_000_000_000},
            {"unitCode": "VUA", "priceVnd": 5_000_000_000},
        ],
    )

    tang = (await client_re.get(f"/api/v1/projects/{ma}/units?sort=price_vnd&limit=50")).json()
    giam = (await client_re.get(f"/api/v1/projects/{ma}/units?sort=price_vnd&desc=true&limit=50")).json()

    assert [c["unitCode"] for c in tang["items"]] == ["RE", "VUA", "DAT"]
    assert [c["unitCode"] for c in giam["items"]] == ["DAT", "VUA", "RE"]


@pytest.mark.asyncio
async def test_can_chua_nhap_gia_xuong_cuoi_ca_hai_chieu(client_re, nap_du_an):
    """`NULLS LAST` cho CẢ hai chiều — mặc định của Postgres là `NULLS FIRST` ở
    chiều giảm, tức căn chưa nhập giá đứng đầu bảng "đắt nhất trước" và người
    dùng đọc ra "căn đắt nhất là căn không có giá"."""
    ma = await _du_an_co_can(
        client_re,
        nap_du_an,
        [{"unitCode": "CHUA-CO"}, {"unitCode": "RE", "priceVnd": 2_000_000_000}],
    )

    tang = (await client_re.get(f"/api/v1/projects/{ma}/units?sort=price_vnd&limit=50")).json()
    giam = (await client_re.get(f"/api/v1/projects/{ma}/units?sort=price_vnd&desc=true&limit=50")).json()

    assert [c["unitCode"] for c in tang["items"]][-1] == "CHUA-CO"
    assert [c["unitCode"] for c in giam["items"]][-1] == "CHUA-CO"


@pytest.mark.asyncio
async def test_sap_xep_giu_dung_thu_tu_qua_cac_trang(client_re, nap_du_an):
    """Sắp xếp + phân trang phải khớp nhau: trang 2 tiếp nối trang 1, không lặp
    và không bỏ sót. Đây là chỗ cursor keyset (`id < X`) sẽ cắt sai nếu router
    quên bỏ nó khi có `sort`."""
    ma = await _du_an_co_can(
        client_re,
        nap_du_an,
        [{"unitCode": f"U-{i}", "priceVnd": (i + 1) * 1_000_000_000} for i in range(5)],
    )

    t1 = (await client_re.get(f"/api/v1/projects/{ma}/units?sort=price_vnd&limit=2&offset=0")).json()
    t2 = (await client_re.get(f"/api/v1/projects/{ma}/units?sort=price_vnd&limit=2&offset=2")).json()

    assert [c["unitCode"] for c in t1["items"]] == ["U-0", "U-1"]
    assert [c["unitCode"] for c in t2["items"]] == ["U-2", "U-3"]


@pytest.mark.asyncio
async def test_sap_xep_gia_tri_la_bi_tu_choi_o_bien(client_re, nap_du_an):
    """Tên cột đi thẳng vào `ORDER BY` (không tham số hoá được), nên biên phải
    từ chối mọi thứ ngoài whitelist thay vì ghép nó vào câu SQL."""
    ma = await _du_an_co_can(client_re, nap_du_an, [{"unitCode": "A"}])

    r = await client_re.get(f"/api/v1/projects/{ma}/units?sort=unit_code")

    assert r.status_code == 422


@pytest.mark.asyncio
async def test_facet_chi_tra_gia_tri_co_that(client_re, nap_du_an):
    ma = await _du_an_co_can(
        client_re,
        nap_du_an,
        [
            {"unitCode": "A", "productType": "chung_cu", "direction": "dong_nam"},
            {"unitCode": "B", "productType": "penthouse", "direction": "dong_nam"},
            {"unitCode": "C", "productType": "chung_cu"},
        ],
    )

    r = (await client_re.get(f"/api/v1/projects/{ma}/units/facets")).json()

    assert sorted(r["productType"]) == ["chung_cu", "penthouse"]
    # Đúng MỘT hướng, không lặp — và căn không nhập hướng không sinh ra mục rỗng.
    assert r["direction"] == ["dong_nam"]


@pytest.mark.asyncio
async def test_facet_cua_du_an_rong_la_hai_mang_rong(client_re, nap_du_an):
    """Dự án chưa có căn nào: `array_agg` trên tập rỗng trả NULL, và một `null`
    lọt ra hợp đồng làm dropdown ở FE nổ chứ không rỗng."""
    ma = (await nap_du_an(1))[0]

    r = await client_re.get(f"/api/v1/projects/{ma}/units/facets")

    assert r.status_code == 200
    assert r.json() == {"productType": [], "direction": []}


@pytest.mark.asyncio
async def test_facet_khong_lay_can_cua_du_an_khac(client_re, nap_du_an):
    a = await _du_an_co_can(client_re, nap_du_an, [{"unitCode": "A", "productType": "chung_cu"}])
    await _du_an_co_can(client_re, nap_du_an, [{"unitCode": "B", "productType": "biet_thu"}], region="Đà Nẵng")

    r = (await client_re.get(f"/api/v1/projects/{a}/units/facets")).json()

    assert r["productType"] == ["chung_cu"]
