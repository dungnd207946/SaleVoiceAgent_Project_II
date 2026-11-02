"""Trạng thái HIỆU LỰC đi vào payload point. Hàm thuần.

Ở module riêng chứ không nội tuyến trong `rag.py`/`media.py`: hai client cùng ghi khoá
`status` và mệnh đề lọc của agent so bằng đúng một giá trị. Hai bản sao của luật này là
hai chỗ để lệch nhau, và lệch ở đây nghĩa là nội dung nháp của một trong hai collection
tới tay khách — không lỗi, không log.
"""

_PUBLISHED = "published"
_ARCHIVED = "archived"
_DRAFT = "draft"


def status_hieu_luc(cua_no: str, cua_cha: str) -> str:
    """`published` CHỈ KHI cả bản ghi và dự án cha đều published.

    Suy ở phía GHI, không ghi hai cột thô rồi để agent tự AND: một point của phân khu, tài
    liệu hay ảnh KHÔNG BIẾT GÌ về hàng dự án, nên agent không có dữ liệu để kiểm luật này.
    Ghi cả hai cột thì agent AND được, nhưng đó là 2 khoá payload thay vì 1.

    Rỗng ⇒ coi là `published`. Cố ý: giữ hành vi của trước khi có khoá này, và quan trọng
    hơn là một đường ghi chưa được cập nhật sẽ KHÔNG âm thầm ẩn dữ liệu — nó vẫn hiện như
    cũ, và đó là hỏng-thấy-được thay vì hỏng-im-lặng.

    ⚠ Giá trị trả về có thể LỆCH với cột `status` trong Postgres: một ảnh `published` dưới
    một dự án `draft` ra `draft`. Đó là đúng — xem docs/contracts/payload-qdrant.md §4.
    """
    a = cua_no or _PUBLISHED
    b = cua_cha or _PUBLISHED
    if a == _PUBLISHED and b == _PUBLISHED:
        return _PUBLISHED
    return _ARCHIVED if _ARCHIVED in (a, b) else _DRAFT
