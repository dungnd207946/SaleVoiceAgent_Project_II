"""Cổng SQL của màn Tổng quan. Mỗi test neo một lỗi im lặng cụ thể."""

import json
from datetime import UTC, date, datetime

import pytest

from portal.modules.ops import repo

from .conftest import TENANT_KHAC, luc, them_ca, them_phien

pytestmark = pytest.mark.asyncio

TINH_DEN = date(2026, 7, 27)


async def test_ngay_khong_co_phien_van_co_mat_voi_0(conn_ops):
    """Ca chốt: `GROUP BY ngay` bỏ hẳn ngày rỗng. Biểu đồ vẽ theo CHỈ SỐ ô, nên
    thiếu một ngày làm mọi ngày sau nó trượt sang trái một cột — trục nói sai
    ngày mà không có dấu hiệu nào."""
    await them_phien(conn_ops, "a", bat_dau=luc(27), source="chat")

    hang = await repo.hoi_thoai_theo_ngay(conn_ops, tinh_den=TINH_DEN)

    assert len(hang) == 7
    assert [r["ngay"] for r in hang] == [date(2026, 7, d) for d in range(21, 28)]
    assert hang[-1]["chat"] == 1
    # Ngày 21 không có phiên nào: LEFT JOIN sinh một hàng NULL cho nó. Thiếu
    # vế `phien.ngay IS NOT NULL` trong FILTER của `khac` thì hàng NULL đó bị
    # đếm nhầm, và `khac` ra 1 cho một ngày hoàn toàn rỗng.
    assert hang[0]["chat"] == 0
    assert hang[0]["voice"] == 0
    assert hang[0]["khac"] == 0


async def test_source_la_roi_vao_khac_khong_bi_bo(conn_ops):
    """`zalo` chưa có trong ChipKenh nhưng vẫn là một phiên có thật. Bỏ nó khỏi
    `khac` làm tổng của ô nhỏ hơn số phiên thật mà không ai đối chiếu được."""
    await them_phien(conn_ops, "z", bat_dau=luc(27), source="zalo_oa")
    await them_phien(conn_ops, "n", bat_dau=luc(27), source=None)

    hang = await repo.hoi_thoai_theo_ngay(conn_ops, tinh_den=TINH_DEN)

    assert hang[-1]["khac"] == 2
    assert hang[-1]["chat"] == 0
    assert hang[-1]["voice"] == 0


async def test_chat_voice_tach_dung_theo_source(conn_ops):
    await them_phien(conn_ops, "c1", bat_dau=luc(26), source="chat")
    await them_phien(conn_ops, "c2", bat_dau=luc(26), source="chat")
    await them_phien(conn_ops, "v1", bat_dau=luc(26), source="voice")

    hang = await repo.hoi_thoai_theo_ngay(conn_ops, tinh_den=TINH_DEN)
    ngay26 = next(r for r in hang if r["ngay"] == date(2026, 7, 26))

    assert (ngay26["chat"], ngay26["voice"]) == (2, 1)


async def test_phien_tenant_khac_khong_lot_vao(conn_ops):
    await them_phien(conn_ops, "ta", bat_dau=luc(27), source="chat")
    await them_phien(conn_ops, "tb", tenant=TENANT_KHAC, bat_dau=luc(27), source="chat")

    hang = await repo.hoi_thoai_theo_ngay(conn_ops, tinh_den=TINH_DEN)

    assert hang[-1]["chat"] == 1


async def test_phien_ngoai_cua_so_khong_dem(conn_ops):
    """Ngày 20/7 nằm ngoài cửa sổ 21→27."""
    await them_phien(conn_ops, "cu", bat_dau=luc(20), source="chat")

    hang = await repo.hoi_thoai_theo_ngay(conn_ops, tinh_den=TINH_DEN)

    assert sum(r["chat"] for r in hang) == 0


