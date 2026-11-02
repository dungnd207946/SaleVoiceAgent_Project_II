"""Căn trỏ toà bằng khoá ngoại (migration 0979): mã toà của căn được chuẩn hoá, xoá toà còn căn bị chặn."""

import asyncpg
import httpx
import pytest

from portal.core.db.session import tenant_conn

pytestmark = pytest.mark.integration


def _url(path: str) -> str:
    return f"/api/v1{path}"


async def _du_an_co_can(client: httpx.AsyncClient, code: str, block: str = "A1") -> dict:
    r = await client.post(_url("/projects"), json={"projectCode": code, "name": f"Dự án {code}"})
    assert r.status_code == 201, r.text
    r = await client.post(_url(f"/projects/{code}/zones"), json={"zoneCode": "Z1", "name": "Khu Z1"})
    assert r.status_code == 201, r.text
    r = await client.post(
        _url(f"/projects/{code}/units"),
        json={"zoneCode": "Z1", "unitCode": "C-0101", "productType": "chung_cu", "block": block},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_xoa_toa_con_can_bi_chan(client_re: httpx.AsyncClient):
    await _du_an_co_can(client_re, "FK1")

    r = await client_re.delete(_url("/projects/FK1/buildings/A1"))

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "BUILDING_HAS_UNITS"
    ds = (await client_re.get(_url("/projects/FK1/buildings"))).json()
    assert [(t["buildingCode"], t["unitCount"]) for t in ds["items"]] == [("A1", 1)]


async def test_xoa_duoc_toa_sau_khi_chuyen_can_sang_toa_khac(client_re: httpx.AsyncClient):
    can = await _du_an_co_can(client_re, "FK2")
    r = await client_re.patch(_url(f"/projects/FK2/units/{can['id']}"), json={"block": "A2"})
    assert r.status_code == 200, r.text

    assert (await client_re.delete(_url("/projects/FK2/buildings/A1"))).status_code == 204


async def test_db_khong_cho_xoa_toa_con_can(client_re: httpx.AsyncClient, pool, workspace_re):
    await _du_an_co_can(client_re, "FK3")
    async with tenant_conn(pool, workspace_re) as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "DELETE FROM tenant_data.buildings WHERE tenant_id = portal.current_tenant() AND project_code = 'FK3'"
            )


async def test_ma_toa_cua_can_duoc_cat_khoang_trang(client_re: httpx.AsyncClient):
    can = await _du_an_co_can(client_re, "FK4", block="  B9 ")

    assert can["block"] == "B9"


async def test_xoa_phan_khu_keo_theo_toa_va_can(client_re: httpx.AsyncClient):
    await _du_an_co_can(client_re, "FK5")

    assert (await client_re.delete(_url("/projects/FK5/zones/Z1"))).status_code == 204
    assert (await client_re.get(_url("/projects/FK5/buildings"))).json()["total"] == 0


async def test_xoa_du_an_keo_theo_toa_va_can(client_re: httpx.AsyncClient):
    await _du_an_co_can(client_re, "FK6")

    assert (await client_re.delete(_url("/projects/FK6"))).status_code == 204
