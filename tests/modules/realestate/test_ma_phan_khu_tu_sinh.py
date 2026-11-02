"""`POST /projects/{code}/zones` không kèm `zoneCode` ⇒ mã suy từ `name`.

Cùng lý lẽ với `test_ma_tu_sinh.py` (dự án): `zone_code` là khoá BẤT BIẾN
(`ZonePatch` không có ô đó) nên bắt người dùng đặt nó ở ô đầu tiên là bắt họ ra
một quyết định vĩnh viễn trước khi biết mình đang làm gì.

⚠️ Phạm vi duy nhất KHÁC dự án: `zone_code` chỉ cần duy nhất trong MỘT dự án, nên
hai dự án đều có «Khu A» thì cả hai mang mã `KA` — không hậu tố.
"""

import httpx
import pytest

pytestmark = pytest.mark.integration


async def _du_an(client: httpx.AsyncClient, ma: str) -> None:
    r = await client.post("/api/v1/projects", json={"projectCode": ma, "name": f"Dự án {ma}"})
    assert r.status_code == 201, r.text


async def test_khong_gui_ma_thi_suy_tu_ten(client_re: httpx.AsyncClient) -> None:
    await _du_an(client_re, "mpk1")
    r = await client_re.post("/api/v1/projects/mpk1/zones", json={"name": "Tháp Sông Hồng"})
    assert r.status_code == 201, r.text
    assert r.json()["zoneCode"] == "TSH"


async def test_ma_tuong_minh_van_duoc_ton_trong(client_re: httpx.AsyncClient) -> None:
    await _du_an(client_re, "mpk2")
    r = await client_re.post("/api/v1/projects/mpk2/zones", json={"zoneCode": "PK_A", "name": "Khu A"})
    assert r.status_code == 201, r.text
    assert r.json()["zoneCode"] == "PK_A"


async def test_ten_trung_trong_cung_du_an_thi_ma_thu_hai_mang_hau_to(client_re: httpx.AsyncClient) -> None:
    await _du_an(client_re, "mpk3")
    a = await client_re.post("/api/v1/projects/mpk3/zones", json={"name": "Khu A"})
    b = await client_re.post("/api/v1/projects/mpk3/zones", json={"name": "Khu A"})
    assert a.json()["zoneCode"] == "KA"
    assert b.status_code == 201, b.text
    assert b.json()["zoneCode"] == "KA_2"


async def test_hai_du_an_dung_chung_mot_ma_khong_dung_nhau(client_re: httpx.AsyncClient) -> None:
    """Phạm vi duy nhất là `(tenant_id, project_code)` — hậu tố ở đây là hậu tố oan."""
    await _du_an(client_re, "mpk4")
    await _du_an(client_re, "mpk5")
    a = await client_re.post("/api/v1/projects/mpk4/zones", json={"name": "Khu A"})
    b = await client_re.post("/api/v1/projects/mpk5/zones", json={"name": "Khu A"})
    assert a.json()["zoneCode"] == "KA"
    assert b.json()["zoneCode"] == "KA"


async def test_thieu_ca_ten_va_ma_thi_422_noi_ro_thieu_ten(client_re: httpx.AsyncClient) -> None:
    await _du_an(client_re, "mpk6")
    r = await client_re.post("/api/v1/projects/mpk6/zones", json={})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "ZONE_NAME_REQUIRED"


async def test_ten_toan_ky_tu_la_cung_bi_tu_choi(client_re: httpx.AsyncClient) -> None:
    await _du_an(client_re, "mpk7")
    r = await client_re.post("/api/v1/projects/mpk7/zones", json={"name": "   "})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "ZONE_NAME_REQUIRED"
