"""Sổ lĩnh vực — mọi bài ở đây thuần, không cần Docker.

Sổ là bảng ánh xạ giữa BA hệ tên: `ma` FE (`NavSegment.linhVuc`), `vertical`
DB (CHECK của 0002), và sổ kỹ năng backend. Test đối chiếu từng cạnh — lệch
cạnh nào là màn /domains sai theo kiểu của cạnh đó.
"""

import pytest
from pydantic import ValidationError

from portal.modules.config.contracts import TEN_KY_NANG
from portal.modules.linh_vuc import so
from portal.modules.linh_vuc.contracts import DatLinhVucIn
from portal.modules.realestate.contracts import SENTINEL_TENANT


def test_ky_nang_chung_nam_trong_so_that():
    """3 kỹ năng chung phải là tên THẬT trong sổ 13 — gõ sai một tên là
    so_ky_nang() đếm sai mà không lỗi nào phát ra."""
    assert so.KY_NANG_CHUNG <= TEN_KY_NANG
    assert len(so.KY_NANG_CHUNG) == 3


def test_vertical_khop_check_cua_0002():
    """CHECK (vertical IN ('realestate','finance')) — literal chép từ 0002.
    Thêm lĩnh vực vào sổ mà quên nới CHECK thì INSERT nổ lúc chạy; bài này
    làm nó nổ lúc test."""
    assert {lv.vertical for lv in so.SO_LINH_VUC} <= {"realestate", "finance"}


def test_ma_khong_trung_va_dung_thu_tu():
    """Thứ tự cố định bds → taichinh: FE render theo thứ tự mảng."""
    assert [lv.ma for lv in so.SO_LINH_VUC] == ["bds", "taichinh"]


def test_so_ky_nang_hom_nay():
    """bds = 11 − 3 = 8 (mọi kỹ năng không-chung đều là BĐS hôm nay, kể cả
    `analyze_projects` — xem cảnh báo tương lai trong docstring so_ky_nang)."""
    bds, taichinh = so.SO_LINH_VUC
    assert so.so_ky_nang(bds) == len(TEN_KY_NANG) - len(so.KY_NANG_CHUNG) == 8
    assert so.so_ky_nang(taichinh) == 0


def test_theo_ma():
    assert so.theo_ma("bds") is not None
    assert so.theo_ma("realestate") is None  # vertical KHÔNG phải ma


def test_sentinel_khop_literal_trong_sql():
    """repo.co_du_lieu_bds (Task 3) viết literal '__ALL__' trong SQL (cổng
    cách ly đọc tĩnh, không expand biến) — bài này neo literal đó vào hằng
    thật của realestate."""
    assert SENTINEL_TENANT == "__ALL__"


def test_dat_linh_vuc_in_chan_khoa_la():
    with pytest.raises(ValidationError):
        DatLinhVucIn(bat=True, la="x")
