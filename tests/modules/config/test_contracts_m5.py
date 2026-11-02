"""Chín ô + hai preset của AG_01 §II.3 — hình dạng đầy đủ của payload.

M3 chạy với đúng hai biến (`ten_agent`, `giong_dieu`) để chứng minh đường ống.
M5 mở ra đủ 9 ô, và đây là chỗ chốt hình dạng mà cả form lẫn `render()` đọc.

LUẬT KHÔNG ĐỔI (spec §2): payload chứa ĐÚNG những gì tenant sửa được. Sáu rào
chắn và 110 dòng cơ chế KHÔNG ở đây — chúng khoá ở tầng render.
"""

import pytest
from pydantic import ValidationError

from portal.modules.config.contracts import SCHEMA_VERSION_HIEN_TAI, ConfigPayload, payload_mac_dinh

TOI_THIEU = {
    "schema_version": SCHEMA_VERSION_HIEN_TAI,
    "danh_tinh": {"ten_agent": "Mai", "ten_thuong_hieu": "An Phú Land"},
    "pham_vi": {"phong_ban": [{"ten": "CSKH", "khi_nao": "khách hỏi về hợp đồng đã ký"}]},
    "tools": {"enabled": ["find_project", "kb_search"]},
}


# ─── Mặc định dùng được ngay ─────────────────────────────────────────────────


def test_khong_dien_gi_ngoai_hai_o_bat_buoc_van_hop_le():
    """AG_01 §I.2: "không điền gì vẫn ra một agent chạy đúng".

    Đây là cổng 5 của M5. Nếu form bắt buộc quá tay thì onboarding tắc ở đúng
    bước mà khách chưa biết mình muốn gì.
    """
    cfg = ConfigPayload.model_validate(TOI_THIEU)

    assert cfg.danh_tinh.tu_xung == "em"
    assert cfg.danh_tinh.goi_khach == "anh/chị"
    assert cfg.giong.giong_dieu == "than_thien"
    assert cfg.giong.do_dai == "trung_binh"
    assert cfg.pham_vi.linh_vuc == "realestate"
    assert cfg.pham_vi.lam_gi  # có mặc định, không rỗng
    assert cfg.pham_vi.khong_lam_gi


def test_payload_mac_dinh_sinh_tu_ten_workspace():
    """AG_01: "Tên thương hiệu — mặc định lấy từ tên workspace".

    BE sinh mặc định chứ không phải FE: gọi thẳng API bỏ qua FE vẫn phải ra một
    cấu hình chạy được, và hai chỗ cùng sinh mặc định là hai chỗ sẽ lệch.
    """
    cfg = payload_mac_dinh("An Phú Land")

    assert cfg.danh_tinh.ten_thuong_hieu == "An Phú Land"
    assert cfg.tools.enabled  # không phải mảng rỗng — ER_03 sẽ chặn
    ConfigPayload.model_validate(cfg.model_dump())  # tự nó phải hợp lệ


def test_xung_ho_la_hai_o_rieng():
    cfg = payload_mac_dinh("An Phú Land")
    assert cfg.danh_tinh.tu_xung == "em"
    assert cfg.danh_tinh.goi_khach == "anh/chị"
    assert not hasattr(cfg.danh_tinh, "xung_ho")


def test_xung_ho_rong_bi_tu_choi():
    """Chuỗi rỗng đi thẳng vào câu agent nói với khách (`bundle.cau_tu_choi()`),
    ra một câu mất chủ ngữ — chặn ở đây rẻ hơn chặn ở render."""
    for xau in (
        {**TOI_THIEU, "danh_tinh": {**TOI_THIEU["danh_tinh"], "tu_xung": ""}},
        {**TOI_THIEU, "danh_tinh": {**TOI_THIEU["danh_tinh"], "goi_khach": ""}},
    ):
        with pytest.raises(ValidationError):
            ConfigPayload.model_validate(xau)


def test_schema_version_la_3():
    assert payload_mac_dinh("X").schema_version == 3


