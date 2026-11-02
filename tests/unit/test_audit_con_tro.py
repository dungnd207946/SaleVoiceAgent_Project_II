"""Con trỏ keyset của `GET /audit`: đục, tròn hai chiều, và mọi thứ không đúng
dạng là LỖI chứ không phải «trang đầu» (trả trang đầu âm thầm làm FE cuộn vô tận)."""

from datetime import UTC, datetime, timedelta

import pytest

from portal.modules.audit.contracts import LoiConTro, doc_con_tro, ma_con_tro

LUC = datetime(2026, 8, 25, 3, 12, 44, 120931, tzinfo=UTC)


def test_tron_hai_chieu() -> None:
    assert doc_con_tro(ma_con_tro(LUC, 412)) == (LUC, 412)


def test_giu_microsecond_va_mui_gio() -> None:
    """`luc` là timestamptz microsecond; mất một trong hai là keyset `(luc, id) <`
    lệch một hàng ở biên trang."""
    luc, _ = doc_con_tro(ma_con_tro(LUC + timedelta(microseconds=7), 1))
    assert luc == LUC + timedelta(microseconds=7)
    assert luc.tzinfo is not None


def test_duc_khong_doc_duoc_bang_mat() -> None:
    assert "2026" not in ma_con_tro(LUC, 412)
    assert "=" not in ma_con_tro(LUC, 412)


@pytest.mark.parametrize("rac", ["", "abc", "NDEy", "MjAyNi0wOC0yNXw0MTI", "bm90fGRhdGV8MQ"])
def test_rac_nem_loi_con_tro(rac: str) -> None:
    # "NDEy" = base64("412") — dạng CŨ chỉ có id; "MjAyNi0wOC0yNXw0MTI" = "2026-08-25|412"
    # thiếu múi giờ. Cả hai phải bị từ chối, không «đoán».
    with pytest.raises(LoiConTro):
        doc_con_tro(rac)
