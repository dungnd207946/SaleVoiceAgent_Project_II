"""Mặt tiền module customers: khách hàng (định danh bằng SĐT) và giữ hàng/hẹn lịch."""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from portal.core.crud import CamelIn
from portal.core.dto import CamelOut

_SDT_VN = re.compile(r"^0[1-9]\d{8}$")


def chuan_hoa_sdt(raw: str) -> str:
    """'+84 912.345.678' → '0912345678'. Ném ValueError nếu không phải di động VN 10 số.

    SĐT là khoá UNIQUE: không chuẩn hoá thì cùng một người gõ hai kiểu thành hai khách.
    """
    s = re.sub(r"[\s.\-]", "", raw)
    if s.startswith("+84"):
        s = "0" + s[3:]
    if not _SDT_VN.fullmatch(s):
        raise ValueError("Số điện thoại phải là di động Việt Nam 10 số, bắt đầu bằng 0")
    return s


SoDienThoai = Annotated[str, AfterValidator(chuan_hoa_sdt)]


class CustomerIn(CamelIn):
    phone: SoDienThoai | None = None
    full_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    province_code: str | None = None
    budget_min_vnd: int | None = Field(default=None, ge=0)
    budget_max_vnd: int | None = Field(default=None, ge=0)
    preferred_brand_id: int | None = None
    needs: str | None = None
    notes: str | None = None


class CustomerOut(CamelOut):
    id: int
    phone: str | None
    full_name: str | None
    email: str | None
    province_code: str | None
    budget_min_vnd: int | None
    budget_max_vnd: int | None
    preferred_brand_id: int | None
    needs: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


ReservationType = Literal["hold_stock", "store_visit", "installment_consult", "callback"]
ReservationStatus = Literal["pending", "confirmed", "completed", "cancelled", "expired"]
Channel = Literal["voice", "chat", "web", "store"]

# Máy trạng thái: trạng thái cuối (completed/cancelled/expired) không đi đâu nữa.
CHUYEN_HOP_LE: dict[str, frozenset[str]] = {
    "pending": frozenset({"confirmed", "cancelled", "expired"}),
    "confirmed": frozenset({"completed", "cancelled", "expired"}),
}


class ReservationIn(CamelIn):
    """Luôn tạo ở `pending`. `hold_stock` bắt buộc variant+store (CHECK DB) và trừ tồn khả dụng."""

    customer_id: int
    reservation_type: ReservationType
    variant_id: int | None = None
    store_id: int | None = None
    quantity: int = Field(default=1, ge=1, le=32767)
    scheduled_at: datetime | None = None
    expires_at: datetime | None = None
    channel: Channel = "chat"
    note: str | None = None


class ReservationPatch(CamelIn):
    status: ReservationStatus | None = None
    note: str | None = None
    scheduled_at: datetime | None = None


class ReservationOut(CamelOut):
    id: int
    customer_id: int
    reservation_type: ReservationType
    variant_id: int | None
    store_id: int | None
    quantity: int
    scheduled_at: datetime | None
    expires_at: datetime | None
    status: ReservationStatus
    channel: Channel
    note: str | None
    created_at: datetime
    updated_at: datetime


class ExpireOut(CamelOut):
    expired: int
