"""Bản ghi DB → văn bản đem nhúng (luồng B). Một hàm `load` cho mỗi entity của trigger.

LOẠI TRỪ GIÁ VÀ TỒN KHO có chủ ý: chúng đổi liên tục (mỗi lần đổi giá là một lượt nhúng
lại vô ích) và agent đọc chúng qua view SQL (`agent_products_v`, `agent_stock_v`) — con số
cũ nằm trong Qdrant là câu trả lời SAI chắc chắn. Kho tri thức chỉ giữ thứ ít đổi: mô tả,
thông số, chính sách, bài viết, FAQ.

`load()` trả `None` khi bản ghi KHÔNG CÒN hoặc KHÔNG HIỂN THỊ (sản phẩm nháp, chính sách
tắt, bài chưa xuất bản, gói dịch vụ tắt) — người gọi coi cả hai là XOÁ khỏi kho, nên ẩn
một bản ghi là gỡ nó khỏi tầm agent ngay lượt trigger kế tiếp.

Phần dựng văn bản là hàm THUẦN trên dict (`*_text`) — test được không cần DB.
"""

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from datetime import date
from decimal import Decimal
from typing import Any

import asyncpg

from portal.modules.kb.contracts import ENTITY_MEDIA, DocMeta, MediaDoc, TextDoc

Row = Mapping[str, Any]

# ─── Định dạng giá trị ──────────────────────────────────────────────────────────


def _so(x: Any) -> str:
    """`Decimal('6.90')` → `6.9`, `Decimal('8.000')` → `8` — số trong bảng thông số không có đuôi 0."""
    if isinstance(x, Decimal):
        return f"{x.normalize():f}"
    return str(x)


def _dung_luong(gb: Any) -> str:
    """RAM/ROM: `0.048` → `48 MB`, `1024` → `1 TB`."""
    d = Decimal(str(gb))
    if d >= 1024:
        return f"{_so(d / 1024)} TB"
    if d < 1:
        return f"{_so(d * 1000)} MB"
    return f"{_so(d)} GB"


def _co_khong(b: bool | None) -> str | None:
    return None if b is None else ("Có" if b else "Không")


def _thang_nam(d: date | None) -> str | None:
    return d.strftime("%m/%Y") if d else None


def _ngay(d: date | None) -> str | None:
    return d.strftime("%d/%m/%Y") if d else None


def _don(x: Any, don_vi: str) -> str | None:
    return f"{_so(x)} {don_vi}" if x is not None else None


def _noi(ds: Iterable[str]) -> str | None:
    ds = [x for x in ds if x]
    return ", ".join(ds) if ds else None


def _dong(nhan: str, gia_tri: Any) -> str | None:
    return f"{nhan}: {gia_tri}" if gia_tri not in (None, "") else None


def _khoi(*dong: str | None) -> str:
    return "\n".join(d for d in dong if d)


# ─── Sản phẩm ───────────────────────────────────────────────────────────────────

LOAI_MAY = {
    "smartphone": "Điện thoại thông minh",
    "foldable": "Điện thoại gập",
    "feature_phone": "Điện thoại phổ thông",
}
TRANG_THAI_SP = {"coming_soon": "Sắp ra mắt", "selling": "Đang kinh doanh", "discontinued": "Ngừng kinh doanh"}
TINH_TRANG_MAY = {"used": "máy cũ", "refurbished": "máy tân trang"}

Spec = Mapping[str, Any]
Feat = Mapping[str, list[str]]
Getter = Callable[[Spec, Feat], Any]


def _f(nhom: str) -> Getter:
    return lambda _s, f: _noi(f.get(nhom, ()))


def _c(cot: str) -> Getter:
    return lambda s, _f: s.get(cot)


def _hoac(cot_text: str, cot_so: str, don_vi: str) -> Getter:
    """Ưu tiên cột `*_text` (nguyên văn như bảng thông số TGDĐ), rơi về cột số + đơn vị."""
    return lambda s, _f: s.get(cot_text) or _don(s.get(cot_so), don_vi)


