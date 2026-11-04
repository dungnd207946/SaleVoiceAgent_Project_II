"""DTO -> LLM-facing JSON. Isolated so the wire shape the model sees is frozen
independent of canonical DTO field names (SP1 KB-Postgres schema keys).
"""

from __future__ import annotations

from noble_agent.data.providers import base


def project_list_json(pl: base.ProjectList) -> dict:
    out: dict = {
        "count": pl.count,
        "projects": [
            {"code": s.code, "name": s.name, "category": list(s.category), "region": s.region}
            for s in pl.projects
        ],
    }
    if pl.region:
        out["region"] = pl.region
    if pl.note:
        out["note"] = pl.note
    return out


def discover_project_json(s: base.ProjectSummary) -> dict:
    return {
        "code": s.code,
        "name": s.name,
        "region": s.region,
        "category": list(s.category),
        "investor": s.investor,
        "price_from_vnd": s.price_from_vnd,
        "sale_phase": s.sale_phase,
    }


def overview_json(ov: base.ProjectOverview) -> dict:
    return {
        "code": ov.code,
        "name": ov.name,
        "region": ov.region or "",
        "address": ov.address or "",
        "investor": ov.investor or "",
        "developer": ov.developer or "",
        "total_land_area_m2": ov.total_land_area_m2,
        "floor_area_m2": ov.floor_area_m2,
        "build_density_pct": ov.build_density_pct,
        "product_scale": ov.product_scale or "",
        "amenities": ov.amenities or "",
        "ownership_form": ov.ownership_form or "",
        "handover_standard": ov.handover_standard or "",
        "total_investment_vnd": ov.total_investment_vnd,
        "sale_phase": ov.sale_phase or "",
        "overview": ov.overview or "",
        "link_360": ov.link_360 or "",
    }


def unit_json(u: base.Unit) -> dict:
    return {
        "unit_code": u.unit_code,
        "product_type": u.product_type,
        "bedrooms": u.bedrooms,
        "direction": u.direction or "",
        "block": u.block or "",
        "floor": u.floor,
        "num_floors": u.num_floors,
        "area_built_m2": u.area_built_m2,
        "area_wall_m2": u.area_wall_m2,
        "area_land_m2": u.area_land_m2,
        "price_vnd": u.price_vnd,
        "price_per_m2_vnd": u.price_per_m2_vnd,
        "sale_status": u.sale_status,
        "image_url": u.image_url or "",
        "project_code": u.project_code,
        "project_name": u.project_name,
    }
