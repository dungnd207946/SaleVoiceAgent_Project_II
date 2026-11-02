"""SQL của hộp thư sale. Mỗi test neo một lỗi im lặng cụ thể."""

import pytest

from portal.modules.ops import repo

from .conftest import TENANT_KHAC, luc, them_ca, them_du_an, them_luot, them_phien

pytestmark = pytest.mark.asyncio


async def test_moi_nhat_len_dau(conn_ops):
    await them_ca(conn_ops, "s-cu", tao_luc=luc(14))
    await them_ca(conn_ops, "s-moi", tao_luc=luc(27))

    hang = await repo.liet_ke_ca(conn_ops)

    assert [r["session_id"] for r in hang] == ["s-moi", "s-cu"]


async def test_khong_thay_ca_cua_tenant_khac(conn_ops):
    await them_ca(conn_ops, "s-ta")
    await them_ca(conn_ops, "s-ho", tenant=TENANT_KHAC)

    hang = await repo.liet_ke_ca(conn_ops)

    assert [r["session_id"] for r in hang] == ["s-ta"]


async def test_ten_du_an_lay_tu_bang_projects(conn_ops):
    """Bảng escalations chỉ có MÃ. Không join thì màn hiện 'SGI' cho khách xem."""
    await them_du_an(conn_ops, "SGI", "Sunshine Green Iconic")
    await them_ca(conn_ops, "s1", du_an="SGI")

    hang = await repo.liet_ke_ca(conn_ops)

    assert hang[0]["ten_du_an"] == "Sunshine Green Iconic"
    assert hang[0]["du_an"] == "SGI"


async def test_ma_du_an_khong_co_trong_projects_van_ra_hang(conn_ops):
    """LEFT JOIN, không JOIN trần: mã lạ vẫn phải hiện, tên để trống."""
    await them_ca(conn_ops, "s1", du_an="XYZ")

    hang = await repo.liet_ke_ca(conn_ops)

    assert len(hang) == 1
    assert hang[0]["ten_du_an"] is None


async def test_kenh_va_so_luot_lay_tu_phien(conn_ops):
    await them_phien(conn_ops, "s1", phone="0912448111")
    await conn_ops.execute("UPDATE tenant_data.conversations SET source = 'voice' WHERE session_id = 's1'")
    await them_luot(conn_ops, "s1", 0)
    await them_luot(conn_ops, "s1", 1)
    await them_ca(conn_ops, "s1")

    hang = await repo.liet_ke_ca(conn_ops)

    assert hang[0]["kenh"] == "voice"
    assert hang[0]["so_luot"] == 2


async def test_ca_chua_co_hang_conversations_van_ra(conn_ops):
    """Agent ghi ca NGAY lúc chuyển; hàng `conversations` chỉ chốt lúc kết thúc
    cuộc gọi. JOIN trần làm ca mới nhất — ca sale cần nhất — biến mất."""
    await them_ca(conn_ops, "s-chua-chot")

    hang = await repo.liet_ke_ca(conn_ops)

    assert len(hang) == 1
    assert hang[0]["so_luot"] == 0
    assert hang[0]["kenh"] is None


async def test_sdt_rong_lay_tu_conversations(conn_ops):
    """Ca đóng băng SĐT lúc chuyển. Khách cho số ở lượt SAU thì hàng ca vẫn rỗng
    trong khi `conversations` đã có — sale sẽ thấy 'chưa có số' một cách sai."""
    await them_phien(conn_ops, "s1", phone="0912448111", ten="Minh Anh")
    await them_ca(conn_ops, "s1", phone=None, ten=None)

    hang = await repo.liet_ke_ca(conn_ops)

    assert hang[0]["phone"] == "0912448111"
    assert hang[0]["ten"] == "Minh Anh"


async def test_loc_theo_trang_thai(conn_ops):
    await them_ca(conn_ops, "s-moi", trang_thai="new")
    await them_ca(conn_ops, "s-dang", trang_thai="contacted")
    await them_ca(conn_ops, "s-xong", trang_thai="done")

    assert len(await repo.liet_ke_ca(conn_ops, trang_thai="new")) == 1
    # Tab «Đã liên hệ» gộp contacted + done
    assert len(await repo.liet_ke_ca(conn_ops, trang_thai="handled")) == 2
    assert len(await repo.liet_ke_ca(conn_ops)) == 3


async def test_tim_theo_ten_va_so(conn_ops):
    await them_ca(conn_ops, "s1", phone="0912448111", ten="Minh Anh")
    await them_ca(conn_ops, "s2", phone="0987000111", ten="Bảo Long")

    assert len(await repo.liet_ke_ca(conn_ops, tim="Long")) == 1
    assert len(await repo.liet_ke_ca(conn_ops, tim="0912")) == 1