def _man_hinh(s: Spec, _f: Feat) -> str | None:
    chinh = f'{_so(s["screen_size_inch"])}"' if s.get("screen_size_inch") is not None else None
    phu = f'màn ngoài {_so(s["cover_screen_size_inch"])}"' if s.get("cover_screen_size_inch") is not None else None
    return _noi((chinh, phu))


def _he_dieu_hanh(s: Spec, _f: Feat) -> str | None:
    return s.get("os_version") or s.get("os_name")


def _kich_thuoc(s: Spec, _f: Feat) -> str | None:
    phan = [
        f"{nhan} {_so(s[cot])} mm"
        for nhan, cot in (("Dài", "length_mm"), ("Ngang", "width_mm"), ("Dày", "thickness_mm"))
        if s.get(cot) is not None
    ]
    return " - ".join(phan) or None


NHOM_THONG_SO: tuple[tuple[str, tuple[tuple[str, Getter], ...]], ...] = (
    (
        "Cấu hình & Bộ nhớ",
        (
            ("Hệ điều hành", _he_dieu_hanh),
            ("Chip xử lý (CPU)", _c("chipset")),
            ("Tốc độ CPU", _c("cpu_speed_text")),
            ("Số nhân CPU", _c("cpu_cores")),
            ("Chip đồ hoạ (GPU)", _c("gpu")),
            ("Thẻ nhớ", _c("memory_card_text")),
            ("Danh bạ", _c("contacts_limit_text")),
        ),
    ),
    (
        "Camera & Màn hình",
        (
            ("Độ phân giải camera sau", _hoac("rear_camera_text", "rear_camera_main_mp", "MP")),
            ("Quay phim camera sau", _f("rear_video")),
            ("Đèn Flash camera sau", lambda s, _f: _co_khong(s.get("rear_flash"))),
            ("Tính năng camera sau", _f("rear_camera")),
            ("Độ phân giải camera trước", _hoac("front_camera_text", "front_camera_mp", "MP")),
            ("Quay phim camera trước", _f("front_video")),
            ("Tính năng camera trước", _f("front_camera")),
            ("Công nghệ màn hình", _c("display_tech")),
            ("Độ phân giải màn hình", lambda s, _f: s.get("display_resolution_text") or s.get("resolution_class")),
            ("Màn hình rộng", _man_hinh),
            ("Tần số quét", lambda s, _f: _don(s.get("refresh_rate_hz"), "Hz")),
            ("Độ sáng tối đa", lambda s, _f: _don(s.get("peak_brightness_nits"), "nits")),
            ("Mặt kính cảm ứng", _c("screen_glass")),
        ),
    ),
    (
        "Pin & Sạc",
        (
            ("Dung lượng pin", _hoac("battery_text", "battery_mah", "mAh")),
            ("Loại pin", _c("battery_type")),
            ("Hỗ trợ sạc tối đa", lambda s, _f: _don(s.get("max_charge_w"), "W")),
            ("Sạc kèm theo máy", lambda s, _f: _co_khong(s.get("charger_included"))),
            ("Công nghệ pin", _f("battery_tech")),
        ),
    ),
    (
        "Tiện ích",
        (
            ("Bảo mật nâng cao", _c("security_text")),
            ("Tính năng đặc biệt", _f("special")),
            ("Tính năng AI", _f("ai")),
            ("Kháng nước, bụi", _c("ip_rating")),
            ("Ghi âm", _c("recorder_text")),
            ("Radio", _c("radio_text")),
            ("Đèn pin", lambda s, _f: _co_khong(s.get("has_flashlight"))),
            ("Xem phim", _f("video_format")),
            ("Nghe nhạc", _f("audio_format")),
        ),
    ),
    (
        "Kết nối",
        (
            ("Mạng di động", lambda s, _f: f"Hỗ trợ {s['network_gen']}" if s.get("network_gen") else None),
            ("SIM", _c("sim_text")),
            ("eSIM", lambda s, _f: _co_khong(s.get("has_esim"))),
            ("Wifi", _f("wifi")),
            ("GPS", _f("gps")),
            ("Bluetooth", _c("bluetooth_version")),
            ("Cổng kết nối/sạc", _c("charging_port")),
            ("Jack tai nghe", _c("headphone_jack")),
            ("NFC", lambda s, _f: _co_khong(s.get("has_nfc"))),
            ("Kết nối khác", _f("connectivity_other")),
        ),
    ),
    (
        "Thiết kế & Chất liệu",
        (
            ("Thiết kế", _c("design_text")),
            ("Chất liệu", _c("material_text")),
            ("Kích thước", _kich_thuoc),
            ("Khối lượng", lambda s, _f: _don(s.get("weight_g"), "g")),
        ),
    ),
)
"""6 nhóm như bảng thông số TGDĐ. Tính năng đa trị (`features.feature_group`) xếp vào đúng nhóm."""


