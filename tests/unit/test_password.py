"""Argon2id. Không cần Postgres — chạy trong test-unit."""

from portal.core.auth import password as pw


def test_bam_roi_kiem_dung():
    h = pw.bam("mat-khau-that")
    assert pw.kiem(h, "mat-khau-that") is True


def test_sai_mat_khau_tra_False():
    h = pw.bam("mat-khau-that")
    assert pw.kiem(h, "mat-khau-sai") is False


def test_hai_lan_bam_ra_hai_hash_khac_nhau():
    """Salt ngẫu nhiên. Hai hash giống nhau nghĩa là không có salt, và một bảng
    tra ngược dùng được cho mọi user."""
    assert pw.bam("x") != pw.bam("x")


def test_hash_rac_tra_False_khong_raise():
    """Một hàng DB hỏng không được làm sập request thành 500 — nó là 401."""
    assert pw.kiem("khong-phai-hash-argon2", "x") is False


def test_hash_rong_tra_False_khong_raise():
    """password_hash rỗng là hàng seed hỏng hoặc user chưa đặt mật khẩu. Cả hai
    đều là 401, không phải 500 — và tuyệt đối không phải True."""
    assert pw.kiem("", "x") is False


def test_kiem_gia_khong_raise():
    """Đường 'email không tồn tại' gọi hàm này để tốn cùng thời gian với đường
    'email có thật nhưng sai mật khẩu'."""
    pw.kiem_gia()


def test_hash_la_argon2id():
    """Argon2 có ba biến thể; chỉ `id` là bản OWASP khuyến nghị (i chống side-channel,
    d chống GPU, id lai cả hai). Mặc định của thư viện đang là id — neo lại để một
    lần đổi mặc định ở upstream không trôi qua im lặng."""
    assert pw.bam("x").startswith("$argon2id$")
