"""SQL đọc cho cửa hàng: thẻ sản phẩm, chi tiết, so sánh.

MỘT chỗ định nghĩa ba khái niệm mà danh sách, chi tiết và so sánh cùng dùng — tách ra
để ba màn không bao giờ báo ba giá khác nhau cho cùng một máy:
- `GIA_HIEN_TAI` / `GIA_THE`: giá bán một SKU và SKU đại diện cho thẻ.
- `dang_chay()`: KM/gói trả góp đang hiệu lực (cờ bật + trong khung giờ).
- `nham_toi()`: một dòng target (SP | SKU | hãng | ngành hàng) có nhắm tới SP `p` không.

Mọi bảng viết kèm schema `shop.` — pool không đặt `search_path`.
"""

from collections.abc import Sequence
from typing import Any

import asyncpg

GIA_HIEN_TAI = "coalesce({v}.sale_price_vnd, {v}.list_price_vnd)"


def gia(v: str) -> str:
    return GIA_HIEN_TAI.format(v=v)


def phan_tram_giam(niem_yet: str, ban: str) -> str:
    return f"round(100.0 * ({niem_yet} - {ban}) / {niem_yet})::int"


def dang_chay(a: str) -> str:
    """Hiệu lực = bật + đã bắt đầu + chưa kết thúc. `ends_at` NULL = không hạn."""
    return f"({a}.is_active AND now() >= {a}.starts_at AND ({a}.ends_at IS NULL OR now() < {a}.ends_at))"


def nham_toi(t: str, p: str) -> str:
    """Target nhắm SKU thì chỉ tính khi SKU đó thuộc SP — KM của một SKU vẫn là KM của trang SP."""
    return (
        f"({t}.product_id = {p}.id OR {t}.brand_id = {p}.brand_id OR {t}.category_id = {p}.category_id"
        f" OR {t}.variant_id IN (SELECT vv.id FROM shop.product_variants vv WHERE vv.product_id = {p}.id))"
    )


def km_ap_dung(p: str) -> str:
    return (
        f"SELECT pr.* FROM shop.promotions pr WHERE {dang_chay('pr')} AND EXISTS ("
        f"SELECT 1 FROM shop.promotion_targets t WHERE t.promotion_id = pr.id AND {nham_toi('t', p)})"
    )


def goi_ap_dung(p: str) -> str:
    return (
        f"SELECT ip.* FROM shop.installment_plans ip WHERE {dang_chay('ip')} AND EXISTS ("
        f"SELECT 1 FROM shop.installment_plan_targets t WHERE t.plan_id = ip.id AND {nham_toi('t', p)})"
    )


# SKU đại diện của thẻ: rẻ nhất trong nhóm còn bán được (còn hàng / đặt trước); SP chưa có SKU
# nào bán được (sắp về, hết hàng) thì rơi về rẻ nhất mọi SKU — thẻ vẫn có giá để hiện.
GIA_THE = f"""
SELECT v.id AS variant_id, {gia("v")} AS price_vnd, v.list_price_vnd
FROM shop.product_variants v
WHERE v.product_id = p.id
ORDER BY (v.sale_status IN ('in_stock', 'pre_order')) DESC, {gia("v")}, v.id
LIMIT 1
"""

# Quà/giảm thêm hiện trên thẻ: giá trị LỚN NHẤT của một KM đang chạy (discount_vnd hoặc phiếu mua
# hàng), không cộng dồn — các KM thường loại trừ nhau (choice_group), cộng lại là thổi phồng.
QUA_THE = f"""
SELECT max(greatest(km.discount_vnd, km.voucher_value_vnd)) AS gift_value_vnd
FROM ({km_ap_dung("p")}) km
"""


