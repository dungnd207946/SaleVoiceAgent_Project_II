"""Mặt tiền module reviews: đánh giá sản phẩm và hỏi đáp."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from portal.core.crud import CamelIn
from portal.core.dto import CamelOut

TrangThai = Literal["pending", "published", "hidden"]


class ReviewIn(CamelIn):
    product_id: int
    variant_id: int | None = None
    customer_id: int | None = None
    author_name: str = Field(min_length=1, max_length=120)
    rating: int = Field(ge=1, le=5)
    content: str | None = None
    is_verified_purchase: bool = False
    status: TrangThai = "pending"


class ReviewPatch(CamelIn):
    """`staffReply` khác null → đóng dấu `repliedAt`; null → gỡ trả lời và dấu."""

    status: TrangThai | None = None
    staff_reply: str | None = None


class ReviewOut(CamelOut):
    id: int
    product_id: int
    variant_id: int | None
    customer_id: int | None
    author_name: str
    rating: int
    content: str | None
    is_verified_purchase: bool
    helpful_count: int
    status: TrangThai
    staff_reply: str | None
    replied_at: datetime | None
    created_at: datetime


class QuestionIn(CamelIn):
    product_id: int
    customer_id: int | None = None
    author_name: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1)
    status: TrangThai = "pending"


class QuestionPatch(CamelIn):
    """`answer` khác null → đóng dấu `answeredAt`. KHÔNG tự đổi status: duyệt là việc tường minh."""

    status: TrangThai | None = None
    answer: str | None = None


class QuestionOut(CamelOut):
    id: int
    product_id: int
    customer_id: int | None
    author_name: str
    question: str
    answer: str | None
    answered_at: datetime | None
    status: TrangThai
    created_at: datetime
