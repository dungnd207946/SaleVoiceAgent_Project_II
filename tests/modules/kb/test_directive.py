"""Tầng directive là hàm thuần — test không cần DB, không cần mạng."""

import pytest

from portal.modules.kb import contracts as c
from portal.modules.kb import settings
from portal.modules.kb.directive import profiles, resolve
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE


def test_hai_nguon_embed_va_projects_chi_xuat_hien_mot_lan():
    """`zones` thôi làm nguồn riêng (spec 2026-08-19); `thong_tin` đã gộp từ trước."""
    assert len(REAL_ESTATE.embed_sources) == 2
    assert [s.table for s in REAL_ESTATE.embed_sources].count("projects") == 1
    assert {s.doc_type for s in REAL_ESTATE.embed_sources} == {"tong_quan", "tai_lieu"}
    # units KHÔNG embed — nó chỉ ở Postgres, agent lọc bằng SQL.
    assert "units" not in {s.table for s in REAL_ESTATE.embed_sources}


def test_dung_bay_category_media_khong_phai_chin():
    """02a §7 ghi "9 category" — SAI. enums/media_categories/rag_config đều 7."""
    assert len(REAL_ESTATE.media_visual) == 7
    assert "csbh" not in REAL_ESTATE.media_visual


def test_ghep_text_giu_dung_thu_tu_khai_bao():
    """Thứ tự field = thứ tự trong embed_sources, KHÔNG phải thứ tự trong dict row."""
    spec = resolve.source_for(REAL_ESTATE, "projects")
    row = {"id": 1, spec.anchor_col: "nplb", "investor": "Noble", "region": "Long Biên"}
    text = resolve.build_text(row, spec)
    assert text.index("## Khu vực") < text.index("## Chủ đầu tư")


def test_ghep_text_ra_MARKDOWN_CO_TIEU_DE_chu_khong_phai_khoi_phang():
    """Chunker cắt theo cấp tiêu đề — khối phẳng `region: X` không có chỗ nào để bám, nên
    nó sẽ rơi về cắt theo độ dài, đúng thứ đợt 2026-08-14 vừa bỏ."""
    spec = resolve.source_for(REAL_ESTATE, "projects")
    row = {"id": 1, spec.anchor_col: "nplb", "region": "Long Biên", "overview": "Đại đô thị"}
    text = resolve.build_text(row, spec)
    assert text.startswith("## Khu vực\n")
    assert "## Tổng quan\nĐại đô thị" in text
    assert "region" not in text, "tên cột DB không được lọt vào chuỗi agent đọc cho khách"


def test_nhan_field_thieu_thi_roi_ve_ten_cot():
    """Thêm field vào spec mà quên khai nhãn không được làm nổ — nó chỉ xấu."""
    from portal.modules.kb.contracts import EntitySpec

    spec = EntitySpec(table="projects", doc_type="tong_quan", fields=("region",), is_anchor=True)
    assert resolve.build_text({"id": 1, "region": "x"}, spec) == "## region\nx"


def test_ghep_text_bo_field_rong_nhung_giu_so_khong():
    """`build_density_pct = 0` là dữ liệu thật, không phải "chưa nhập"."""
    spec = resolve.source_for(REAL_ESTATE, "projects")
    row = {"id": 1, spec.anchor_col: "nplb", "region": "  ", "build_density_pct": 0}
    text = resolve.build_text(row, spec)
    assert "Khu vực" not in text
    assert "## Mật độ xây dựng\n0" in text


def test_breadcrumb_cua_documents_gom_ten_du_an_va_tieu_de():
    spec = resolve.source_for(REAL_ESTATE, "documents")
    row = {"id": 9, "project_code": "nplb", "title": "Chính sách bán hàng Q3", "body": "x"}
    d = resolve.resolve_text(workspace_slug="acme", row=row, anchor_name="Noble Palace", spec=spec)
    assert d.section == "Noble Palace > Chính sách bán hàng Q3"
    assert d.doc_type == "khac", "không có tiền tố thì rơi về khac, không phải tai_lieu"
    assert (d.chunk.max_chars, d.chunk.overlap, d.chunk.min_chars) == (
        settings.CHUNK_MAX_CHARS,
        settings.CHUNK_OVERLAP,
        settings.CHUNK_MIN_CHARS,
    )
    # Tiêu đề tài liệu vào `chunk_root`, KHÔNG prepend một dòng `#` vào body: chữ bóc từ
    # docx/xlsx đã mang `#` của chính nó.
    assert d.chunk_root == ("Chính sách bán hàng Q3",)


