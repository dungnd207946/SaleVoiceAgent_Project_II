"""Phân trang CÓ SỐ TRANG (`offset` + `total`) — spec vòng 2 §4.8.

CANH ĐÚNG MỘT THỨ MÀ CURSOR KHÔNG LÀM ĐƯỢC: nhảy thẳng tới trang thứ n mà
không đi qua n-1 trang trước. Và canh `total` khớp vị từ lọc — `total` đếm theo
một mệnh đề `WHERE` khác câu lấy hàng là lỗi kinh điển của lối này: người dùng
thấy "237 hàng" rồi bấm trang cuối ra rỗng.

`pytestmark` (M-7, review vòng cuối): mọi test ở đây đi qua `client_re` →
`workspace_re` → `pool`, cần Postgres thật. Thiếu marker này, `pytest -m "not
integration"` vẫn gọi 9 test này và chỉ đỏ vì thiếu Docker, không phải vì code sai.
"""

import pytest

from tests.modules.realestate.test_crud import _seed_sentinel

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_total_dem_dung_so_du_an_va_khong_dem_sentinel(client_re, nap_du_an, pool, workspace_re):
    # M-3 (review vòng cuối): mọi tenant provision THẬT đều có row `__ALL__`
    # (`scripts/seed_bds.py`) — bản trước của test này không seed nó, nên cổng
    # rỗng: `dem_du_an` đếm lẫn sentinel vẫn xanh (198 passed). Seed đúng như
    # provisioning thật để cổng canh được đúng thứ nó tuyên bố canh.
    await _seed_sentinel(pool, workspace_re)
    await nap_du_an(7)

    r = await client_re.get("/api/v1/projects?limit=3")

    assert r.status_code == 200
    than = r.json()
    assert len(than["items"]) == 3
    # 7 dự án thật. `__ALL__` bị ẩn khỏi danh sách nên KHÔNG được đếm vào total —
    # nếu nó lọt vào thì total = 8 và trang cuối hiện một hàng trống.
    assert than["total"] == 7


@pytest.mark.asyncio
async def test_offset_nhay_thang_toi_trang_thu_ba(client_re, nap_du_an):
    ma = await nap_du_an(7)

    trang1 = (await client_re.get("/api/v1/projects?limit=3&offset=0")).json()
    trang3 = (await client_re.get("/api/v1/projects?limit=3&offset=6")).json()

    assert [d["projectCode"] for d in trang1["items"]] == ma[:3]
    # offset=6 với limit=3 ⇒ trang thứ ba, còn đúng 1 hàng.
    assert [d["projectCode"] for d in trang3["items"]] == ma[6:7]
    assert trang3["total"] == 7


@pytest.mark.asyncio
async def test_total_theo_dung_bo_loc_dang_ap(client_re, nap_du_an):
    """`total` phải đếm theo CÙNG vị từ với câu lấy hàng. Nếu hai câu lệch nhau
    thì test này đỏ — và đó là toàn bộ lý do `_loc_du_an()` tồn tại."""
    await nap_du_an(5, region="Hà Nội")
    await nap_du_an(2, region="Đà Nẵng")

    r = (await client_re.get("/api/v1/projects?region=Đà Nẵng&limit=50")).json()

    assert len(r["items"]) == 2
    assert r["total"] == 2


@pytest.mark.asyncio
async def test_nextcursor_van_con_va_van_dung(client_re, nap_du_an):
    """`nextCursor` KHÔNG bị bỏ — nó là hợp đồng đang dùng (Global Constraints)."""
    await nap_du_an(7)

    trang1 = (await client_re.get("/api/v1/projects?limit=3")).json()
    assert trang1["nextCursor"] is not None

    trang2 = (await client_re.get(f"/api/v1/projects?limit=3&cursor={trang1['nextCursor']}")).json()
    ma1 = {d["projectCode"] for d in trang1["items"]}
    ma2 = {d["projectCode"] for d in trang2["items"]}
    assert not (ma1 & ma2), "hai trang keyset không được trùng hàng nào"


@pytest.mark.asyncio
async def test_offset_am_va_offset_qua_lon(client_re, nap_du_an):
    await nap_du_an(3)

    # `offset` âm bị FastAPI chặn ở tầng validate (ge=0) — 422, không phải 500.
    assert (await client_re.get("/api/v1/projects?offset=-5")).status_code == 422
    # Vượt quá số hàng ⇒ trang rỗng, `total` vẫn đúng. KHÔNG phải lỗi.
    r = (await client_re.get("/api/v1/projects?limit=10&offset=99")).json()
    assert r["items"] == []
    assert r["total"] == 3


