"""Khai báo real_estate — nguyên văn `rag_config["real_estate"]` (§15.1).

Thêm/bớt field embed, đổi nhãn, đổi caption profile → sửa ở đây. `units` không embed.
`zones` (và `buildings` lồng trong từng phân khu) là khối con của doc dự án, không phải doc riêng.
"""

import json

from portal.modules.kb.contracts import (
    MEDIA_VISUAL_REAL_ESTATE,
    ChildBlockSpec,
    EntitySpec,
    VerticalSpec,
    doc_type_of,
)
from portal.modules.realestate.contracts import DIRECTION_LABELS, PROJECT_TYPE_LABELS, SALE_PHASE_LABELS

ANCHOR_CODE_COL = "project_code"


def _ban_giao(v: object) -> str:
    """jsonb (chuỗi JSON hoặc list) → mỗi hạng mục một dòng «- Hạng mục: vật liệu · hãng · xuất xứ — ghi chú»."""
    hang_muc = json.loads(v) if isinstance(v, str) else v
    dong = []
    for h in hang_muc or []:
        chi_tiet = " · ".join(x for x in (h.get("material"), h.get("brand"), h.get("origin")) if x)
        ghi_chu = f" — {h['note']}" if h.get("note") else ""
        dong.append(f"- {h['item']}" + (f": {chi_tiet}" if chi_tiet else "") + ghi_chu)
    return "\n".join(dong)


def _so(v: object) -> str:
    """12000 → «12.000»."""
    return f"{round(float(v)):,}".replace(",", ".")


BUILDINGS = ChildBlockSpec(
    table="buildings",
    name_col="name",
    section="",
    subsection="Toà",
    fields=(
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
    ),
    field_labels={
        "num_floors": "Số tầng",
        "num_basements": "Số hầm",
        "units_per_floor": "Căn mỗi sàn",
        "elevators_passenger": "Thang máy khách",
        "elevators_service": "Thang máy hàng",
        "car_slots": "Chỗ đỗ ô tô",
        "moto_slots": "Chỗ đỗ xe máy",
        "ceiling_height_m": "Trần (m)",
        "facing": "Hướng toà",
        "sale_phase": "Giai đoạn bán",
        "amenities": "Tiện ích",
    },
    value_labels={"facing": DIRECTION_LABELS, "sale_phase": SALE_PHASE_LABELS},
    line_fields=("amenities",),
    parent_col="zone_code",
)

REAL_ESTATE = VerticalSpec(
    key="real_estate",
    anchor_table="projects",
    anchor_code_col=ANCHOR_CODE_COL,
    embed_sources=(
        EntitySpec(
            table="projects",
            doc_type="tong_quan",
            is_anchor=True,
            anchor_col=ANCHOR_CODE_COL,
            fields=(
                "region",
                "investor",
                "total_land_area_m2",
                "floor_area_m2",
                "build_density_pct",
                "product_scale",
                "ownership_form",
                "handover_standard",
                "total_investment_vnd",
                "overview",
                "amenities",
                "total_units",
                "num_buildings",
                "management_fee_vnd_m2",
                "parking_car_fee_vnd",
                "parking_moto_fee_vnd",
            ),
            field_labels={
                "region": "Khu vực",
                "investor": "Chủ đầu tư",
                "total_land_area_m2": "Diện tích đất",
                "floor_area_m2": "Diện tích sàn",
                "build_density_pct": "Mật độ xây dựng",
                "product_scale": "Quy mô sản phẩm",
                "ownership_form": "Hình thức sở hữu",
                "handover_standard": "Tiêu chuẩn bàn giao",
                "total_investment_vnd": "Tổng mức đầu tư",
                "overview": "Tổng quan",
                "amenities": "Tiện ích",
                "total_units": "Tổng số căn",
                "num_buildings": "Số toà",
                "management_fee_vnd_m2": "Phí quản lý (đồng/m²/tháng)",
                "parking_car_fee_vnd": "Phí gửi ô tô (đồng/xe/tháng)",
                "parking_moto_fee_vnd": "Phí gửi xe máy (đồng/xe/tháng)",
            },
            formatters={
                "handover_standard": _ban_giao,
                "total_units": _so,
                "management_fee_vnd_m2": _so,
                "parking_car_fee_vnd": _so,
                "parking_moto_fee_vnd": _so,
            },
            child_block=ChildBlockSpec(
                table="zones",
                name_col="name",
                section="Cơ cấu sản phẩm",
                subsection="Phân khu",
                fields=(
                    "category",
                    "sale_phase",
                    "total_units",
                    "num_buildings",
                    "product_scale",
                    "note",
                    "amenities",
                    "overview",
                ),
                field_labels={
                    "category": "Loại hình",
                    "sale_phase": "Giai đoạn bán",
                    "total_units": "Số căn",
                    "num_buildings": "Số toà",
                    "product_scale": "Quy mô",
                    "note": "Vị trí",
                    "amenities": "Tiện ích",
                },
                value_labels={"category": PROJECT_TYPE_LABELS, "sale_phase": SALE_PHASE_LABELS},
                line_fields=("note", "amenities"),
                key_col="zone_code",
                child=BUILDINGS,
                orphan_heading="Toà chưa gắn phân khu",
            ),
        ),
        EntitySpec(
            table="documents",
            doc_type="tai_lieu",
            fields=("body",),
            extra_cols=("file_url", "title", "thumb_url"),
            section_col="title",
            noi_dung_da_markdown=True,
            doc_type_from=doc_type_of,
        ),
    ),
    media_visual=MEDIA_VISUAL_REAL_ESTATE,
    caption_profiles={"default": "caption"},
    document_extract={"pdf_scan": "ocr_markdown"},
)
