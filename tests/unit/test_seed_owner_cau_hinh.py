"""`doc_cau_hinh()` — phép validate env của vai `seed-owner`. Không cần Postgres.

VÌ SAO TÁCH RA HÀM THUẦN ĐỂ TEST: hai biến bắt buộc của vai này đi vào những chỗ
KHÔNG sửa lại được. (`SEED_ORG_ID` đã bỏ 2026-08-15 cùng tầng tổ chức.) Cấu hình còn lại nằm trong mọi
hàng `users`/`tenants` sau đó — đổi nó về sau là một migration dữ liệu. Nên phép
kiểm phải nổ TRƯỚC khi mở kết nối, không phải bằng một CheckViolationError của
asyncpg vào giữa transaction.
"""

import pytest

from portal.cli.seed_owner import TEN_WORKSPACE_MAC_DINH, LoiBootstrap, doc_cau_hinh

DU = {"SEED_OWNER_EMAIL": "dang@anphuland.vn"}


def test_du_hai_bien_bat_buoc_thi_qua():
    c = doc_cau_hinh(DU)
    assert c.email == "dang@anphuland.vn"


@pytest.mark.parametrize(
    "env",
    [
        {},
        {},
        # Không có @ thì không phải hộp thư — và hộp thư là chỗ link mời đi tới.
        {"SEED_OWNER_EMAIL": "dang"},
    ],
)
def test_thieu_hoac_sai_email_thi_chan(env):
    with pytest.raises(LoiBootstrap, match="SEED_OWNER_EMAIL"):
        doc_cau_hinh(env)


# `test_org_id_khong_khop_check_cua_0102_thi_chan` XOÁ 2026-08-15: `SEED_ORG_ID`
# và constraint `organizations_id_check` đều không còn.


def test_email_duoc_chuan_hoa():
    """CHECK `email = lower(email)` (0100) là lưới thứ hai, không phải lưới đầu.

    Devops gõ email vào `docker compose run -e ...` bằng tay, nên hoa/thường và
    khoảng trắng dán kèm là chuyện thường. Để nó nổ ở INSERT thì thông điệp là
    một CheckViolationError, không phải "email của bạn có chữ hoa".
    """
    c = doc_cau_hinh({**DU, "SEED_OWNER_EMAIL": "  Dang@AnPhuLand.VN "})
    assert c.email == "dang@anphuland.vn"


def test_mac_dinh_suy_ra_khi_bo_trong():
    """Ba biến tuỳ chọn đều có mặc định dùng được — devops không phải đoán."""
    c = doc_cau_hinh(DU)
    assert c.ten_nguoi == "dang"  # phần trước @
    assert c.ten_workspace == TEN_WORKSPACE_MAC_DINH
    assert c.goc_url == ""


def test_goc_url_bo_dau_gach_cuoi():
    """`duong_dan_moi()` trả đường dẫn có `/` ở đầu — nối thẳng là `//invite/...`."""
    c = doc_cau_hinh({**DU, "SEED_PORTAL_URL": "https://portal.noblex.vn/"})
    assert c.goc_url == "https://portal.noblex.vn"
