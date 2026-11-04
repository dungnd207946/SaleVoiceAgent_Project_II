"""Mặt tiền module promotions: DTO khuyến mãi + đối tượng áp dụng."""

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from portal.core.crud import CamelIn
from portal.core.dto import CamelOut

PromoType = Literal[
    "discount_amount",
    "discount_percent",
    "voucher",
    "gift_product",
    "payment_discount",
    "trade_in_bonus",
    "bundle_discount",
    "other",
]
Channel = Literal["all", "online", "store"]

# promo_type → cột giá trị BẮT BUỘC (chép các CHECK của bảng promotions).
COT_BAT_BUOC: dict[str, str] = {
    "discount_amount": "discount_vnd",
    "discount_percent": "discount_percent",
    "voucher": "voucher_value_vnd",
    "gift_product": "gift_product_id",
}


class PromotionIn(CamelIn):
    code: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=300)
    description: str | None = None
    promo_type: PromoType
    discount_vnd: int | None = Field(default=None, gt=0)
    discount_percent: float | None = Field(default=None, gt=0, le=100)
    max_discount_vnd: int | None = Field(default=None, gt=0)
    voucher_value_vnd: int | None = Field(default=None, gt=0)
    voucher_scope: str | None = None
    gift_product_id: int | None = None
    payment_method: str | None = None
    choice_group: str | None = None
    is_stackable: bool = True
    excludes_installment_0: bool = False
    channel: Channel = "all"
    priority: int = 0
    terms: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def _khop_check_db(self) -> Self:
        """Báo sớm, chỉ ở POST. PATCH (model sinh bởi `ban_sua`) không mang validator này —
        ở đó DB CHECK là chốt chặn (422 CHECK_FAILED)."""
        cot = COT_BAT_BUOC.get(self.promo_type)
        if cot and getattr(self, cot) is None:
            raise ValueError(f"promoType={self.promo_type} bắt buộc có {cot}")
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("endsAt phải sau startsAt")
        return self


class PromotionOut(CamelOut):
    id: int
    code: str | None
    name: str
    description: str | None
    promo_type: PromoType
    discount_vnd: int | None
    discount_percent: float | None
    max_discount_vnd: int | None
    voucher_value_vnd: int | None
    voucher_scope: str | None
    gift_product_id: int | None
    payment_method: str | None
    choice_group: str | None
    is_stackable: bool
    excludes_installment_0: bool
    channel: Channel
    priority: int
    terms: str | None
    starts_at: datetime
    ends_at: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


AppliesVia = Literal["variant", "product", "brand", "category"]


class PromotionApDungOut(PromotionOut):
    """KM đang chạy kèm LÝ DO áp dụng — FE cần biết KM chỉ áp cho vài SKU (`variantIds`)
    để hiện đúng khi khách đổi cấu hình/màu."""

    gift_product_name: str | None
    applies_via: list[AppliesVia]
    variant_ids: list[int] | None  # None = áp cho mọi SKU của sản phẩm


class NhomChonOut(CamelOut):
    choice_group: str
    promotion_ids: list[int]


class KhuyenMaiApDungOut(CamelOut):
    product_id: int
    variant_id: int | None
    promotions: list[PromotionApDungOut]
    choice_groups: list[NhomChonOut]  # «Chọn 1 trong các quà»: khách chọn đúng 1 KM mỗi nhóm
