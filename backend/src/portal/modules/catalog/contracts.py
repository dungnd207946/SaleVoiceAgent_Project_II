"""Mặt tiền module catalog: DTO của hãng, ngành hàng, dòng máy, nhãn, từ điển tính năng."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from portal.core.crud import CamelIn
from portal.core.dto import CamelOut

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=120)]


class BrandIn(CamelIn):
    slug: Slug
    name: str = Field(min_length=1, max_length=120)
    country: str | None = None
    logo_url: str | None = None
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True


class BrandOut(CamelOut):
    id: int
    slug: str
    name: str
    country: str | None
    logo_url: str | None
    description: str | None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryIn(CamelIn):
    parent_id: int | None = None
    slug: Slug
    name: str = Field(min_length=1, max_length=120)
    sort_order: int = 0
    is_active: bool = True


class CategoryOut(CamelOut):
    id: int
    parent_id: int | None
    slug: str
    name: str
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SeriesIn(CamelIn):
    brand_id: int
    slug: Slug
    name: str = Field(min_length=1, max_length=120)


class SeriesOut(CamelOut):
    id: int
    brand_id: int
    slug: str
    name: str
    created_at: datetime


TagKind = Literal["need", "segment", "badge"]


class TagIn(CamelIn):
    kind: TagKind
    slug: Slug
    name: str = Field(min_length=1, max_length=120)


class TagOut(CamelOut):
    id: int
    kind: TagKind
    slug: str
    name: str


FeatureGroup = Literal[
    "rear_camera",
    "front_camera",
    "rear_video",
    "front_video",
    "battery_tech",
    "special",
    "ai",
    "wifi",
    "gps",
    "connectivity_other",
    "video_format",
    "audio_format",
]


class FeatureIn(CamelIn):
    feature_group: FeatureGroup
    name: str = Field(min_length=1, max_length=200)
    slug: Slug
    is_filterable: bool = False
    sort_order: int = 0


class FeatureOut(CamelOut):
    id: int
    feature_group: FeatureGroup
    name: str
    slug: str
    is_filterable: bool
    sort_order: int
