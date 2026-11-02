"""Mặt tiền của module nhan_vat — hình dạng FE dùng ở `features/platform/nhanVat.ts`.

Field camelCase y nguyên như FE. URL tệp (poster, video xem trước) là đường dẫn API
`/api/v1/nhan-vat/...` — tệp nằm trong kho riêng của tenant, đi qua phiên đăng nhập.
"""

from pydantic import BaseModel, ConfigDict, Field


class LoiNhanVat(BaseModel):
    ma: str
    huongDan: str
    """Câu hướng dẫn khách tự sửa (dịch từ `ma`)."""
    chiTiet: str | None = None


class XemTruocOut(BaseModel):
    cau: str
    url: str


class NhanVatOut(BaseModel):
    id: str
    ten: str
    nguon: str
    """`video` (khách upload) | `anh` (sinh video từ ảnh bằng API)."""
    trangThai: str
    """`tao_video` | `dung` | `xem_truoc` | `san_sang` | `loi`."""
    buoc: str | None
    tienDo: float
    """0–1 — tiến độ ƯỚC LƯỢNG toàn bộ quy trình (cho thanh tiến độ)."""
    loi: LoiNhanVat | None
    dangDung: bool
    avatarId: str | None
    """Id nhân vật trên service lip sync — CHỈ có khi `san_sang` (FE gắn vào URL WebSocket)."""
    posterUrl: str | None
    xemTruoc: list[XemTruocOut]
    videoUrl: str | None = None
    """Video NGUỒN của nhân vật (khách upload, hoặc video AI sinh từ ảnh) — có ngay khi video
    về kho, kể cả lúc nhân vật còn đang dựng. Để khách xem AI đã tạo ra gì."""
    videoTayUrl: str | None = None
    taoLuc: str


class DanhSachNhanVatOut(BaseModel):
    nhanVat: list[NhanVatOut]
    dangDung: str | None
    """Id nhân vật đang dùng; None = người dẫn mặc định."""
    taoTuAnh: bool
    """Đã cấu hình nhà cung cấp sinh video từ ảnh (`NHAN_VAT_VIDEO_PROVIDER`)."""
    nhaCungCap: str | None
    toiDa: int
    cauDemo: list[str]


class DangDungOut(BaseModel):
    """Nhân vật tab Voice dùng. `id` None = người dẫn mặc định."""

    id: str | None
    ten: str | None
    avatarId: str | None
    posterUrl: str | None


class ChonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None
    """None = quay về người dẫn mặc định."""


class XemTruocIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cau: str = Field(min_length=1, max_length=300)
