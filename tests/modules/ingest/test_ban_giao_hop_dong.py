"""`handoverStandard` của cổng nạp: chuỗi (adapter cũ) hoặc danh sách hạng mục → JSON cho cột jsonb."""

import json

from portal.modules.ingest.hop_dong import kiem


def _ban_giao(gia_tri):
    cot, loi = kiem("project", {"name": "A", "handoverStandard": gia_tri})
    return cot.get("handover_standard"), [e.ly_do for e in loi]


def test_chuoi_thanh_mot_hang_muc():
    v, loi = _ban_giao("  Thô, giãn xây ")
    assert not loi
    assert json.loads(v) == [{"item": "Tiêu chuẩn chung", "note": "Thô, giãn xây"}]


def test_chuoi_rong_thanh_null():
    assert _ban_giao("   ") == (None, [])


def test_danh_sach_bo_truong_rong_va_null():
    v, loi = _ban_giao([{"item": "Sàn", "brand": "Kronotex", "origin": None, "note": " "}])
    assert not loi
    assert json.loads(v) == [{"item": "Sàn", "brand": "Kronotex"}]


def test_hang_muc_thieu_item_bi_tu_choi():
    v, loi = _ban_giao([{"brand": "TOTO"}])
    assert v is None and loi


def test_kieu_khac_bi_tu_choi():
    v, loi = _ban_giao({"item": "Sàn"})
    assert v is None and loi
