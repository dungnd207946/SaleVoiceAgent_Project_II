"""MẶT TIỀN của module realestate — file DUY NHẤT module khác được import.

Import `repo.py` / `router.py` từ module khác là LỖI CI (`tests/test_module_boundaries.py`
đọc AST). `repo.py` (cùng module) NGƯỢC LẠI được phép import từ đây — đó không phải
"mặt tiền phụ thuộc ngược vào ruột" (luật cấm việc contracts→repo/router), mà là
repo dùng chung một nguồn sự thật duy nhất cho danh sách cột/enum/lỗi với người gọi
từ ngoài (Task 4 — router; sau này agent module) — đúng nếp `chinh_sach.py` cũ, chỉ
gộp lại vào một file vì `chinh_sach.py`/`gia.py`/`service.py` đã xoá ở Task 2.

Tên trường DTO **camelCase** vì đây là hợp đồng HTTP — cùng lý do
`modules/kb/contracts.py`/`modules/auth/contracts.py`. Tên CỘT (trong các hằng số
`COT_*`, dùng để ghép SQL) giữ snake_case — chúng LÀ tên cột thật trong
`tenant_data` (`docs/build_module_knowledgebase/02a §4`), không phải một bản dịch.

Field mô tả từng bảng — xem `02a §4` (nguồn sự thật). File này không lặp lại field,
chỉ định nghĩa HỢP ĐỒNG (DTO + hằng số) map 1:1 vào đó.
"""

import base64
import binascii
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from portal.core.dto import CamelOut

__all__ = [
    "COT_CAN",
    "COT_DU_AN",
    "COT_TOA",
    "COT_MEDIA",
    "COT_PHAN_KHU",
    "COT_TAI_LIEU",
    "GIOI_HAN_OFFSET",
    "GIOI_HAN_TRANG",
    "TRANG_MAC_DINH",
    "CanOut",
    "DuAnOut",
    "Entity",
    "FacetCan",
    "HangMucBanGiao",
    "LoiConTro",
    "LoiTruongLa",
    "MediaOut",
    "PhanKhuOut",
    "TaiLieuOut",
    "ToaOut",
    "TrangCan",
    "TrangDuAn",
    "TrangMedia",
    "TrangPhanKhu",
    "TrangTaiLieu",
    "TrangToa",
    "KbStatusOut",
    "DIRECTION_LABELS",
    "PROJECT_TYPE_LABELS",
    "SALE_PHASE_LABELS",
    "SENTINEL_TENANT",
    "doc_con_tro",
    "ma_con_tro",
]

# `zones.category` / `projects.category` — bản chép thứ hai của FE `enums.ts::LOAI_HINH`.
PROJECT_TYPE_LABELS: dict[str, str] = {
    "chung_cu": "Chung cư",
    "biet_thu": "Biệt thự",
    "lien_ke": "Liền kề",
    "shophouse": "Shophouse",
    "dat_nen": "Đất nền",
    "van_phong": "Văn phòng",
}

SALE_PHASE_LABELS: dict[str, str] = {
    "sap_mo_ban": "Sắp mở bán",
    "dang_ban": "Đang bán",
    "ban_giao": "Đang bàn giao",
    "dong_gio_hang": "Đã đóng giỏ hàng",
}

DIRECTION_LABELS: dict[str, str] = {
    "dong": "Đông",
    "tay": "Tây",
    "nam": "Nam",
    "bac": "Bắc",
    "dong_bac": "Đông Bắc",
    "dong_nam": "Đông Nam",
    "tay_bac": "Tây Bắc",
    "tay_nam": "Tây Nam",
}

Entity = Literal["project", "zone", "building", "unit", "document", "media"]
"""5 thực thể KB BĐS (`02a §4`), khớp `_BANG`/`_COT_*` của `repo.py`."""

SENTINEL_TENANT = "__ALL__"
"""`02 §2`/`02a §4b`: giá trị `project_code` đặc biệt = tài liệu/media dùng chung
toàn tenant. Chỉ `documents` và `media` có bản cấp-tenant — `projects`/`zones`/`units`
không dùng sentinel này (chúng LÀ chính cây dự án)."""


