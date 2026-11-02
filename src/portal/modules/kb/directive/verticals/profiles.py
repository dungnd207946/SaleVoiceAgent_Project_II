"""Đối chiếu profile mà vertical tham chiếu với prompts.yaml của Portal.

TRƯỚC 2026-08-10 file này giữ một danh sách chép tay "bốn profile santa-models cài",
và docstring ghi "prompt do service own". Cả hai hết đúng: Portal tự chạy VLM nên
prompt về đây, và `profile_names()` nay ĐỌC TỪ prompts.yaml — hết một bản sao phải
đồng bộ tay.
"""

from portal.modules.kb import prompts
from portal.modules.kb.contracts import VerticalSpec

DEFAULT_CAPTION = "caption"


def profile_names() -> frozenset[str]:
    return frozenset(prompts.load())


def validate(vertical: VerticalSpec) -> list[str]:
    """Trả danh sách profile được tham chiếu nhưng không tồn tại."""
    referenced = set(vertical.caption_profiles.values()) | set(vertical.document_extract.values())
    return sorted(referenced - profile_names())
