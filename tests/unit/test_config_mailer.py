import pytest

from portal.core.config import Settings


def test_mac_dinh_mailer_tat_va_signup_mo():
    """`_env_file=None` BẮT BUỘC — nếu không bài này đo `.env` của lập trình viên."""
    c = Settings(_env_file=None)
    assert c.smtp_host == ""
    assert c.public_base_url == ""
    assert c.smtp_port == 587
    assert c.smtp_from_name == "NobleX"
    assert c.smtp_starttls is True
    assert c.signup_enabled is True


def test_ten_truong_la_starttls_khong_phai_secure():
    """Neo quyết định spec §5.2: cổng 587 + `SMTP_SECURE=false` của Nodemailer
    nghĩa là STARTTLS, KHÔNG phải 'không mã hoá'. Đặt tên `smtp_secure` ở đây là
    mời người sau map thẳng sang `use_tls=False` và gửi credential dạng chữ thường."""
    assert not hasattr(Settings(_env_file=None), "smtp_secure")
    assert hasattr(Settings(_env_file=None), "smtp_starttls")


# ─── Chặn cấu hình mâu thuẫn ở PRODUCTION (①b) ───────────────────────────────
#
# `_env_file=None` BẮT BUỘC ở mọi bài dưới — đo hằng số trong code, không đo
# `.env` của người đang lập trình.


def test_production_signup_bat_thieu_mailer_nem_runtime_error():
    c = Settings(_env_file=None, environment="production", signup_enabled=True)
    with pytest.raises(RuntimeError):
        c.kiem_tra_dang_ky_mau_thuan_san_xuat()


def test_production_signup_tat_khong_nem_du_thieu_mailer():
    """SIGNUP_ENABLED=false ⇒ mailer thiếu cấu hình không còn quan trọng, không ai gọi /auth/register."""
    c = Settings(_env_file=None, environment="production", signup_enabled=False)
    c.kiem_tra_dang_ky_mau_thuan_san_xuat()  # không ném


def test_production_signup_bat_du_mailer_khong_nem():
    c = Settings(
        _env_file=None,
        environment="production",
        signup_enabled=True,
        smtp_host="smtp.vn",
        smtp_from="a@b.vn",
        public_base_url="https://p.vn",
    )
    c.kiem_tra_dang_ky_mau_thuan_san_xuat()  # không ném


def test_dev_signup_bat_thieu_mailer_khong_nem():
    """Ở dev KHÔNG chặn — mailer tự in thư ra stdout (①a) nên dev vẫn dùng được."""
    c = Settings(_env_file=None, environment="development", signup_enabled=True)
    c.kiem_tra_dang_ky_mau_thuan_san_xuat()  # không ném


def test_production_signup_bat_thieu_mot_truong_bao_dung_ten_bien():
    c = Settings(
        _env_file=None,
        environment="production",
        signup_enabled=True,
        smtp_host="smtp.vn",
        smtp_from="a@b.vn",
        public_base_url="",
    )
    with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL"):
        c.kiem_tra_dang_ky_mau_thuan_san_xuat()