# ─── ER_01 · ER_02 · ER_03 ───────────────────────────────────────────────────


def test_ten_agent_rong_bi_tu_choi():
    """AG_01 ER_01."""
    xau = {**TOI_THIEU, "danh_tinh": {"ten_agent": "", "ten_thuong_hieu": "X"}}

    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(xau)


def test_ten_agent_qua_40_ky_tu_bi_tu_choi():
    """AG_01 ER_01: tối đa 40 ký tự."""
    xau = {**TOI_THIEU, "danh_tinh": {"ten_agent": "M" * 41, "ten_thuong_hieu": "X"}}

    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(xau)


def test_khong_con_phong_ban_nao_bi_tu_choi():
    """AG_01 ER_02: "Không có phòng ban thì khách bị bỏ rơi giữa cuộc"."""
    xau = {**TOI_THIEU, "pham_vi": {"phong_ban": []}}

    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(xau)


def test_qua_tam_phong_ban_bi_tu_choi():
    """AG_01 §II.3: tối đa 8 mục."""
    xau = {**TOI_THIEU, "pham_vi": {"phong_ban": [{"ten": f"P{i}", "khi_nao": "x"} for i in range(9)]}}

    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(xau)


def test_tat_het_ky_nang_bi_tu_choi():
    """AG_01 ER_03."""
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate({**TOI_THIEU, "tools": {"enabled": []}})


# ─── Preset là danh sách đóng ────────────────────────────────────────────────


def test_giong_dieu_ngoai_ba_preset_bi_tu_choi():
    """AG_01 BR07: ba preset do platform viết, workspace CHỈ CHỌN.

    Nhận chuỗi tự do ở đây là mở lại đúng cánh cửa BR02 đóng — tenant gõ thẳng
    một đoạn hướng dẫn vào cái ô "giọng điệu" và nó đi vào prompt.
    """
    xau = {**TOI_THIEU, "giong": {"giong_dieu": "tôi tự viết giọng của tôi"}}

    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(xau)


def test_do_dai_ngoai_ba_preset_bi_tu_choi():
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate({**TOI_THIEU, "giong": {"do_dai": "dai_that_dai"}})


def test_linh_vuc_ngoai_danh_sach_bi_tu_choi():
    """MVP chỉ có bất động sản. Nhận vertical lạ ⇒ render một bundle mà agent
    không có bộ kỹ năng tương ứng."""
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate({**TOI_THIEU, "pham_vi": {**TOI_THIEU["pham_vi"], "linh_vuc": "bao_hiem"}})


# ─── BR02 — không đường nào gửi prompt thô ───────────────────────────────────


def test_tu_choi_truong_la_o_moi_tang():
    """AG_01 BR02. `extra="forbid"` phải có ở CẢ model lồng trong, không chỉ gốc.

    Chỉ chặn ở gốc thì `{"danh_tinh": {"prompt_tho": "..."}}` lọt qua — và một
    trường lạ được nuốt im lặng là chỗ FE gõ sai tên mà không ai biết.
    """
    for xau in (
        {**TOI_THIEU, "prompt_tho": "# luật của tôi"},
        {**TOI_THIEU, "danh_tinh": {**TOI_THIEU["danh_tinh"], "prompt_tho": "x"}},
        {**TOI_THIEU, "pham_vi": {**TOI_THIEU["pham_vi"], "he_thong": "x"}},
        {**TOI_THIEU, "tools": {"enabled": ["kb_search"], "rao_chan": []}},
    ):
        with pytest.raises(ValidationError):
            ConfigPayload.model_validate(xau)


def test_rao_chan_khong_nam_trong_payload():
    """Sáu rào chắn khoá ở tầng render. Có mặt trong payload nghĩa là có đường
    tắt bằng một request — AG_01 BR08 gọi đó là bán một công tắc gây sự cố."""
    assert "rao_chan" not in ConfigPayload.model_fields