# ── Ranh giới ngày theo múi giờ VN ──────────────────────────────────────────
# `_NGAY`/`_NGAY_FB` (`repo.py`) tồn tại CHỈ vì ca này, và trước round fix
# 2026-08-13 ca này có độ phủ BẰNG 0: mọi test khác chèn phiên lúc 10:00 UTC
# (= 17:00 VN), tức ngày UTC và ngày VN trùng nhau, nên bỏ hẳn `AT TIME ZONE`
# vẫn xanh cả bộ.
#
# Hai mốc dưới đây nằm trong CÙNG một ngày UTC (27/7) nhưng KHÁC ngày VN:
#   · 16:30Z = 23:30 VN ngày 27  → thuộc cột CUỐI của cửa sổ
#   · 17:30Z = 00:30 VN ngày 28  → đã là NGÀY MAI theo giờ VN, ngoài cửa sổ
# Nên chúng bắt được cả hai kiểu hỏng:
#   · bỏ `AT TIME ZONE` ⇒ cả hai đọc ra ngày 27 UTC ⇒ cột cuối đếm 2
#   · đổi cột sang `timestamp` naive ⇒ `AT TIME ZONE` đổi chiều (diễn giải giờ
#     UTC đã lưu THÀNH giờ VN rồi quy về UTC) ⇒ cũng ra 27 cho cả hai ⇒ đếm 2
TRUA_DEM_VN = datetime(2026, 7, 27, 16, 30, tzinfo=UTC)  # 23:30 VN, ngày 27
NUA_DEM_HOM_SAU_VN = datetime(2026, 7, 27, 17, 30, tzinfo=UTC)  # 00:30 VN, ngày 28


async def test_phien_23h30_gio_vn_roi_vao_cot_cuoi_chu_khong_phai_hom_sau(conn_ops):
    """Gom theo ngày phải ở MÚI GIỜ NGƯỜI DÙNG, không phải UTC.

    Gom sai thì cột cuối biểu đồ (hôm nay) hụt mất các phiên muộn nhất — đúng
    những phiên người xem để ý nhất — và thay vào đó nuốt các phiên rạng sáng
    của ngày mai, một cột nói về hai ngày mà không có dấu hiệu nào.
    """
    await them_phien(conn_ops, "muon", bat_dau=TRUA_DEM_VN, source="chat")
    await them_phien(conn_ops, "mai-som", bat_dau=NUA_DEM_HOM_SAU_VN, source="chat")

    hang = await repo.hoi_thoai_theo_ngay(conn_ops, tinh_den=TINH_DEN)

    assert hang[-1]["ngay"] == date(2026, 7, 27)
    assert hang[-1]["chat"] == 1
    # Phiên 00:30 VN ngày 28 KHÔNG được lọt vào bất kỳ cột nào của cửa sổ 21→27.
    assert sum(r["chat"] for r in hang) == 1


async def test_dem_va_theo_kenh_cung_dung_ranh_gioi_ngay_vn(conn_ops):
    """Ba truy vấn dùng chung hằng `_NGAY` — nhưng chúng là ba câu SQL RỜI, và
    một lần sửa chỉ chạm hai trong ba là chỗ ô Hội thoại lệch khỏi chú thích
    kênh của chính nó."""
    await them_phien(conn_ops, "muon", bat_dau=TRUA_DEM_VN, source="chat")
    await them_phien(conn_ops, "mai-som", bat_dau=NUA_DEM_HOM_SAU_VN, source="chat")

    tu_ngay = date(2026, 7, 21)
    kenh = await repo.hoi_thoai_theo_kenh(conn_ops, tu_ngay=tu_ngay, tinh_den=TINH_DEN)
    tong = await repo.dem_hoi_thoai(conn_ops, tu_ngay=tu_ngay, tinh_den=TINH_DEN)
    cs = await repo.dem_chuyen_sale(conn_ops, tu_ngay=tu_ngay, tinh_den=TINH_DEN)

    assert tong == 1
    assert sum(r["n"] for r in kenh) == 1
    assert cs["tong"] == 1


