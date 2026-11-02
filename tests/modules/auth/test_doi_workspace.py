"""CỔNG 9 — đổi sang workspace mình không thuộc: 403, và phiên KHÔNG đổi.

Phần "phiên không đổi" là phần dễ bỏ: nếu code ghi tenant_id mới vào Redis TRƯỚC
khi kiểm membership thì request 403 vẫn để lại một phiên trỏ vào workspace lạ, và
request kế tiếp sẽ 403 mãi mà người dùng không hiểu vì sao.
"""

import pytest

pytestmark = pytest.mark.integration


async def test_doi_sang_workspace_minh_thuoc(dang_nhap_san):
    c = dang_nhap_san
    r = await c.post("/api/v1/me/workspace", json={"workspaceId": "cs_sunrise"})

    assert r.status_code == 200
    assert r.json()["currentWorkspaceId"] == "cs_sunrise"
    assert (await c.get("/api/v1/me")).json()["currentWorkspaceId"] == "cs_sunrise"


async def test_doi_sang_workspace_khong_thuoc_403_va_phien_khong_doi(dang_nhap_san):
    c = dang_nhap_san
    r = await c.post("/api/v1/me/workspace", json={"workspaceId": "cs_haven"})

    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"
    # Phiên vẫn ở workspace cũ — không bị đẩy sang trạng thái hỏng.
    assert (await c.get("/api/v1/me")).json()["currentWorkspaceId"] == "cs_anphu"


async def test_doi_sang_workspace_khong_ton_tai_403(dang_nhap_san):
    """Không phân biệt "không tồn tại" với "không thuộc": phân biệt là cho không
    một máy dò danh sách workspace của mọi khách hàng."""
    c = dang_nhap_san
    assert (await c.post("/api/v1/me/workspace", json={"workspaceId": "cs_bay_gio_moi_nghi"})).status_code == 403


async def test_hai_ma_loi_giong_het_nhau(dang_nhap_san):
    """Cùng mã 403 mà khác câu chữ thì vẫn phân biệt được — máy dò chỉ cần đọc
    `message`. Hai đường phải trả body giống nhau từng byte."""
    c = dang_nhap_san
    khong_thuoc = await c.post("/api/v1/me/workspace", json={"workspaceId": "cs_haven"})
    khong_co = await c.post("/api/v1/me/workspace", json={"workspaceId": "cs_bay_gio_moi_nghi"})

    assert khong_thuoc.json() == khong_co.json()


async def test_doi_workspace_khong_can_dang_nhap_lai(dang_nhap_san):
    """Đổi workspace giữ nguyên phiên — cùng session id, không phải cấp phiên mới.
    Cấp mới nghĩa là mỗi lần bấm switcher là một hàng Redis rác."""
    c = dang_nhap_san
    from portal.core.auth.session import TEN_COOKIE

    sid_truoc = c.cookies[TEN_COOKIE]
    await c.post("/api/v1/me/workspace", json={"workspaceId": "cs_sunrise"})

    assert c.cookies[TEN_COOKIE] == sid_truoc
