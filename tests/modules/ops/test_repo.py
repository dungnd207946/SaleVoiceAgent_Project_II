"""Cổng cho SQL của M7. Mỗi test neo một lỗi im lặng cụ thể, không phải "kiểm tra hàm chạy"."""

import pytest

from portal.modules.ops import repo

from .conftest import TENANT, TENANT_KHAC, cach_day, luc, them_luot, them_phien

pytestmark = pytest.mark.asyncio


async def test_ba_phien_cung_so_gop_thanh_mot_hang(conn_ops):
    for i in range(3):
        await them_phien(conn_ops, f"s{i}", phone="0912448111", bat_dau=luc(20 + i))

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all")

    assert len(hang) == 1
    assert hang[0]["phone"] == "0912448111"
    assert hang[0]["so_phien"] == 3


async def test_ten_lay_cua_phien_moi_nhat_khong_phai_max(conn_ops):
    """Ca chốt: `max(customer_name)` trả 'Zũng' vì Z > A. Đúng phải là 'An' — phiên mới hơn."""
    await them_phien(conn_ops, "cu", ten="Zũng", bat_dau=luc(14))
    await them_phien(conn_ops, "moi", ten="An", bat_dau=luc(27))

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all")

    assert hang[0]["ten"] == "An"


async def test_phien_khong_co_ten_khong_xoa_ten_da_biet(conn_ops):
    await them_phien(conn_ops, "co_ten", ten="An", bat_dau=luc(14))
    await them_phien(conn_ops, "khong_ten", ten=None, bat_dau=luc(27))

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all")

    assert hang[0]["ten"] == "An"


async def test_phone_null_gop_thanh_nhom_khoa_rong(conn_ops):
    await them_phien(conn_ops, "an1", phone=None)
    await them_phien(conn_ops, "an2", phone=None)
    await them_phien(conn_ops, "co_so", phone="0912448111")

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all")
    theo_phone = {r["phone"]: r for r in hang}

    assert theo_phone[""]["so_phien"] == 2
    assert theo_phone["0912448111"]["so_phien"] == 1


async def test_da_chuyen_dung_bool_or_khong_phai_phien_cuoi(conn_ops):
    await them_phien(conn_ops, "cu", chuyen=True, bat_dau=luc(14))
    await them_phien(conn_ops, "moi", chuyen=False, bat_dau=luc(27))

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all")

    assert hang[0]["da_chuyen"] is True


async def test_q_chua_phan_tram_khong_khop_toan_bo(conn_ops):
    await them_phien(conn_ops, "s1", phone="0912448111")

    hang = await repo.liet_ke_khach(conn_ops, tim="%", tu_ngay="all")

    assert hang == []


async def test_q_chua_gach_duoi_khong_khop_moi_ky_tu_don(conn_ops):
    await them_phien(conn_ops, "s1", phone="0912448111", ten="An")

    hang = await repo.liet_ke_khach(conn_ops, tim="_", tu_ngay="all")

    assert hang == []


async def test_sap_theo_phien_gan_nhat_giam_dan(conn_ops):
    await them_phien(conn_ops, "cu", phone="0900000001", bat_dau=luc(14))
    await them_phien(conn_ops, "moi", phone="0900000002", bat_dau=luc(27))

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all")

    assert [r["phone"] for r in hang] == ["0900000002", "0900000001"]


async def test_khong_thay_hang_cua_tenant_khac(conn_ops):
    await them_phien(conn_ops, "cua_toi", tenant=TENANT, phone="0900000001")
    await them_phien(conn_ops, "cua_ho", tenant=TENANT_KHAC, phone="0900000002")

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all")

    assert [r["phone"] for r in hang] == ["0900000001"]


async def test_dem_tong_tra_ca_so_khach_va_so_phien(conn_ops):
    await them_phien(conn_ops, "a1", phone="0900000001")
    await them_phien(conn_ops, "a2", phone="0900000001")
    await them_phien(conn_ops, "b1", phone="0900000002")

    so_khach, so_phien = await repo.dem_tong(conn_ops, tu_ngay="all")

    assert (so_khach, so_phien) == (2, 3)


# ─── Bộ lọc chạy ở mức NHÓM, không mức hàng ────────────────────────────────
# Bốn test dưới đây canh đúng một lớp lỗi: lọc trước khi gom thì con số trả về
# vẫn "hợp lý" nên không ai nhìn ra. Xem docstring `_dieu_kien_thoi_gian`.