async def test_danh_gia_23h30_gio_vn_thuoc_ngay_vn(conn_ops, pool):
    """`_NGAY_FB` là hằng THỨ HAI (bảng `agent_feedback` chỉ có `created_at`) —
    nó có thể bị sửa rời khỏi `_NGAY` mà không câu nào khác đỏ."""
    async with pool.acquire() as c, c.transaction():
        for sid, luc_ in (("fb-muon", TRUA_DEM_VN), ("fb-mai-som", NUA_DEM_HOM_SAU_VN)):
            await c.execute(
                "INSERT INTO tenant_data.agent_feedback (tenant_id, session_id, rating, created_at)"
                " VALUES ('opsw',$1,5,$2)",
                sid,
                luc_,
            )

    r = await repo.danh_gia(conn_ops, tu_ngay=date(2026, 7, 21), tinh_den=TINH_DEN)

    assert r["tong"] == 1


async def test_theo_kenh_cong_lai_bang_tong(conn_ops):
    """Bất biến của ô: dòng chú thích cộng lại phải ra đúng con số lớn ở trên.
    Hai truy vấn khác nhau cho hai số của cùng một tập là chỗ chúng lệch nhau."""
    for i, s in enumerate(["chat", "chat", "voice", "zalo_oa", None]):
        await them_phien(conn_ops, f"k{i}", bat_dau=luc(25), source=s)

    kenh = await repo.hoi_thoai_theo_kenh(conn_ops, tu_ngay=date(2026, 7, 21), tinh_den=TINH_DEN)
    tong = await repo.dem_hoi_thoai(conn_ops, tu_ngay=date(2026, 7, 21), tinh_den=TINH_DEN)

    assert sum(r["n"] for r in kenh) == tong == 5
    theo = {r["kenh"]: r["n"] for r in kenh}
    assert theo["chat"] == 2
    assert theo[None] == 1


async def test_chuyen_sale_dem_CA_trong_escalations_khong_dem_co_tren_phien(conn_ops):
    """Tử số phải đếm ĐÚNG loại bản ghi mà `/chuyen-sale` bày ra (đổi 2026-08-14).

    Trước đó ô ② đếm `conversations.transferred_to_sales` — một CỜ agent ghi
    lúc CHỐT bản tóm tắt cuối cuộc gọi — trong khi màn nó dẫn tới liệt kê hàng
    `tenant_data.escalations`, agent ghi NGAY lúc chuyển. Người dùng đối chiếu
    hai số và thấy vênh.

    Dữ liệu dưới đây dựng cho hai cách đếm ra HAI con số khác nhau — nếu không
    thì bài xanh cho cả bản cũ lẫn bản mới và không neo được gì:
      · `p1` chỉ có CỜ (cuộc gọi đã chốt, không có hàng ca)
      · `p2`, `p4` chỉ có CA (vừa mở, cuộc gọi chưa chốt)
      · `p3` có CẢ hai
    ⇒ đếm theo cờ ra 2 (`p1`,`p3`), đếm theo ca ra 3 (`p2`,`p3`,`p4`).
    """
    await them_phien(conn_ops, "p1", bat_dau=luc(25), chuyen=True)
    await them_phien(conn_ops, "p2", bat_dau=luc(25), chuyen=False)
    await them_phien(conn_ops, "p3", bat_dau=luc(25), chuyen=True)
    await them_phien(conn_ops, "p4", bat_dau=luc(25), chuyen=False)
    await them_ca(conn_ops, "p2", tao_luc=luc(25))
    await them_ca(conn_ops, "p3", tao_luc=luc(25))
    await them_ca(conn_ops, "p4", tao_luc=luc(25))
    # Ngoài cửa sổ — không được lọt vào vế nào.
    await them_phien(conn_ops, "cu", bat_dau=luc(10), chuyen=True)
    await them_ca(conn_ops, "cu", tao_luc=luc(10))

    r = await repo.dem_chuyen_sale(conn_ops, tu_ngay=date(2026, 7, 21), tinh_den=TINH_DEN)

    # 3 CA trong kỳ (p2, p3, p4) — KHÔNG phải 2 cờ (p1, p3).
    assert r["chuyen"] == 3
    # Mẫu số vẫn là PHIÊN trong kỳ: p1..p4.
    assert r["tong"] == 4