def _cau_hinh(variants: Iterable[Row]) -> str | None:
    """`8 GB/256 GB, 12 GB/512 GB (máy cũ)` — chỉ cấu hình, KHÔNG giá/tình trạng hàng."""
    ds: list[str] = []
    for v in variants:
        phan = [_dung_luong(v[k]) for k in ("ram_gb", "storage_gb") if v.get(k) is not None]
        if not phan:
            continue
        nhan = "/".join(phan)
        if v.get("condition") in TINH_TRANG_MAY:
            nhan += f" ({TINH_TRANG_MAY[v['condition']]})"
        if nhan not in ds:
            ds.append(nhan)
    return _noi(ds)


def _kha_dung(variants: Iterable[Row]) -> str | None:
    ds = []
    for v in variants:
        if v.get("storage_available_gb") is not None and v.get("storage_gb") is not None:
            x = f"khoảng {_dung_luong(v['storage_available_gb'])} (bản {_dung_luong(v['storage_gb'])})"
            if x not in ds:
                ds.append(x)
    return _noi(ds)


def product_text(
    p: Row,
    *,
    spec: Spec | None,
    features: Feat,
    colors: Iterable[str],
    variants: Iterable[Row],
    tags: Iterable[str],
) -> str:
    variants = list(variants)
    spec = spec or {}
    phan = [
        f"# {p['name']}",
        _khoi(
            _dong("Hãng", p.get("brand")),
            _dong("Dòng máy", p.get("series")),
            _dong("Ngành hàng", p.get("category")),
            _dong("Loại máy", LOAI_MAY.get(p.get("phone_type") or "")),
            _dong("Mã model", p.get("model_code")),
            _dong("Thời điểm ra mắt", _thang_nam(p.get("release_date"))),
            _dong("Tình trạng kinh doanh", TRANG_THAI_SP.get(p.get("status") or "")),
        ),
        p.get("short_description") or "",
    ]
    if p.get("highlights_md"):
        phan.append(f"## Điểm nổi bật\n\n{p['highlights_md']}")
    phien_ban = _khoi(_dong("Màu sắc", _noi(colors)), _dong("Cấu hình RAM/ROM", _cau_hinh(variants)))
    if phien_ban:
        phan.append(f"## Phiên bản\n\n{phien_ban}")

    nhom_ra: list[str] = []
    for ten_nhom, truong in NHOM_THONG_SO:
        dong = [_dong(nhan, lay(spec, features)) for nhan, lay in truong]
        if ten_nhom == "Cấu hình & Bộ nhớ":
            dong.insert(5, _dong("Dung lượng lưu trữ khả dụng", _kha_dung(variants)))
        than = _khoi(*dong)
        if than:
            nhom_ra.append(f"### {ten_nhom}\n\n{than}")
    if nhom_ra:
        phan.append("## Thông số kỹ thuật\n\n" + "\n\n".join(nhom_ra))

    if nhu_cau := _noi(tags):
        phan.append(f"## Phù hợp nhu cầu\n\n{nhu_cau}")
    if p.get("in_box"):
        phan.append(f"## Bộ sản phẩm gồm\n\n{p['in_box']}")
    bao_hanh = _khoi(_dong("Thời gian bảo hành", _don(p.get("warranty_months"), "tháng")), p.get("warranty_note"))
    if bao_hanh:
        phan.append(f"## Bảo hành\n\n{bao_hanh}")
    return "\n\n".join(x for x in phan if x)