class LoiTruongLa(ValueError):
    """Payload ghi (`chen_*`/`sua_*`) có khoá không nằm trong danh sách trắng `COT_*`.

    RAISE chứ không lọc-bỏ-âm-thầm: nguồn là dữ liệu người dùng vừa nhập, và bỏ
    một trường họ tưởng đã lưu là mất dữ liệu không ai biết."""


class LoiConTro(ValueError):
    """Cursor phân trang không giải mã được. Người gọi (router, Task 4) dịch sang lỗi 422."""


# ─── Phân trang keyset (`(id)`, bất biến) ───────────────────────────────────

TRANG_MAC_DINH = 50
"""Số bản ghi một trang khi không truyền `limit`. Đủ nhỏ để trang đầu của danh
sách căn (có thể hàng nghìn dòng) không kéo nguyên bảng."""

GIOI_HAN_TRANG = 200
"""Trần cứng — không có trần thì `?limit=100000` biến phân trang thành trang trí."""

GIOI_HAN_OFFSET = 1_000_000_000
"""Trần cứng cho `offset` — trước đây chỉ kẹp DƯỚI (`max(0, offset)`), không trần
TRÊN. `asyncpg` gửi tham số nguyên xuống Postgres như `bigint`; `offset` vượt
`2^63-1` (int64) làm Postgres từ chối tham số bằng `DataError`, và vì
`api/loi.py` không có handler catch-all, lỗi đó nổi lên thành 500 kèm stack
trace thay vì 422 có cấu trúc.

1 tỷ, KHÔNG phải sát trần int64: không tenant nào có ngần ấy hàng, nên số này
là LƯỚI AN TOÀN, không phải giới hạn nghiệp vụ thật — và nó nằm xa TRÊN `2^31`
(2147483648 vẫn phải là offset hợp lệ, một số bình thường lớn hơn int32 một
chút) lẫn xa DƯỚI `2^63-1`, nên không có `offset` nào chạm nó trong sử dụng
thật, chỉ chặn được input kiểu `?offset=99999999999999999999`."""


def ma_con_tro(id_: int) -> str:
    """`id` (khoá keyset) → chuỗi opaque.

    ĐỤC (base64), không phải số trần: cursor là CHI TIẾT CÀI ĐẶT. Để nó đọc được
    là mời FE tự chế/tự tăng — và ngày khoá sắp xếp đổi thì cách dùng đó gãy âm
    thầm. Đục thì hợp đồng chỉ còn "gửi lại nguyên văn cái server vừa đưa".
    """
    return base64.urlsafe_b64encode(str(id_).encode()).decode().rstrip("=")


def doc_con_tro(con_tro: str) -> int:
    """Ngược của `ma_con_tro`. Raise `LoiConTro` với mọi thứ không đúng dạng —
    trả về trang đầu một cách âm thầm sẽ làm FE cuộn vô tận (xin trang sau, nhận
    lại trang đầu, xin tiếp...). Thà một lỗi đọc được một lần."""
    try:
        tho = base64.urlsafe_b64decode(con_tro + "==").decode()
        return int(tho)
    except (ValueError, binascii.Error, UnicodeDecodeError) as e:
        raise LoiConTro("Con trỏ phân trang không hợp lệ") from e


# ─── Danh sách trắng tên cột (payload ghi là dict động — `chen_*`/`sua_*`) ──

COT_DU_AN: frozenset[str] = frozenset(
    {
        "project_code",
        "name",
        "category",
        "region",
        "address",
        "investor",
        "developer",
        "total_land_area_m2",
        "floor_area_m2",
        "build_density_pct",
        "product_scale",
        "amenities",
        "ownership_form",
        "handover_standard",
        "total_investment_vnd",
        "sale_phase",
        "overview",
        "link_360",
        "cover_media_id",
        "map_media_id",
        "status",
        "total_units",
        "num_buildings",
        "management_fee_vnd_m2",
        "parking_car_fee_vnd",
        "parking_moto_fee_vnd",
    }
)

