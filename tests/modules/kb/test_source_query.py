"""SQL sinh ra phải mang đủ điều kiện cách ly + cascade. So chuỗi, không cần DB.

KHÔNG CÒN lọc `status = 'published'` (2026-08-14): hàng nháp cũng được nạp, và trạng thái
HIỆU LỰC trong payload + mệnh đề lọc của agent mới là chỗ ẩn nó. Nhờ vậy công bố một dự án
chỉ cần cập nhật payload chứ không phải nhúng lại cả cây con.

Thiếu `_CACH_LY` thì index vẫn chạy, vẫn xanh, chỉ là chứa dữ liệu của tenant khác — không
có triệu chứng nào khác, nên đó là thứ file này canh gắt nhất.
"""

import pytest

from portal.modules.kb.directive import resolve
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE
from portal.modules.kb.source import query


def test_cau_cua_anchor_khong_join_chinh_no():
    spec = resolve.source_for(REAL_ESTATE, "projects")
    sql = query.read_record_sql(REAL_ESTATE, spec)
    assert "JOIN" not in sql
    assert "status = 'published'" not in sql, "hàng nháp cũng phải nạp được"
    # Trạng thái vẫn phải được SELECT — nó đi vào payload point.
    assert "status" in sql and "anchor_status" in sql
    assert "region" in sql and "investor" in sql


def test_cau_cua_bang_con_join_bang_FK_TO_HOP_va_kiem_status_HAI_phia():
    """FK tổ hợp là lưới thứ hai sau RLS: câu này không trỏ sang tenant khác được."""
    spec = resolve.source_for(REAL_ESTATE, "documents")
    sql = query.read_record_sql(REAL_ESTATE, spec)
    # Dùng hằng số thay vì gõ tên cột: câu assert này sống qua lúc M4 rename
    # `projects.code` → `project_code` mà không cần sửa.
    assert f"(a.tenant_id, a.{REAL_ESTATE.anchor_code_col}) = (c.tenant_id, c.{spec.anchor_col})" in sql
    assert "status = 'published'" not in sql, "hàng nháp cũng phải nạp được"
    # Trạng thái của CẢ HAI phía vẫn phải được select: payload mang trạng thái HIỆU LỰC, và
    # nó là phép AND của hai cột này.
    assert "c.status" in sql and "a.status AS anchor_status" in sql
    # Van duyệt: tài liệu đang chờ duyệt bị loại khỏi đường nạp NGAY Ở ĐÂY, không phải bằng
    # một nhánh riêng ở các bước sau.
    assert "body_cho_duyet" in sql


def test_chan_ten_dinh_danh_khong_hop_le():
    with pytest.raises(ValueError, match="không hợp lệ"):
        query._safe_ident("documents; DROP TABLE control.tenants")


def test_cau_theo_anchor_loc_ma_du_an():
    """`ops/sync.py` cần cả hai vị từ: status (chỉ hàng published) và mã dự án (không tràn)."""
    spec = resolve.source_for(REAL_ESTATE, "documents")
    sql = query.list_ban_ghi_theo_anchor_sql(REAL_ESTATE, spec)
    assert "status = 'published'" not in sql, "hàng nháp cũng phải nạp được"
    assert "project_code = $1" in sql


def test_cau_theo_anchor_cua_anchor_loc_dung_cot_ma_cua_chinh_no():
    """`projects` là is_anchor=True — vị từ mã dự án phải lọc trên cột mã của CHÍNH bảng đó."""
    spec = resolve.source_for(REAL_ESTATE, "projects")
    sql = query.list_ban_ghi_theo_anchor_sql(REAL_ESTATE, spec)
    assert f"{REAL_ESTATE.anchor_code_col} = $1" in sql


def test_cau_media_theo_anchor_loc_ma_du_an():
    sql = query.list_media_theo_anchor_sql(REAL_ESTATE)
    assert "FROM tenant_data.media" in sql
    assert "status = 'published'" not in sql, "hàng nháp cũng phải nạp được"
    assert f"{REAL_ESTATE.media_anchor_col} = $1" in sql


