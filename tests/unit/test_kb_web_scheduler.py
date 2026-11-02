"""`scheduler.next_run` — mốc kế tiếp theo giờ VN cho ba nhịp."""

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from portal.modules.kb.web.scheduler import next_run

VN = ZoneInfo("Asia/Ho_Chi_Minh")


def vn(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=VN)


def test_dem_hom_nay_neu_chua_toi_gio_khong_thi_mai():
    assert next_run("nightly", vn(2026, 10, 5, 0, 30), at=time(1, 10)) == vn(2026, 10, 5, 1, 10)
    assert next_run("nightly", vn(2026, 10, 5, 1, 10), at=time(1, 10)) == vn(2026, 10, 6, 1, 10)


def test_dem_tinh_theo_gio_vn_khong_phai_utc():
    # 2026-10-04 18:30 UTC = 2026-10-05 01:30 VN — 01:10 hôm nay VN đã qua
    after = datetime(2026, 10, 4, 18, 30, tzinfo=UTC)
    assert next_run("nightly", after, at=time(1, 10)) == vn(2026, 10, 6, 1, 10)


def test_tuan_lay_ngay_ke_tiep_trong_danh_sach():
    monday = vn(2026, 10, 5, 9)  # thứ Hai
    assert next_run("weekly", monday, at=time(4), weekdays=[1, 3, 5]) == vn(2026, 10, 6, 4)
    assert next_run("weekly", vn(2026, 10, 6, 4), at=time(4), weekdays=[1, 3, 5]) == vn(2026, 10, 8, 4)
    assert next_run("weekly", vn(2026, 10, 10, 5), at=time(4), weekdays=[5]) == vn(2026, 10, 17, 4)


def test_tuan_khong_ngay_nao_thi_none():
    assert next_run("weekly", vn(2026, 10, 5), at=time(4), weekdays=[]) is None


@pytest.mark.parametrize(
    ("after", "months", "rule", "expected"),
    [
        (vn(2026, 10, 5), 3, "d1", vn(2027, 1, 1, 5)),
        (vn(2026, 9, 30), 3, "d1", vn(2026, 10, 1, 5)),
        (vn(2026, 10, 1, 5), 3, "d1", vn(2027, 1, 1, 5)),
        (vn(2026, 10, 5), 1, "d1", vn(2026, 11, 1, 5)),
        (vn(2026, 10, 5), 1, "d15", vn(2026, 10, 15, 5)),
        (vn(2026, 10, 5), 1, "first_sunday", vn(2026, 11, 1, 5)),  # CN đầu tháng 10 là 4/10, đã qua
        (vn(2026, 10, 3), 1, "first_sunday", vn(2026, 10, 4, 5)),
        (vn(2026, 12, 20), 1, "d1", vn(2027, 1, 1, 5)),
        (vn(2026, 10, 5), 6, "d1", vn(2027, 1, 1, 5)),
        (vn(2026, 10, 5), 12, "d1", vn(2027, 1, 1, 5)),
        (vn(2027, 1, 2), 12, "d1", vn(2028, 1, 1, 5)),
        (vn(2026, 10, 5), 5, "d1", vn(2027, 2, 1, 5)),  # tháng 9/2026 là mốc bội 5 ⇒ 2/2027, 7/2027…
        (vn(2027, 2, 2), 5, "d1", vn(2027, 7, 1, 5)),
    ],
)
def test_viet_lai_moi_n_thang_va_luat_ngay(after, months, rule, expected):
    assert next_run("rebuild", after, at=time(5), every_months=months, day_rule=rule) == expected


def test_mode_la_thi_nem():
    with pytest.raises(ValueError):
        next_run("init", vn(2026, 10, 5), at=time(1))
