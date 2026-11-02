"""`.env` production có `MEDIA_HNSW_EF=64  # ghi chú`, và systemd EnvironmentFile lẫn
docker compose env_file đều KHÔNG cắt phần sau `#` → int() vỡ nếu không strip."""

import pytest

from embed import settings


def test_clean_cat_inline_comment_sau_khoang_trang():
    assert settings.clean("64  # ghi chú") == "64"


def test_clean_cat_inline_comment_sau_tab():
    assert settings.clean("64\t# ghi chú") == "64"


def test_clean_strip_khoang_trang():
    assert settings.clean("  abc  ") == "abc"


def test_clean_giu_dau_thang_lien_ke():
    """URL fragment / password chứa `#` không có khoảng trắng trước → không được cắt."""
    assert settings.clean("http://host/x#frag") == "http://host/x#frag"


def test_env_doc_va_clean(monkeypatch):
    monkeypatch.setenv("ODYSSEY_TEST_X", "10  # mười")
    assert settings.env("ODYSSEY_TEST_X") == "10"


def test_env_default_khi_thieu(monkeypatch):
    monkeypatch.delenv("ODYSSEY_TEST_Y", raising=False)
    assert settings.env("ODYSSEY_TEST_Y", "mặc định") == "mặc định"


def test_env_int(monkeypatch):
    monkeypatch.setenv("ODYSSEY_TEST_N", "64  # ef")
    assert settings.env_int("ODYSSEY_TEST_N", 8) == 64


def test_env_int_rong_dung_default(monkeypatch):
    monkeypatch.setenv("ODYSSEY_TEST_N", "  ")
    assert settings.env_int("ODYSSEY_TEST_N", 8) == 8


def test_env_int_gia_tri_rac_thi_no(monkeypatch):
    """Cấu hình sai phải nổ lúc boot, không phải im lặng dùng default rồi debug 2 giờ."""
    monkeypatch.setenv("ODYSSEY_TEST_N", "abc")
    with pytest.raises(ValueError):
        settings.env_int("ODYSSEY_TEST_N", 8)
