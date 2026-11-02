"""Mã hoá at-rest — phần thuần, không cần Docker.

Bài quan trọng nhất KHÔNG nằm ở đây mà ở `tests/modules/ingest/test_token.py`:
«cột trong DB có còn chứa chuỗi thô không». Ở đây chỉ canh tính chất của phép mã
hoá — thứ mà một bài đọc DB không phân biệt được.
"""

import pytest

from portal.core import bi_mat_luu


def test_vong_ma_hoa_giai_ma():
    tho = "ody_in_5QVD-HWxyz_bi_mat"
    assert bi_mat_luu.giai_ma(bi_mat_luu.ma_hoa(tho)) == tho


def test_ciphertext_khong_chua_ban_ro():
    tho = "ody_ag_chuoi_rat_de_nhan_ra"
    assert tho not in bi_mat_luu.ma_hoa(tho)


def test_hai_lan_ma_hoa_CUNG_chuoi_ra_KHAC_nhau():
    """Nonce ngẫu nhiên mỗi lượt.

    Nếu hai lượt ra giống nhau thì nonce đang tất định, và dùng lại nonce với cùng
    khoá là mất TOÀN BỘ bảo đảm của GCM — không chỉ lộ bản rõ mà lộ cả khoá xác
    thực. Đây là bài canh rẻ nhất cho lỗi đắt nhất của AEAD.
    """
    a, b = bi_mat_luu.ma_hoa("giong het nhau"), bi_mat_luu.ma_hoa("giong het nhau")
    assert a != b
    assert bi_mat_luu.giai_ma(a) == bi_mat_luu.giai_ma(b) == "giong het nhau"


def test_chuoi_khong_co_tien_to_di_qua_nguyen_van():
    """Hàng CŨ chưa backfill phải đọc được — đó là thứ cho phép deploy code TRƯỚC,
    backfill SAU. Bỏ nhánh này là buộc hai bước phải xảy ra cùng một giây."""
    assert bi_mat_luu.giai_ma("ody_ag_hang_cu_plaintext") == "ody_ag_hang_cu_plaintext"
    assert bi_mat_luu.giai_ma(None) is None
    assert bi_mat_luu.giai_ma("") == ""


def test_sua_mot_ky_tu_thi_NEM_chu_khong_tra_rac():
    """GCM là AEAD: sửa ciphertext phải nổ, không được giải ra một chuỗi khác.

    Và người gọi KHÔNG được nuốt lỗi đó — một chuỗi rỗng hay chính ciphertext trả
    ra sẽ hiện lên giao diện như một khoá thật, và người vận hành sẽ đi dán nó.
    """
    x = bi_mat_luu.ma_hoa("bi mat")
    hong = x[:-2] + ("AA" if x[-2:] != "AA" else "BB")
    with pytest.raises(Exception):  # noqa: B017 — InvalidTag của cryptography, không cần siết kiểu
        bi_mat_luu.giai_ma(hong)


def test_chuoi_rong_khong_bi_ma_hoa():
    """Mã hoá chuỗi rỗng ra một ciphertext dài ngoằng cho không nội dung nào, và
    làm phép kiểm «cột này có giá trị không» ở tầng trên đọc sai."""
    assert bi_mat_luu.ma_hoa("") == ""