COT_PHAN_KHU: frozenset[str] = frozenset(
    {
        "project_code",
        "zone_code",
        "name",
        "category",
        "product_scale",
        "overview",
        "cover_media_id",
        "map_media_id",
        "status",
        "sale_phase",
        "note",
        "amenities",
        "num_buildings",
        "total_units",
    }
)

COT_TOA: frozenset[str] = frozenset(
    {
        "project_code",
        "zone_code",
        "building_code",
        "name",
        "num_floors",
        "num_basements",
        "units_per_floor",
        "elevators_passenger",
        "elevators_service",
        "car_slots",
        "moto_slots",
        "ceiling_height_m",
        "facing",
        "sale_phase",
        "amenities",
        "overview",
        "status",
    }
)

COT_CAN: frozenset[str] = frozenset(
    {
        "project_code",
        "zone_code",
        "unit_code",
        "product_type",
        "bedrooms",
        "block",
        "floor",
        "num_floors",
        "direction",
        "area_built_m2",
        "area_wall_m2",
        "area_land_m2",
        "price_vnd",
        "price_per_m2_vnd",
        "sale_status",
        "image_url",
        "status",
        "views",
        "is_corner",
        "open_sides",
        "bathrooms",
        "handover_condition",
        "layout_media_id",
        "hr_balcony_m2",
        "hr_loggia_m2",
        "lr_frontage_m",
        "lr_depth_m",
        "lr_road_width_m",
    }
)

COT_TAI_LIEU: frozenset[str] = frozenset({"project_code", "title", "body", "file_url", "body_cho_duyet", "status"})

COT_MEDIA: frozenset[str] = frozenset(
    {
        "project_code",
        "zone_code",
        "unit_code",
        "content_type",
        "category",
        "caption",
        "file_name",
        "media_url",
        "thumb_url",
        "public_url",
        "public_thumb_url",
        "content_hash",
        "uploaded_by",
        "status",
    }
)


# ─── DTO đọc (HTTP, camelCase) ──────────────────────────────────────────────


