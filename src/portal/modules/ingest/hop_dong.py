"""HỢP ĐỒNG DỮ LIỆU — schema cố định của `data`, và phép kiểm nó. HÀM THUẦN, không I/O.

Adapter bên khách code vào đúng bảng này. Nó là thứ Swagger phơi ra, và là thứ
duy nhất đứng giữa payload của họ và `tenant_data`.

⚠️ TÊN CỘT VÀ GIÁ TRỊ ENUM Ở ĐÂY LÀ BẢN CHÉP TAY của `migrations/versions/`.
Cùng hạng `lib/tools.ts` bên FE — nhưng KHÁC ở một điểm: bản này CÓ cổng parity.
`tests/modules/ingest/test_hop_dong_khop_schema.py` đọc `information_schema` +
`pg_constraint` của DB thật rồi so từng cột và từng giá trị enum. Thêm một trường
ở đây mà DB không có (hoặc ngược lại) là CI đỏ, không phải một bản ghi bị từ chối
ở nhà khách hàng sáu tháng sau.

Ba chỗ hợp đồng LỆCH khỏi trực giác, và cả ba đã suýt sai lúc dựng FE:
  · `link360` → cột `link_360` (có gạch dưới trước số).
  · `media.contentType` chỉ nhận **`image` · `video` · `tour_360`** — KHÔNG phải
    MIME type. Bản nháp FE ghi «VD image/webp» và sai. `tour_360` có trong enum vì
    DB có, nhưng nền tảng TỰ SINH nó từ `project.link_360` (`chieu._sync_tour_360`)
    — Swagger dặn adapter đừng gửi trực tiếp.
  · `document.loai` KHÔNG phải cột: nó nhập vào `title` thành tiền tố
    (`kb.contracts.join_title`). Xem `_ghep_tieu_de`.

── `unit.zoneExternalId` TUỲ CHỌN (đổi 2026-08-15) ─────────────────────────
`units.zone_code` nullable từ `0902` (tenant thật: 3015/3015 căn không phân khu).
FK tổ hợp `(tenant_id, project_code, zone_code)` với zone_code NULL thì Postgres
không cưỡng chế (MATCH SIMPLE) — đúng hình dạng `media.zone_code` đã có từ 0400.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from portal.modules.ingest.contracts import Entity

Kieu = Literal["chuoi", "so", "nguyen", "enum", "enum_nhieu", "ban_giao"]

# ─── Giá trị enum — chép từ `0400_kb_real_estate.py` (+ `0918` cho media) ────

TRANG_THAI = ("draft", "published", "archived")
LOAI_HINH = ("chung_cu", "biet_thu", "lien_ke", "shophouse", "dat_nen", "van_phong")
SALE_PHASE = ("sap_mo_ban", "dang_ban", "ban_giao", "dong_gio_hang")
SALE_STATUS = ("available", "booked", "sold")
HUONG = ("dong", "tay", "nam", "bac", "dong_bac", "dong_nam", "tay_bac", "tay_nam")
PRODUCT_TYPE = (
    "chung_cu", "studio", "duplex", "penthouse", "officetel", "condotel",
    "biet_thu", "lien_ke", "shophouse", "nha_pho", "dat_nen", "van_phong",
)  # fmt: skip
MEDIA_CONTENT_TYPE = ("image", "video", "tour_360")
MEDIA_CATEGORY = (
    "tong_quan", "ngoai_that", "noi_that", "tien_ich", "mat_bang", "vi_tri", "tien_do",
)  # fmt: skip
LOAI_TAI_LIEU = ("csbh", "phap_ly", "huong_dan", "khac")

TRANG_THAI_MAC_DINH = "published"


@dataclass(frozen=True)
class Truong:
    ten: str
    """Tên trong payload — camelCase, thứ dev bên khách gõ."""
    cot: str
    """Cột trong `tenant_data` — snake_case, tên THẬT."""
    kieu: Kieu
    bat_buoc: bool = False
    gia_tri: tuple[str, ...] = ()
    """Chỉ với `enum`/`enum_nhieu`."""


HOP_DONG: dict[Entity, tuple[Truong, ...]] = {
    "project": (
        Truong("name", "name", "chuoi", bat_buoc=True),
        Truong("code", "project_code", "chuoi"),
        Truong("region", "region", "chuoi"),
        Truong("address", "address", "chuoi"),
        Truong("investor", "investor", "chuoi"),
        Truong("developer", "developer", "chuoi"),
        Truong("category", "category", "enum_nhieu", gia_tri=LOAI_HINH),
        Truong("salePhase", "sale_phase", "enum", gia_tri=SALE_PHASE),
        Truong("productScale", "product_scale", "chuoi"),
        Truong("overview", "overview", "chuoi"),
        Truong("amenities", "amenities", "chuoi"),
        Truong("ownershipForm", "ownership_form", "chuoi"),
        Truong("handoverStandard", "handover_standard", "ban_giao"),
        Truong("totalLandAreaM2", "total_land_area_m2", "so"),
        Truong("floorAreaM2", "floor_area_m2", "so"),
        Truong("buildDensityPct", "build_density_pct", "so"),
        Truong("totalInvestmentVnd", "total_investment_vnd", "nguyen"),
        Truong("link360", "link_360", "chuoi"),
        Truong("status", "status", "enum", gia_tri=TRANG_THAI),
    ),
    "zone": (
        Truong("name", "name", "chuoi", bat_buoc=True),
        Truong("category", "category", "enum", gia_tri=LOAI_HINH),
        Truong("productScale", "product_scale", "chuoi"),
        Truong("overview", "overview", "chuoi"),
        Truong("status", "status", "enum", gia_tri=TRANG_THAI),
    ),
    "unit": (
        Truong("unitCode", "unit_code", "chuoi", bat_buoc=True),
        Truong("saleStatus", "sale_status", "enum", bat_buoc=True, gia_tri=SALE_STATUS),
        Truong("productType", "product_type", "enum", bat_buoc=True, gia_tri=PRODUCT_TYPE),
        Truong("priceVnd", "price_vnd", "so"),
        Truong("pricePerM2Vnd", "price_per_m2_vnd", "so"),
        Truong("direction", "direction", "enum", gia_tri=HUONG),
        Truong("bedrooms", "bedrooms", "nguyen"),
        Truong("block", "block", "chuoi"),
        Truong("floor", "floor", "nguyen"),
        Truong("numFloors", "num_floors", "nguyen"),
        Truong("areaBuiltM2", "area_built_m2", "so"),
        Truong("areaWallM2", "area_wall_m2", "so"),
        Truong("areaLandM2", "area_land_m2", "so"),
        Truong("imageUrl", "image_url", "chuoi"),
        Truong("status", "status", "enum", gia_tri=TRANG_THAI),
    ),
    "document": (
        Truong("title", "title", "chuoi", bat_buoc=True),
        Truong("loai", "title", "enum", gia_tri=LOAI_TAI_LIEU),
        Truong("body", "body", "chuoi"),
        Truong("fileUrl", "file_url", "chuoi"),
        Truong("status", "status", "enum", gia_tri=TRANG_THAI),
    ),
    "media": (
        Truong("mediaUrl", "media_url", "chuoi", bat_buoc=True),
        Truong("contentType", "content_type", "enum", bat_buoc=True, gia_tri=MEDIA_CONTENT_TYPE),
        Truong("category", "category", "enum", bat_buoc=True, gia_tri=MEDIA_CATEGORY),
        Truong("caption", "caption", "chuoi"),
        Truong("fileName", "file_name", "chuoi"),
        Truong("status", "status", "enum", gia_tri=TRANG_THAI),
    ),
}

QUAN_HE: dict[Entity, tuple[tuple[str, Entity, bool], ...]] = {
    "project": (),
    "zone": (("projectExternalId", "project", True),),
    "unit": (("projectExternalId", "project", True), ("zoneExternalId", "zone", False)),
    "document": (("projectExternalId", "project", True),),
    "media": (
        ("projectExternalId", "project", True),
        ("zoneExternalId", "zone", False),
        ("unitExternalId", "unit", False),
    ),
}


class LoiTruong(Exception):
    """Một trường sai. `truong` rỗng ⇒ lỗi ở cấp bản ghi."""

    def __init__(self, truong: str, ly_do: str) -> None:
        super().__init__(ly_do)
        self.truong = truong
        self.ly_do = ly_do


def _so(gia_tri: object, truong: str, nguyen: bool) -> float | int | None:
    if gia_tri is None:
        return None
    if isinstance(gia_tri, bool):
        raise LoiTruong(truong, "Phải là số, nhận được true/false")
    if isinstance(gia_tri, int | float):
        return int(gia_tri) if nguyen else float(gia_tri)
    raise LoiTruong(truong, f"Phải là số, nhận được chuỗi {gia_tri!r}")


def _enum(gia_tri: object, t: Truong) -> str | None:
    if gia_tri is None:
        return None
    if not isinstance(gia_tri, str) or gia_tri not in t.gia_tri:
        raise LoiTruong(t.ten, f"Giá trị {gia_tri!r} không hợp lệ — chỉ nhận {' · '.join(t.gia_tri)}")
    return gia_tri


def _chuoi(gia_tri: object, truong: str) -> str | None:
    if gia_tri is None:
        return None
    if isinstance(gia_tri, str):
        if "\x00" in gia_tri:
            raise LoiTruong(truong, "Chuỗi không được chứa ký tự NUL (\\u0000)")
        return gia_tri
    if isinstance(gia_tri, int | float | date | datetime) and not isinstance(gia_tri, bool):
        return str(gia_tri)
    raise LoiTruong(truong, f"Phải là chuỗi, nhận được {type(gia_tri).__name__}")


_KHOA_BAN_GIAO = ("item", "material", "brand", "origin", "note")


def _ban_giao(gia_tri: object, truong: str) -> str | None:
    """Chuỗi (adapter cũ) thành một hạng mục; danh sách `{item, material, brand, origin, note}` giữ nguyên.

    Trả JSON cho cột jsonb; rỗng ⇒ None (cột về DEFAULT NULL).
    """
    if gia_tri is None:
        return None
    if isinstance(gia_tri, str):
        chu = (_chuoi(gia_tri, truong) or "").strip()
        return json.dumps([{"item": "Tiêu chuẩn chung", "note": chu}], ensure_ascii=False) if chu else None
    if not isinstance(gia_tri, list):
        raise LoiTruong(truong, f"Phải là chuỗi hoặc danh sách hạng mục, nhận được {type(gia_tri).__name__}")
    hang_muc = []
    for h in gia_tri:
        if not isinstance(h, dict) or not isinstance(h.get("item"), str) or not h["item"].strip():
            raise LoiTruong(truong, "Mỗi hạng mục phải là object có `item` là chuỗi không rỗng")
        ra = {}
        for k in _KHOA_BAN_GIAO:
            v = h.get(k)
            if v is None:
                continue
            if not isinstance(v, str) or "\x00" in v:
                raise LoiTruong(truong, f"`{k}` của hạng mục phải là chuỗi")
            if v.strip():
                ra[k] = v.strip()
        hang_muc.append(ra)
    return json.dumps(hang_muc, ensure_ascii=False) if hang_muc else None


def _ghep_tieu_de(cot: dict, data: dict) -> None:
    """`loai` + `title` → một `title` có tiền tố. Xem docstring đầu tệp.

    Gọi SAU vòng kiểm chính, vì cả hai trường cùng ghi vào `title` và thứ tự
    duyệt `dict` không đảm bảo cái nào tới trước.
    """
    from portal.modules.kb.contracts import join_title

    loai = data.get("loai")
    if loai is None:
        return
    tieu_de = cot.get("title")
    if not isinstance(tieu_de, str):
        return
    cot["title"] = join_title(loai, tieu_de)


def kiem(entity: Entity, data: dict) -> tuple[dict[str, object], list[LoiTruong]]:
    """`data` của khách → `{cột: giá trị}` sẵn sàng ghi, kèm danh sách lỗi.

    TRẢ VỀ TẤT CẢ LỖI, không dừng ở cái đầu tiên: bên khách sửa adapter theo lô,
    và bắt họ đẩy lại năm lần để phát hiện năm lỗi là năm vòng cho một việc.

    TRƯỜNG LẠ ⇒ BỎ QUA IM LẶNG, không vào danh sách lỗi (spec quyết định #3). Hệ
    thống bên họ sẽ mọc thêm cột theo thời gian; biến mỗi lần như thế thành một sự
    cố bên mình là làm hợp đồng giòn tới mức không dùng được.
    """
    spec = {t.ten: t for t in HOP_DONG[entity]}
    quan_he = {ten for ten, _, _ in QUAN_HE[entity]}
    cot: dict[str, object] = {}
    loi: list[LoiTruong] = []

    for ten, gia_tri in data.items():
        if ten in quan_he:
            continue  # khoá giải, xử lý ở service — không phải cột
        t = spec.get(ten)
        if t is None:
            continue  # trường lạ
        if ten in ("loai", "code"):
            try:
                _enum(gia_tri, t) if ten == "loai" else _chuoi(gia_tri, ten)
            except LoiTruong as e:
                loi.append(e)
            continue
        try:
            if t.kieu == "chuoi":
                v = _chuoi(gia_tri, ten)
            elif t.kieu in ("so", "nguyen"):
                v = _so(gia_tri, ten, nguyen=t.kieu == "nguyen")
            elif t.kieu == "enum":
                v = _enum(gia_tri, t)
            elif t.kieu == "ban_giao":
                v = _ban_giao(gia_tri, ten)
            else:  # enum_nhieu
                if gia_tri is None:
                    v = None
                elif not isinstance(gia_tri, list):
                    raise LoiTruong(ten, f"Phải là danh sách, nhận được {type(gia_tri).__name__}")
                else:
                    if any(x is None for x in gia_tri):
                        raise LoiTruong(ten, "Danh sách không được chứa phần tử null")
                    v = [_enum(x, t) for x in gia_tri]
        except LoiTruong as e:
            loi.append(e)
            continue
        if v is not None:
            cot[t.cot] = v

    da_bao = {e.truong for e in loi}
    for t in HOP_DONG[entity]:
        if not t.bat_buoc or t.ten in da_bao:
            continue
        if t.ten not in data:
            loi.append(LoiTruong(t.ten, "Thiếu trường bắt buộc"))
        elif data[t.ten] is None:
            loi.append(LoiTruong(t.ten, "Trường bắt buộc không được để null"))
        elif t.kieu == "chuoi" and isinstance(data[t.ten], str) and not data[t.ten].strip():
            loi.append(LoiTruong(t.ten, "Trường bắt buộc không được để chuỗi rỗng"))

    for ten, _cha, bat_buoc in QUAN_HE[entity]:
        gia_tri = data.get(ten)
        if gia_tri is None:
            if bat_buoc:
                ly_do = "Khoá tham chiếu cha không được để null" if ten in data else "Thiếu khoá tham chiếu bản ghi cha"
                loi.append(LoiTruong(ten, ly_do))
            continue
        hop_le = (isinstance(gia_tri, str) and gia_tri.strip() and "\x00" not in gia_tri) or (
            isinstance(gia_tri, int) and not isinstance(gia_tri, bool) and gia_tri != 0
        )
        if not hop_le:
            loi.append(LoiTruong(ten, "Khoá tham chiếu cha phải là chuỗi không rỗng"))

    if "loai" in data and "loai" not in da_bao:
        try:
            _ghep_tieu_de(cot, data)
        except ValueError as e:
            loi.append(LoiTruong("loai", str(e)))

    cot.setdefault("status", TRANG_THAI_MAC_DINH)
    return cot, loi
