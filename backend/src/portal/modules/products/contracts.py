"""Mặt tiền module products: DTO quản trị (sản phẩm → màu → SKU, thông số, media, FAQ, liên quan)
và DTO đọc cho cửa hàng (thẻ sản phẩm, trang chi tiết, so sánh).

Cột `numeric` của DB: vào là `Decimal` (giữ đúng 0.048 GB, so khớp `= ANY` không lệch số thực),
ra là `float` (Decimal serialize thành chuỗi — FE phải parse lại). Tiền là `int` VND.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from portal.core.crud import CamelIn
from portal.core.dto import CamelOut

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=160)]
Tien = Annotated[int, Field(gt=0)]

# Literal mirror đúng danh sách CHECK trong schema — sai giá trị bị chặn 422 trước khi tới DB.
PhoneType = Literal["smartphone", "foldable", "feature_phone"]
ProductStatus = Literal["draft", "coming_soon", "selling", "discontinued"]
Condition = Literal["new", "used", "refurbished"]
SaleStatus = Literal["in_stock", "out_of_stock", "pre_order", "coming_soon", "discontinued"]
MediaType = Literal["image", "video", "image_360", "thumbnail"]
RelationType = Literal["accessory", "bought_together", "similar", "newer_model", "older_model"]
OsName = Literal["iOS", "Android", "HarmonyOS", "Khác"]
ResolutionClass = Literal["QQVGA", "QVGA", "HD+", "Full HD+", "1.5K", "1.5K+", "2K+", "QXGA+", "Retina"]
NetworkGen = Literal["2G", "3G", "4G", "5G"]
SortKey = Literal["featured", "newest", "best_selling", "discount", "price_asc", "price_desc"]


# ---------------------------------------------------------------------------
# Quản trị: sản phẩm
# ---------------------------------------------------------------------------
class ProductIn(CamelIn):
    """Không có rating/sold: đó là số cache do job tổng hợp ghi, admin sửa tay là lệch nguồn."""

    category_id: int
    brand_id: int
    series_id: int | None = None
    slug: Slug
    name: str = Field(min_length=1, max_length=200)
    model_code: str | None = None
    phone_type: PhoneType | None = None
    release_date: date | None = None
    short_description: str | None = None
    highlights_md: str | None = None
    in_box: str | None = None
    warranty_months: int = Field(default=12, ge=0, le=600)
    warranty_note: str | None = None
    status: ProductStatus = "draft"
    is_featured: bool = False


class ProductOut(CamelOut):
    id: int
    category_id: int
    brand_id: int
    series_id: int | None
    slug: str
    name: str
    model_code: str | None
    phone_type: PhoneType | None
    release_date: date | None
    short_description: str | None
    highlights_md: str | None
    in_box: str | None
    warranty_months: int
    warranty_note: str | None
    status: ProductStatus
    is_featured: bool
    rating_avg: float | None
    rating_count: int
    sold_count: int
    created_at: datetime
    updated_at: datetime


class ColorIn(CamelIn):
    name: str = Field(min_length=1, max_length=120)
    hex_code: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    sort_order: int = 0


class ColorOut(CamelOut):
    id: int
    product_id: int
    name: str
    hex_code: str | None
    sort_order: int


class VariantIn(CamelIn):
    color_id: int | None = None
    sku: str = Field(min_length=1, max_length=80)
    ram_gb: Decimal | None = Field(default=None, gt=0)
    storage_gb: Decimal | None = Field(default=None, gt=0)
    storage_available_gb: Decimal | None = Field(default=None, gt=0)
    condition: Condition = "new"
    condition_note: str | None = None
    list_price_vnd: Tien
    sale_price_vnd: Tien | None = None
    sale_status: SaleStatus = "in_stock"
    is_default: bool = False
    sort_order: int = 0


class VariantOut(CamelOut):
    id: int
    product_id: int
    color_id: int | None
    sku: str
    ram_gb: float | None
    storage_gb: float | None
    storage_available_gb: float | None
    condition: Condition
    condition_note: str | None
    list_price_vnd: int
    sale_price_vnd: int | None
    sale_status: SaleStatus
    is_default: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class PriceHistoryOut(CamelOut):
    id: int
    variant_id: int
    list_price_vnd: int
    sale_price_vnd: int | None
    changed_at: datetime


class SpecsIn(CamelIn):
    """PUT = thay TRỌN: trường vắng mặt thành NULL. `has_5g` là cột sinh từ `network_gen` — không nhận.

    Alias `hasFace3d`/`has5g` viết tay: `to_camel` sinh `hasFace3D`/`has5G`, lệch tên tham số lọc của storefront.
    """

    os_name: OsName | None = None
    os_version: str | None = None
    chipset: str | None = None
    cpu_cores: int | None = Field(default=None, gt=0)
    cpu_speed_text: str | None = None
    gpu: str | None = None
    memory_card_text: str | None = None
    supports_memory_card: bool | None = None
    contacts_limit_text: str | None = None
    rear_camera_text: str | None = None
    rear_camera_main_mp: Decimal | None = None
    rear_camera_count: int | None = Field(default=None, ge=0)
    rear_flash: bool | None = None
    front_camera_text: str | None = None
    front_camera_mp: Decimal | None = None
    display_tech: str | None = None
    display_resolution_text: str | None = None
    resolution_class: ResolutionClass | None = None
    screen_size_inch: Decimal | None = Field(default=None, gt=0)
    cover_screen_size_inch: Decimal | None = Field(default=None, gt=0)
    refresh_rate_hz: int | None = Field(default=None, gt=0)
    peak_brightness_nits: int | None = Field(default=None, gt=0)
    screen_glass: str | None = None
    battery_mah: int | None = Field(default=None, gt=0)
    battery_text: str | None = None
    battery_type: str | None = None
    max_charge_w: Decimal | None = Field(default=None, gt=0)
    charger_included: bool | None = None
    security_text: str | None = None
    has_face_3d: bool | None = Field(default=None, alias="hasFace3d")
    ip_rating: str | None = None
    recorder_text: str | None = None
    radio_text: str | None = None
    has_flashlight: bool | None = None
    network_gen: NetworkGen | None = None
    sim_text: str | None = None
    sim_slots: int | None = Field(default=None, ge=0)
    has_esim: bool | None = None
    bluetooth_version: str | None = None
    charging_port: str | None = None
    headphone_jack: str | None = None
    has_nfc: bool | None = None
    design_text: str | None = None
    material_text: str | None = None
    weight_g: Decimal | None = Field(default=None, gt=0)
    thickness_mm: Decimal | None = Field(default=None, gt=0)
    length_mm: Decimal | None = Field(default=None, gt=0)
    width_mm: Decimal | None = Field(default=None, gt=0)


class SpecsOut(CamelOut):
    product_id: int
    os_name: OsName | None
    os_version: str | None
    chipset: str | None
    cpu_cores: int | None
    cpu_speed_text: str | None
    gpu: str | None
    memory_card_text: str | None
    supports_memory_card: bool | None
    contacts_limit_text: str | None
    rear_camera_text: str | None
    rear_camera_main_mp: float | None
    rear_camera_count: int | None
    rear_flash: bool | None
    front_camera_text: str | None
    front_camera_mp: float | None
    display_tech: str | None
    display_resolution_text: str | None
    resolution_class: ResolutionClass | None
    screen_size_inch: float | None
    cover_screen_size_inch: float | None
    refresh_rate_hz: int | None
    peak_brightness_nits: int | None
    screen_glass: str | None
    battery_mah: int | None
    battery_text: str | None
    battery_type: str | None
    max_charge_w: float | None
    charger_included: bool | None
    security_text: str | None
    has_face_3d: bool | None = Field(alias="hasFace3d")
    ip_rating: str | None
    recorder_text: str | None
    radio_text: str | None
    has_flashlight: bool | None
    network_gen: NetworkGen | None
    has_5g: bool | None = Field(alias="has5g")
    sim_text: str | None
    sim_slots: int | None
    has_esim: bool | None
    bluetooth_version: str | None
    charging_port: str | None
    headphone_jack: str | None
    has_nfc: bool | None
    design_text: str | None
    material_text: str | None
    weight_g: float | None
    thickness_mm: float | None
    length_mm: float | None
    width_mm: float | None
    updated_at: datetime


class FeatureIdsIn(CamelIn):
    feature_ids: list[int] = Field(max_length=500)


class TagIdsIn(CamelIn):
    tag_ids: list[int] = Field(max_length=200)


class FeatureMini(CamelOut):
    id: int
    feature_group: str
    name: str
    slug: str


class TagMini(CamelOut):
    id: int
    kind: str
    slug: str
    name: str


class MediaIn(CamelIn):
    color_id: int | None = None
    media_type: MediaType
    url: str = Field(min_length=1, max_length=2000)
    alt_text: str | None = None
    sort_order: int = 0


class MediaOut(CamelOut):
    id: int
    product_id: int
    color_id: int | None
    media_type: MediaType
    url: str
    alt_text: str | None
    sort_order: int


class FaqIn(CamelIn):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    sort_order: int = 0


class FaqTaoIn(FaqIn):
    """`POST /faqs`: thiếu `productId` = FAQ chung (hiện ở mọi trang chi tiết)."""

    product_id: int | None = None


class FaqOut(CamelOut):
    id: int
    product_id: int | None
    question: str
    answer: str
    sort_order: int


class RelationIn(CamelIn):
    related_product_id: int
    relation_type: RelationType
    sort_order: int = 0


class RelationOut(CamelOut):
    related_product_id: int
    relation_type: RelationType
    sort_order: int
    slug: str
    name: str
    status: ProductStatus


# ---------------------------------------------------------------------------
# Cửa hàng (storefront)
# ---------------------------------------------------------------------------
class BrandMini(CamelOut):
    id: int
    name: str
    slug: str


class RefMini(CamelOut):
    id: int
    name: str
    slug: str


class ProductCard(CamelOut):
    """Một thẻ ở trang danh sách. Giá = SKU rẻ nhất còn bán được (xem `repo.GIA_THE`)."""

    id: int
    slug: str
    name: str
    status: ProductStatus
    brand: BrandMini
    phone_type: PhoneType | None
    is_featured: bool
    release_date: date | None
    thumbnail: str | None
    screen_size_inch: float | None
    display_tech: str | None
    resolution_class: str | None
    variant_id: int | None
    price_vnd: int | None
    list_price_vnd: int | None
    discount_percent: int | None
    ram_options: list[float]
    storage_options: list[float]
    rating_avg: float | None
    rating_count: int
    sold_count: int
    has_installment_0: bool
    gift_value_vnd: int | None
    tags: list[str]


class VariantDetail(CamelOut):
    id: int
    sku: str
    color_id: int | None
    color_name: str | None
    ram_gb: float | None
    storage_gb: float | None
    condition: Condition
    condition_note: str | None
    list_price_vnd: int
    price_vnd: int
    discount_percent: int
    sale_status: SaleStatus
    is_default: bool
    qty_available: int


class FeatureGroupOut(CamelOut):
    group: str
    items: list[FeatureMini]


class PromotionOut(CamelOut):
    id: int
    code: str | None
    name: str
    description: str | None
    promo_type: str
    discount_vnd: int | None
    discount_percent: float | None
    max_discount_vnd: int | None
    voucher_value_vnd: int | None
    voucher_scope: str | None
    gift_product_id: int | None
    gift_product_name: str | None
    payment_method: str | None
    choice_group: str | None
    is_stackable: bool
    excludes_installment_0: bool
    channel: str
    priority: int
    terms: str | None
    starts_at: datetime
    ends_at: datetime | None
    applies_to_all_variants: bool
    variant_ids: list[int]


class PartnerMini(CamelOut):
    id: int
    code: str
    name: str
    partner_type: str


class InstallmentPlanOut(CamelOut):
    id: int
    name: str
    partner: PartnerMini
    tenor_months: int
    interest_rate_monthly: float
    min_down_payment_percent: float
    fixed_fee_vnd: int
    min_price_vnd: int | None
    max_price_vnd: int | None
    required_docs: str | None
    conditions: str | None
    ends_at: datetime | None
    applies_to_all_variants: bool
    variant_ids: list[int]


class PolicyMini(CamelOut):
    id: int
    policy_type: str
    slug: str
    title: str
    summary: str | None


class ServicePackageMini(CamelOut):
    id: int
    code: str
    name: str
    service_type: str
    duration_months: int
    price_vnd: int | None
    price_percent: float | None
    terms_md: str | None


class RelatedOut(CamelOut):
    relation_type: RelationType
    sort_order: int
    product: ProductCard


class RatingSummary(CamelOut):
    """Đếm lại từ review `published` — không dùng cache `products.rating_*` để khớp phân bố sao."""

    avg: float | None
    count: int
    distribution: dict[str, int]


class ProductDetail(CamelOut):
    product: ProductOut
    brand: BrandMini
    category: RefMini
    series: RefMini | None
    price_vnd: int | None
    list_price_vnd: int | None
    discount_percent: int | None
    has_installment_0: bool
    gift_value_vnd: int | None
    colors: list[ColorOut]
    variants: list[VariantDetail]
    specs: SpecsOut | None
    features: list[FeatureGroupOut]
    tags: list[TagMini]
    media: list[MediaOut]
    faqs: list[FaqOut]
    promotions: list[PromotionOut]
    installment_plans: list[InstallmentPlanOut]
    policies: list[PolicyMini]
    service_packages: list[ServicePackageMini]
    related: list[RelatedOut]
    rating: RatingSummary


class CompareItem(CamelOut):
    product: ProductCard
    specs: SpecsOut | None
