"""Cổng prompt: vertical tham chiếu profile nào thì profile đó phải có thật.

Gõ sai tên profile phải đỏ ở CI, không phải lúc worker gọi VLM lần đầu trên production.
"""

import pytest

from portal.modules.kb import prompts
from portal.modules.kb.directive.verticals import profiles
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE


def test_nap_duoc_tu_wheel():
    """Đọc bằng importlib.resources — Path(__file__).parent gãy khi chạy từ wheel."""
    assert prompts.load(), "prompts.yaml rỗng hoặc không nạp được"


def test_moi_profile_co_du_truong():
    for spec in prompts.load().values():
        assert spec.model, f"{spec.name} thiếu model"
        assert spec.max_tokens > 0, f"{spec.name} max_tokens phải dương"


def test_ba_profile_bat_buoc_ton_tai():
    ten = set(prompts.load())
    assert {"caption", "video_describe", "ocr_markdown"} <= ten


def test_vertical_khong_tham_chieu_profile_ma():
    """`profile_names()` nay đọc từ prompts.yaml, nên đây là phép so thật chứ không phải
    so với một danh sách chép tay ở file khác."""
    assert profiles.validate(REAL_ESTATE) == []


def test_profile_khong_ton_tai_thi_bao_loi():
    with pytest.raises(KeyError):
        prompts.get("khong_he_ton_tai")
