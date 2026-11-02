"""`GET /api/v1/audit` — quyền · cách ly · ẩn máy · join người.

Bài quan trọng nhất: `test_cach_ly_tenant_va_hang_he_thong` — hàng tenant B và
hàng `tenant_id NULL` KHÔNG BAO GIỜ lộ. `control.*` không có RLS đỡ phía sau; vị
từ tenant nằm ở câu SQL và đây là bài duy nhất canh nó.
"""

from portal.modules.audit.contracts import GIOI_HAN_TRANG
from tests.modules.audit.conftest import (
    EMAIL_QT,
    EMAIL_XEM,
    SO_HANG_A,
    SO_HANG_A_KHONG_MAY,
    USER_DA_XOA,
    USER_QT,
    dang_nhap,
)

DUONG = "/api/v1/audit"
GIOI_HAN_TRANG_PLUS = GIOI_HAN_TRANG + 1


async def test_401_khong_phien(app_client, workspace_audit) -> None:
    r = await app_client.get(DUONG)
    assert r.status_code == 401, r.text


async def test_403_nguoi_xem_khong_co_audit_read(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_XEM)
    r = await app_client.get(DUONG)
    assert r.status_code == 403, r.text
    assert "Xem Nhật ký hoạt động" in r.json()["error"]["message"], "403 phải nói LÝ DO bằng nhãn action"


async def test_cach_ly_tenant_va_hang_he_thong(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    r = await app_client.get(DUONG, params={"may": "true"})
    assert r.status_code == 200, r.text
    d = r.json()
    hanh_dong = [x["hanhDong"] for x in d["items"]]
    assert "kb.delete" not in hanh_dong, "hàng của tenant B lộ — vị từ tenant hỏng"
    assert "user.doi_mat_khau" not in hanh_dong, "hàng tenant_id NULL lộ (spec §2 #6)"
    assert len(d["items"]) == SO_HANG_A
    assert d["nextCursor"] is None


async def test_moi_nhat_truoc(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG)).json()
    luc = [x["luc"] for x in d["items"]]
    assert luc == sorted(luc, reverse=True)
    assert d["items"][0]["hanhDong"] == "role.sua", "hàng 22/08 phải đứng đầu dù id chèn nhỏ"


async def test_mac_dinh_an_hanh_dong_may(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG)).json()
    assert len(d["items"]) == SO_HANG_A_KHONG_MAY
    assert all(x["actorId"] != "agent" for x in d["items"])
    # Hàng hệ thống (`''`) và các hàng người VẪN hiện — chỉ `agent` bị ẩn.
    assert "ingest.tenant_im_lang" in [x["hanhDong"] for x in d["items"]]


async def test_may_true_hien_hanh_dong_may(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG, params={"may": "true"})).json()
    assert len(d["items"]) == SO_HANG_A
    may = next(x for x in d["items"] if x["actorId"] == "agent")
    assert may["hanhDong"] == "agent.runtime_credentials"
    assert may["actorTen"] is None and may["actorEmail"] is None


async def test_join_nguoi(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG)).json()
    theo = {x["hanhDong"]: x for x in d["items"]}
    assert theo["thanh_vien.moi"]["actorId"] == USER_QT
    assert theo["thanh_vien.moi"]["actorTen"] == "Quản Trị Viên"
    assert theo["thanh_vien.moi"]["actorEmail"] == EMAIL_QT
    # Người đã bị gỡ: actorId giữ NGUYÊN, tên/email null — không được lọc bỏ hàng.
    assert theo["kb.upload"]["actorId"] == USER_DA_XOA
    assert theo["kb.upload"]["actorTen"] is None
    assert theo["ingest.tenant_im_lang"]["actorId"] == ""


async def test_chi_tiet_nguyen_ven(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG)).json()
    hang = next(x for x in d["items"] if x["hanhDong"] == "realestate.project.update")
    assert hang["chiTiet"] == {"project_code": "NT2", "truong": ["name"]}
    assert isinstance(hang["id"], int)
    assert hang["luc"].endswith("+00:00") or hang["luc"].endswith("Z")


# ─── Lọc nhóm ────────────────────────────────────────────────────────────────


async def test_loc_mot_nhom(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG, params={"nhom": "realestate"})).json()
    assert [x["hanhDong"] for x in d["items"]] == ["realestate.project.update"]


async def test_loc_nhieu_nhom(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG, params={"nhom": "thanh_vien,user"})).json()
    assert sorted(x["hanhDong"] for x in d["items"]) == ["thanh_vien.moi", "user.nhan_moi_ws"]


async def test_nhom_khop_tien_to_chinh_xac(app_client, workspace_audit) -> None:
    """`agent` KHÔNG khớp `agent_config` — split_part, không LIKE."""
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG, params={"nhom": "agent", "may": "true"})).json()
    assert [x["hanhDong"] for x in d["items"]] == ["agent.runtime_credentials"]


