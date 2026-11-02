"""Sổ lĩnh vực — hằng của sản phẩm, KHÔNG cho tenant tự thêm/xoá.

Khớp quyết định phía FE (docstring `QuanLyLinhVuc.tsx`): sổ hôm nay là hai
hằng số (vertical #1 đã có, #2 chưa), một nút «Thêm lĩnh vực» sẽ hứa rằng
thêm xong agent biết làm gì đó, trong khi kỹ năng và dữ liệu của một vertical
mới là việc của backend.

VÌ SAO CÓ ÁNH XẠ ma ↔ vertical: FE nav dùng `bds`/`taichinh`
(`NavSegment.linhVuc`, hợp đồng đã đóng băng 2026-08-08), còn CHECK của
`control.tenant_verticals` (0002) chỉ nhận `'realestate'`/`'finance'`. Đổi
phía nào cũng đắt hơn bảng ánh xạ hai dòng này.
"""

from typing import NamedTuple

from portal.modules.config.contracts import TEN_KY_NANG


class LinhVuc(NamedTuple):
    ma: str
    """Khoá FE — khớp `NavSegment.linhVuc` bên repo frontend. Đổi là vỡ hợp đồng."""
    ten: str
    vertical: str
    """Giá trị cột `control.tenant_verticals.vertical` — phải nằm trong CHECK của 0002."""


SO_LINH_VUC: tuple[LinhVuc, ...] = (
    LinhVuc("bds", "Bất động sản", "realestate"),
    LinhVuc("taichinh", "Tài chính", "finance"),
)
"""Thứ tự CỐ ĐỊNH — GET trả đúng thứ tự này, FE render theo mảng."""

KY_NANG_CHUNG: frozenset[str] = frozenset({"kb_search", "update_customer", "escalate"})
"""3 kỹ năng không thuộc lĩnh vực nào — tra tài liệu, cập nhật khách, chuyển
người thật là việc agent làm bất kể đang nói về gì. FE khai Y HỆT ở
`features/agent/kyNang.ts` (`KY_NANG_CHUNG`); backend chưa có khái niệm này
nên khai ở đây, test đối chiếu ⊆ TEN_KY_NANG."""


def theo_ma(ma: str) -> LinhVuc | None:
    """`None` = ma lạ — router trả 404, không đoán."""
    return next((lv for lv in SO_LINH_VUC if lv.ma == ma), None)


def so_ky_nang(lv: LinhVuc) -> int:
    """Số kỹ năng thuộc lĩnh vực — SUY từ sổ thật, không hằng chép tay
    (bài học overview 2026-08-14: mẫu số viết cứng sai ngay ngày sổ đổi).

    ⚠️ Công thức bds = «mọi kỹ năng không-chung» chỉ đúng khi cả sổ ngoài
    phần chung đều là BĐS — hôm nay đúng (9/9), và FE đang suy Y HỆT
    (`KY_NANG_TAB_BDS = MUOI_HAI_KY_NANG − chung`). Ngày sổ kỹ năng mọc kỹ
    năng finance, công thức này gán nhầm nó cho bds — lúc đó phải chuyển sổ
    sang gắn nhãn lĩnh vực từng kỹ năng (cả đây lẫn FE).
    """
    if lv.ma == "bds":
        return len(TEN_KY_NANG) - len(KY_NANG_CHUNG)
    return 0
