"""Cổng chống lệch giữa từ điển nhãn và enum thật."""

from typing import get_args

from portal.modules.realestate import router
from portal.modules.realestate.contracts import PROJECT_TYPE_LABELS


def test_nhan_phu_dung_tap_gia_tri_cua_enum():
    """Thêm giá trị vào `_LoaiHinhDuAn` mà quên nhãn ⇒ mã thô lọt vào vector nhúng."""
    assert set(PROJECT_TYPE_LABELS) == set(get_args(router._LoaiHinhDuAn))


def test_moi_nhan_deu_co_chu_va_khac_ma():
    for ma, nhan in PROJECT_TYPE_LABELS.items():
        assert nhan.strip()
        assert nhan != ma
