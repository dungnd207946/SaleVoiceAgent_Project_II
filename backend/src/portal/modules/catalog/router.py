"""Danh mục: hãng · ngành hàng · dòng máy · nhãn nhu cầu · từ điển tính năng. Toàn bảng phẳng."""

from fastapi import APIRouter

from portal.core.crud import dang_ky_crud
from portal.modules.catalog.contracts import (
    BrandIn,
    BrandOut,
    CategoryIn,
    CategoryOut,
    FeatureIn,
    FeatureOut,
    SeriesIn,
    SeriesOut,
    TagIn,
    TagOut,
)

ROUTER = APIRouter()

dang_ky_crud(
    ROUTER,
    duong_dan="/brands",
    bang="brands",
    ten="hãng",
    model_in=BrandIn,
    model_out=BrandOut,
    tim_kiem=("name", "slug"),
    sap_xep="sort_order, id",
)
dang_ky_crud(
    ROUTER,
    duong_dan="/categories",
    bang="categories",
    ten="ngành hàng",
    model_in=CategoryIn,
    model_out=CategoryOut,
    loc={"parentId": "parent_id"},
    tim_kiem=("name", "slug"),
    sap_xep="sort_order, id",
)
dang_ky_crud(
    ROUTER,
    duong_dan="/series",
    bang="series",
    ten="dòng máy",
    model_in=SeriesIn,
    model_out=SeriesOut,
    loc={"brandId": "brand_id"},
    tim_kiem=("name", "slug"),
)
dang_ky_crud(
    ROUTER,
    duong_dan="/tags",
    bang="tags",
    ten="nhãn",
    model_in=TagIn,
    model_out=TagOut,
    tim_kiem=("name", "slug"),
    sap_xep="kind, id",
)
dang_ky_crud(
    ROUTER,
    duong_dan="/features",
    bang="features",
    ten="tính năng",
    model_in=FeatureIn,
    model_out=FeatureOut,
    tim_kiem=("name",),
    sap_xep="feature_group, sort_order, id",
)
