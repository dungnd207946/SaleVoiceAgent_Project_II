"""Trường mua nhà mới (migration 0978): bàn giao dạng danh sách, toà, cột mới của dự án/phân khu/căn."""

import httpx
import pytest

from portal.core.db.session import tenant_conn

pytestmark = pytest.mark.integration


def _url(path: str) -> str:
    return f"/api/v1{path}"


async def _du_an(client: httpx.AsyncClient, code: str, **kw) -> dict:
    r = await client.post(_url("/projects"), json={"projectCode": code, "name": f"Dự án {code}", **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def _phan_khu(client: httpx.AsyncClient, project: str, zone: str, **kw) -> dict:
    r = await client.post(_url(f"/projects/{project}/zones"), json={"zoneCode": zone, "name": f"Khu {zone}", **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def test_ban_giao_luu_danh_sach_hang_muc(client_re: httpx.AsyncClient):
    hang_muc = [
        {"item": "Sàn phòng ngủ", "material": "Gỗ kỹ thuật 12mm", "brand": "Kronotex", "origin": "Đức"},
        {"item": "Thiết bị vệ sinh", "brand": "TOTO"},
    ]
    tao = await _du_an(client_re, "BG1", handoverStandard=hang_muc)
    assert [h["item"] for h in tao["handoverStandard"]] == ["Sàn phòng ngủ", "Thiết bị vệ sinh"]
    rong = {"material": "", "origin": "", "note": ""}
    assert tao["handoverStandard"][1] == {"item": "Thiết bị vệ sinh", "brand": "TOTO", **rong}

    doc = (await client_re.get(_url("/projects/BG1"))).json()
    assert doc["handoverStandard"] == tao["handoverStandard"]


async def test_ban_giao_dang_chuoi_cua_fe_cu_van_luu_duoc(client_re: httpx.AsyncClient):
    await _du_an(client_re, "BG2")
    r = await client_re.patch(_url("/projects/BG2"), json={"handoverStandard": "Thô, giãn xây"})
    assert r.status_code == 200, r.text
    assert r.json()["handoverStandard"] == [
        {"item": "Tiêu chuẩn chung", "material": "", "brand": "", "origin": "", "note": "Thô, giãn xây"}
    ]

    r = await client_re.patch(_url("/projects/BG2"), json={"handoverStandard": ""})
    assert r.json()["handoverStandard"] == []


async def test_hang_muc_thieu_ten_bi_tu_choi(client_re: httpx.AsyncClient):
    await _du_an(client_re, "BG3")
    r = await client_re.patch(_url("/projects/BG3"), json={"handoverStandard": [{"brand": "TOTO"}]})
    assert r.status_code == 422


async def test_truong_moi_cua_du_an_va_phan_khu(client_re: httpx.AsyncClient):
    tao = await _du_an(client_re, "TM1", totalUnits=1200, numBuildings=3, managementFeeVndM2=15000)
    assert (tao["totalUnits"], tao["numBuildings"], tao["managementFeeVndM2"]) == (1200, 3, 15000)

    zone = await _phan_khu(
        client_re, "TM1", "Z1", salePhase="dang_ban", note="Sát cổng chính", amenities="Bể bơi", numBuildings=2
    )
    assert (zone["salePhase"], zone["note"], zone["amenities"], zone["numBuildings"]) == (
        "dang_ban",
        "Sát cổng chính",
        "Bể bơi",
        2,
    )


async def test_truong_moi_cua_can(client_re: httpx.AsyncClient):
    await _du_an(client_re, "CN1")
    await _phan_khu(client_re, "CN1", "Z1")
    r = await client_re.post(
        _url("/projects/CN1/units"),
        json={
            "zoneCode": "Z1",
            "unitCode": "A1-1201",
            "productType": "chung_cu",
            "views": ["song", "cong_vien"],
            "isCorner": True,
            "openSides": 2,
            "bathrooms": 2,
            "handoverCondition": "hoan_thien",
            "hrBalconyM2": 4.5,
        },
    )
    assert r.status_code == 201, r.text
    can = r.json()
    assert (can["views"], can["isCorner"], can["openSides"]) == (["song", "cong_vien"], True, 2)
    assert can["hrBalconyM2"] == 4.5

    sai = await client_re.patch(_url(f"/projects/CN1/units/{can['id']}"), json={"views": ["view_dep"]})
    assert sai.status_code == 422


async def test_toa_crud(client_re: httpx.AsyncClient):
    await _du_an(client_re, "TA1")
    await _phan_khu(client_re, "TA1", "Z1")

    r = await client_re.post(
        _url("/projects/TA1/buildings"),
        json={"buildingCode": "A1", "zoneCode": "Z1", "numFloors": 25, "elevatorsPassenger": 4, "facing": "dong_nam"},
    )
    assert r.status_code == 201, r.text
    toa = r.json()
    assert (toa["name"], toa["zoneCode"], toa["numFloors"], toa["unitCount"]) == ("A1", "Z1", 25, 0)

    trung = await client_re.post(_url("/projects/TA1/buildings"), json={"buildingCode": "A1"})
    assert trung.status_code == 409

    sua = await client_re.patch(_url("/projects/TA1/buildings/A1"), json={"name": "Toà A1", "amenities": "Gym"})
    assert (sua.json()["name"], sua.json()["amenities"]) == ("Toà A1", "Gym")

    ds = (await client_re.get(_url("/projects/TA1/buildings"))).json()
    assert ds["total"] == 1 and ds["items"][0]["buildingCode"] == "A1"

    assert (await client_re.delete(_url("/projects/TA1/buildings/A1"))).status_code == 204
    assert (await client_re.patch(_url("/projects/TA1/buildings/A1"), json={"name": "x"})).status_code == 404


async def test_toa_gan_phan_khu_khong_ton_tai(client_re: httpx.AsyncClient):
    await _du_an(client_re, "TA2")
    r = await client_re.post(_url("/projects/TA2/buildings"), json={"buildingCode": "B1", "zoneCode": "KHONG_CO"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ZONE_NOT_FOUND"


async def test_can_mang_block_moi_tu_tao_toa_va_xep_viec_nap(client_re: httpx.AsyncClient, pool, workspace_re):
    await _du_an(client_re, "TA3")
    await _phan_khu(client_re, "TA3", "Z1")
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute("DELETE FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_index'", workspace_re)

    can = {"zoneCode": "Z1", "unitCode": "B9-0101", "productType": "chung_cu", "block": " B9 "}
    r = await client_re.post(_url("/projects/TA3/units"), json=can)
    assert r.status_code == 201, r.text

    ds = (await client_re.get(_url("/projects/TA3/buildings"))).json()
    assert [(t["buildingCode"], t["zoneCode"], t["unitCount"]) for t in ds["items"]] == [("B9", "Z1", 1)]
    async with tenant_conn(pool, workspace_re) as conn:
        viec = await conn.fetch(
            "SELECT payload->>'entity' AS entity FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_index'",
            workspace_re,
        )
    assert [v["entity"] for v in viec] == ["projects"]
