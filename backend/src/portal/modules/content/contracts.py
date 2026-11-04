"""Mặt tiền module content: bài viết (giới thiệu/đánh giá/tin/tư vấn) + liên kết sản phẩm."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from portal.core.crud import CamelIn
from portal.core.dto import CamelOut

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=200)]
ArticleKind = Literal["overview", "review", "news", "buying_guide"]


class ArticleIn(CamelIn):
    kind: ArticleKind
    slug: Slug
    title: str = Field(min_length=1, max_length=300)
    content_md: str = Field(min_length=1)
    published_at: datetime | None = None  # NULL = nháp; tương lai = hẹn giờ đăng


class ArticleOut(CamelOut):
    id: int
    kind: ArticleKind
    slug: str
    title: str
    content_md: str
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ArticleProductsIn(CamelIn):
    product_ids: list[int] = Field(max_length=500)


class ArticleProductOut(CamelOut):
    product_id: int
    name: str
    slug: str
