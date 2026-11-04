"""Mặt tiền module stores: DTO tỉnh/thành, cửa hàng, tồn kho, độ phủ hàng theo cửa hàng."""

from datetime import datetime, time
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from portal.core.crud import CamelIn
from portal.core.dto import CamelOut

MaTinh = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,20}$")]
StoreType = Literal["store", "warehouse"]


class ProvinceIn(CamelIn):
    code: MaTinh
    name: str = Field(min_length=1, max_length=120)


class ProvincePatch(CamelIn):
    """Không cho đổi `code`: là PK text, cửa hàng/khách tham chiếu tới."""

    name: str = Field(min_length=1, max_length=120)


class ProvinceOut(CamelOut):
    code: str
    name: str


class StoreIn(CamelIn):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    store_type: StoreType = "store"
    address: str = Field(min_length=1)
    ward: str | None = None
    province_code: MaTinh
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    phone: str | None = None
    open_time: time | None = None
    close_time: time | None = None
    is_active: bool = True


class StoreOut(CamelOut):
    id: int
    code: str
    name: str
    store_type: StoreType
    address: str
    ward: str | None
    province_code: str
    latitude: float | None
    longitude: float | None
    phone: str | None
    open_time: time | None
    close_time: time | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InventorySet(CamelIn):
    """Đặt số tồn tuyệt đối (kiểm kê). `reserved_qty` giữ nguyên — do reservations quản."""

    store_id: int
    variant_id: int
    quantity: int = Field(ge=0)


class InventoryAdjust(CamelIn):
    """Nhập/xuất tương đối — cộng dồn nguyên tử, tránh mất cập nhật khi hai người cùng sửa."""

    store_id: int
    variant_id: int
    delta: int

    @field_validator("delta")
    @classmethod
    def _khac_khong(cls, v: int) -> int:
        if v == 0:
            raise ValueError("delta phải khác 0")
        return v


class InventoryOut(CamelOut):
    store_id: int
    store_name: str
    province_code: str
    variant_id: int
    sku: str
    product_name: str
    quantity: int
    reserved_qty: int
    qty_available: int
    updated_at: datetime


class StoreStock(CamelOut):
    store_id: int
    store_name: str
    address: str
    ward: str | None
    phone: str | None
    open_time: time | None
    close_time: time | None
    qty_available: int


class ProvinceStock(CamelOut):
    province_code: str
    province_name: str
    qty_available: int
    stores: list[StoreStock]


class AvailabilityOut(CamelOut):
    """Khối "còn hàng tại cửa hàng": gom theo tỉnh để FE hiện dropdown tỉnh → danh sách cửa hàng."""

    variant_id: int
    qty_available: int
    provinces: list[ProvinceStock]
