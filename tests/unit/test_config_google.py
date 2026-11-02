"""Cấu hình cửa Google — bật/tắt và một cấu hình production mâu thuẫn."""

import pytest

from portal.core.config import Settings


def test_rong_la_tat():
    c = Settings(google_client_id="", google_client_secret="")
    assert c.google_bat() is False


def test_du_hai_bien_la_bat():
    c = Settings(google_client_id="abc.apps.googleusercontent.com", google_client_secret="s3cret")
    assert c.google_bat() is True


def test_thieu_mot_trong_hai_van_la_tat():
    """Nửa cấu hình còn tệ hơn không cấu hình: nút hiện ra rồi đổi code thất bại
    ở bước 7, và người dùng chỉ thấy một lần redirect về /login không lý do."""
    assert Settings(google_client_id="abc", google_client_secret="").google_bat() is False
    assert Settings(google_client_id="", google_client_secret="s").google_bat() is False


def test_redirect_uri_suy_tu_public_base_url():
    c = Settings(
        google_client_id="abc",
        google_client_secret="s",
        public_base_url="https://portal.noblex.vn",
    )
    assert c.google_redirect_uri() == "https://portal.noblex.vn/api/v1/auth/google/callback"


def test_redirect_uri_cat_dau_gach_cheo_thua():
    """Google khớp redirect_uri theo từng ký tự. `https://x/` + `/api/...` sinh
    ra một dấu gạch đôi và Google từ chối, với một thông báo không nói ra vì sao."""
    c = Settings(
        google_client_id="abc",
        google_client_secret="s",
        public_base_url="https://portal.noblex.vn/",
    )
    assert c.google_redirect_uri() == "https://portal.noblex.vn/api/v1/auth/google/callback"


def test_production_bat_google_ma_thieu_public_base_url_thi_no():
    """Phép kiểm này giờ ở `kiem_tra_google_mau_thuan_san_xuat()` riêng — người
    gọi thật là `_cau_hinh_google()` (`modules/auth/router.py`), chạy trên MỌI
    lượt vào cửa Google, không phải `kiem_tra_dang_ky_mau_thuan_san_xuat()`
    (chỉ chạy khi có ai `POST /auth/register`, và đường Google không đi qua đó)."""
    c = Settings(
        environment="production",
        google_client_id="abc",
        google_client_secret="s",
        public_base_url="",
        signup_enabled=False,
    )
    with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL"):
        c.kiem_tra_google_mau_thuan_san_xuat()


def test_production_tat_google_thi_khong_no():
    c = Settings(environment="production", google_client_id="", public_base_url="", signup_enabled=False)
    c.kiem_tra_google_mau_thuan_san_xuat()


def test_dang_ky_mau_thuan_san_xuat_khong_con_kiem_google():
    """Sau khi tách: `kiem_tra_dang_ky_mau_thuan_san_xuat()` KHÔNG còn ném dù
    Google thiếu `PUBLIC_BASE_URL` — nó chỉ còn kiểm mailer/đăng ký. Bài canh
    ngược: nếu ai vô tình gộp lại phép kiểm Google vào đây, bài này đỏ ngay."""
    c = Settings(
        environment="production",
        google_client_id="abc",
        google_client_secret="s",
        public_base_url="",
        signup_enabled=False,
    )
    c.kiem_tra_dang_ky_mau_thuan_san_xuat()  # không ném — Google không thuộc phạm vi hàm này nữa
