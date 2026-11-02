"""Kiểm tra kỹ năng trong payload — phần không đổi giữa v1 và v2.

Chín ô và hai preset ở `test_contracts_m5.py`. File này giữ đúng những luật về
`tools.enabled`, vì chúng là chỗ AG_01 BR03 và cổng 6 của M5 cùng dựa vào.
"""

import pytest
from pydantic import ValidationError

from portal.modules.config.contracts import ConfigPayload

HOP_LE = {
    "schema_version": 3,
    "danh_tinh": {"ten_agent": "Mai", "ten_thuong_hieu": "An Phú Land"},
    "pham_vi": {"phong_ban": [{"ten": "CSKH", "khi_nao": "khách hỏi hợp đồng đã ký"}]},
    "tools": {"enabled": ["find_project", "kb_search"]},
}


def test_payload_hop_le_parse_duoc():
    cfg = ConfigPayload.model_validate(HOP_LE)

    assert cfg.danh_tinh.ten_agent == "Mai"
    assert cfg.tools.enabled == ["find_project", "kb_search"]


def test_tu_choi_ky_nang_khong_ton_tai():
    """Bật một tool agent không đăng ký ⇒ prompt dạy gọi một thứ không có schema."""
    xau = {**HOP_LE, "tools": {"enabled": ["find_project", "toi_bia_ra"]}}

    with pytest.raises(ValidationError, match="toi_bia_ra"):
        ConfigPayload.model_validate(xau)


def test_tu_choi_khi_thieu_phu_thuoc():
    """Cổng 6 của M5, và nó phải chặn ở BE.

    Cảnh báo chỉ có ở FE là cảnh báo bỏ qua được bằng một `curl`. `booking` cần
    `find_project` vì mã dự án chỉ có một đường lấy.
    """
    xau = {**HOP_LE, "tools": {"enabled": ["booking", "kb_search"]}}

    with pytest.raises(ValidationError, match="find_project"):
        ConfigPayload.model_validate(xau)


def test_schema_version_bat_buoc():
    """Thiếu nó thì các hàng `config_versions` bất biến sau này không migrate được."""
    thieu = {k: v for k, v in HOP_LE.items() if k != "schema_version"}

    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(thieu)