async def test_chuyen_sale_ca_cua_tenant_khac_khong_lot_vao(conn_ops):
    """Tử số đổi sang một bảng MỚI ⇒ vị từ cách ly của bảng đó chưa từng được
    bài nào ở đây đo. Không có bài này thì một `WHERE` thiếu `tenant_id` trên
    `escalations` chỉ lộ ra dưới dạng «gauge của workspace A cao bất thường»."""
    await them_phien(conn_ops, "ta", bat_dau=luc(25))
    await them_ca(conn_ops, "ta", tao_luc=luc(25))
    await them_ca(conn_ops, "tb", tenant=TENANT_KHAC, tao_luc=luc(25))

    r = await repo.dem_chuyen_sale(conn_ops, tu_ngay=date(2026, 7, 21), tinh_den=TINH_DEN)

    assert r["chuyen"] == 1


async def test_chuyen_sale_ca_23h30_gio_vn_thuoc_ngay_vn(conn_ops):
    """`_NGAY_ESC` là hằng THỨ BA cùng họ với `_NGAY`/`_NGAY_FB` — nó có thể bị
    sửa rời khỏi hai hằng kia mà không câu nào khác đỏ (đúng lớp lỗi mà ba bài
    múi giờ 2026-08-13 sinh ra để chặn)."""
    await them_ca(conn_ops, "muon", tao_luc=TRUA_DEM_VN)
    await them_ca(conn_ops, "mai-som", tao_luc=NUA_DEM_HOM_SAU_VN)

    r = await repo.dem_chuyen_sale(conn_ops, tu_ngay=date(2026, 7, 21), tinh_den=TINH_DEN)

    # Ca 00:30 VN ngày 28 nằm NGOÀI cửa sổ 21→27.
    assert r["chuyen"] == 1


async def test_danh_gia_trung_binh_va_phan_bo_tu_MOT_truy_van(conn_ops, pool):
    """Điểm trung bình phải tính TỪ chính phân bố đang vẽ. Hai nguồn rời nhau
    làm ngôi sao tô một đằng, con số in một nẻo."""
    async with pool.acquire() as c, c.transaction():
        for i, sao in enumerate([5, 5, 4, 3, 1]):
            await c.execute(
                "INSERT INTO tenant_data.agent_feedback (tenant_id, session_id, rating, created_at)"
                " VALUES ($1,$2,$3,$4)",
                "opsw",
                f"fb{i}",
                sao,
                luc(25),
            )

    r = await repo.danh_gia(conn_ops, tu_ngay=date(2026, 7, 21), tinh_den=TINH_DEN)

    assert r["tong"] == 5
    assert float(r["trung_binh"]) == pytest.approx(18 / 5)
    assert (r["sao5"], r["sao4"], r["sao3"], r["sao2"], r["sao1"]) == (2, 1, 1, 0, 1)


async def test_danh_gia_khong_co_luot_nao_tra_tong_0_khong_no(conn_ops):
    """Workspace mới toanh. `avg()` trên tập rỗng trả NULL — nếu router ép float
    thẳng thì màn 500 ngay lần mở đầu tiên, đúng lúc không ai gỡ được."""
    r = await repo.danh_gia(conn_ops, tu_ngay=date(2026, 7, 21), tinh_den=TINH_DEN)

    assert r["tong"] == 0
    assert r["trung_binh"] is None