async def test_loc_7_ngay_van_dem_du_phien_cu_cua_khach(conn_ops):
    """Khách vừa nhắn 2 hôm trước, còn một phiên 40 ngày trước ⇒ «2 phiên».

    Lọc ở WHERE thì ra «1 phiên» — đúng kiểu con số sai mà trông hợp lý.
    """
    await them_phien(conn_ops, "moi", phone="0900000001", bat_dau=cach_day(2))
    await them_phien(conn_ops, "cu", phone="0900000001", bat_dau=cach_day(40))

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="7")

    assert len(hang) == 1
    assert hang[0]["so_phien"] == 2


async def test_loc_7_ngay_bo_khach_lau_khong_nhan(conn_ops):
    await them_phien(conn_ops, "cu", phone="0900000001", bat_dau=cach_day(40))

    assert await repo.liet_ke_khach(conn_ops, tu_ngay="7") == []


async def test_mac_dinh_30_ngay_bo_khach_cu_hon(conn_ops):
    """Nhánh mặc định `"30"` — không truyền `tu_ngay` thì phải là 30 ngày."""
    await them_phien(conn_ops, "trong_han", phone="0900000001", bat_dau=cach_day(10))
    await them_phien(conn_ops, "qua_han", phone="0900000002", bat_dau=cach_day(40))

    hang = await repo.liet_ke_khach(conn_ops)

    assert [r["phone"] for r in hang] == ["0900000001"]


async def test_tim_ten_cu_van_hien_du_ca_nhom(conn_ops):
    """Gõ tên CŨ vẫn ra hồ sơ đầy đủ: tên mới nhất, đủ số phiên.

    Quyết định của chủ sản phẩm 06/08: trúng một phiên là hiện cả người.
    """
    await them_phien(conn_ops, "cu", phone="0900000001", ten="Zũng", bat_dau=luc(14))
    await them_phien(conn_ops, "moi", phone="0900000001", ten="An", bat_dau=luc(27))

    hang = await repo.liet_ke_khach(conn_ops, tim="Zũng", tu_ngay="all")

    assert len(hang) == 1
    assert hang[0]["ten"] == "An"
    assert hang[0]["so_phien"] == 2


async def test_dem_tong_dem_tren_tap_da_loc(conn_ops):
    """Bỏ `WHERE`/`HAVING` khỏi câu đếm thì test cũ vẫn xanh — test này thì không."""
    await them_phien(conn_ops, "a1", phone="0900000001", ten="An")
    await them_phien(conn_ops, "a2", phone="0900000001", ten="An")
    await them_phien(conn_ops, "b1", phone="0900000002", ten="Bảo")

    assert await repo.dem_tong(conn_ops, tim="An", tu_ngay="all") == (1, 2)
    assert await repo.dem_tong(conn_ops, tu_ngay="all") == (2, 3)


async def test_phien_khong_co_luot_nao_van_hien_voi_so_luot_0(conn_ops):
    """Cổng cho LEFT JOIN. `JOIN` trần làm phiên rỗng biến mất và không ai biết là mất."""
    await them_phien(conn_ops, "rong", phone="0912448111")

    hang = await repo.liet_ke_phien(conn_ops, phone="0912448111")

    assert len(hang) == 1
    assert hang[0]["so_luot"] == 0
    assert hang[0]["tin_nhan_dau"] is None


async def test_tin_nhan_dau_la_noi_dung_seq_nho_nhat(conn_ops):
    """Ca chốt giống `test_doc_luot_sap_theo_seq_khong_phai_created_at`: chèn seq 1
    TRƯỚC seq 0, với `created_at` đảo ngược `seq`. `array_agg(... ORDER BY m.seq)`
    sai thứ tự thì test này đỏ, `ORDER BY m.created_at` (giống lỗi đã có ở `doc_luot`)
    cũng đỏ."""
    await them_phien(conn_ops, "co_luot", phone="0912448111")
    await them_luot(conn_ops, "co_luot", 1, content="lượt sau", tao_luc=luc(27, 14))
    await them_luot(conn_ops, "co_luot", 0, content="lượt đầu", tao_luc=luc(27, 15))

    hang = await repo.liet_ke_phien(conn_ops, phone="0912448111")

    assert hang[0]["tin_nhan_dau"] == "lượt đầu"