@pytest.mark.asyncio
async def test_offset_vuot_tran_tra_422_khong_500(client_re, nap_du_an):
    """I-1 (review vòng cuối): `offset` trước đây chỉ kẹp DƯỚI (`ge=0`), không
    trần TRÊN — một giá trị vượt `int64` (Postgres `bigint`) vỡ ở `asyncpg`
    thành `DataError`, và vì `api/loi.py` không có handler catch-all, nó nổi
    lên thành 500 kèm stack trace thay vì 422 có cấu trúc."""
    await nap_du_an(1)

    r = await client_re.get("/api/v1/projects?offset=99999999999999999999")

    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_total_va_offset_cho_can(client_re, nap_du_an, nap_can):
    ma = (await nap_du_an(1))[0]
    await nap_can(ma, 5)

    trang2 = (await client_re.get(f"/api/v1/projects/{ma}/units?limit=2&offset=2")).json()

    assert trang2["total"] == 5
    assert len(trang2["items"]) == 2


@pytest.mark.asyncio
async def test_offset_dung_cua_so_cho_phan_khu(client_re, nap_du_an, nap_phan_khu):
    """M-1/M-2 (review vòng cuối): `test_total_va_offset_cho_can`/`_media` chỉ
    canh ĐỘ DÀI trang, không canh ĐÚNG cửa sổ — `limit=2&offset=2` trên 5 hàng
    cho `len(items)==2` dù `offset` có bị bỏ qua hay không. So với DANH SÁCH ĐẦY
    ĐỦ (không offset) mới lộ ra offset có thật sự dịch cửa sổ hay không."""
    ma = (await nap_du_an(1))[0]
    await nap_phan_khu(ma, 5)

    day_du = (await client_re.get(f"/api/v1/projects/{ma}/zones?limit=50")).json()["items"]
    trang = (await client_re.get(f"/api/v1/projects/{ma}/zones?limit=2&offset=2")).json()["items"]

    assert [z["id"] for z in trang] == [z["id"] for z in day_du[2:4]]


@pytest.mark.asyncio
async def test_offset_dung_cua_so_cho_can(client_re, nap_du_an, nap_can):
    """Cùng lý do `test_offset_dung_cua_so_cho_phan_khu`, cho `units`."""
    ma = (await nap_du_an(1))[0]
    await nap_can(ma, 5)

    day_du = (await client_re.get(f"/api/v1/projects/{ma}/units?limit=50")).json()["items"]
    trang = (await client_re.get(f"/api/v1/projects/{ma}/units?limit=2&offset=2")).json()["items"]

    assert [u["id"] for u in trang] == [u["id"] for u in day_du[2:4]]


@pytest.mark.asyncio
async def test_offset_dung_cua_so_cho_tai_lieu(client_re, nap_du_an, nap_tai_lieu):
    """Cùng lý do `test_offset_dung_cua_so_cho_phan_khu`, cho `documents` — endpoint
    này KHÔNG có test offset nào trước bản vá (chỉ có test `total`)."""
    ma = (await nap_du_an(1))[0]
    await nap_tai_lieu(ma, 5)

    day_du = (await client_re.get(f"/api/v1/projects/{ma}/documents?limit=50")).json()["items"]
    trang = (await client_re.get(f"/api/v1/projects/{ma}/documents?limit=2&offset=2")).json()["items"]

    assert [d["id"] for d in trang] == [d["id"] for d in day_du[2:4]]


@pytest.mark.asyncio
async def test_offset_dung_cua_so_cho_media(client_re, nap_du_an, nap_media):
    """Cùng lý do `test_offset_dung_cua_so_cho_phan_khu`, cho `media`."""
    ma = (await nap_du_an(1))[0]
    await nap_media(ma, 5)

    day_du = (await client_re.get(f"/api/v1/projects/{ma}/media?limit=50")).json()["items"]
    trang = (await client_re.get(f"/api/v1/projects/{ma}/media?limit=2&offset=2")).json()["items"]

    assert [m["id"] for m in trang] == [m["id"] for m in day_du[2:4]]


@pytest.mark.asyncio
async def test_total_cua_can_theo_dung_bo_loc(client_re, nap_du_an, nap_can):
    """Cổng canh vị từ dùng chung — `units` có BỐN filter, nhiều nhất trong năm
    danh sách, nên nó là chỗ dễ để `dem_can` lệch khỏi `liet_ke_can` nhất."""
    ma = (await nap_du_an(1))[0]
    await nap_can(ma, 3, product_type="chung_cu")
    await nap_can(ma, 2, product_type="biet_thu")

    # `product_type` (snake_case) — bộ lọc GET của endpoint này KHÔNG có alias
    # camelCase (khác body `*In`, xem `UnitIn.product_type`); gõ `productType`
    # là một query param lạ, bị bỏ qua, và lộ đúng cái lỗi này ra thành "lọc
    # không hoạt động" — dễ nhầm với lỗi mà test này thật sự muốn canh.
    r = (await client_re.get(f"/api/v1/projects/{ma}/units?product_type=biet_thu&limit=50")).json()

    assert len(r["items"]) == 2
    assert r["total"] == 2