async def _them_feedback(pool, sao: int, luc_: datetime, sid: str, tenant: str = "opsw") -> None:
    async with pool.acquire() as c, c.transaction():
        await c.execute(
            "INSERT INTO tenant_data.agent_feedback (tenant_id, session_id, rating, created_at) VALUES ($1,$2,$3,$4)",
            tenant,
            sid,
            sao,
            luc_,
        )


async def test_danh_gia_khong_truyen_cua_so_dem_TOAN_BO(conn_ops, pool):
    """Ca mới 2026-08-14 — ô ③ màn Tổng quan phải in ĐÚNG con số dải thống kê
    `/quality` in.

    `/quality` (`enrollment/service.py::liet_ke_feedback_cua_tenant`) cố ý đếm
    toàn bộ feedback của tenant, KHÔNG lọc thời gian và cũng không theo bộ lọc
    sao đang áp. Ô ③ trước đây lọc 7 ngày, nên hai màn cạnh nhau in hai con số
    khác nhau dưới cùng một nhãn «điểm trung bình» — người đọc không có cách
    nào biết cái nào đúng, và kết luận cả hai đều sai.
    """
    await _them_feedback(pool, 5, luc(25), "fb-trong-ky")
    await _them_feedback(pool, 1, luc(2), "fb-thang-truoc")

    r = await repo.danh_gia(conn_ops)

    assert r["tong"] == 2
    assert float(r["trung_binh"]) == pytest.approx(3.0)
    assert (r["sao5"], r["sao1"]) == (1, 1)


async def test_danh_gia_toan_bo_van_cach_ly_tenant(conn_ops, pool):
    """Bỏ vế thời gian khỏi `WHERE` là chạm vào chính câu `WHERE` mang vị từ
    cách ly — bài này chặn ca bỏ nhầm cả hai."""
    await _them_feedback(pool, 5, luc(25), "fb-ta")
    await _them_feedback(pool, 1, luc(25), "fb-tb", tenant=TENANT_KHAC)

    r = await repo.danh_gia(conn_ops)

    assert r["tong"] == 1
    assert float(r["trung_binh"]) == pytest.approx(5.0)


async def test_danh_gia_truoc_ngay_cat_o_dau_ky_khong_co_can_duoi(conn_ops, pool):
    """Mốc so của badge delta: cũng TÍCH LUỸ, nhưng tính tới trước kỳ này.

    So một số tích luỹ (`dg`) với trung bình của riêng bảy ngày trước đó là so
    hai đại lượng khác loại — ở tenant mới nó vẽ ra một mũi tên rất to nói dối.
    `truoc_ngay` vì thế KHÔNG có cận dưới: nó gom mọi lượt chấm từ trước tới
    đầu kỳ.
    """
    await _them_feedback(pool, 1, luc(2), "fb-rat-cu")  # trước cả kỳ trước
    await _them_feedback(pool, 3, luc(18), "fb-ky-truoc")
    await _them_feedback(pool, 5, luc(25), "fb-ky-nay")  # phải bị cắt

    r = await repo.danh_gia(conn_ops, truoc_ngay=date(2026, 7, 21))

    assert r["tong"] == 2
    assert float(r["trung_binh"]) == pytest.approx(2.0)


async def test_kien_thuc_thay_dem_published_tong_dem_tat_ca(conn_ops, pool):
    """Ca chốt của cả ô: agent KHÔNG đọc được bản nháp (`status <> 'published'`).
    Đếm `thay` bằng tổng là con số làm người xem yên tâm sai."""
    async with pool.acquire() as c, c.transaction():
        for ma, st in (("P1", "published"), ("P2", "published"), ("P3", "draft")):
            await c.execute(
                "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) VALUES ('opsw',$1,$2,$3)",
                ma,
                f"Dự án {ma}",
                st,
            )

    r = await repo.kien_thuc(conn_ops)

    assert (r["du_an_thay"], r["du_an_tong"]) == (2, 3)


