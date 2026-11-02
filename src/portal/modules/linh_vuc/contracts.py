"""Mặt tiền của module linh_vuc — module khác chỉ được import file này.

`LinhVucOut` chép ĐÚNG hình dạng FE khai ở `features/agent/linhVuc.ts`
(hợp đồng FE định trước 2026-08-08, đóng băng): tên field camelCase y nguyên,
GET trả mảng TRẦN các object này, PATCH trả MỘT object.
"""

from pydantic import BaseModel, ConfigDict


class LinhVucOut(BaseModel):
    ma: str
    ten: str
    bat: bool
    soKyNang: int
    """Để màn quản lý nói rõ tắt đi là mất gì."""
    coDuLieu: bool
    """`False` ⇒ bật lên agent cũng chưa trả lời được — FE hiện «chưa có dữ
    liệu để agent tra»."""


class DatLinhVucIn(BaseModel):
    """Body của PATCH. `extra="forbid"` — khoá lạ là 422 ngay, cùng nếp
    `DatTrangThaiKhoaIn` của enrollment."""

    model_config = ConfigDict(extra="forbid")

    bat: bool
