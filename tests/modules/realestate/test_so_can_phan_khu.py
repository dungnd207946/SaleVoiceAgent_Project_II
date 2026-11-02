"""Phân khu trả số căn đã nhập (`unitCount`) ở danh sách, bản đọc và sau khi sửa."""

import httpx
import pytest

pytestmark = pytest.mark.integration


def _url(path: str) -> str:
    return f"/api/v1{path}"


async def test_phan_khu_tra_so_can_da_nhap(client_re: httpx.AsyncClient):
    r = await client_re.post(_url("/projects"), json={"projectCode": "UC1", "name": "Dự án UC1"})
    assert r.status_code == 201, r.text
    for z in ("Z1", "Z2"):
        r = await client_re.post(_url("/projects/UC1/zones"), json={"zoneCode": z, "name": f"Khu {z}"})
        assert r.status_code == 201, r.text
    for ma in ("C-0101", "C-0102"):
        r = await client_re.post(
            _url("/projects/UC1/units"), json={"zoneCode": "Z1", "unitCode": ma, "productType": "chung_cu"}
        )
        assert r.status_code == 201, r.text

    ds = (await client_re.get(_url("/projects/UC1/zones"))).json()
    assert {z["zoneCode"]: z["unitCount"] for z in ds["items"]} == {"Z1": 2, "Z2": 0}
    assert (await client_re.get(_url("/projects/UC1/zones/Z1"))).json()["unitCount"] == 2
    r = await client_re.patch(_url("/projects/UC1/zones/Z1"), json={"name": "Khu Z1 mới"})
    assert r.status_code == 200, r.text
    assert r.json()["unitCount"] == 2