def test_breadcrumb_cua_anchor_chi_la_ten_no():
    spec = resolve.source_for(REAL_ESTATE, "projects")
    row = {"id": 1, spec.anchor_col: "nplb", "overview": "Đại đô thị ven sông"}
    d = resolve.resolve_text(workspace_slug="acme", row=row, anchor_name="Noble Palace", spec=spec)
    assert d.section == "Noble Palace"


def test_quick_fact_va_van_xuoi_nam_chung_mot_spec():
    """Gộp xong thì overview/amenities cũng mang nhãn — và thứ tự vẫn là hợp đồng vì
    content_hash tính trên chuỗi ghép ra."""
    spec = resolve.source_for(REAL_ESTATE, "projects")
    assert spec.fields.index("overview") > spec.fields.index("total_investment_vnd")
    row = {"id": 1, spec.anchor_col: "nplb", "region": "Long Biên", "overview": "Đại đô thị"}
    text = resolve.build_text(row, spec)
    assert "## Khu vực\nLong Biên" in text
    assert "## Tổng quan\nĐại đô thị" in text


def test_source_for_bo_qua_doc_type_khi_bang_chi_co_mot_spec():
    """Caller cũ truyền "thong_tin" vẫn chạy và KHÔNG báo gì — đó là lý do phải
    sửa caller tường minh, đừng đợi test đỏ hộ."""
    assert resolve.source_for(REAL_ESTATE, "projects", "thong_tin").doc_type == "tong_quan"
    assert resolve.source_for(REAL_ESTATE, "projects").doc_type == "tong_quan"


def test_extract_profile_chi_khi_body_rong_va_co_file():
    """Đã trích một lần thì lần sau gửi text, không gửi lại PDF (§4.2b)."""
    assert profiles.extract_profile(REAL_ESTATE, body="", file_url="docs/a.pdf") == "ocr_markdown"
    assert profiles.extract_profile(REAL_ESTATE, body="đã có nội dung", file_url="docs/a.pdf") is None
    assert profiles.extract_profile(REAL_ESTATE, body="", file_url=None) is None


def test_caption_profile_moi_category_deu_ve_mot_prompt():
    """Bản tách hai (ảnh chụp / sơ đồ) đã gộp: khác biệt duy nhất là bắt thuật lại nhãn
    và số hiệu, mà đó là việc của bước bóc chữ."""
    assert profiles.caption_profile(REAL_ESTATE, "mat_bang") == "caption"
    assert profiles.caption_profile(REAL_ESTATE, "ngoai_that") == "caption"


def test_category_ngoai_bay_gia_tri_thi_khong_index():
    assert profiles.should_index_media(REAL_ESTATE, "mat_bang") is True
    assert profiles.should_index_media(REAL_ESTATE, "csbh") is False


def test_caption_co_san_thi_gui_di_de_service_bo_qua_vlm():
    """§4.2b — user sửa caption chỉ tốn 1 lần embed, không gọi lại VLM."""
    row = {
        "id": 8802,
        "project_code": "nplb",
        "content_type": "image",
        "category": "mat_bang",
        "caption": "Mặt bằng tầng điển hình",
        "media_url": "media/mb.webp",
    }
    d = profiles.resolve_media(workspace_slug="acme", row=row, vertical=REAL_ESTATE, file_url="https://x")
    assert d.caption == "Mặt bằng tầng điển hình"

    row["caption"] = "   "
    d2 = profiles.resolve_media(workspace_slug="acme", row=row, vertical=REAL_ESTATE, file_url="https://x")
    assert d2.caption is None, "caption chỉ có khoảng trắng phải thành None để service sinh lại"