def sql_the(where: str) -> str:
    """Một hàng / sản phẩm, đủ cột cho `ProductCard`. Mọi phần phụ là LATERAL — không N+1."""
    return f"""
SELECT p.id, p.slug, p.name, p.status, p.phone_type, p.is_featured, p.release_date,
       p.rating_avg, p.rating_count, p.sold_count,
       b.id AS brand_id, b.name AS brand_name, b.slug AS brand_slug,
       sp.screen_size_inch, sp.display_tech, sp.resolution_class,
       g.variant_id, g.price_vnd, g.list_price_vnd,
       CASE WHEN g.list_price_vnd IS NOT NULL THEN {phan_tram_giam("g.list_price_vnd", "g.price_vnd")} END
         AS discount_percent,
       anh.url AS thumbnail,
       coalesce(ch.ram_options, '{{}}') AS ram_options,
       coalesce(ch.storage_options, '{{}}') AS storage_options,
       coalesce(nh.tags, '{{}}') AS tags,
       qua.gift_value_vnd,
       EXISTS (SELECT 1 FROM ({goi_ap_dung("p")}) gp WHERE gp.interest_rate_monthly = 0) AS has_installment_0
FROM shop.products p
JOIN shop.brands b ON b.id = p.brand_id
LEFT JOIN shop.phone_specs sp ON sp.product_id = p.id
LEFT JOIN LATERAL ({GIA_THE}) g ON true
LEFT JOIN LATERAL (
  -- ưu tiên ảnh 'thumbnail' khai riêng, không có thì ảnh thường đầu tiên
  SELECT m.url FROM shop.product_media m
  WHERE m.product_id = p.id AND m.media_type IN ('thumbnail', 'image')
  ORDER BY (m.media_type = 'thumbnail') DESC, m.sort_order, m.id LIMIT 1
) anh ON true
LEFT JOIN LATERAL (
  SELECT array_agg(DISTINCT v.ram_gb ORDER BY v.ram_gb) FILTER (WHERE v.ram_gb IS NOT NULL) AS ram_options,
         array_agg(DISTINCT v.storage_gb ORDER BY v.storage_gb) FILTER (WHERE v.storage_gb IS NOT NULL)
           AS storage_options
  FROM shop.product_variants v WHERE v.product_id = p.id
) ch ON true
LEFT JOIN LATERAL (
  SELECT array_agg(t.name ORDER BY t.name) AS tags
  FROM shop.product_tags pt JOIN shop.tags t ON t.id = pt.tag_id WHERE pt.product_id = p.id
) nh ON true
LEFT JOIN LATERAL ({QUA_THE}) qua ON true
WHERE {where}
"""


def ve_the(r: asyncpg.Record) -> dict[str, Any]:
    d = {k: v for k, v in dict(r).items() if k not in ("brand_id", "brand_name", "brand_slug", "_total")}
    d["brand"] = {"id": r["brand_id"], "name": r["brand_name"], "slug": r["brand_slug"]}
    return d


# Khoá sắp xếp → ORDER BY trên cột của CTE `the`. Luôn kết bằng id để phân trang ổn định.
SAP_XEP = {
    "featured": "is_featured DESC, sold_count DESC, id",
    "newest": "release_date DESC NULLS LAST, id DESC",
    "best_selling": "sold_count DESC, id",
    "discount": "discount_percent DESC NULLS LAST, id",
    "price_asc": "price_vnd ASC NULLS LAST, id",
    "price_desc": "price_vnd DESC NULLS LAST, id",
}


class BoLoc:
    """Gom mảnh WHERE + tham số bind; `$n` đánh số theo thứ tự thêm."""

    def __init__(self) -> None:
        self.trong: list[str] = []  # lọc trên p/b/sp — trước khi tính giá
        self.ngoai: list[str] = []  # lọc trên cột đã tính của thẻ (giá)
        self.ts: list[Any] = []

    def ts_moi(self, v: Any) -> str:
        self.ts.append(v)
        return f"${len(self.ts)}"


async def liet_ke_the(
    conn: asyncpg.Connection, loc: BoLoc, sap_xep: str, limit: int, offset: int
) -> tuple[list[asyncpg.Record], int]:
    trong = " AND ".join(loc.trong) or "true"
    ngoai = " AND ".join(loc.ngoai) or "true"
    n = len(loc.ts)
    rows = await conn.fetch(
        f"WITH the AS ({sql_the(trong)}) SELECT *, count(*) OVER () AS _total FROM the WHERE {ngoai} "
        f"ORDER BY {SAP_XEP[sap_xep]} LIMIT ${n + 1} OFFSET ${n + 2}",
        *loc.ts,
        limit,
        offset,
    )
    if rows:
        return rows, int(rows[0]["_total"])
    total = await conn.fetchval(f"WITH the AS ({sql_the(trong)}) SELECT count(*) FROM the WHERE {ngoai}", *loc.ts)
    return [], int(total)


async def the_theo_id(conn: asyncpg.Connection, ids: Sequence[int]) -> dict[int, asyncpg.Record]:
    """Thẻ cho trang chi tiết/so sánh/liên quan — mọi trạng thái trừ `draft` (máy ngừng bán vẫn so được)."""
    rows = await conn.fetch(sql_the("p.id = ANY($1::bigint[]) AND p.status <> 'draft'"), list(ids))
    return {r["id"]: r for r in rows}


# ---------------------------------------------------------------------------
# Chi tiết: mỗi phần một câu, đều lọc theo đúng một product_id — số câu cố định, không N+1.
# ---------------------------------------------------------------------------
SQL_SP = """
SELECT p.*, b.name AS b_name, b.slug AS b_slug, c.name AS c_name, c.slug AS c_slug,
       s.id AS s_id, s.name AS s_name, s.slug AS s_slug
FROM shop.products p
JOIN shop.brands b ON b.id = p.brand_id
JOIN shop.categories c ON c.id = p.category_id
LEFT JOIN shop.series s ON s.id = p.series_id
WHERE p.slug = $1 AND p.status <> 'draft'
"""