async def test_ky_tu_dai_dien_nguoi_dung_go_khong_khop_tat_ca(conn_ops):
    await them_ca(conn_ops, "s1", ten="Minh Anh")

    assert await repo.liet_ke_ca(conn_ops, tim="%") == []


async def test_dem_tinh_tren_tap_da_loc(conn_ops):
    """Đếm toàn bảng thì lọc xong con số không đổi — người dùng tưởng lọc hỏng."""
    await them_ca(conn_ops, "s1", trang_thai="new")
    await them_ca(conn_ops, "s2", trang_thai="done")

    assert await repo.dem_ca(conn_ops, trang_thai="new") == 1
    assert await repo.dem_ca(conn_ops) == 2


async def test_phan_trang(conn_ops):
    for i in range(3):
        await them_ca(conn_ops, f"s{i}", tao_luc=luc(20 + i))

    trang1 = await repo.liet_ke_ca(conn_ops, limit=2, offset=0)
    trang2 = await repo.liet_ke_ca(conn_ops, limit=2, offset=2)

    assert [r["session_id"] for r in trang1] == ["s2", "s1"]
    assert [r["session_id"] for r in trang2] == ["s0"]


async def test_nhan_ca_ghi_du_bon_cot(conn_ops):
    eid = await them_ca(conn_ops, "s1")

    ok = await repo.cap_nhat_ca(
        conn_ops, ca_id=eid, trang_thai="done", nguoi="u_ops", ghi_chu="đã gọi, khách hẹn thứ 5"
    )

    assert ok is True
    r = await conn_ops.fetchrow(
        "SELECT status, handled_by, handled_at, handled_note FROM tenant_data.escalations WHERE id = $1", eid
    )
    assert r["status"] == "done"
    assert r["handled_by"] == "u_ops"
    assert r["handled_at"] is not None
    assert r["handled_note"] == "đã gọi, khách hẹn thứ 5"


async def test_cap_nhat_ca_cua_tenant_khac_khong_an_thua(conn_ops):
    """RLS phải chặn; hàm trả False để router ra 404, không phải 200 im lặng."""
    eid = await them_ca(conn_ops, "s-ho", tenant=TENANT_KHAC)

    assert await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="done", nguoi="u_ops") is False


async def test_ghi_chu_bo_trong_thi_giu_ghi_chu_cu(conn_ops):
    """Đổi trạng thái không được xoá ghi chú sale đã gõ."""
    eid = await them_ca(conn_ops, "s1")
    await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="contacted", nguoi="u_ops", ghi_chu="gọi lần 1 không nghe")

    await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="done", nguoi="u_ops", ghi_chu=None)

    assert (
        await conn_ops.fetchval("SELECT handled_note FROM tenant_data.escalations WHERE id = $1", eid)
        == "gọi lần 1 không nghe"
    )


async def test_nguoi_xu_ly_ra_ten_nguoi_khong_phai_user_id(conn_ops):
    """`handled_by` lưu user_id; hiện thẳng lên màn thì sale đọc «u_dang đang xử lý»."""
    eid = await them_ca(conn_ops, "s1")
    await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="contacted", nguoi="u_ops")

    hang = await repo.liet_ke_ca(conn_ops)

    assert hang[0]["nguoi_xu_ly"] == "Đăng"


async def test_user_id_khong_con_trong_control_users_van_ra_hang(conn_ops):
    """Người rời tổ chức → LEFT JOIN, rơi về chính user_id chứ không nuốt cả hàng."""
    eid = await them_ca(conn_ops, "s1")
    await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="done", nguoi="u_da_nghi")

    hang = await repo.liet_ke_ca(conn_ops)

    assert len(hang) == 1
    assert hang[0]["nguoi_xu_ly"] == "u_da_nghi"


async def test_tra_lai_ca_xoa_nguoi_nhan(conn_ops):
    """Về `new` = chưa ai cầm. Giữ `handled_by` thì hộp thư nói ca có chủ trong
    khi nhãn ghi «Chưa liên hệ» — hai chỗ nói ngược nhau."""
    eid = await them_ca(conn_ops, "s1")
    await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="contacted", nguoi="u_ops", ghi_chu="gọi lần 1")

    await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="new", nguoi="u_ops")

    r = await conn_ops.fetchrow(
        "SELECT status, handled_by, handled_at, handled_note FROM tenant_data.escalations WHERE id = $1", eid
    )
    assert r["status"] == "new"
    assert r["handled_by"] is None and r["handled_at"] is None
    assert r["handled_note"] == "gọi lần 1", "ghi chú là lịch sử, không xoá theo"


