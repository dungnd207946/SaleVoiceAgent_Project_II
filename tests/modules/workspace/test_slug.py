"""`slug_tenant()` — tên workspace tiếng Việt -> `tenants.id` hợp lệ.

VÌ SAO PROPERTY TEST Ở ĐÂY CHỨ KHÔNG CHỈ VÀI CA MẪU:
đầu ra của hàm này đi vào BA chỗ cưỡng chế cùng một biểu thức
`^[a-z][a-z0-9_]{1,30}$`:

  · CHECK `tenants_id_check`            (migration 0002)
  · `control.create_agent_role()`       (migration 0005 — nó RAISE nếu không khớp,
                                         vì tên role ghép vào câu CREATE ROLE)
  · `control.dat_mat_khau_agent()`      (migration 0900 — cùng biểu thức)

Một chuỗi lọt qua hàm này mà không khớp regex thì lỗi không nổ ở đây — nó nổ ở
lúc cấp phát hạ tầng, cách chỗ sai vài ngày. Nên cổng phải ở ngay đầu ra của hàm.

Ba ca mẫu dưới đây KHÔNG dư so với property test: property test nói "hợp lệ",
chúng nói "đúng cái người dùng mong đợi". `"Sàn Đông Nam"` ra `s_n_ng_nam` vẫn
hợp lệ hoàn hảo — và vẫn là một lỗi.
"""

import random
import re
import unicodedata

from portal.modules.workspace.service import DAI_ID_TOI_DA, DAI_ID_TOI_THIEU, slug_tenant

# Cùng biểu thức với migration 0002. Khai lại ở đây, không import từ migration:
# migration phải tự đứng độc lập (xem header 0104), nên hằng số sống hai chỗ có
# chủ đích — và đây là chỗ neo hai bản lại với nhau.
REGEX_ID = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


def test_bo_dau_tieng_viet():
    assert slug_tenant("Sàn Đông Nam") == "san_dong_nam"


def test_chu_d_gach_ngang():
    """`đ`/`Đ` KHÔNG bị NFD tách ra — phải xử lý riêng, nếu không nó biến mất."""
    assert slug_tenant("Đất Xanh") == "dat_xanh"
    assert slug_tenant("Điện Biên") == "dien_bien"


def test_khoang_trang_hai_dau_va_ky_tu_la():
    assert slug_tenant("An Phú --- Land!!!") == "an_phu_land"


def test_ten_mot_ky_tu_duoc_dem_len_hai():
    """CHECK là `{1,30}` chứ không `{0,30}` ⇒ id một ký tự VI PHẠM.

    Property test đã bắt đúng ca này lúc viết hàm; giữ lại thành ca có tên để
    người sửa sau biết `_ws` ở đó để làm gì.
    """
    assert slug_tenant("  A  ") == "a_ws"
    assert slug_tenant("Ẹ") == "e_ws"
    assert len(slug_tenant("A")) >= DAI_ID_TOI_THIEU


def test_bat_dau_bang_so_duoc_them_tien_to():
    """CHECK đòi ký tự đầu thuộc `[a-z]`. `123_land` vi phạm, không phải chỉ xấu."""
    assert slug_tenant("123 Land") == "w_123_land"


def test_rong_sau_khi_fold_thi_co_ten_du_phong():
    assert slug_tenant("🏠🏠") == "workspace"
    assert slug_tenant("・・・") == "workspace"
    assert slug_tenant("") == "workspace"


def test_cat_dung_do_dai_toi_da():
    ra = slug_tenant("Công ty cổ phần đầu tư và phát triển bất động sản An Phú Land Miền Nam")
    assert len(ra) <= DAI_ID_TOI_DA
    assert REGEX_ID.match(ra)


def test_khong_ket_thuc_bang_gach_duoi():
    """Cắt giữa một dấu `_` để lại hậu tố cụt — hợp regex nhưng đọc như lỗi."""
    ra = slug_tenant("a" * 30 + " b")
    assert not ra.endswith("_")


def test_moi_dau_ra_deu_khop_regex_cua_db():
    """500 chuỗi ngẫu nhiên. Đây là cổng thật; các test trên là ví dụ."""
    rng = random.Random(20260804)
    kho = (
        "aàáảãạăằắẳẵặâầấẩẫậbcdđeèéẻẽẹêềếểễệ0123456789"
        " -_.!@#$%^&*()[]{}|\\/<>?,;:'\"`~+="
        "AÀÁBCĐEÊ"
        "🏠🌟・日本語中文한국어"
        "\t\n ​"
    )
    for _ in range(500):
        n = rng.randint(0, 60)
        ten = "".join(rng.choice(kho) for _ in range(n))
        ra = slug_tenant(ten)
        assert REGEX_ID.match(ra), f"{ten!r} -> {ra!r} không khớp {REGEX_ID.pattern}"


def test_khong_con_ky_tu_to_hop_nao_sot_lai():
    """Fold phải bỏ HẾT dấu, không chỉ dấu tiếng Việt — `ü`, `ñ`, `å` cũng vậy."""
    ra = slug_tenant("Zürich Ñandú Åland")
    assert ra == "zurich_nandu_aland"
    assert all(not unicodedata.combining(c) for c in ra)
