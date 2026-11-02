"""Hình dạng JSON của `/kb-web/*` — hợp đồng với màn «Dữ liệu ngoài» (`docs/contracts/kb-web.md`).

camelCase như các module khác; chữ hiển thị là việc của FE, ở đây chỉ mã (`nightly`/`weekly`/`rebuild`,
`http`/`browser`, `news`/`living`).
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["nightly", "weekly", "rebuild"]
FetchMode = Literal["http", "browser"]
Kind = Literal["news", "living"]
DayRule = Literal["d1", "d15", "first_sunday"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ─── job ─────────────────────────────────────────────────────────────────────


class JobOut(BaseModel):
    id: int
    loai: Literal["kbweb_run", "kbweb_project", "kbweb_probe"]
    mode: str
    duAn: str | None = None
    duAnTen: str | None = None
    url: str | None = None
    tinhTrangNguon: str | None = None
    """Lượt kiểm tra nguồn: ok|blocked|no_feed|timeout|private."""
    trangThai: str
    nguoi: str
    nguoiTen: str | None = None
    """Tên người bấm; None với lượt theo lịch."""
    taoLuc: datetime
    batDau: datetime | None = None
    ketThuc: datetime | None = None
    soLuong: int = 0
    thongDiep: str = ""
    chiPhi: Decimal | None = None
    """Tiền của lượt chạy (VND); None khi chưa ghi sổ hoặc người xem không có `billing.read`."""


# ─── tổng quan ───────────────────────────────────────────────────────────────


class OverviewOut(BaseModel):
    soDuAn: int
    soDuAnCoHoSo: int
    hoSoCuNhat: datetime | None
    baiBayNgay: int
    baiBaMuoiNgay: int
    soNguonBat: int
    groundingThang: int
    groundingTran: int
    trinhDuyetHomNay: int
    trinhDuyetTran: int
    dangChay: list[JobOut]
    loiGanDay: list[JobOut]
    lanKeTiep: datetime | None
    """Lượt theo lịch gần nhất sắp tới (bất kể nhịp nào)."""


# ─── nguồn ───────────────────────────────────────────────────────────────────


class NguonOut(BaseModel):
    id: int
    domain: str
    ten: str
    bat: bool
    macDinh: bool
    cheDo: FetchMode
    theoDoi: Kind
    baiBayNgay: int
    tinhTrang: str | None
    ghiChu: str
    thuLuc: datetime | None


class ThuNguonIn(_Strict):
    url: str = Field(min_length=3, max_length=500)


class NguonDeXuat(BaseModel):
    domain: str
    ten: str
    cheDo: FetchMode
    theoDoi: Kind
    rss: list[str] = []
    sitemapIndex: str = ""
    newsSitemaps: list[str] = []
    categoryPages: list[str] = []
    articlePattern: str = ""


class ThuNguonOut(BaseModel):
    trangThai: Literal["ok", "blocked", "no_feed", "timeout", "private"]
    ghiChu: str
    soBai: int
    soTrangThu: int
    soTrangDoc: int
    daCo: bool = False
    """Domain này đã có trong danh sách nguồn của workspace."""
    deXuat: NguonDeXuat | None = None


class ThemNguonIn(_Strict):
    """FE gửi lại `deXuat` của lượt thử (có thể sửa `ten`); `tinhTrang`/`ghiChu` của lượt thử đi kèm."""

    domain: str = Field(min_length=3, max_length=200)
    ten: str = Field(min_length=1, max_length=120)
    cheDo: FetchMode = "http"
    theoDoi: Kind = "news"
    rss: list[str] = []
    sitemapIndex: str = ""
    newsSitemaps: list[str] = []
    categoryPages: list[str] = []
    articlePattern: str = ""
    tinhTrang: Literal["ok", "no_feed"] | None = None
    ghiChu: str = ""


class SuaNguonIn(_Strict):
    bat: bool | None = None
    ten: str | None = Field(default=None, min_length=1, max_length=120)


# ─── chủ đề ──────────────────────────────────────────────────────────────────


class ChuDeOut(BaseModel):
    id: int
    code: str
    ten: str
    nhan: str
    moTa: str
    cauTim: list[str]
    tuKhoa: list[str]
    bat: bool
    macDinh: bool
    vaoHoSo: bool
    thuTu: int


class SoanChuDeIn(_Strict):
    ten: str = Field(min_length=1, max_length=80)
    moTa: str = Field(default="", max_length=1000)


class SoanChuDeOut(BaseModel):
    cauTim: list[str]
    tuKhoa: list[str]


class ThemChuDeIn(_Strict):
    ten: str = Field(min_length=1, max_length=80)
    moTa: str = Field(default="", max_length=1000)
    cauTim: list[str] = Field(min_length=1, max_length=4)
    tuKhoa: list[str] = Field(default=[], max_length=12)


class SuaChuDeIn(_Strict):
    bat: bool | None = None
    ten: str | None = Field(default=None, min_length=1, max_length=80)
    moTa: str | None = Field(default=None, max_length=1000)
    cauTim: list[str] | None = Field(default=None, min_length=1, max_length=4)
    tuKhoa: list[str] | None = Field(default=None, max_length=12)


# ─── lịch ────────────────────────────────────────────────────────────────────


class LichOut(BaseModel):
    mode: Mode
    bat: bool
    gio: str
    """`HH:MM` giờ VN."""
    ngayTrongTuan: list[int] = []
    """0 = thứ Hai … 6 = Chủ nhật; chỉ `weekly`."""
    soThang: int | None = None
    """Viết lại mỗi N tháng (1..12); chỉ `rebuild`."""
    ngayTrongChuKy: DayRule | None = None
    latCat: int = 1
    lanGanNhat: datetime | None = None
    lanKeTiep: datetime | None = None


class GioiHanOut(BaseModel):
    groundingThang: int
    trinhDuyetNgay: int
    ngayHoi: int


class LichTongOut(BaseModel):
    lich: list[LichOut]
    gioiHan: GioiHanOut


class LichIn(_Strict):
    mode: Mode
    bat: bool
    gio: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    ngayTrongTuan: list[int] = Field(default=[], max_length=7)
    soThang: int | None = Field(default=None, ge=1, le=12)
    ngayTrongChuKy: DayRule | None = None
    latCat: int = Field(default=1, ge=1, le=7)


class GioiHanIn(_Strict):
    groundingThang: int = Field(ge=0, le=100_000)
    trinhDuyetNgay: int = Field(ge=0, le=10_000)
    ngayHoi: int = Field(ge=1, le=365)


class LichTongIn(_Strict):
    lich: list[LichIn] = Field(min_length=1, max_length=3)
    gioiHan: GioiHanIn | None = None


# ─── dự án ───────────────────────────────────────────────────────────────────


class DuAnOut(BaseModel):
    code: str
    ten: str
    soMuc: int
    soChuDe: int
    capNhatLuc: datetime | None
    dangChay: bool
    viecGanNhat: JobOut | None = None


class NguonBaiOut(BaseModel):
    url: str
    ten: str
    ngay: datetime | None


class MucHoSoOut(BaseModel):
    nhan: str
    ten: str
    noiDung: str
    nguon: list[NguonBaiOut]
    capNhatLuc: datetime | None
    an: bool


class BaiOut(BaseModel):
    url: str
    tieuDe: str
    domain: str
    ngayDang: datetime | None
    thuLuc: datetime | None
    loai: bool
    """Người dùng đã loại bài này khỏi hồ sơ."""


class ChiTietDuAnOut(BaseModel):
    code: str
    ten: str
    muc: list[MucHoSoOut]
    mucAn: list[str]
    bai: list[BaiOut]
    dangChay: bool


class LamMoiIn(_Strict):
    mode: Literal["init", "rebuild"] = "init"


class MucIn(_Strict):
    nhan: str = Field(min_length=1, max_length=120)
    an: bool


class BaiIn(_Strict):
    url: str = Field(min_length=8, max_length=2000)
    loai: bool