def test_caption_cua_khach_thang_caption_may_sinh():
    """Hai cột, thứ tự cố định — xem migration `0936`.

    `caption` là cột hợp đồng của cổng nạp (khách gửi, hoặc người gõ trong form);
    `caption_auto` do job `kb_caption` sinh. Đảo thứ tự này là mô tả máy đè lên chữ
    người viết, và không có đường nào để người giành lại.
    """
    goc = {
        "id": 9,
        "project_code": "nplb",
        "content_type": "image",
        "category": "mat_bang",
        "media_url": "media/mb.webp",
        "caption_auto": "Ảnh chụp một mặt bằng tầng.",
    }

    d = profiles.resolve_media(
        workspace_slug="acme", row=goc | {"caption": ""}, vertical=REAL_ESTATE, file_url="https://x"
    )
    assert d.caption == "Ảnh chụp một mặt bằng tầng.", "caption rỗng phải rơi về bản máy sinh"

    d2 = profiles.resolve_media(
        workspace_slug="acme", row=goc | {"caption": "Mặt bằng tầng 12"}, vertical=REAL_ESTATE, file_url="https://x"
    )
    assert d2.caption == "Mặt bằng tầng 12", "khách gửi mô tả thì bản của họ thắng"

    d3 = profiles.resolve_media(
        workspace_slug="acme", row=goc | {"caption": "", "caption_auto": ""}, vertical=REAL_ESTATE, file_url="https://x"
    )
    assert d3.caption is None, "rỗng cả hai vẫn là None, không phải chuỗi rỗng"


def test_doc_type_from_lay_gia_tri_tu_row_thay_vi_hang():
    """Cơ chế của spec §4.2 — spec khai hàm thì directive lấy doc_type theo từng row."""
    from portal.modules.kb.contracts import EntitySpec

    spec = EntitySpec(
        table="documents",
        doc_type="tai_lieu",
        fields=("title",),
        doc_type_from=lambda row: "csbh" if row["title"].startswith("CSBH") else "khac",
    )
    d = resolve.resolve_text(
        workspace_slug="acme",
        row={"id": 1, "project_code": "nplb", "title": "CSBH — Bảng giá"},
        anchor_name="NP",
        spec=spec,
    )
    assert d.doc_type == "csbh"


def test_khong_khai_doc_type_from_thi_van_dung_hang():
    spec = resolve.source_for(REAL_ESTATE, "projects")
    d = resolve.resolve_text(
        workspace_slug="acme",
        row={"id": 1, "project_code": "nplb", "name": "Dự án A", "overview": "x"},
        anchor_name="NP",
        spec=spec,
    )
    assert d.doc_type == "tong_quan"


def test_directive_mang_ten_bang_nguon():
    """`entity` KHÔNG còn vào payload (2026-08-14) nhưng directive vẫn mang nó: tầng trên
    dùng nó để CHỌN client (media hay rag), và `service.delete_index` lọc sổ theo nó."""
    for entity in ("projects", "documents"):
        spec = resolve.source_for(REAL_ESTATE, entity)
        d = resolve.resolve_text(
            workspace_slug="acme",
            row={"id": 1, "project_code": "nplb", "name": "x", "title": "y", "overview": "z"},
            anchor_name="NP",
            spec=spec,
        )
        assert d.entity == entity


def test_tach_tieu_de_nhan_dung_bon_loai():
    assert c.split_title("CSBH — Bảng giá đợt 3") == ("csbh", "Bảng giá đợt 3")
    assert c.split_title("Pháp lý — Hợp đồng mẫu") == ("phap_ly", "Hợp đồng mẫu")
    assert c.split_title("Hướng dẫn — Sổ tay bàn giao") == ("huong_dan", "Sổ tay bàn giao")


def test_tach_tieu_de_khong_co_ngan_cach_thi_giu_nguyen():
    assert c.split_title("Brochure công ty") == ("khac", "Brochure công ty")


def test_tach_tieu_de_co_ngan_cach_nhung_tien_to_la_thi_GIU_NGUYEN_CA_CAU():
    """Bẫy chính: cắt phần đầu của một tiêu đề tự do là âm thầm đổi tên tài liệu."""
    assert c.split_title("Quy trình — bước 2") == ("khac", "Quy trình — bước 2")


