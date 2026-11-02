"""`POST /projects` không kèm `projectCode` ⇒ mã suy từ `name` (spec §3.1).

Ô «Mã dự án» biến mất khỏi form: nó là khoá BẤT BIẾN (`ProjectPatch` không có ô
đó, `0400` không có `ON UPDATE CASCADE`) nên bắt người dùng đặt nó ngay ở ô đầu
tiên là bắt họ ra một quyết định vĩnh viễn trước khi biết mình đang làm gì.

`projectCode` tường minh VẪN NHẬN — đường nạp ngoài và mọi test cũ gửi nó, và
đây là thay đổi additive chứ không phải breaking.
"""

import httpx
import pytest

pytestmark = pytest.mark.integration


def _url(path: str) -> str:
    return f"/api/v1{path}"


async def test_khong_gui_ma_thi_suy_tu_ten(client_re: httpx.AsyncClient) -> None:
    r = await client_re.post(_url("/projects"), json={"name": "Vinhomes Ocean Park 2"})
    assert r.status_code == 201, r.text
    assert r.json()["projectCode"] == "VOP2"


async def test_ma_la_viet_tat_khong_phai_slug(client_re: httpx.AsyncClient) -> None:
    """Người yêu cầu chốt mã viết tắt (2026-08-21) — `NPTTL`, không phải
    `NOBLE_PALACE_TAY_THANG_LONG`."""
    r = await client_re.post(_url("/projects"), json={"name": "Noble Palace Tây Thăng Long"})
    assert r.json()["projectCode"] == "NPTTL"


async def test_ma_tuong_minh_van_duoc_ton_trong(client_re: httpx.AsyncClient) -> None:
    """Additive: đường nạp ngoài gửi mã đã sinh sẵn và nó phải đi nguyên văn."""
    r = await client_re.post(_url("/projects"), json={"projectCode": "ERP_PRJ_14", "name": "Bất kỳ"})
    assert r.status_code == 201, r.text
    assert r.json()["projectCode"] == "ERP_PRJ_14"


async def test_ten_trung_thi_ma_thu_hai_mang_hau_to(client_re: httpx.AsyncClient) -> None:
    a = await client_re.post(_url("/projects"), json={"name": "Akari City"})
    b = await client_re.post(_url("/projects"), json={"name": "Akari City"})
    assert a.json()["projectCode"] == "AC"
    assert b.status_code == 201, b.text
    assert b.json()["projectCode"] == "AC_2"


async def test_thieu_ca_ten_va_ma_thi_422_noi_ro_thieu_ten(client_re: httpx.AsyncClient) -> None:
    """KHÔNG tự đúc `DA_1`: một mã vô nghĩa là thứ người dùng phải mang vĩnh viễn.
    Frontend hỏi đúng một ô «Dự án này tên gì?» ở đúng lúc cần."""
    r = await client_re.post(_url("/projects"), json={})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "PROJECT_NAME_REQUIRED"


async def test_ten_toan_ky_tu_la_cung_bi_tu_choi(client_re: httpx.AsyncClient) -> None:
    """`"!!!"` sinh ra mã dự phòng `DA` — một mã không nói gì về dự án. Chặn ở
    tầng tên chứ đừng để nó thành một hàng mang mã `DA`."""
    r = await client_re.post(_url("/projects"), json={"name": "   "})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "PROJECT_NAME_REQUIRED"


async def test_ma_tu_sinh_khong_bao_gio_dung_sentinel(client_re: httpx.AsyncClient) -> None:
    """`__ALL__` là row hệ thống, `POST /projects` từ chối nó bằng 409. Một người
    đặt tên dự án là «all» không được rơi vào lỗi đó."""
    r = await client_re.post(_url("/projects"), json={"name": "__ALL__"})
    assert r.status_code == 201, r.text
    assert r.json()["projectCode"] == "A"
