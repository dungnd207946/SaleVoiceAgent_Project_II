"""Test `completeness.py` — HÀM THUẦN, không cần Postgres (không có `pytestmark
= pytest.mark.integration`, khác `test_repo.py`/`test_crud.py`).

Nguồn sự thật: `docs/build_module_knowledgebase/02a-real-estate-template.md` §7
— *"project cần name+region+overview; unit cần
price_vnd+area_built_m2+sale_status."*

⚠️ LUẬT `project` NAY LÀ NĂM TRƯỜNG (spec 2026-08-21 §3.5), không phải hai như
`02a §7` cũng không phải ba như bản 2026-08-18. `overview` QUAY LẠI, và thêm
`investor` + `product_scale`.

Nguồn để chọn: `kb/directive/verticals/real_estate.py` khai đúng 11 trường của
`projects` được biến thành văn bản cho agent đọc. Trường ngoài danh sách đó có
điền cũng không tới tay agent nên không có lý do gác cổng. `amenities` NẰM trong
11 trường nhưng CỐ Ý ở ngoài cổng — đo trên Aurora dev: rỗng ở 94/94 dự án đang
published, và một cổng mà mọi thứ đều không qua thì không còn phân biệt được gì.
"""

from portal.modules.realestate.completeness import BAT_BUOC, thieu_truong


def test_bat_buoc_dung_bon_truong_cua_du_an():
    """Cổng chống trôi ngược: đổi danh sách này là đổi một hợp đồng HTTP đang
    chạy (422 `INCOMPLETE_DATA`) và làm lệch `completeness.ts` bên frontend."""
    assert BAT_BUOC == {
        "project": ("name", "region", "overview", "investor"),
        "unit": ("price_vnd", ("area_built_m2", "area_land_m2"), "sale_status"),
    }


def test_quy_mo_san_pham_o_NGOAI_cong():
    """BỎ 2026-08-25 theo yêu cầu người dùng. `product_scale` là câu mô tả tự do
    («3 toà · 1.240 căn hộ · 68 shophouse»), không phải dữ liệu agent tra cứu —
    chặn phát hành vì thiếu nó là chặn ở chỗ không đổi được câu trả lời nào của
    agent. Bài này đảo chiều bài cũ chứ không xoá: nếu ai đó thêm lại thì đỏ."""
    assert "product_scale" not in BAT_BUOC["project"]


def test_amenities_co_y_o_NGOAI_cong():
    """Rỗng ở 94/94 dự án published trên Aurora dev. Đưa nó vào cổng là gắn cờ
    thiếu dữ liệu cho toàn bộ dữ liệu đang có — xem spec §3.5.1."""
    assert "amenities" not in BAT_BUOC["project"]


def test_truong_agent_khong_doc_thi_khong_gac_cong():
    """`salePhase`/`developer`/`link360` không nằm trong `embed_sources` của
    `real_estate.py`, nên có điền cũng không tới tay agent."""
    for truong in ("sale_phase", "developer", "link_360"):
        assert truong not in BAT_BUOC["project"]


# ─── `project` ───────────────────────────────────────────────────────────────


DU_AN_DU = {
    "name": "Noble Palace",
    "region": "Long Biên, Hà Nội",
    "overview": "Đại đô thị ven sông",
    "investor": "Noble Group",
    "product_scale": "3 toà · 1.240 căn",
}


def test_project_du_du_lieu_tra_rong():
    assert thieu_truong("project", DU_AN_DU) == []


def test_project_thieu_tong_quan_thi_khong_du():
    """Đảo lại `test_project_chi_thieu_tong_quan_thi_van_du` của bản 2026-08-18."""
    assert thieu_truong("project", {**DU_AN_DU, "overview": ""}) == ["overview"]


def test_project_thieu_chu_dau_tu():
    """`product_scale` rỗng KHÔNG còn được kể tên — nó đã rời cổng."""
    thieu = thieu_truong("project", {**DU_AN_DU, "investor": "", "product_scale": ""})
    assert thieu == ["investor"]


def test_project_du_du_khong_can_tien_ich():
    assert thieu_truong("project", {**DU_AN_DU, "amenities": ""}) == []


def test_project_thieu_ca_hai_truong():
    """Cột `text NOT NULL DEFAULT ''` — "thiếu" là CHUỖI RỖNG, không phải
    `None` (cột NOT NULL không bao giờ `None`, kiểm bằng `information_schema`
    thật — xem task-5-report.md)."""
    ban_ghi = dict.fromkeys(DU_AN_DU, "")
    assert thieu_truong("project", ban_ghi) == list(BAT_BUOC["project"])


def test_project_none_cung_bi_bat_du_khong_dung_o_db_that():
    """DB thật không bao giờ cho `NULL` ở ba cột này (NOT NULL) — nhưng hàm vẫn
    kiểm tổng quát nên `None` (vd `ban_ghi` dựng tay trong test khác) cũng phải
    bị bắt là thiếu, không được đi lọt qua vì "không phải chuỗi rỗng"."""
    assert thieu_truong("project", {**DU_AN_DU, "name": None}) == ["name"]


# ─── `unit` ───────────────────────────────────────────────────────────────────


def test_unit_du_du_lieu_tra_rong():
    ban_ghi = {
        "price_vnd": 5_620_000_000,
        "area_built_m2": 78.4,
        "area_land_m2": None,
        "sale_status": "available",
    }
    assert thieu_truong("unit", ban_ghi) == []