@pytest.mark.asyncio
async def test_total_can_theo_dung_sale_status(client_re, nap_du_an):
    """M-4 (review vòng cuối): `sale_status` là 1/4 filter của `dem_can` mà
    KHÔNG test nào canh trước bản vá — ép router truyền `sale_status=""` cho
    `dem_can` vẫn xanh hết. Kịch bản thật: mở tab "Đã bán" cho `total` = TOÀN BỘ
    căn của dự án, không phải riêng phần đã bán."""
    ma = (await nap_du_an(1))[0]
    z = await client_re.post(f"/api/v1/projects/{ma}/zones", json={"zoneCode": "Z1", "name": "Z1"})
    assert z.status_code == 201, z.text
    for i in range(3):
        r = await client_re.post(
            f"/api/v1/projects/{ma}/units",
            json={"zoneCode": "Z1", "unitCode": f"AV-{i}", "productType": "chung_cu", "saleStatus": "available"},
        )
        assert r.status_code == 201, r.text
    for i in range(2):
        r = await client_re.post(
            f"/api/v1/projects/{ma}/units",
            json={"zoneCode": "Z1", "unitCode": f"SO-{i}", "productType": "chung_cu", "saleStatus": "sold"},
        )
        assert r.status_code == 201, r.text

    r = (await client_re.get(f"/api/v1/projects/{ma}/units?sale_status=sold&limit=50")).json()

    assert len(r["items"]) == 2
    assert r["total"] == 2


@pytest.mark.asyncio
async def test_total_va_offset_cho_media(client_re, nap_du_an, nap_media):
    ma = (await nap_du_an(1))[0]
    await nap_media(ma, 4, category="ngoai_that")
    await nap_media(ma, 3, category="noi_that")

    r = (await client_re.get(f"/api/v1/projects/{ma}/media?category=noi_that&limit=2&offset=2")).json()

    assert r["total"] == 3
    assert len(r["items"]) == 1


@pytest.mark.asyncio
async def test_total_media_theo_zone_unit_content_type(client_re, nap_du_an):
    """M-4 (review vòng cuối): `zone_code`/`unit_code`/`content_type` là 3/5
    filter của `dem_media` mà KHÔNG test nào canh trước bản vá. Kịch bản thật:
    mở folder phân khu ở tab Media (`?zone_code=Z1`) thì `total` phải là số ảnh
    CỦA phân khu đó, không phải toàn bộ media dự án."""
    ma = (await nap_du_an(1))[0]
    z = await client_re.post(f"/api/v1/projects/{ma}/zones", json={"zoneCode": "Z1", "name": "Z1"})
    assert z.status_code == 201, z.text

    # (1) cấp dự án, ảnh
    r1 = await client_re.post(
        f"/api/v1/projects/{ma}/media",
        json={"category": "ngoai_that", "contentType": "image", "mediaUrl": "tenants/t/kb-bds/a/a.webp"},
    )
    assert r1.status_code == 201, r1.text
    # (2) cấp phân khu Z1, video
    r2 = await client_re.post(
        f"/api/v1/projects/{ma}/media",
        json={
            "category": "ngoai_that",
            "contentType": "video",
            "mediaUrl": "tenants/t/kb-bds/b/b.mp4",
            "zoneCode": "Z1",
        },
    )
    assert r2.status_code == 201, r2.text
    # (3) cấp căn U1 trong Z1, ảnh
    r3 = await client_re.post(
        f"/api/v1/projects/{ma}/media",
        json={
            "category": "ngoai_that",
            "contentType": "image",
            "mediaUrl": "tenants/t/kb-bds/c/c.webp",
            "zoneCode": "Z1",
            "unitCode": "U1",
        },
    )
    assert r3.status_code == 201, r3.text

    theo_zone = (await client_re.get(f"/api/v1/projects/{ma}/media?zone_code=Z1&limit=50")).json()
    assert theo_zone["total"] == 2  # (2) và (3)

    theo_unit = (await client_re.get(f"/api/v1/projects/{ma}/media?unit_code=U1&limit=50")).json()
    assert theo_unit["total"] == 1  # chỉ (3)

    theo_content_type = (await client_re.get(f"/api/v1/projects/{ma}/media?content_type=video&limit=50")).json()
    assert theo_content_type["total"] == 1  # chỉ (2)


@pytest.mark.asyncio
async def test_total_cho_phan_khu_va_tai_lieu(client_re, nap_du_an, nap_phan_khu, nap_tai_lieu):
    ma = (await nap_du_an(1))[0]
    await nap_phan_khu(ma, 3)
    await nap_tai_lieu(ma, 4)

    assert (await client_re.get(f"/api/v1/projects/{ma}/zones?limit=2")).json()["total"] == 3
    assert (await client_re.get(f"/api/v1/projects/{ma}/documents?limit=2")).json()["total"] == 4