async def _load_product(conn: asyncpg.Connection, record_id: int) -> TextDoc | None:
    p = await conn.fetchrow(
        """SELECT p.*, b.name AS brand, c.name AS category, s.name AS series
             FROM shop.products p
             JOIN shop.brands b ON b.id = p.brand_id
             JOIN shop.categories c ON c.id = p.category_id
             LEFT JOIN shop.series s ON s.id = p.series_id
            WHERE p.id = $1""",
        record_id,
    )
    if p is None or p["status"] == "draft":
        return None
    spec = await conn.fetchrow("SELECT * FROM shop.phone_specs WHERE product_id = $1", record_id)
    feats: dict[str, list[str]] = {}
    for r in await conn.fetch(
        """SELECT f.feature_group, f.name FROM shop.product_features pf
             JOIN shop.features f ON f.id = pf.feature_id
            WHERE pf.product_id = $1 ORDER BY f.feature_group, f.sort_order, f.name""",
        record_id,
    ):
        feats.setdefault(r["feature_group"], []).append(r["name"])
    colors = [
        r["name"]
        for r in await conn.fetch(
            "SELECT name FROM shop.product_colors WHERE product_id = $1 ORDER BY sort_order, id", record_id
        )
    ]
    variants = await conn.fetch(
        """SELECT DISTINCT ram_gb, storage_gb, storage_available_gb, condition
             FROM shop.product_variants WHERE product_id = $1
            ORDER BY condition, ram_gb NULLS FIRST, storage_gb NULLS FIRST""",
        record_id,
    )
    tags = [
        r["name"]
        for r in await conn.fetch(
            """SELECT t.name FROM shop.product_tags pt JOIN shop.tags t ON t.id = pt.tag_id
                WHERE pt.product_id = $1 ORDER BY t.kind, t.name""",
            record_id,
        )
    ]
    text = product_text(
        dict(p),
        spec=dict(spec) if spec else None,
        features=feats,
        colors=colors,
        variants=[dict(v) for v in variants],
        tags=tags,
    )
    meta = DocMeta(product_id=p["id"], brand_id=p["brand_id"], brand=p["brand"], category=p["category"])
    return TextDoc(doc_type="product", record_id=record_id, title=p["name"], text=text, meta=meta)


# ─── Chính sách · gói dịch vụ ───────────────────────────────────────────────────

LOAI_CHINH_SACH = {
    "warranty": "Bảo hành",
    "return_exchange": "Đổi trả",
    "installment": "Trả góp",
    "delivery": "Giao hàng",
    "payment": "Thanh toán",
    "unboxing": "Đồng kiểm / mở hộp",
    "trade_in": "Thu cũ đổi mới",
    "privacy": "Bảo mật thông tin",
    "other": "Khác",
}
LOAI_DICH_VU = {
    "extended_warranty": "Bảo hành mở rộng",
    "drop_damage": "Bảo hành rơi vỡ",
    "one_to_one_exchange": "1 đổi 1",
    "insurance": "Bảo hiểm",
    "other": "Khác",
}


def _pham_vi(r: Row) -> str:
    phan = [
        x for x in (r.get("brand") and f"hãng {r['brand']}", r.get("category") and f"ngành hàng {r['category']}") if x
    ]
    return "Áp dụng cho " + " · ".join(phan) if phan else "Áp dụng cho mọi sản phẩm"


def policy_text(r: Row) -> str:
    hieu_luc = _ngay(r.get("effective_from"))
    if r.get("effective_to"):
        hieu_luc = f"{hieu_luc} đến {_ngay(r['effective_to'])}"
    dau = _khoi(
        _dong("Loại chính sách", LOAI_CHINH_SACH.get(r.get("policy_type") or "")),
        _dong("Phạm vi", _pham_vi(r)),
        _dong("Hiệu lực từ", hieu_luc),
    )
    return "\n\n".join(x for x in (f"# {r['title']}", dau, r.get("summary"), r.get("content_md")) if x)


