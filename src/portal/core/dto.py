"""Gốc chung cho DTO đọc dựng thẳng từ một hàng DB."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelOut(BaseModel):
    """Field snake_case khớp tên cột, trên dây là camelCase (FastAPI serialize theo alias).

    Dựng bằng `XxxOut.model_validate(dict(hang))` khi mọi field là cột cùng tên — có cột
    phải đổi tên/tính toán thì giữ cách dựng tay.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