async def _them_agent_config(pool, ky_nang: list[str], tenant: str = "opsw", role: str = "customer") -> None:
    async with pool.acquire() as c, c.transaction():
        # Role phải có trong `role_config` (FK, `0967`) — `customer` thì trigger đã tạo sẵn.
        await c.execute(
            "INSERT INTO tenant_data.role_config (tenant_id, key, ten) VALUES ($1, $2, $2) ON CONFLICT DO NOTHING",
            tenant,
            role,
        )
        await c.execute(
            "INSERT INTO tenant_data.agent_config"
            " (tenant_id, role, name, brand_name, tone, reply_length, skills, version)"
            " VALUES ($1,$3,'Trợ lý','NobleX','lich_su','ngan',$2::jsonb,1)",
            tenant,
            json.dumps(ky_nang),
            role,
        )


async def test_kien_thuc_ky_nang_hai_role_dem_hop_khong_trung(conn_ops, pool):
    """`0966`: hai hàng mỗi tenant. Subquery vô hướng cũ nổ «more than one row» ⇒
    Tổng quan 500; con số đúng là số kỹ năng KHÁC NHAU bật ở ít nhất một role."""
    await _them_agent_config(pool, ["find_project", "kb_search"], role="customer")
    await _them_agent_config(pool, ["find_project", "booking", "escalate"], role="sale")

    r = await repo.kien_thuc(conn_ops)

    assert r["ky_nang_thay"] == 4


async def test_kien_thuc_ky_nang_dem_skills_cua_cau_hinh_dang_chay(conn_ops, pool):
    """`thay` = số kỹ năng ĐANG BẬT ở bản cấu hình đang phục vụ khách.

    `tenant_data.agent_config` là nguồn duy nhất nói được "agent thật đang bật
    gì" (từ `0966` không còn bản nháp nào khác).
    """
    await _them_agent_config(pool, ["find_project", "kb_search", "escalate"])

    r = await repo.kien_thuc(conn_ops)

    assert r["ky_nang_thay"] == 3


async def test_kien_thuc_ky_nang_chua_publish_lan_nao_tra_0_khong_NULL(conn_ops):
    """Workspace chưa từng bấm «Lưu và áp dụng» ⇒ KHÔNG có hàng.

    Subquery không hàng trả NULL; thiếu `COALESCE` thì contract `thay: int`
    nổ 500 ngay lần mở màn đầu tiên của một workspace mới — đúng lúc không ai
    gỡ được. `0` ở đây là câu trả lời ĐÚNG nghĩa nghiệp vụ: chưa áp dụng cấu
    hình nào thì agent chưa bật kỹ năng nào.
    """
    r = await repo.kien_thuc(conn_ops)

    assert r["ky_nang_thay"] == 0


async def test_kien_thuc_ky_nang_cua_tenant_khac_khong_lot_vao(conn_ops, pool):
    """`agent_config` là bảng MỚI với câu này ⇒ vị từ cách ly của nó chưa từng
    được bài nào ở đây đo. Thiếu nó thì workspace vừa tạo hiện số kỹ năng của
    workspace khác — một con số trông rất hợp lý và hoàn toàn sai."""
    await _them_agent_config(pool, ["find_project"])
    await _them_agent_config(pool, ["find_project", "kb_search"], tenant=TENANT_KHAC)

    r = await repo.kien_thuc(conn_ops)

    assert r["ky_nang_thay"] == 1


