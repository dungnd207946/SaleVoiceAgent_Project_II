"""Cổng canh bất biến point-id — spec 2026-08-10 §4.3.

⚠️ KHI TEST NÀY ĐỎ, ĐỪNG SỬA `values` CHO XANH. Nó đỏ nghĩa là một tiền tố mới
trong TITLE_PREFIXES sinh ra doc_type đã thuộc về nguồn khác. Point id là
`uuid5(doc_type:record_id:idx)` và KHÔNG chứa tên bảng, nên `projects` id 12 và
`documents` id 12 cùng doc_type sẽ ghi đè nhau — không lỗi, không log, một trong
hai biến mất khỏi kho vector. Sửa bằng cách đổi tên mã loại mới.
"""

from typing import get_args

from portal.modules.kb.contracts import DEFAULT_DOC_TYPE, TITLE_PREFIXES
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE
from portal.modules.realestate.router import _LoaiTaiLieu


def test_loai_tai_lieu_khong_dung_doc_type_cua_nguon_khac():
    values = set(TITLE_PREFIXES.values()) | {DEFAULT_DOC_TYPE}
    khac = {s.doc_type for s in REAL_ESTATE.embed_sources if s.doc_type_from is None}
    assert values & khac == set()


def test_moi_tien_to_sinh_mot_ma_rieng():
    """Hai tiền tố cùng mã nghĩa là join_title() mất tính nghịch đảo."""
    assert len(set(TITLE_PREFIXES.values())) == len(TITLE_PREFIXES)


def test_enum_o_bien_http_khop_bang_tien_to():
    """`_LoaiTaiLieu` là bản sao miền giá trị của `TITLE_PREFIXES`. Thêm tiền tố mà
    quên nó ⇒ API trả 422 cho loại mới trong khi mọi test khác vẫn xanh."""
    assert set(get_args(_LoaiTaiLieu)) == set(TITLE_PREFIXES.values()) | {DEFAULT_DOC_TYPE}
