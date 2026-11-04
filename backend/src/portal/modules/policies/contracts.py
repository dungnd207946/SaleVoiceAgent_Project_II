"""Mặt tiền module policies: chính sách (bảo hành, đổi trả…) · gói dịch vụ bán thêm."""

from datetime import date
from datetime import datetime as dt
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from portal.core.crud import CamelIn
from portal.core.dto import CamelOut

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=120)]

PolicyType = Literal[
    "warranty",
    "return_exchange",
    "installment",
    "delivery",
    "payment",
    "unboxing",
    "trade_in",
    "privacy",
    "other",
]
ServiceType = Literal["extended_warranty", "drop_damage", "one_to_one_exchange", "insurance", "other"]


class PolicyIn(CamelIn):
    policy_type: PolicyType
    slug: Slug
    title: str = Field(min_length=1, max_length=300)
    summary: str | None = None
    content_md: str = Field(min_length=1)
    brand_id: int | None = None  # NULL = mọi hãng
    category_id: int | None = None  # NULL = mọi ngành hàng
    effective_from: date | None = None  # bỏ trống ⇒ DB mặc định current_date
    effective_to: date | None = None
    is_active: bool = True


class PolicyOut(CamelOut):
    id: int
    policy_type: PolicyType
    slug: str
    title: str
    summary: str | None
    content_md: str
    brand_id: int | None
    category_id: int | None
    effective_from: date
    effective_to: date | None
    is_active: bool
    created_at: dt
    updated_at: dt


class ServicePackageIn(CamelIn):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=300)
    service_type: ServiceType
    duration_months: int = Field(gt=0, le=120)
    price_vnd: int | None = Field(default=None, ge=0)
    price_percent: float | None = Field(default=None, gt=0, le=100)  # % giá máy
    min_product_price_vnd: int | None = Field(default=None, ge=0)
    max_product_price_vnd: int | None = Field(default=None, ge=0)
    brand_id: int | None = None
    category_id: int | None = None
    terms_md: str | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def _mot_kieu_gia(self) -> Self:
        """Chép CHECK `num_nonnulls(price_vnd, price_percent) = 1` để báo sớm ở POST."""
        if (self.price_vnd is None) == (self.price_percent is None):
            raise ValueError("Cần đúng một trong priceVnd | pricePercent")
        return self


class ServicePackageOut(CamelOut):
    id: int
    code: str
    name: str
    service_type: ServiceType
    duration_months: int
    price_vnd: int | None
    price_percent: float | None
    min_product_price_vnd: int | None
    max_product_price_vnd: int | None
    brand_id: int | None
    category_id: int | None
    terms_md: str | None
    is_active: bool


class BaoGiaGoiDichVuOut(ServicePackageOut):
    product_price_vnd: int
    quoted_price_vnd: int  # price_vnd, hoặc round(giá máy × % / 100)
