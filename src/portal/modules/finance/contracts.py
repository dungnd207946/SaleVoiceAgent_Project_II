"""Mặt tiền module finance: đối tác tài chính · gói trả góp · báo giá trả góp."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from portal.core.crud import CamelIn
from portal.core.dto import CamelOut

PartnerType = Literal["finance_company", "credit_card", "bnpl"]


class FinancePartnerIn(CamelIn):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    partner_type: PartnerType
    hotline: str | None = None
    late_fee_note: str | None = None
    is_active: bool = True


class FinancePartnerOut(CamelOut):
    id: int
    code: str
    name: str
    partner_type: PartnerType
    hotline: str | None
    late_fee_note: str | None
    is_active: bool


class InstallmentPlanIn(CamelIn):
    partner_id: int
    name: str = Field(min_length=1, max_length=300)
    tenor_months: int = Field(gt=0, le=120)
    interest_rate_monthly: float = Field(default=0, ge=0, lt=100)  # % / tháng
    min_down_payment_percent: float = Field(default=0, ge=0, le=100)
    fixed_fee_vnd: int = Field(default=0, ge=0)
    min_price_vnd: int | None = Field(default=None, ge=0)
    max_price_vnd: int | None = Field(default=None, ge=0)
    min_age: int | None = 18
    max_age: int | None = 60
    required_docs: str | None = None
    conditions: str | None = None
    starts_at: datetime | None = None  # bỏ trống ⇒ DB mặc định now()
    ends_at: datetime | None = None
    is_active: bool = True


class InstallmentPlanOut(CamelOut):
    id: int
    partner_id: int
    name: str
    tenor_months: int
    interest_rate_monthly: float
    min_down_payment_percent: float
    fixed_fee_vnd: int
    min_price_vnd: int | None
    max_price_vnd: int | None
    min_age: int | None
    max_age: int | None
    required_docs: str | None
    conditions: str | None
    starts_at: datetime
    ends_at: datetime | None
    is_active: bool


class BaoGiaTraGopOut(CamelOut):
    """Ước tính — công ty tài chính quyết hợp đồng thật. Mọi số tiền là int VND."""

    plan_id: int
    plan_name: str
    partner_id: int
    partner_name: str
    variant_id: int
    tenor_months: int
    interest_rate_monthly: float
    price_vnd: int
    down_payment_percent: float
    down_payment_vnd: int
    loan_vnd: int
    monthly_payment_vnd: int
    fixed_fee_vnd: int
    total_payment_vnd: int
    extra_cost_vnd: int
