"""Hợp đồng của M7 — hằng số phân trang và DTO. Không logic, không SQL.

Field DTO đặt camelCase không dấu vì chúng là hợp đồng với FE (`features/ops/api.ts`
chép tay theo tệp này). Đổi tên ở đây mà không đổi bên kia thì màn hiện `undefined`
chứ không nổ — nên đổi thì đổi cùng commit.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from portal.core.dto import CamelOut

__all__ = [
    "GIOI_HAN_TRANG",
    "PHONE_TRONG",
    "TRANG_CA",
    "TRICH_SO_LUOT",
    "TRANG_MAC_DINH",
    "CaOut",
    "ChanDungOut",
    "ChiTietPhienOut",
    "GhiChuOut",
    "KhachOut",
    "LuotOut",
    "MucDuAn",
    "NhanCaIn",
    "PhienOut",
    "TrangCa",
    "TrangKhach",
    "SO_NGAY",
    "KENH_CHAT",
    "KENH_VOICE",
    "MocOut",
    "NgayOut",
    "KenhOut",
    "HoiThoaiOut",
    "ChuyenSaleOut",
    "DanhGiaOut",
    "MucKienThucOut",
    "KienThucOut",
    "OverviewOut",
]

TRANG_MAC_DINH = 50
GIOI_HAN_TRANG = 200

TRANG_CA = 10

TRICH_SO_LUOT = 6
"""Số lượt thoại trích quanh mốc chuyển sale — khoảng ba lượt trao đổi. Đủ dựng
lại bối cảnh mà không biến panel chi tiết thành một transcript thứ hai."""

PHONE_TRONG = "_"


class KhachOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    phone: str
    ten: str | None
    avatar: str | None
    """Data URI SVG DiceBear seed bằng `ten` (`core/avatar.py`) — NULL khi chưa có
    tên: FE giữ icon người trung tính, không đoán một avatar không có căn cứ."""
    soPhien: int
    ganNhat: datetime
    dauTien: datetime
    daChuyen: bool
    summaryCuoi: str | None
    duAn: str | None
    tenDuAn: str | None
    leadStage: str | None = None
    """Lead MỚI NHẤT của khách (lead của phiên mới nhất có lead — spec §2). NULL = chưa
    phân loại. Chuỗi thô agent ghi; không `Literal` để một bậc mới không làm 500."""
    leadScore: int | None = None
    audience: str | None = None


class TrangKhach(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[KhachOut]
    tongKhach: int
    tongPhien: int


class PhienOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    sessionId: str
    ten: str | None
    avatar: str | None
    """Data URI SVG DiceBear seed bằng `ten` (`core/avatar.py`) — NULL khi chưa có
    tên: FE giữ icon người trung tính, không đoán một avatar không có căn cứ."""
    batDau: datetime | None
    ketThuc: datetime | None
    soLuot: int
    tinNhanDau: str | None
    summary: str | None
    duAn: str | None
    tenDuAn: str | None
    daChuyen: bool
    runningVersion: int | None
    source: str | None
    phone: str | None
    leadStage: str | None = None
    """Lead của CHÍNH phiên này (hàng ca mới nhất có stage). NULL = phiên không chuyển sale."""
    leadScore: int | None = None
    audience: str | None = None


class ChanDungOut(BaseModel):
    """Chân dung khách — những gì AGENT đã khai thác về một số, gộp qua mọi phiên."""

    model_config = ConfigDict(frozen=True)

    hoSo: dict
    """`contacts.profile` NGUYÊN VĂN (agent `update_customer` ghi, gộp nông theo khoá).
    FE chọn khoá nào hiện — không lọc ở đây để một trường agent mới thêm không phải đợi
    một bản backend. `{}` = agent chưa ghi gì."""
    ghiNho: str | None
    """`contacts.snapshot` — tóm tắt LLM gộp sau mỗi cuộc gọi. Chuỗi rỗng ⇒ NULL."""
    tinHieu: list[str]
    """`escalations.lead_signals` của lead hiện tại (mã như `co_ngan_sach`)."""
    capNhatLuc: datetime | None


class LuotOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    role: str
    content: str
    taoLuc: datetime
    meta: dict


class CaOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    sessionId: str
    phone: str | None
    ten: str | None
    avatar: str | None
    """Data URI SVG DiceBear seed bằng `ten` (`core/avatar.py`) — NULL khi chưa có
    tên: FE giữ icon người trung tính, không đoán một avatar không có căn cứ."""
    duAn: str | None
    tenDuAn: str | None
    toolThieuDuLieu: str | None
    summary: str | None
    summaryLuc: datetime | None
    messageSeq: int | None
    trangThai: str
    nguoiXuLy: str | None
    xuLyLuc: datetime | None
    ghiChu: str | None
    kenh: str | None
    soLuot: int
    taoLuc: datetime


class MucDuAn(BaseModel):
    """Một mục của dropdown lọc dự án: `ma` là giá trị gửi lên, `ten` là nhãn.

    KHÔNG phải `list[str]` như trước: mã dự án của tenant thật là UUID, nên một
    dropdown chỉ có mã bắt người trực chọn giữa những dòng không đọc được.
    """

    model_config = ConfigDict(frozen=True)

    ma: str
    ten: str | None


class TrangCa(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[CaOut]
    tongCa: int
    duAnCo: list[MucDuAn]


class GhiChuOut(CamelOut):
    model_config = ConfigDict(frozen=True)

    id: int
    noi_dung: str
    nguoi: str | None
    luc: datetime


class NhanCaIn(BaseModel):
    trangThai: Literal["new", "contacted", "done"]
    ghiChu: str | None = Field(default=None, max_length=2000)


class ChiTietPhienOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    phien: PhienOut
    luot: list[LuotOut]
    skillCalls: list


# ── Overview — màn /dashboard ───────────────────────────────────────────────

SO_NGAY = 7
"""Cửa sổ của ô Hội thoại. Nhãn trục x là 7 ngày, con số delta cũng đo trên
cửa sổ này — hai thứ lệch cửa sổ nhau là hai câu chuyện về cùng một biểu đồ."""

KENH_CHAT = "chat"
KENH_VOICE = "voice"
"""Hai giá trị `conversations.source` mà agent thật ghi (`base_session`/
`telephony` → `voice`, `text_chat` → `chat`; xem `components/ui/ChipKenh.tsx`).
Cột là `text` KHÔNG CHECK có chủ ý — kênh mới có thể tới bất cứ lúc nào — nên
mọi giá trị khác (và NULL) rơi vào `khac`, và `theoKenh` giữ nguyên văn nguồn
thô để chú thích gọi đúng tên nó."""


class MocOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    tuNgay: date
    tinhDen: date


class NgayOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    ngay: date
    chat: int
    voice: int
    khac: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tong(self) -> int:
        """TÍNH, không nhận từ ngoài — xem test_ngay_out_tu_tinh_tong."""
        return self.chat + self.voice + self.khac


class KenhOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    kenh: str | None
    n: int


class HoiThoaiOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    tong: int
    truoc: int
    theoNgay: list[NgayOut]
    theoKenh: list[KenhOut]


class ChuyenSaleOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    chuyen: int
    tuXuLy: int


class DanhGiaOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    trungBinh: float
    truoc: float | None
    tong: int
    theoSao: dict[str, int]


class MucKienThucOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    khoa: str
    thay: int
    tong: int


class KienThucOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    muc: list[MucKienThucOut]


class OverviewOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    moc: MocOut
    hoiThoai: HoiThoaiOut
    chuyenSale: ChuyenSaleOut
    danhGia: DanhGiaOut
    kienThuc: KienThucOut
