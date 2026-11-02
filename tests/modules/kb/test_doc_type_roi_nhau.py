"""Cổng canh điều kiện DUY NHẤT để bỏ được khoá payload `entity` (2026-08-14).

`<slug>_documents` chứa point của BA bảng dùng ba sequence riêng, nên `projects#5`,
`zones#5` và `documents#5` cùng tồn tại. Vị từ xoá cần hai thành phần; trước đây thành
phần thứ hai là khoá `entity` trong payload, nay là `doc_type`.

Phép thay đó CHỈ đúng khi ba tập giá trị doc_type RỜI NHAU. Mất tính rời nhau thì xoá một
tài liệu sẽ cuốn theo point của dự án cùng số id — im lặng, không lỗi, không log, và không
có test nào khác trong repo phát hiện được.

Cách nó hỏng trong thực tế: ai đó thêm một loại tài liệu tên `tong_quan` (nghe rất hợp lý
cho một tài liệu "tổng quan dự án"), và từ lúc đó mọi lần xoá tài liệu đó xoá luôn chunk
tổng quan của dự án.
"""

from portal.modules.kb.contracts import DOC_TYPE_KB_FILE, TITLE_PREFIXES, doc_type_of
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE


def _doc_types_cua_documents() -> set[str]:
    """Mọi giá trị `doc_type` mà bảng `documents` sinh ra được.

    Đọc từ `TITLE_PREFIXES` (nguồn sự thật của tiền tố tiêu đề) cộng giá trị rơi-về mà
    `doc_type_of` trả khi tiêu đề không có tiền tố nào.
    """
    return set(TITLE_PREFIXES.values()) | {doc_type_of({"title": "Một tiêu đề tự do"})}


def test_doc_type_cua_ba_bang_roi_nhau():
    cua_documents = _doc_types_cua_documents()
    theo_bang = {s.table: {s.doc_type} for s in REAL_ESTATE.embed_sources if s.table != "documents"}
    theo_bang["documents"] = cua_documents

    # Kho «Tài liệu tra cứu» (kb_files) là nguồn thứ TƯ ghi vào <slug>_documents
    # (spec 2026-08-20). Vị từ xoá của nó cũng là doc_type — mất tính rời nhau
    # thì xoá một tệp tra cứu cuốn theo point của bảng khác cùng record_id.
    theo_bang["kb_files"] = {DOC_TYPE_KB_FILE}

    for bang, tap in theo_bang.items():
        for bang_khac, tap_khac in theo_bang.items():
            if bang >= bang_khac:
                continue
            giao = tap & tap_khac
            assert not giao, (
                f"{bang!r} và {bang_khac!r} dùng chung doc_type {sorted(giao)} — vị từ xoá "
                "`record_id + doc_type` không còn phân biệt được hai bảng, và xoá một bên "
                "sẽ cuốn theo point của bên kia. Xem docs/contracts/payload-qdrant.md §6."
            )


def test_moi_bang_khai_it_nhat_mot_doc_type():
    """Một bảng không có doc_type nào là một bảng mà vị từ xoá chỉ còn `record_id`."""
    for s in REAL_ESTATE.embed_sources:
        assert s.doc_type, f"{s.table!r} không khai doc_type"
    assert _doc_types_cua_documents(), "documents không sinh được doc_type nào"


def test_doc_type_khong_rong_va_khong_trung_trong_chinh_documents():
    """Hai tiền tố tiêu đề khác nhau ra cùng một doc_type nghĩa là đổi loại tài liệu từ
    cái này sang cái kia KHÔNG sinh point mới — nên nhánh dọn point loại cũ không chạy."""
    gia_tri = list(TITLE_PREFIXES.values())
    assert len(gia_tri) == len(set(gia_tri)), f"tiền tố trùng doc_type: {gia_tri}"
    assert all(v for v in gia_tri)
