"""Khối con trong doc anchor — hàm thuần, không DB."""

from portal.modules.kb.contracts import ChildBlockSpec, ChunkSpec, EntitySpec
from portal.modules.kb.directive.resolve import build_text, child_block_text
from portal.modules.kb.index import chunker

TOA = ChildBlockSpec(
    table="buildings",
    name_col="name",
    section="",
    subsection="Toà",
    fields=("num_floors", "facing", "amenities"),
    field_labels={"num_floors": "Số tầng", "facing": "Hướng toà", "amenities": "Tiện ích"},
    value_labels={"facing": {"dong_nam": "Đông Nam"}},
    line_fields=("amenities",),
    parent_col="zone_code",
)

BLOCK = ChildBlockSpec(
    table="zones",
    name_col="name",
    section="Cơ cấu sản phẩm",
    subsection="Phân khu",
    fields=("category", "product_scale", "note", "overview"),
    field_labels={"category": "Loại hình", "product_scale": "Quy mô", "note": "Vị trí"},
    value_labels={"category": {"biet_thu": "Biệt thự", "lien_ke": "Liền kề"}},
    line_fields=("note",),
    key_col="zone_code",
    child=TOA,
    orphan_heading="Toà chưa gắn phân khu",
)

ANCHOR = EntitySpec(
    table="projects",
    doc_type="tong_quan",
    is_anchor=True,
    fields=("region", "investor"),
    field_labels={"region": "Khu vực", "investor": "Chủ đầu tư"},
    child_block=BLOCK,
)

# Sáu phân khu THẬT của aina_2/CE9F4363 — chỉ có tên, trùng ba cặp.
ZONES_THAT = [
    {"name": n, "zone_code": n, "category": None, "product_scale": "", "note": "", "overview": "", "children": []}
    for n in [
        "Vịnh Bình Minh 2",
        "Vịnh Bình Minh 1",
        "Vịnh Bình Minh 2",
        "Thiên Đường Nhiệt Đới 1",
        "Vịnh Bình Minh 1",
        "Thiên Đường Nhiệt Đới 1",
    ]
]


def _zone(name: str, **kw) -> dict:
    return {"name": name, "zone_code": name, "category": None, "product_scale": "", "note": "", "overview": "", **kw}


def test_khong_co_hang_con_thi_khong_sinh_section_rong():
    assert child_block_text([], BLOCK) == ""


def test_phan_khu_chi_co_ten_nam_o_dong_danh_sach_khong_thanh_tieu_de():
    """Ca SẢN XUẤT. Tiêu đề không có thân thì chunker bỏ hẳn — tên phải nằm trong dòng «Gồm N …»."""
    ra = child_block_text([_zone("A")], BLOCK)
    assert ra == "## Cơ cấu sản phẩm\n### Phân khu\nGồm 1 phân khu: A."


def test_danh_sach_gop_ten_trung():
    ra = child_block_text(ZONES_THAT, BLOCK)
    assert "Gồm 3 phân khu: Vịnh Bình Minh 2, Vịnh Bình Minh 1, Thiên Đường Nhiệt Đới 1." in ra
    assert "####" not in ra


def test_phan_khu_co_thong_tin_thanh_muc_rieng():
    ra = child_block_text([_zone("A", category="biet_thu", product_scale="120 căn", note="Sát cổng chính")], BLOCK)
    assert "#### Phân khu A\nLoại hình: Biệt thự · Quy mô: 120 căn\nVị trí: Sát cổng chính" in ra
    assert "biet_thu" not in ra


def test_ten_da_mo_dau_bang_nhan_thi_khong_lap():
    ra = child_block_text([_zone("Phân khu Sakura", overview="Ven hồ.")], BLOCK)
    assert "#### Phân khu Sakura\n" in ra


def test_trung_ten_khac_field_thi_giu_ca_hai():
    rows = [_zone("A", category="biet_thu"), _zone("A", category="lien_ke")]
    assert child_block_text(rows, BLOCK).count("#### Phân khu A") == 2