def service_package_text(r: Row) -> str:
    dau = _khoi(
        _dong("Loại dịch vụ", LOAI_DICH_VU.get(r.get("service_type") or "")),
        _dong("Thời hạn", _don(r.get("duration_months"), "tháng")),
        _dong("Phạm vi", _pham_vi(r)),
    )
    dieu_khoan = f"## Điều khoản\n\n{r['terms_md']}" if r.get("terms_md") else ""
    return "\n\n".join(x for x in (f"# {r['name']}", dau, dieu_khoan) if x)


_JOIN_PHAM_VI = """LEFT JOIN shop.brands b ON b.id = x.brand_id
                   LEFT JOIN shop.categories c ON c.id = x.category_id"""


async def _load_policy(conn: asyncpg.Connection, record_id: int) -> TextDoc | None:
    r = await conn.fetchrow(
        f"SELECT x.*, b.name AS brand, c.name AS category FROM shop.policies x {_JOIN_PHAM_VI} WHERE x.id = $1",
        record_id,
    )
    if r is None or not r["is_active"]:
        return None
    meta = DocMeta(brand_id=r["brand_id"], brand=r["brand"], category=r["category"])
    return TextDoc(doc_type="policy", record_id=record_id, title=r["title"], text=policy_text(dict(r)), meta=meta)


async def _load_service_package(conn: asyncpg.Connection, record_id: int) -> TextDoc | None:
    r = await conn.fetchrow(
        f"SELECT x.*, b.name AS brand, c.name AS category FROM shop.service_packages x {_JOIN_PHAM_VI} WHERE x.id = $1",
        record_id,
    )
    if r is None or not r["is_active"]:
        return None
    meta = DocMeta(brand_id=r["brand_id"], brand=r["brand"], category=r["category"])
    return TextDoc(
        doc_type="service_package", record_id=record_id, title=r["name"], text=service_package_text(dict(r)), meta=meta
    )


# ─── Bài viết · FAQ ─────────────────────────────────────────────────────────────

LOAI_BAI = {"overview": "Giới thiệu", "review": "Đánh giá", "news": "Tin tức", "buying_guide": "Tư vấn chọn mua"}


def article_text(r: Row, products: Iterable[str]) -> str:
    dau = _khoi(_dong("Loại bài", LOAI_BAI.get(r.get("kind") or "")), _dong("Sản phẩm liên quan", _noi(products)))
    return "\n\n".join(x for x in (f"# {r['title']}", dau, r.get("content_md")) if x)


def faq_text(r: Row) -> str:
    return "\n\n".join(
        x for x in (f"# Hỏi: {r['question']}", _dong("Sản phẩm", r.get("product")), f"Trả lời: {r['answer']}") if x
    )


async def _load_article(conn: asyncpg.Connection, record_id: int) -> TextDoc | None:
    r = await conn.fetchrow("SELECT * FROM shop.articles WHERE id = $1", record_id)
    if r is None or r["published_at"] is None:
        return None
    sp = await conn.fetch(
        """SELECT p.id, p.name, p.brand_id, b.name AS brand, c.name AS category
             FROM shop.article_products ap
             JOIN shop.products p ON p.id = ap.product_id
             JOIN shop.brands b ON b.id = p.brand_id
             JOIN shop.categories c ON c.id = p.category_id
            WHERE ap.article_id = $1 ORDER BY p.name, p.id""",
        record_id,
    )
    # Một sản phẩm ⇒ đủ khoá lọc như tài liệu riêng của máy đó; nhiều sản phẩm (bài so sánh)
    # ⇒ chỉ `product_ids` — gán một hãng/ngành cho bài so sánh hai hãng là lọc sai.
    mot = sp[0] if len(sp) == 1 else None
    meta = DocMeta(
        product_id=mot["id"] if mot else None,
        brand_id=mot["brand_id"] if mot else None,
        brand=mot["brand"] if mot else None,
        category=mot["category"] if mot else None,
        product_ids=tuple(x["id"] for x in sp),
    )
    text = article_text(dict(r), [x["name"] for x in sp])
    return TextDoc(doc_type="article", record_id=record_id, title=r["title"], text=text, meta=meta)