async def test_kien_thuc_tai_lieu_tra_cuu_dem_kb_files_KHONG_dem_documents(conn_ops, pool):
    """Hàng «Tài liệu tra cứu» đếm `kb_files` (kho `/kb`), KHÔNG phải
    `documents` (tài liệu gõ tay của từng dự án).

    Ca này neo một lỗi ĐÃ XẢY RA THẬT (2026-08-14): ô ⑤ từng có hàng «Tài liệu
    dự án» đếm `documents` nhưng bấm vào lại sang `/kb` — người dùng thấy 6/6
    trong khi màn `/kb` trống trơn và hỏi «số liệu fake à?». Portal có HAI kho
    tài liệu, khác bảng · khác endpoint · khác tool agent đọc (`kb_search` vs
    `get_document`) — xem `features/kb/nav.ts` phía FE. Bài này chèn CẢ HAI kho
    để một lần trỏ nhầm bảng là đỏ ngay, không cần đoán.

    `kb_files` cũng không có cột `status` — nó dùng `state`, và giá trị agent
    đọc được là `'san_sang'` (đã bóc chữ → chia đoạn → nhúng vector xong). Hai
    luật khác nhau cho hai bảng khác nhau, ĐỪNG gộp về một điều kiện chung.
    """
    async with pool.acquire() as c, c.transaction():
        for i, st in enumerate(["san_sang", "san_sang", "dang_xu_ly", "loi"]):
            await c.execute(
                "INSERT INTO tenant_data.kb_files (tenant_id, ten_file, s3_key, kich_thuoc, loai, state)"
                " VALUES ('opsw',$1,$2,100,'pdf',$3)",
                f"f{i}.pdf",
                f"k/{i}",
                st,
            )
        # Kho KIA — phải KHÔNG lọt vào con số nào của hàng này.
        await c.execute(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status)"
            " VALUES ('opsw','PJD','Dự án có tài liệu','published')"
        )
        for ma in ("T1", "T2", "T3"):
            await c.execute(
                "INSERT INTO tenant_data.documents (tenant_id, project_code, title, status)"
                " VALUES ('opsw','PJD',$1,'published')",
                ma,
            )

    r = await repo.kien_thuc(conn_ops)

    assert (r["tai_lieu_tra_cuu_thay"], r["tai_lieu_tra_cuu_tong"]) == (2, 4)


async def test_kien_thuc_phan_khu_can_dem_theo_status_published(conn_ops, pool):
    """`zones`/`units` KHÔNG có test riêng nào trước round fix này — một lỗi
    copy-paste ở hai khối SQL đó (sai tên bảng, sai cột lọc) không làm test nào
    đỏ, và cổng isolation tĩnh chỉ biết dò vị từ cách ly, không biết đang đếm
    đúng bảng hay đúng cột hay không.

    `units` có CẢ `status` (hiển thị, agent đọc được) LẪN `sale_status` (kinh
    doanh) — hai cột khác nghĩa, dễ lấy nhầm. `sale_status` không hề nhận giá
    trị `'published'` (enum của nó chỉ có `available/booked/sold`), nên ba
    hàng dưới đây gán `sale_status` NGƯỢC PHA với `status`: nếu SQL lỡ lọc
    theo `sale_status = 'published'` thay vì `status = 'published'` thì
    `can_thay` tụt xuống 0 — test đỏ ngay, không cần đoán.
    """
    async with pool.acquire() as c, c.transaction():
        # Dự án cha — zones/units đều FK tới (tenant_id, project_code).
        await c.execute(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status)"
            " VALUES ('opsw','PJ1','Dự án cha','published')"
        )
        for ma, st in (("Z1", "published"), ("Z2", "published"), ("Z3", "draft")):
            await c.execute(
                "INSERT INTO tenant_data.zones (tenant_id, project_code, zone_code, status)"
                " VALUES ('opsw','PJ1',$1,$2)",
                ma,
                st,
            )
        for ma, st, sale_st in (
            ("U1", "published", "sold"),
            ("U2", "published", "sold"),
            ("U3", "draft", "available"),
        ):
            await c.execute(
                "INSERT INTO tenant_data.units"
                " (tenant_id, project_code, zone_code, unit_code, product_type, status, sale_status)"
                " VALUES ('opsw','PJ1','Z1',$1,'chung_cu',$2,$3)",
                ma,
                st,
                sale_st,
            )

    r = await repo.kien_thuc(conn_ops)

    assert (r["phan_khu_thay"], r["phan_khu_tong"]) == (2, 3)
    assert (r["can_thay"], r["can_tong"]) == (2, 3)