async def test_moi_lan_ghi_chu_them_mot_hang_lich_su(conn_ops):
    """Ghi chú của sale trước không được biến mất khi sale sau ghi tiếp."""
    eid = await them_ca(conn_ops, "s1")

    await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="contacted", nguoi="u_ops", ghi_chu="gọi lần 1 không nghe")
    await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="done", nguoi="u_hai", ghi_chu="gọi lại, khách hẹn thứ 5")

    lich_su = await repo.doc_ghi_chu(conn_ops, ca_id=eid)
    assert [(g["noi_dung"], g["nguoi_id"]) for g in lich_su] == [
        ("gọi lần 1 không nghe", "u_ops"),
        ("gọi lại, khách hẹn thứ 5", "u_hai"),
    ]


async def test_handled_note_van_la_ban_moi_nhat(conn_ops):
    """Hàng danh sách đọc `handled_note`, nên nó phải theo kịp ghi chú cuối."""
    eid = await them_ca(conn_ops, "s1")
    await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="contacted", nguoi="u_ops", ghi_chu="lần 1")
    await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="done", nguoi="u_hai", ghi_chu="lần 2")

    assert await conn_ops.fetchval("SELECT handled_note FROM tenant_data.escalations WHERE id = $1", eid) == "lần 2"


async def test_doi_trang_thai_khong_go_ghi_chu_thi_khong_them_hang(conn_ops):
    eid = await them_ca(conn_ops, "s1")
    await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="contacted", nguoi="u_ops", ghi_chu="lần 1")

    await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="done", nguoi="u_hai", ghi_chu=None)

    assert len(await repo.doc_ghi_chu(conn_ops, ca_id=eid)) == 1


async def test_ghi_chu_ra_ten_nguoi_khong_phai_user_id(conn_ops):
    eid = await them_ca(conn_ops, "s1")

    await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="done", nguoi="u_ops", ghi_chu="xong")

    assert (await repo.doc_ghi_chu(conn_ops, ca_id=eid))[0]["nguoi"] == "Đăng"


async def test_nguoi_ghi_da_roi_to_chuc_van_ra_ghi_chu(conn_ops):
    eid = await them_ca(conn_ops, "s1")

    await repo.cap_nhat_ca(conn_ops, ca_id=eid, trang_thai="done", nguoi="u_da_nghi", ghi_chu="xong")

    assert (await repo.doc_ghi_chu(conn_ops, ca_id=eid))[0]["nguoi"] == "u_da_nghi"


async def test_khong_doc_duoc_ghi_chu_ca_cua_tenant_khac(conn_ops):
    eid = await them_ca(conn_ops, "s-ho", tenant=TENANT_KHAC)

    assert await repo.doc_ghi_chu(conn_ops, ca_id=eid) == []


async def test_tab_dang_xu_ly_va_xong_tach_nhau(conn_ops):
    await them_ca(conn_ops, "s-moi", trang_thai="new")
    await them_ca(conn_ops, "s-dang", trang_thai="contacted")
    await them_ca(conn_ops, "s-xong", trang_thai="done")

    async def ma(tt: str) -> set[str]:
        return {r["session_id"] for r in await repo.liet_ke_ca(conn_ops, trang_thai=tt)}

    assert await ma("contacted") == {"s-dang"}
    assert await ma("done") == {"s-xong"}
    assert await ma("handled") == {"s-dang", "s-xong"}


async def test_sap_xep_cho_lau_nhat_len_dau(conn_ops):
    await them_ca(conn_ops, "s-cu", tao_luc=luc(20))
    await them_ca(conn_ops, "s-moi", tao_luc=luc(27))

    moi = await repo.liet_ke_ca(conn_ops, sap_xep="moi")
    cu = await repo.liet_ke_ca(conn_ops, sap_xep="cu")

    assert [r["session_id"] for r in moi] == ["s-moi", "s-cu"]
    assert [r["session_id"] for r in cu] == ["s-cu", "s-moi"]


async def test_loc_theo_du_an(conn_ops):
    await them_ca(conn_ops, "s-sgi", du_an="SGI")
    await them_ca(conn_ops, "s-ncr", du_an="NCR")

    hang = await repo.liet_ke_ca(conn_ops, du_an="SGI")

    assert [r["session_id"] for r in hang] == ["s-sgi"]
    assert await repo.dem_ca(conn_ops, du_an="SGI") == 1


async def test_danh_sach_du_an_co_ca_khong_phu_thuoc_bo_loc(conn_ops):
    """Dropdown phải giữ nguyên lựa chọn sau khi người dùng đã chọn một dự án."""
    await them_ca(conn_ops, "s-sgi", du_an="SGI")
    await them_ca(conn_ops, "s-ncr", du_an="NCR")
    await them_ca(conn_ops, "s-trong", du_an=None)

    # Sắp theo TÊN, `NULLS LAST` — cả hai dự án đây đều chưa có hàng trong KB nên
    # rơi về thứ tự mã. Bài `test_ten_du_an.py` phủ ca có tên thật.
    assert [dict(r) for r in await repo.du_an_co_ca(conn_ops)] == [
        {"ma": "NCR", "ten": None},
        {"ma": "SGI", "ten": None},
    ]