async def test_dem_luot_dung_so_luong(conn_ops):
    """Đếm đúng số lượt của một phiên CÓ lượt.

    Lưu ý: test này KHÔNG phân biệt `count(*)` với `count(m.seq)` — `seq` là
    NOT NULL nên với phiên có ≥1 lượt hai cách đếm cho cùng kết quả. Cổng cho
    `count(m.seq)` là `test_phien_khong_co_luot_nao_van_hien_voi_so_luot_0`
    ở trên, nơi LEFT JOIN sinh ra một hàng NULL.
    """
    await them_phien(conn_ops, "co_luot", phone="0912448111")
    for i in range(3):
        await them_luot(conn_ops, "co_luot", i)

    hang = await repo.liet_ke_phien(conn_ops, phone="0912448111")

    assert hang[0]["so_luot"] == 3


async def test_liet_ke_phien_cua_nhom_chua_co_so(conn_ops):
    await them_phien(conn_ops, "an", phone=None)
    await them_phien(conn_ops, "co_so", phone="0912448111")

    hang = await repo.liet_ke_phien(conn_ops, phone=None)

    assert [r["session_id"] for r in hang] == ["an"]


async def test_doc_luot_sap_theo_seq_khong_phai_created_at(conn_ops):
    """Ca chốt: `created_at` ĐẢO NGƯỢC so với `seq`.

    seq 0 mang giờ MUỘN hơn seq 1. Sắp theo `seq` ⇒ ["lượt trước", "lượt sau"];
    sắp theo `created_at` ⇒ thứ tự ngược lại. Đây là điều kiện DUY NHẤT làm test
    này đỏ được khi ai đó đổi `ORDER BY seq` thành `ORDER BY created_at`.

    ⚠️ ĐỪNG đổi hai mốc giờ này thành BẰNG NHAU cho "giống đời thật". Đã đo trên
    chính schema này: PK `(tenant_id, session_id, seq)` làm Postgres index-scan
    theo `seq`, nên khi `created_at` bằng nhau thì `ORDER BY created_at` vẫn trả
    đúng thứ tự `seq` — test xanh cho cả code sai, và cái gate này thành đồ trang
    trí. Giờ đảo ngược là thứ duy nhất phân biệt được hai câu ORDER BY.
    """
    await them_phien(conn_ops, "s1")
    await them_luot(conn_ops, "s1", 1, content="lượt sau", tao_luc=luc(27, 14))
    await them_luot(conn_ops, "s1", 0, content="lượt trước", tao_luc=luc(27, 15))

    luot = await repo.doc_luot(conn_ops, "s1")

    assert [r["content"] for r in luot] == ["lượt trước", "lượt sau"]


async def test_doc_phien_tra_du_cot_man_can(conn_ops):
    """`customer_name` phải đi qua `_COT_PHIEN` — Task 3 dựng `PhienOut.ten` từ nó.

    Không có test này thì việc nó có mặt chỉ được bảo đảm bằng mắt người đọc code.
    """
    await them_phien(conn_ops, "s1", ten="Minh Anh", du_an="Ocean Park 2", chuyen=True)
    await them_luot(conn_ops, "s1", 0, content="xin chào")

    r = await repo.doc_phien(conn_ops, "s1")

    assert r is not None
    assert r["customer_name"] == "Minh Anh"
    assert r["project"] == "Ocean Park 2"
    assert r["transferred_to_sales"] is True
    assert r["so_luot"] == 1
    assert r["tin_nhan_dau"] == "xin chào"


async def test_doc_luot_khong_thay_luot_cua_tenant_khac(conn_ops):
    await them_phien(conn_ops, "trung_ten", tenant=TENANT)
    await them_phien(conn_ops, "trung_ten", tenant=TENANT_KHAC)
    await them_luot(conn_ops, "trung_ten", 0, tenant=TENANT, content="của tôi")
    await them_luot(conn_ops, "trung_ten", 0, tenant=TENANT_KHAC, content="của họ")

    luot = await repo.doc_luot(conn_ops, "trung_ten")

    assert [r["content"] for r in luot] == ["của tôi"]


async def test_doc_phien_tra_none_khi_session_khong_thuoc_tenant(conn_ops):
    await them_phien(conn_ops, "cua_ho", tenant=TENANT_KHAC)

    assert await repo.doc_phien(conn_ops, "cua_ho") is None