# Tồn khả dụng = tồn - đang giữ, chỉ cửa hàng/kho còn hoạt động.
SQL_SKU = f"""
SELECT v.id, v.sku, v.color_id, c.name AS color_name, v.ram_gb, v.storage_gb, v.condition, v.condition_note,
       v.list_price_vnd, {gia("v")} AS price_vnd, {phan_tram_giam("v.list_price_vnd", gia("v"))} AS discount_percent,
       v.sale_status, v.is_default,
       coalesce((SELECT sum(i.quantity - i.reserved_qty) FROM shop.inventory i
                 JOIN shop.stores st ON st.id = i.store_id AND st.is_active
                 WHERE i.variant_id = v.id), 0)::int AS qty_available
FROM shop.product_variants v
LEFT JOIN shop.product_colors c ON c.id = v.color_id
WHERE v.product_id = $1
ORDER BY v.sort_order, v.id
"""

SQL_TINH_NANG = """
SELECT f.id, f.feature_group, f.name, f.slug
FROM shop.product_features pf JOIN shop.features f ON f.id = pf.feature_id
WHERE pf.product_id = $1
ORDER BY f.feature_group, f.sort_order, f.id
"""

SQL_NHAN = """
SELECT t.id, t.kind, t.slug, t.name
FROM shop.product_tags pt JOIN shop.tags t ON t.id = pt.tag_id
WHERE pt.product_id = $1 ORDER BY t.kind, t.name
"""

SQL_FAQ = """
SELECT * FROM shop.faqs WHERE product_id = $1 OR product_id IS NULL
ORDER BY (product_id IS NULL), sort_order, id
"""

# KM/gói áp dụng: `applies_to_all_variants` = có target cấp SP/hãng/ngành; ngược lại chỉ các SKU trong
# `variant_ids` được hưởng — FE dùng để đổi KM hiện ra khi khách chọn phiên bản.
_PHAM_VI = """
  EXISTS (SELECT 1 FROM {bang} t WHERE t.{khoa} = x.id
          AND (t.product_id = p.id OR t.brand_id = p.brand_id OR t.category_id = p.category_id))
    AS applies_to_all_variants,
  ARRAY(SELECT t.variant_id FROM {bang} t JOIN shop.product_variants vv ON vv.id = t.variant_id
        WHERE t.{khoa} = x.id AND vv.product_id = p.id ORDER BY t.variant_id) AS variant_ids
"""

SQL_KM = f"""
SELECT x.*, gp.name AS gift_product_name,
{_PHAM_VI.format(bang="shop.promotion_targets", khoa="promotion_id")}
FROM shop.products p
CROSS JOIN LATERAL ({km_ap_dung("p")}) x
LEFT JOIN shop.products gp ON gp.id = x.gift_product_id
WHERE p.id = $1
ORDER BY x.priority DESC, x.id
"""

SQL_TRA_GOP = f"""
SELECT x.*, fp.code AS fp_code, fp.name AS fp_name, fp.partner_type AS fp_type,
{_PHAM_VI.format(bang="shop.installment_plan_targets", khoa="plan_id")}
FROM shop.products p
CROSS JOIN LATERAL ({goi_ap_dung("p")}) x
JOIN shop.finance_partners fp ON fp.id = x.partner_id AND fp.is_active
WHERE p.id = $1
ORDER BY x.interest_rate_monthly, x.tenor_months, x.id
"""

# Chính sách: NULL ở brand/category = áp cho mọi hãng/ngành; hiệu lực theo ngày.
SQL_CHINH_SACH = """
SELECT po.id, po.policy_type, po.slug, po.title, po.summary
FROM shop.policies po
WHERE po.is_active AND po.effective_from <= current_date
  AND (po.effective_to IS NULL OR po.effective_to >= current_date)
  AND (po.brand_id IS NULL OR po.brand_id = $1)
  AND (po.category_id IS NULL OR po.category_id = $2)
ORDER BY po.policy_type, po.id
"""

# Gói dịch vụ: như chính sách + khoảng giá máy (so với giá thẻ $4; NULL = không xét khoảng).
SQL_GOI_DV = """
SELECT sp.id, sp.code, sp.name, sp.service_type, sp.duration_months, sp.price_vnd, sp.price_percent, sp.terms_md
FROM shop.service_packages sp
WHERE sp.is_active
  AND (sp.brand_id IS NULL OR sp.brand_id = $1)
  AND (sp.category_id IS NULL OR sp.category_id = $2)
  AND ($3::bigint IS NULL OR ((sp.min_product_price_vnd IS NULL OR sp.min_product_price_vnd <= $3)
                              AND (sp.max_product_price_vnd IS NULL OR sp.max_product_price_vnd >= $3)))
ORDER BY sp.service_type, sp.duration_months, sp.id
"""

SQL_LIEN_QUAN = """
SELECT r.related_product_id, r.relation_type, r.sort_order
FROM shop.product_relations r WHERE r.product_id = $1
ORDER BY r.relation_type, r.sort_order, r.related_product_id
"""

SQL_DANH_GIA = """
SELECT rating, count(*)::int AS n FROM shop.product_reviews
WHERE product_id = $1 AND status = 'published' GROUP BY rating
"""