def test_tach_tieu_de_phan_biet_hoa_thuong():
    """`csbh —` không phải tiền tố hợp lệ: khoan dung ở đây nghĩa là hai tiêu đề
    khác nhau sinh cùng một doc_type, và không ai nhìn ra lúc đọc dữ liệu."""
    assert c.split_title("csbh — Bảng giá") == ("khac", "csbh — Bảng giá")


def test_ghep_tieu_de_la_nghich_dao_cua_tach():
    assert c.join_title("csbh", "Bảng giá đợt 3") == "CSBH — Bảng giá đợt 3"
    assert c.join_title("khac", "Brochure công ty") == "Brochure công ty"
    assert c.split_title(c.join_title("phap_ly", "Sổ đỏ")) == ("phap_ly", "Sổ đỏ")


def test_ghep_tieu_de_voi_ma_loai_la_thi_no_LOI():
    """Nuốt im lặng nghĩa là tài liệu rơi về `khac` mà không ai thấy — và lớp
    `Literal` ở biên HTTP là thứ duy nhất còn chắn, nên nó lệch là cả hai cùng câm."""
    with pytest.raises(ValueError):
        c.join_title("tong_quan", "Bảng giá")


def test_loai_tai_lieu_doc_tu_cot_title_cua_row():
    assert c.doc_type_of({"title": "CSBH — Bảng giá"}) == "csbh"
    assert c.doc_type_of({"title": "Brochure"}) == "khac"


def test_spec_documents_khai_doc_type_from_nen_directive_mang_loai_that():
    spec = resolve.source_for(REAL_ESTATE, "documents")
    row = {"id": 9, "project_code": "nplb", "title": "CSBH — Bảng giá đợt 3", "body": "x"}
    d = resolve.resolve_text(workspace_slug="acme", row=row, anchor_name="Noble Palace", spec=spec)
    assert d.doc_type == "csbh"
    # Breadcrumb tự mang loại vì section_col="title" — không cần chèn cấp nào.
    assert d.section == "Noble Palace > CSBH — Bảng giá đợt 3"


def test_phan_khu_khong_co_tong_quan_van_ra_chu():
    """Phân khu thiếu `overview` PHẢI vẫn sinh được nội dung.

    Trước 2026-08-18 `zones` khai `fields=("overview",)` — đúng MỘT trường — nên một phân
    khu đủ tên, loại hình, quy mô mà bỏ trống tổng quan cho ra text rỗng, chunker trả 0
    chunk, job báo `+0 point` và phân khu đó VÔ HÌNH với agent. Đã đo trên EC2: 22/22 job
    `zones` thành công mà không ghi được point nào.

    Từ spec 2026-08-19 phân khu là khối con của doc dự án — bất biến vẫn y nguyên, chỉ
    đổi đường đi.
    """
    spec = resolve.source_for(REAL_ESTATE, "projects")
    text = resolve.build_text(
        {
            "id": 1,
            "project_code": "nplb",
            "children": [
                {"name": "Phân khu Hoa Lan", "category": "biet_thu", "product_scale": "120 căn", "overview": ""}
            ],
        },
        spec,
    )
    assert text.strip(), "phân khu không có tổng quan vẫn phải ra chữ"
    assert "Phân khu Hoa Lan" in text
    assert "120 căn" in text


def test_phan_khu_chi_co_ten_van_ra_chu():
    """Trường hợp mỏng nhất hợp lệ: hợp đồng nạp chỉ bắt buộc `name` cho zone."""
    spec = resolve.source_for(REAL_ESTATE, "projects")
    text = resolve.build_text({"id": 1, "project_code": "nplb", "children": [{"name": "Phân khu B"}]}, spec)
    assert "Phân khu B" in text


def test_phan_khu_van_giu_tong_quan_khi_co():
    spec = resolve.source_for(REAL_ESTATE, "projects")
    text = resolve.build_text(
        {
            "id": 1,
            "project_code": "nplb",
            "children": [{"name": "PK A", "overview": "Biệt thự ven hồ, mật độ thấp."}],
        },
        spec,
    )
    assert "Biệt thự ven hồ, mật độ thấp." in text
