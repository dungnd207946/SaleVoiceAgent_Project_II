"""`duong_dan_goc` — chốt duy nhất của backfill: câu UPDATE ghi đè `public_url` của MỌI
hàng media, nên một base sai không hỏng một hàng mà hỏng cả bảng."""

import pytest
from scripts.backfill_public_url import duong_dan_goc


def test_noi_base_voi_duong_cong_khai(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://odyssey-dev.noble.vn")
    assert duong_dan_goc() == "https://odyssey-dev.noble.vn/api/v1/public/files/"


def test_gach_cheo_cuoi_khong_sinh_gach_doi(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://odyssey-dev.noble.vn/")
    assert "//api" not in duong_dan_goc()


def test_base_noi_bo_bi_tu_choi(monkeypatch):
    """Đúng cách DB local có `http://localhost:8100/…`: script nối thẳng, không kiểm."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8100")
    with pytest.raises(ValueError, match="nội bộ"):
        duong_dan_goc()