async def test_nhom_sai_dang_422(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    for xau in ("Thanh_Vien", "a;b", ",".join(["a"] * 11), "x" * 33):
        r = await app_client.get(DUONG, params={"nhom": xau})
        assert r.status_code == 422, (xau, r.text)
        assert r.json()["error"]["code"] == "NHOM_KHONG_HOP_LE"


# ─── Khoảng ngày theo giờ VN ─────────────────────────────────────────────────


async def test_khoang_ngay_theo_gio_vn(app_client, workspace_audit) -> None:
    """Hàng 16:30 UTC 22/08 = 23:30 giờ VN 22/08 ⇒ thuộc ngày 22 (VN), KHÔNG
    phải 22 theo UTC-rồi-lệch. `to` là cận trên MỞ."""
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG, params={"from": "2026-08-22", "to": "2026-08-23"})).json()
    assert [x["hanhDong"] for x in d["items"]] == ["role.sua"]
    d2 = (await app_client.get(DUONG, params={"from": "2026-08-23", "to": "2026-08-24"})).json()
    assert d2["items"] == []
    # Ngày 20/08 VN = [19/08 17:00Z, 20/08 17:00Z): các hàng 09Z..16Z ⇒ 8 hàng không-máy
    d3 = (await app_client.get(DUONG, params={"from": "2026-08-20", "to": "2026-08-21"})).json()
    assert len(d3["items"]) == SO_HANG_A_KHONG_MAY - 1  # trừ role.sua (22/08)


async def test_chi_from_hoac_chi_to(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG, params={"from": "2026-08-22"})).json()
    assert [x["hanhDong"] for x in d["items"]] == ["role.sua"]
    d2 = (await app_client.get(DUONG, params={"to": "2026-08-22"})).json()
    assert len(d2["items"]) == SO_HANG_A_KHONG_MAY - 1


async def test_from_lon_hon_bang_to_422(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    r = await app_client.get(DUONG, params={"from": "2026-08-22", "to": "2026-08-22"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "KHOANG_KHONG_HOP_LE"


# ─── Phân trang keyset ───────────────────────────────────────────────────────


async def test_phan_trang_khong_trung_khong_sot(app_client, workspace_audit) -> None:
    """`limit=3` trên 9 hàng, ba hàng CÙNG `luc` bị cắt giữa trang 1 và 2 —
    keyset trên `(luc, id)` phải đi qua biên đó không trùng không sót."""
    await dang_nhap(app_client, EMAIL_QT)
    thay: list[int] = []
    cursor = None
    so_trang = 0
    while True:
        params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        d = (await app_client.get(DUONG, params=params)).json()
        so_trang += 1
        thay.extend(x["id"] for x in d["items"])
        cursor = d["nextCursor"]
        if cursor is None:
            break
        assert so_trang < 10, "không bao giờ hết trang — cursor không tiến"
    assert so_trang == 3
    assert len(thay) == SO_HANG_A_KHONG_MAY
    assert len(set(thay)) == SO_HANG_A_KHONG_MAY, "có hàng lặp giữa các trang"
    # Trang đầu: role.sua rồi 2 trong 3 hàng cùng luc; trang 2 bắt đầu bằng hàng cùng luc còn lại.
    d1 = (await app_client.get(DUONG, params={"limit": 3})).json()
    assert d1["items"][0]["hanhDong"] == "role.sua"
    assert [x["hanhDong"] for x in d1["items"][1:]] == ["agent_config.publish"] * 2
    d2 = (await app_client.get(DUONG, params={"limit": 3, "cursor": d1["nextCursor"]})).json()
    assert d2["items"][0]["hanhDong"] == "agent_config.publish"
    assert d2["items"][0]["id"] not in {x["id"] for x in d1["items"]}


async def test_trang_cuoi_dung_bang_limit_khong_co_cursor(app_client, workspace_audit) -> None:
    """9 hàng, `limit=9` ⇒ xin 10, nhận 9 < 10 ⇒ `nextCursor` null ngay trang đầu."""
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG, params={"limit": SO_HANG_A_KHONG_MAY})).json()
    assert len(d["items"]) == SO_HANG_A_KHONG_MAY and d["nextCursor"] is None


async def test_cursor_rac_400(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    for rac in ("abc", "NDEy", "MjAyNi0wOC0yNXw0MTI"):
        r = await app_client.get(DUONG, params={"cursor": rac})
        assert r.status_code == 400, (rac, r.text)
        assert r.json()["error"]["code"] == "CURSOR_KHONG_HOP_LE"


async def test_limit_ngoai_bien_422(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    assert (await app_client.get(DUONG, params={"limit": 0})).status_code == 422
    assert (await app_client.get(DUONG, params={"limit": GIOI_HAN_TRANG_PLUS})).status_code == 422