def test_toa_long_trong_phan_khu_va_mang_ten_phan_khu():
    toa = [
        {"name": "A1", "zone_code": "K", "num_floors": 25, "facing": "dong_nam", "amenities": "Gym"},
        {"name": "A2", "zone_code": "K", "num_floors": None, "facing": None, "amenities": ""},
    ]
    ra = child_block_text([_zone("KOMOREBI", zone_code="K", children=toa)], BLOCK)
    assert "#### Phân khu KOMOREBI\nGồm 2 toà: A1, A2." in ra
    assert "##### Toà A1 — phân khu KOMOREBI\nSố tầng: 25 · Hướng toà: Đông Nam\nTiện ích: Gym" in ra
    assert "##### Toà A2" not in ra, "toà chỉ có tên chỉ nằm trong dòng danh sách"


def test_toa_chua_gan_phan_khu_co_muc_rieng():
    mo_coi = [{"name": "B1", "zone_code": None, "num_floors": 9, "facing": None, "amenities": ""}]
    ra = child_block_text([_zone("A")], BLOCK, mo_coi)
    assert "#### Toà chưa gắn phân khu\nGồm 1 toà: B1.\n\n##### Toà B1\nSố tầng: 9" in ra


def test_build_text_noi_khoi_con_vao_cuoi():
    row = {"id": 1, "region": "Quảng Ninh", "investor": "Vinhomes", "children": ZONES_THAT}
    text = build_text(row, ANCHOR)
    assert text.index("## Khu vực") < text.index("## Cơ cấu sản phẩm")
    assert text.endswith("Thiên Đường Nhiệt Đới 1.")


def test_build_text_khong_co_children_thi_nhu_cu():
    row = {"id": 1, "region": "Quảng Ninh", "investor": "Vinhomes"}
    assert build_text(row, ANCHOR) == "## Khu vực\nQuảng Ninh\n\n## Chủ đầu tư\nVinhomes"


def test_formatter_doi_gia_tri_truoc_khi_ghep():
    spec = EntitySpec(
        table="projects",
        doc_type="tong_quan",
        fields=("fee",),
        field_labels={"fee": "Phí"},
        formatters={"fee": lambda v: f"{int(v):,}".replace(",", ".")},
    )
    assert build_text({"id": 1, "fee": 15000}, spec) == "## Phí\n15.000"


def test_khoi_con_luon_thanh_point_rieng():
    """Ranh giới đến từ ĐỘ SÂU đường dẫn, không từ cỡ chunk — nên đúng ở mọi `min_chars`."""
    row = {"id": 1, "region": "Quảng Ninh", "investor": "Vinhomes", "children": ZONES_THAT}
    text = build_text(row, ANCHOR)
    for min_chars in (0, 300, 600):
        chunks = chunker.split(text, ChunkSpec(1000, 100, min_chars))
        rieng = [c for c in chunks if c.section_path[:1] == ("Cơ cấu sản phẩm",)]
        chung = [c for c in chunks if c.section_path[:1] != ("Cơ cấu sản phẩm",)]
        assert len(rieng) == 1, min_chars
        assert len(chung) == 1, min_chars
        assert not any("Phân khu" in c.text for c in chung), min_chars
        assert rieng[0].section_path == ("Cơ cấu sản phẩm", "Phân khu")


def test_nhieu_phan_khu_van_khong_lan_sang_point_tong_quan():
    rows = [
        _zone(
            f"Phân khu số {i}",
            category="biet_thu",
            product_scale=f"{i * 10} căn",
            overview=f"Phân khu thứ {i} nằm ở phía đông dự án, tiếp giáp trục cảnh quan chính.",
            children=[],
        )
        for i in range(1, 41)
    ]
    row = {"id": 1, "region": "Quảng Ninh", "investor": "Vinhomes", "children": rows}
    chunks = chunker.split(build_text(row, ANCHOR), ChunkSpec(1000, 100, 300))
    chung = [c for c in chunks if c.section_path[:1] != ("Cơ cấu sản phẩm",)]
    assert len(chung) == 1
    assert not any("Phân khu" in c.text for c in chung)
    assert all(len(c.text) <= 1000 for c in chunks)
