"""`ConfigPayload.tts_normalization` — từ điển cách đọc TTS của tenant.

Bốn phép validate ở đây đều chặn một lỗi HỎNG IM LẶNG, không phải lỗi thẩm mỹ: khoá trùng
thì JSON lấy giá trị cuối mà không ai biết; khoá có khoảng trắng ở mép thì `\\b` bên agent
không bao giờ khớp và mục đó vô hiệu vĩnh viễn.
"""

import pytest
from pydantic import ValidationError

from portal.modules.config.contracts import ConfigPayload
from tests.modules.config.conftest import PAYLOAD_HOP_LE


def _payload(entries: list[dict]) -> dict:
    return {**PAYLOAD_HOP_LE, "tts_normalization": entries}


def test_mac_dinh_la_danh_sach_rong():
    """Trường THÊM, có default — nên mọi payload v3 cũ vẫn validate được."""
    assert ConfigPayload.model_validate(PAYLOAD_HOP_LE).tts_normalization == []


def test_nhan_muc_hop_le():
    cfg = ConfigPayload.model_validate(_payload([{"term": "NCLB", "read_as": "Noble Crystal Long Biên"}]))

    assert cfg.tts_normalization[0].term == "NCLB"
    assert cfg.tts_normalization[0].read_as == "Noble Crystal Long Biên"


def test_giu_nguyen_thu_tu_nguoi_dung_nhap():
    cfg = ConfigPayload.model_validate(
        _payload(
            [
                {"term": "SSLC", "read_as": "Sunshine Legend City"},
                {"term": "NCLB", "read_as": "Noble Crystal Long Biên"},
            ]
        )
    )

    assert [e.term for e in cfg.tts_normalization] == ["SSLC", "NCLB"]


def test_tu_choi_khoa_trung_khong_phan_biet_hoa_thuong():
    """`NCLB` và `nclb` là một khoá với người dùng. Hai dòng trông giống nhau cho hai kết
    quả khác nhau là bẫy không đáng bán."""
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(
            _payload(
                [
                    {"term": "NCLB", "read_as": "Noble Crystal Long Biên"},
                    {"term": "nclb", "read_as": "Noble Crystal Long Biên 2"},
                ]
            )
        )


def test_tu_choi_khoang_trang_o_mep():
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(_payload([{"term": " NCLB", "read_as": "Noble"}]))


def test_tu_choi_term_trung_read_as():
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(_payload([{"term": "NCLB", "read_as": "NCLB"}]))


def test_tu_choi_ky_tu_dieu_khien():
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(_payload([{"term": "NC\tLB", "read_as": "Noble"}]))


def test_tu_choi_qua_tran_200_muc():
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(_payload([{"term": f"MA{i}", "read_as": f"Mã số {i}"} for i in range(201)]))


def test_tu_choi_truong_la_trong_muc():
    """`_Nghiem` chặn trường lạ ở MỌI tầng — một `kind` bị nuốt im lặng là chỗ FE gõ sai
    tên trường mà không ai biết."""
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(_payload([{"term": "NCLB", "read_as": "Noble", "kind": "abbrev"}]))