class HangMucBanGiao(BaseModel):
    """Một hạng mục trong `projects.handover_standard` (jsonb mảng). Chỉ `item` bắt buộc."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    item: str = Field(min_length=1, max_length=200)
    material: str = Field(default="", max_length=500)
    brand: str = Field(default="", max_length=200)
    origin: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=1000)


class DuAnOut(BaseModel):
    id: int
    projectCode: str
    name: str
    category: list[str]
    region: str
    address: str
    investor: str
    developer: str
    totalLandAreaM2: float | None
    floorAreaM2: float | None
    buildDensityPct: float | None
    productScale: str
    amenities: str
    ownershipForm: str
    handoverStandard: list[HangMucBanGiao]
    totalInvestmentVnd: int | None
    salePhase: str
    overview: str
    link360: str
    coverMediaId: int | None
    mapMediaId: int | None
    status: str
    createdAt: datetime
    updatedAt: datetime
    totalUnits: int | None = None
    numBuildings: int | None = None
    managementFeeVndM2: float | None = None
    parkingCarFeeVnd: float | None = None
    parkingMotoFeeVnd: float | None = None


class PhanKhuOut(CamelOut):
    id: int
    project_code: str
    zone_code: str
    name: str
    category: str | None
    product_scale: str
    overview: str
    cover_media_id: int | None
    map_media_id: int | None
    status: str
    created_at: datetime
    updated_at: datetime
    sale_phase: str | None = None
    note: str = ""
    amenities: str = ""
    num_buildings: int | None = None
    total_units: int | None = None
    unit_count: int = 0


class ToaOut(CamelOut):
    id: int
    project_code: str
    zone_code: str | None
    building_code: str
    name: str
    num_floors: int | None
    num_basements: int | None
    units_per_floor: int | None
    elevators_passenger: int | None
    elevators_service: int | None
    car_slots: int | None
    moto_slots: int | None
    ceiling_height_m: float | None
    facing: str | None
    sale_phase: str | None
    amenities: str
    overview: str
    status: str
    unit_count: int = 0
    created_at: datetime
    updated_at: datetime


class CanOut(CamelOut):
    id: int
    project_code: str
    zone_code: str | None
    zone_name: str | None
    unit_code: str
    product_type: str
    bedrooms: int | None
    block: str | None
    floor: int | None
    num_floors: int | None
    direction: str | None
    area_built_m2: float | None
    area_wall_m2: float | None
    area_land_m2: float | None
    price_vnd: float | None
    price_per_m2_vnd: float | None
    sale_status: str
    image_url: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    views: list[str] = []
    is_corner: bool | None = None
    open_sides: int | None = None
    bathrooms: int | None = None
    handover_condition: str | None = None
    layout_media_id: int | None = None
    hr_balcony_m2: float | None = None
    hr_loggia_m2: float | None = None
    lr_frontage_m: float | None = None
    lr_depth_m: float | None = None
    lr_road_width_m: float | None = None


class TaiLieuOut(BaseModel):
    id: int
    projectCode: str
    loai: str
    title: str
    body: str
    fileUrl: str | None
    bodyChoDuyet: bool
    status: str
    createdAt: datetime
    updatedAt: datetime


class MediaOut(BaseModel):
    id: int
    projectCode: str
    zoneCode: str | None
    unitCode: str | None
    contentType: str
    category: str
    caption: str
    fileName: str
    mediaUrl: str
    thumbUrl: str | None
    contentHash: str
    uploadedBy: str | None
    status: str
    createdAt: datetime
    updatedAt: datetime


class TrangDuAn(BaseModel):
    items: list[DuAnOut]
    nextCursor: str | None = None
    total: int


class TrangPhanKhu(BaseModel):
    items: list[PhanKhuOut]
    nextCursor: str | None = None
    total: int


class TrangToa(BaseModel):
    items: list[ToaOut]
    total: int


class TrangCan(BaseModel):
    items: list[CanOut]
    nextCursor: str | None = None
    total: int


class FacetCan(BaseModel):
    """Giá trị CÓ THẬT trong quỹ căn của một dự án — nguồn của hai ô lọc.

    VÌ SAO KHÔNG DÙNG THẲNG ENUM: `_ProductType` có 12 giá trị và `_Direction` có
    8, còn một dự án chung cư thường chỉ có 2–3 loại. Dropdown liệt kê cả 12 bắt
    người dùng đọc qua chín mục mà chọn vào là ra bảng rỗng — nó hứa một bộ lọc
    không có gì để lọc. Danh sách này chỉ chứa giá trị đang có hàng.
    """

    productType: list[str]
    direction: list[str]


class TrangTaiLieu(BaseModel):
    items: list[TaiLieuOut]
    nextCursor: str | None = None
    total: int


class TrangMedia(BaseModel):
    items: list[MediaOut]
    nextCursor: str | None = None
    total: int


class KbStatusOut(CamelOut):
    """Một dòng cho mỗi dự án — chỉ báo trên danh sách đọc đúng danh sách này.

    CÓ SỐ, từ 2026-08-25. Quyết định «hai cờ, không có số» viết cho thời nhập tay vài
    bản ghi; nay cổng nạp đổ vào hàng trăm ảnh một lượt và một dòng chữ tĩnh không phân
    biệt được «chậm» với «kẹt». `total = 0` nghĩa là dự án chưa có gì để nạp.
    """

    project_code: str
    indexing: bool
    has_error: bool
    total: int = 0
    done: int = 0


# ── mặt tiền hàm ─────────────────────────────────────────────────────────────
_MAT_TIEN_HAM = frozenset({"sync_tour_360"})


def __getattr__(name: str):
    if name in _MAT_TIEN_HAM:
        from portal.modules.realestate import repo as _repo

        return getattr(_repo, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