def test_unit_thieu_gia_va_dien_tich_la_null():
    """Cột `numeric` NULLABLE (không DEFAULT) — "thiếu" là `NULL`/`None`, KHÔNG
    phải chuỗi rỗng (kiểm bằng `information_schema` thật)."""
    ban_ghi = {
        "price_vnd": None,
        "area_built_m2": None,
        "area_land_m2": None,
        "sale_status": "available",
    }
    assert thieu_truong("unit", ban_ghi) == ["price_vnd", "area_built_m2 hoặc area_land_m2"]


def test_unit_gia_bang_khong_khong_tinh_la_thieu():
    """`0` là một giá trị SỐ hợp lệ (khác `None`) — hàm không được coi giá trị
    falsy-nhưng-không-None/không-rỗng-chuỗi (như số `0`) là thiếu."""
    ban_ghi = {"price_vnd": 0, "area_built_m2": 0, "area_land_m2": None, "sale_status": "available"}
    assert thieu_truong("unit", ban_ghi) == []


def test_unit_sale_status_rong_cung_bi_bat():
    """`sale_status` NOT NULL DEFAULT 'available' + CHECK enum — thực tế DB
    không bao giờ cho `''`, nhưng hàm vẫn kiểm tổng quát (không hardcode kiểu
    theo từng field) nên `ban_ghi` dựng tay với `sale_status=""` vẫn bị bắt."""
    ban_ghi = {"price_vnd": 100, "area_built_m2": 50, "area_land_m2": None, "sale_status": ""}
    assert thieu_truong("unit", ban_ghi) == ["sale_status"]


# ─── Entity không có luật — `02a §7` không định nghĩa cho zone/document/media ─


def test_zone_document_media_luon_tra_rong():
    """`zone`/`document`/`media` không có mặt trong `BAT_BUOC` — không có luật
    thì không có gì để thiếu, dù `ban_ghi` rỗng toàn bộ."""
    assert thieu_truong("zone", {}) == []
    assert thieu_truong("document", {}) == []
    assert thieu_truong("media", {}) == []


def test_entity_la_tra_rong_khong_raise():
    """Entity không tồn tại (gõ sai/lạ) — trả rỗng, không raise KeyError. Hàm
    THUẦN không phải nơi validate tên entity (việc đó là của Pydantic/router)."""
    assert thieu_truong("khong-ton-tai", {}) == []


# ─── Diện tích: MỘT TRONG HAI (2026-08-25) ───────────────────────────────────
#
# Sản phẩm ĐẤT (biệt thự · nhà phố · shophouse) không bao giờ có diện tích thông
# thuỷ — đo trên DB dev `aina_prod`: 0/5.133 căn có `area_built_m2`, 5.133/5.133
# có `area_land_m2`. Cổng cũ bắt `area_built_m2` cho MỌI loại hình, nên nó gắn
# cờ thiếu lên 5.133 căn trong đó 4.189 căn đang published và hoàn toàn bình
# thường — một cổng kêu ở cả ca đúng lẫn ca sai thì không phân biệt được gì.
#
# Luật là «có ÍT NHẤT MỘT số đo diện tích», KHÔNG phải một danh sách loại-hình-
# nào-dùng-cột-nào: danh sách đó là bản chép thứ ba của ngữ nghĩa loại hình, và
# nó không thể đúng với loại lưỡng tính như `shophouse`.


def test_unit_chi_co_dien_tich_dat_van_du():
    """Biệt thự: có DT đất, không có DT thông thuỷ — phải qua cổng."""
    ban_ghi = {
        "price_vnd": 21_467_716_830,
        "area_built_m2": None,
        "area_land_m2": 180,
        "sale_status": "sold",
    }
    assert thieu_truong("unit", ban_ghi) == []


def test_unit_chi_co_dien_tich_thong_thuy_van_du():
    """Chiều ngược lại — căn hộ chung cư, không có DT đất."""
    ban_ghi = {
        "price_vnd": 5_620_000_000,
        "area_built_m2": 78.4,
        "area_land_m2": None,
        "sale_status": "available",
    }
    assert thieu_truong("unit", ban_ghi) == []


def test_unit_thieu_ca_hai_dien_tich_thi_bao_mot_muc():
    """Thiếu cả hai ⇒ MỘT mục nói rõ là «hoặc», không phải hai mục — hai mục đọc
    thành «phải điền cả hai», đúng cái luật này vừa bỏ."""
    ban_ghi = {
        "price_vnd": 100,
        "area_built_m2": None,
        "area_land_m2": None,
        "sale_status": "available",
    }
    assert thieu_truong("unit", ban_ghi) == ["area_built_m2 hoặc area_land_m2"]


def test_cot_cua_trai_phang_de_kiem_payload_cham_cong():
    """`_chan_publish_thieu` hỏi «payload có chạm cổng không» bằng cách so TÊN CỘT.
    Nhóm một-trong là tuple, nên nó cần một bản trải phẳng — thiếu hàm này thì phép
    so `truong in payload` đem một tuple đi so với các khoá chuỗi và LUÔN sai."""
    from portal.modules.realestate.completeness import cot_cua

    assert cot_cua("unit") == ("price_vnd", "area_built_m2", "area_land_m2", "sale_status")
    assert cot_cua("project") == ("name", "region", "overview", "investor")
    assert cot_cua("zone") == ()