def test_MOI_ham_sinh_sql_deu_mang_vi_tu_cach_ly_tenant():
    """Cổng cách ly cho `query.py`, đứng NGAY TRONG bộ test của module.

    Cổng thật (`tests/isolation/test_loc_tenant_o_tang_app.py`) đang ĐỎ vì hai món nợ cũ
    ở `modules/ops/repo.py`, nên bỏ vị từ tenant khỏi một hàm ở đây không làm CI đỏ thêm
    một dòng nào — đã mutation-test: bỏ `_CACH_LY` khỏi `list_ban_ghi_theo_anchor_sql`
    thì 151/151 test kb vẫn xanh. Sau `0909` không còn RLS đỡ, và kết quả của năm câu
    này đi THẲNG vào Qdrant: một record của tenant khác lọt vào là nó được embed rồi ghi
    vào collection của tenant này.

    Liệt kê hàm bằng `inspect`, không gõ tay: hàm sinh SQL viết ngày mai cũng bị xét.
    """
    import inspect

    from portal.modules.kb.contracts import ChildBlockSpec

    spec = resolve.source_for(REAL_ESTATE, "documents")
    block = ChildBlockSpec(
        table="zones",
        name_col="name",
        section="s",
        subsection="ss",
        fields=("overview",),
        field_labels={},
    )
    doi_so = {
        "read_record_sql": (REAL_ESTATE, spec),
        "read_child_rows_sql": (block,),
        "read_media_sql": (REAL_ESTATE,),
        "list_ban_ghi_theo_anchor_sql": (REAL_ESTATE, spec),
        "list_media_theo_anchor_sql": (REAL_ESTATE,),
    }
    ham_sinh_sql = [
        ten
        for ten, _ in inspect.getmembers(query, inspect.isfunction)
        if ten.endswith("_sql") and not ten.startswith("_")
    ]
    assert set(ham_sinh_sql) == set(doi_so), "có hàm sinh SQL mới chưa khai đối số cho cổng này"

    thieu = [ten for ten in ham_sinh_sql if query._CACH_LY not in getattr(query, ten)(*doi_so[ten])]
    assert thieu == [], f"câu sinh ra thiếu vị từ cách ly tenant: {thieu}"


def test_body_cua_tai_lieu_noi_ca_hai_cot():
    """Chữ khách gửi ở `body`, chữ ta bóc từ tệp ở `body_auto` (migration `0937`).

    NỐI chứ không coalesce (2026-08-25): `body` của bản ghi cổng nạp thường chỉ là siêu dữ
    liệu («Phạm vi… Hiệu lực…»), nên để nó thắng là agent chỉ thấy 43 ký tự trong khi nội
    dung thật nằm trong PDF. Đo trên `aina_prod`: 27/40 tài liệu rơi vào đúng ca đó.
    """
    spec = resolve.source_for(REAL_ESTATE, "documents")
    sql = query.read_record_sql(REAL_ESTATE, spec)

    assert "concat_ws" in sql and "c.body" in sql and "c.body_auto" in sql
    assert "coalesce(nullif(c.body, ''), c.body_auto) AS body" not in sql, "coalesce làm siêu dữ liệu thắng"
    # KHÔNG được còn `c.body` đọc trần trong danh sách cột — đọc trần là bỏ qua chữ đã bóc.
    assert ", c.body," not in sql


def test_bang_khac_khong_bi_dinh_bieu_thuc_body():
    """`_COT_SUY` chỉ áp cho `documents`. Rò sang bảng khác là SQL nổ vì cột không tồn tại."""
    sql = query.read_record_sql(REAL_ESTATE, resolve.source_for(REAL_ESTATE, "projects"))
    assert "body_auto" not in sql
    # `zones` nay đi đường khối con — vẫn phải sạch biểu thức của `documents`.
    block = REAL_ESTATE.embed_sources[0].child_block
    assert "body_auto" not in query.read_child_rows_sql(block)


def test_sql_hang_con_mang_vi_tu_cach_ly_va_thu_tu_on_dinh():
    from portal.modules.kb.contracts import ChildBlockSpec

    block = ChildBlockSpec(
        table="zones",
        name_col="name",
        section="Cơ cấu sản phẩm",
        subsection="Phân khu",
        fields=("category", "overview"),
        field_labels={"category": "Loại hình"},
    )
    sql = query.read_child_rows_sql(block)
    assert "tenant_id = portal.current_tenant()" in sql
    assert "tenant_data.zones" in sql
    assert "project_code = $1" in sql
    assert "ORDER BY id" in sql
    # Cột đọc đúng tập khai báo, không thừa không thiếu.
    assert "SELECT name, category, overview" in sql
    # KHÔNG lọc status — spec §D4.
    assert "status" not in sql


def test_sql_hang_con_tu_choi_ten_bang_khong_hop_le():
    from portal.modules.kb.contracts import ChildBlockSpec

    block = ChildBlockSpec(
        table="zones; DROP TABLE x",
        name_col="name",
        section="s",
        subsection="ss",
        fields=(),
        field_labels={},
    )
    with pytest.raises(ValueError, match="không hợp lệ"):
        query.read_child_rows_sql(block)
