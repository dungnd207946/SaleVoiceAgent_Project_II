"""`public_url_of` — ba nhánh, và nhánh URL ngoài là nhánh dễ sai nhất."""

from portal.core.public_url import public_url_of


def test_rong_thi_rong():
    assert public_url_of("") == ""


def test_khoa_duoc_noi_base(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://portal.test")
    ra = public_url_of("tenants/anphu/kb-bds/9f3c/mb.jpg")
    assert ra == "https://portal.test/api/v1/public/files/tenants/anphu/kb-bds/9f3c/mb.jpg"


def test_url_ngoai_giu_nguyen_van():
    """Ảnh dán từ CDN của khách: nối base vào là ra một URL không tồn tại."""
    assert public_url_of("https://cdn.khach.vn/a.jpg") == "https://cdn.khach.vn/a.jpg"
    assert public_url_of("http://cdn.khach.vn/a.jpg") == "http://cdn.khach.vn/a.jpg"


def test_base_co_gach_cheo_cuoi_khong_sinh_gach_doi(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://portal.test/")
    assert "//api" not in public_url_of("tenants/a/kb-bds/x.jpg")


def test_localhost_bi_tu_choi_o_moi_moi_truong(monkeypatch):
    """URL này đi vào Qdrant rồi tới trình duyệt khách — localhost ở đó là ảnh vỡ.

    `kiem_base` là đường GHI (script backfill). Ném ở đó vẫn đúng và vẫn phải ném.
    """
    import pytest

    from portal.core.public_url import kiem_base

    for xau in ("http://localhost:8100", "http://127.0.0.1:8100", "http://host.docker.internal"):
        with pytest.raises(ValueError, match="nội bộ"):
            kiem_base(xau)


def test_base_noi_bo_thi_khong_sinh_link_chu_khong_nem(monkeypatch):
    """Đường ĐỌC không được ném — từ 2026-08-17 biến này cũng mang link mời, và ở dev
    nó ĐÚNG là `http://localhost:5273`. Ném ở đây = mọi lượt đọc media ở dev thành 500.

    Rỗng chứ không phải link localhost: khách vẫn không mở được ảnh ở địa chỉ đó.
    """
    for xau in ("http://localhost:5273", "http://127.0.0.1:8100", "http://host.docker.internal"):
        monkeypatch.setenv("PUBLIC_BASE_URL", xau)
        assert public_url_of("tenants/a/kb-bds/x.jpg") == ""


def test_domain_that_thi_duoc():
    from portal.core.public_url import kiem_base

    assert kiem_base("https://portal.noblex.vn") == "https://portal.noblex.vn"


def test_chua_cau_hinh_thi_khong_sinh_link(monkeypatch):
    """Thà không có link còn hơn một link không mở được."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "")
    assert public_url_of("tenants/a/kb-bds/x.jpg") == ""