async def _load_faq(conn: asyncpg.Connection, record_id: int) -> TextDoc | None:
    r = await conn.fetchrow(
        """SELECT f.*, p.name AS product, p.status AS product_status, p.brand_id, b.name AS brand, c.name AS category
             FROM shop.faqs f
             LEFT JOIN shop.products p ON p.id = f.product_id
             LEFT JOIN shop.brands b ON b.id = p.brand_id
             LEFT JOIN shop.categories c ON c.id = p.category_id
            WHERE f.id = $1""",
        record_id,
    )
    if r is None or r["product_status"] == "draft":
        return None
    meta = DocMeta(product_id=r["product_id"], brand_id=r["brand_id"], brand=r["brand"], category=r["category"])
    return TextDoc(doc_type="faq", record_id=record_id, title=r["question"], text=faq_text(dict(r)), meta=meta)


# ─── Ảnh sản phẩm ───────────────────────────────────────────────────────────────

LOAI_MEDIA = {"image": "Ảnh", "video": "Video", "image_360": "Ảnh 360°", "thumbnail": "Ảnh đại diện"}


def media_caption(r: Row) -> str:
    """`Ảnh iPhone 16 Pro màu Titan sa mạc. <alt>` — đủ để agent tìm ảnh theo máy + màu
    mà không cần VLM mô tả. alt trùng tên máy thì không lặp."""
    dau = f"{LOAI_MEDIA.get(r.get('media_type') or '', 'Ảnh')} {r['product']}"
    if r.get("color"):
        dau += f" màu {r['color']}"
    alt = (r.get("alt_text") or "").strip()
    return f"{dau}. {alt}" if alt and alt != r["product"] else dau


async def _load_media(conn: asyncpg.Connection, record_id: int) -> MediaDoc | None:
    r = await conn.fetchrow(
        """SELECT m.*, p.name AS product, p.status AS product_status, p.brand_id,
                  b.name AS brand, c.name AS category, pc.name AS color
             FROM shop.product_media m
             JOIN shop.products p ON p.id = m.product_id
             JOIN shop.brands b ON b.id = p.brand_id
             JOIN shop.categories c ON c.id = p.category_id
             LEFT JOIN shop.product_colors pc ON pc.id = m.color_id
            WHERE m.id = $1""",
        record_id,
    )
    if r is None or r["product_status"] == "draft":
        return None
    meta = DocMeta(product_id=r["product_id"], brand_id=r["brand_id"], brand=r["brand"], category=r["category"])
    return MediaDoc(
        record_id=record_id,
        title=r["product"],
        caption=media_caption(dict(r)),
        media_type=r["media_type"],
        media_url=r["url"],
        color=r["color"],
        meta=meta,
    )


# ─── Điểm vào ───────────────────────────────────────────────────────────────────

LOADERS: dict[str, Callable[[asyncpg.Connection, int], Any]] = {
    "product": _load_product,
    "policy": _load_policy,
    "article": _load_article,
    "faq": _load_faq,
    "service_package": _load_service_package,
    ENTITY_MEDIA: _load_media,
}

SOURCE_TABLES: dict[str, str] = {
    "product": "products",
    "policy": "policies",
    "article": "articles",
    "faq": "faqs",
    "service_package": "service_packages",
    ENTITY_MEDIA: "product_media",
}
"""Bảng chứa id của entity — `kb_reindex_all` quét những bảng này."""


async def load(conn: asyncpg.Connection, entity: str, record_id: int) -> TextDoc | MediaDoc | None:
    loader = LOADERS.get(entity)
    if loader is None:
        raise ValueError(f"entity lạ: {entity!r}")
    return await loader(conn, record_id)


def content_hash(doc: TextDoc | MediaDoc) -> str:
    """Băm MỌI thứ đi vào point (văn bản + khoá lọc): đổi tên hãng cũng phải nạp lại,
    không thì payload `brand` cũ nằm mãi vì nội dung chính không đổi."""
    if isinstance(doc, MediaDoc):
        than = [doc.caption, doc.media_type, doc.media_url, doc.title, doc.color]
    else:
        than = [doc.title, doc.text]
    return hashlib.sha256(json.dumps([than, doc.meta.payload()], ensure_ascii=False).encode()).hexdigest()
