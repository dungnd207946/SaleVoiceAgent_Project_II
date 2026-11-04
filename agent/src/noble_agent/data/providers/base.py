"""Data-provider contract — canonical DTOs, capabilities, Protocol.

The stable boundary between agent tools and any data source (currently the
Postgres KB — see docs/BA-docs/db-design/db-design/02a-real-estate-template.md).
Providers map their native rows onto these DTOs and speak only in canonical
units (price=VND int, area=m² float, region / type / status = canonical
enums). Missing field → None (never fabricated).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

ESCALATE_SIGNAL = "Thông tin đã được chuyển đến chuyên viên tư vấn"


class Capability(StrEnum):
    LISTING = "listing"
    OVERVIEW = "overview"
    UNIT_SEARCH = "unit_search"


# ── DTOs (frozen; Optional where the field is not guaranteed) ────────────────
@dataclass(frozen=True)
class ProjectSummary:
    code: str
    name: str
    region: str
    category: tuple[str, ...]
    investor: str = ""
    price_from_vnd: int | None = None   # project entry price if source exposes one; else None
    sale_phase: str = ""
    # Selling material for the over-budget pitch (agent/tools/upsell.py). Only
    # populated where the source query selects it (discover); None elsewhere.
    amenities: str | None = None


@dataclass(frozen=True)
class ProjectList:
    count: int
    projects: list[ProjectSummary]
    region: str = ""
    note: str = ""


@dataclass(frozen=True)
class ProjectDiscovery:
    total: int                          # total matches BEFORE the page slice
    projects: list[ProjectSummary]      # already ranked (stable total order) + sliced [offset, offset+limit)


@dataclass(frozen=True)
class ProjectOverview:
    code: str
    name: str
    region: str | None = None
    address: str | None = None
    investor: str | None = None
    developer: str | None = None
    total_land_area_m2: float | None = None
    floor_area_m2: float | None = None
    build_density_pct: float | None = None
    product_scale: str | None = None
    amenities: str | None = None
    ownership_form: str | None = None
    handover_standard: str | None = None
    total_investment_vnd: int | None = None
    sale_phase: str | None = None
    overview: str | None = None
    link_360: str | None = None


@dataclass(frozen=True)
class Unit:
    project_code: str
    project_name: str
    zone_code: str | None
    unit_code: str
    product_type: str | None
    bedrooms: int | None
    block: str | None
    floor: int | None
    num_floors: int | None
    direction: str | None
    area_built_m2: float | None    # diện tích thông thủy
    area_wall_m2: float | None     # diện tích tim tường
    area_land_m2: float | None     # diện tích đất (nhà thấp tầng)
    price_vnd: int | None
    price_per_m2_vnd: int | None
    sale_status: str                # available | booked | sold
    image_url: str | None
    # Project amenities carried onto the unit row (selling material for the
    # over-budget pitch — agent/tools/upsell.py). None where not selected.
    amenities: str | None = None


@dataclass(frozen=True)
class Document:
    project_code: str
    title: str
    body: str
    file_url: str | None = None


@dataclass(frozen=True)
class ProjectRegistryRow:
    code: str
    name: str
    region: str
    type: str


# ── Query objects (all values already canonical) ─────────────────────────────
@dataclass(frozen=True)
class UnitQuery:
    project_code: str  # "" = tìm xuyên TẤT CẢ dự án
    product_type: str = ""
    max_price_vnd: int = 0
    direction: str = ""
    floor: int = 0
    block: str = ""
    unit_code: str = ""
    sale_status: str = "available"
    min_area_built_m2: float = 0.0
    max_area_built_m2: float = 0.0  # 0 = không chặn trên; tool đặt cả hai cho "tầm X m²"
    # union recommend → search (merge 2026-09-07)
    bedrooms: int = 0
    region: str = ""  # khớp cụm fold-dấu trên region+address+name, y hệt discover_projects


@dataclass(frozen=True)
class DiscoverQuery:
    region: str = ""
    budget_max_vnd: int = 0
    product_type: str = ""      # canonical enum value
    purpose: str = ""           # canonical enum value (advisory, not a filter)
    investor: str = ""
    sale_phase: str = ""
    offset: int = 0
    limit: int = 5


@runtime_checkable
class DataProvider(Protocol):
    name: str
    capabilities: frozenset[Capability]

    async def list_projects(self, *, region: str = "") -> ProjectList | None: ...
    async def get_overview(self, project_code: str) -> ProjectOverview | None: ...
    async def search_units(self, query: UnitQuery) -> list[Unit] | None: ...
    async def discover_projects(self, query: DiscoverQuery) -> ProjectDiscovery | None: ...
    async def get_document(self, project_code: str, query: str = "") -> list[Document] | None: ...

    async def warm(self) -> None: ...
    async def warm_if_stale(self, ttl_sec: float) -> None: ...
    def registry_rows(self) -> list[ProjectRegistryRow]: ...
    def cached_codes(self) -> list[str]: ...
    def code_to_name(self) -> dict[str, str]: ...
