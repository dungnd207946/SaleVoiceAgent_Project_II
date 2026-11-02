"""Hai luật cross-field của contract vai trò."""

import pytest
from pydantic import ValidationError

from portal.modules.auth.contracts import SuaVaiTroIn, TaoVaiTroIn


def test_ten_rong_bi_tu_choi():
    with pytest.raises(ValidationError):
        TaoVaiTroIn(name="   ", description=None, actions=[])


def test_vai_tro_khong_quyen_duoc_phep():
    """Đã tạo, chưa cấu hình là một trạng thái THẬT — spec §4.

    Chặn nó là bắt người dùng tích bừa một ô để lưu được.
    """
    v = TaoVaiTroIn(name="Tạm", description=None, actions=[])
    assert v.actions == []


def test_action_trung_bi_gom_lai():
    """Gửi trùng không phải lỗi của người dùng — PK (role_id, action_code) sẽ nổ
    ở tầng dưới, và một 500 cho một việc vô hại là sai."""
    v = TaoVaiTroIn(name="X", description=None, actions=["catalog.read", "catalog.read"])
    assert v.actions == ["catalog.read"]


def test_ten_duoc_trim():
    v = SuaVaiTroIn(name="  Trưởng nhóm  ", description=None, actions=[])
    assert v.name == "Trưởng nhóm"
