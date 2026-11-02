"""Cờ Secure của cookie phiên — cấu hình được, nhưng MẶC ĐỊNH phải là bật.

VÌ SAO CÓ CỜ NÀY. Trình duyệt chỉ miễn trừ "Secure trên http" cho `localhost`.
Nên mở portal từ máy khác trong LAN qua `http://<IP>:5273` là đăng nhập không
bao giờ dính cookie: login trả 200, rồi màn nào cũng bật về /login. Tắt Secure
là cách duy nhất cho kịch bản đó mà không phải dựng TLS ở máy dev.

VÌ SAO PHẢI CANH BẰNG TEST. Cái cờ này nới đúng thứ nó được sinh ra để giữ:
tắt nhầm ở production là cookie phiên đi qua đường không mã hoá, và không có
triệu chứng nào — mọi thứ vẫn chạy bình thường, chỉ là nghe lén được. Một cấu
hình mà "sai thì vẫn chạy" chỉ an toàn khi default an toàn và có test neo default
lại. Đây là test đó.

Chạy được không cần Docker.
"""

from pathlib import Path

import pytest
from fastapi import Response

from portal.core.auth.session import TEN_COOKIE
from portal.core.config import Settings
from portal.modules.auth.router import _dat_cookie, _xoa_cookie

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_EXAMPLE = BACKEND_ROOT / ".env.example"


@pytest.fixture
def khong_co_env(monkeypatch):
    """Đọc default CỦA CODE, không phải default của máy đang chạy test.

    `Settings()` trần sẽ nuốt cả `.env` lẫn biến môi trường — mà trên máy dev nào
    dùng cờ này thì `.env` ĐANG đặt COOKIE_SECURE=false, đúng theo thiết kế. Test
    default mà đọc phải .env thì nó đỏ vì cấu hình hợp lệ của người dùng, chứ
    không phải vì code sai: một test báo động giả sẽ bị tắt, và khi bị tắt thì nó
    không còn canh gì nữa.
    """
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    return lambda: Settings(_env_file=None)


def dat(res: Response) -> str:
    return res.headers["set-cookie"].lower()


def test_mac_dinh_cookie_secure_la_true(khong_co_env):
    """Default là thứ chạy khi ai đó deploy mà chưa đặt biến nào."""
    assert khong_co_env().cookie_secure is True


def test_dat_cookie_gan_secure_khi_cau_hinh_bat(monkeypatch):
    monkeypatch.setattr("portal.core.config.get_settings", lambda: Settings(_env_file=None, cookie_secure=True))
    res = Response()

    _dat_cookie(res, "sid-abc")

    assert "; secure" in dat(res)


def test_dat_cookie_bo_secure_khi_cau_hinh_tat(monkeypatch):
    monkeypatch.setattr("portal.core.config.get_settings", lambda: Settings(_env_file=None, cookie_secure=False))
    res = Response()

    _dat_cookie(res, "sid-abc")

    assert "; secure" not in dat(res)


def test_tat_secure_khong_lam_mat_httponly_va_samesite(monkeypatch):
    """Nới ĐÚNG MỘT cờ. HttpOnly chặn XSS đọc phiên, SameSite chặn CSRF — không cờ
    nào trong hai cái đó dính dáng gì tới việc kết nối có TLS hay không."""
    monkeypatch.setattr("portal.core.config.get_settings", lambda: Settings(_env_file=None, cookie_secure=False))
    res = Response()

    _dat_cookie(res, "sid-abc")

    assert "httponly" in dat(res)
    assert "samesite=lax" in dat(res)


def test_xoa_cookie_theo_cung_cau_hinh(monkeypatch):
    """Logout phải theo cùng cờ, nếu không thì tắt Secure xong ĐĂNG XUẤT hỏng.

    `delete_cookie` cũng là một Set-Cookie: gắn Secure lên nó rồi gửi qua http là
    trình duyệt vứt luôn cả cái lệnh xoá. Triệu chứng là bấm đăng xuất, server dọn
    phiên ở Redis, nhưng cookie vẫn nằm đó — người dùng thấy mình đã đăng xuất,
    còn cookie chết thì vẫn đi kèm mọi request tới khi hết hạn.
    """
    monkeypatch.setattr("portal.core.config.get_settings", lambda: Settings(_env_file=None, cookie_secure=False))
    res = Response()

    _xoa_cookie(res)

    d = dat(res)
    assert TEN_COOKIE in d
    assert "; secure" not in d


def test_env_example_khong_day_tat_secure():
    """Cùng lý do như DSN runtime ở test_config.py: một default an toàn trong code
    mà `.env.example` vẫn dạy sai thì lỗ hổng chỉ dịch chỗ — ai cũng
    `cp .env.example .env` rồi chạy.

    ⚠️ CẤM GIÁ TRỊ TẮT, KHÔNG CẤM DÒNG. Bản trước chặn mọi dòng `COOKIE_SECURE=`
    kể cả `=true`, nên biến chỉ tồn tại dưới dạng comment — và một biến bị comment
    là một biến không ai biết mình đang chạy giá trị nào. `=true` khai tường minh
    dạy đúng thứ default trong code đã chọn; chỉ `false` mới là thứ không được đi
    theo `cp .env.example .env`.
    """
    TAT = {"false", "0", "no", "off", ""}
    for ln in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s.startswith("#") or not s.lower().startswith("cookie_secure="):
            continue
        gia_tri = s.split("=", 1)[1].strip().strip('"').strip("'").lower()
        assert gia_tri not in TAT, f"{s} — .env.example đang tắt Secure sẵn cho mọi người"
