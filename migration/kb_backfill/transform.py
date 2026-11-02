"""Pure Mongo-nbx → Postgres-KB row mapping (no I/O). See the SP2 spec §4."""
from __future__ import annotations

import json
import unicodedata


def _to_vnd(price_ty) -> int | None:
    try:
        return int(round(float(price_ty) * 1e9))
    except (TypeError, ValueError):
        return None


def _to_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _bedrooms(unit_type_name: str) -> int | None:
    s = (unit_type_name or "").strip().upper()
    if s.endswith("PN") and s[:-2].strip().isdigit():
        return int(s[:-2].strip())
    if s == "STUDIO":
        return 0
    return None


def _fold(s: str) -> str:
    s = (s or "").replace("đ", "d").replace("Đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())


# folded free-text direction -> canonical 8-enum (both token orders covered).
_DIR_MAP = {
    "dong": "dong", "tay": "tay", "nam": "nam", "bac": "bac",
    "dong bac": "dong_bac", "bac dong": "dong_bac",
    "dong nam": "dong_nam", "nam dong": "dong_nam",
    "tay bac": "tay_bac", "bac tay": "tay_bac",
    "tay nam": "tay_nam", "nam tay": "tay_nam",
}


def _fold_direction(raw, stats: dict) -> str | None:
    if not raw:
        return None
    f = _fold(str(raw)).replace("-", " ").replace("_", " ")
    # live nbx_units often concatenates a scraped area figure after the direction,
    # e.g. "Đông Nam Thông thủy 54.4 m² -->" — drop the "thong thuy ..." garbage tail.
    f = f.split("thong thuy")[0]
    f = " ".join(f.split())
    hit = _DIR_MAP.get(f)
    if hit is None:
        stats["direction_unmapped"] = stats.get("direction_unmapped", 0) + 1
    return hit


_STATUS_MAP = {"available": "available", "ready": "available", "sold": "sold", "locked": "booked"}


def _sale_status(raw, stats: dict) -> str:
    s = (raw or "").strip().lower()
    hit = _STATUS_MAP.get(s)
    if hit is None:
        stats["sale_status_fallback"] = stats.get("sale_status_fallback", 0) + 1
        return "available"
    return hit


# project `type` -> default single product_type when a unit's own type is unknown.
_TYPE_DEFAULT = {"cao_tang": "chung_cu", "thap_tang": "biet_thu", "hon_hop": "chung_cu"}


def _product_type(unit_type_name: str, project_type: str, stats: dict) -> str | None:
    if (unit_type_name or "").strip().upper().startswith("STU"):
        return "studio"
    hit = _TYPE_DEFAULT.get((project_type or "").strip().lower())
    if hit is None:
        stats["product_type_null"] = stats.get("product_type_null", 0) + 1
    return hit


def _category_from_type(project_type: str) -> list[str]:
    t = (project_type or "").strip().lower()
    if t == "hon_hop":
        return sorted(["chung_cu", "biet_thu"])
    d = _TYPE_DEFAULT.get(t)
    return [d] if d else []


def _overview_obj(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def project_code_of(doc: dict) -> str:
    return str(doc.get("projectCode") or "").strip().upper()


def unit_row(u: dict, project_code: str, project_type: str, stats: dict) -> dict:
    ut_raw = u.get("unitType")
    if isinstance(ut_raw, dict):
        ut_name = ut_raw.get("name", "")
    else:
        # live nbx_units mostly carries unitType as a bare code string (e.g. "STU"/"LK")
        # or None, not a dict — use the raw string itself as the type-code signal (so a
        # bare "STU" still resolves to product_type=studio below) and count the fallback.
        stats["unittype_string_fallback"] = stats.get("unittype_string_fallback", 0) + 1
        ut_name = ut_raw if isinstance(ut_raw, str) else ""
    area = _to_float(u.get("area"))
    price = _to_vnd(u.get("price"))
    ppm2 = round(price / area) if (price is not None and area) else None
    return {
        "project_code": project_code,
        "unit_code": u.get("code") or "",
        "product_type": _product_type(ut_name, project_type, stats),
        "bedrooms": _bedrooms(ut_name),
        "direction": _fold_direction(u.get("direction"), stats),
        "area_built_m2": area,
        "area_wall_m2": _to_float(u.get("areaBuild")),
        "price_vnd": price,
        "price_per_m2_vnd": ppm2,
        "sale_status": _sale_status(u.get("status"), stats),
        "image_url": u.get("image") or None,
    }


def project_row(doc: dict, unit_rows: list[dict]) -> dict:
    ov = _overview_obj(doc.get("overview"))
    cats = sorted({r["product_type"] for r in unit_rows if r.get("product_type")})
    if not cats:
        cats = _category_from_type(doc.get("type", ""))
    return {
        "project_code": project_code_of(doc),
        "name": doc.get("name") or "",
        "category": cats,
        "region": doc.get("areaRegion") or None,
        "address": doc.get("location") or None,
        "investor": doc.get("investor") or None,
        "product_scale": ov.get("scale") or None,
        "ownership_form": ov.get("ownership") or None,
        "overview": doc.get("description") or None,
        "sale_phase": "dang_ban",
    }
