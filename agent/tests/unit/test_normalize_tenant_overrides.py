"""Lớp từ điển của tenant chồng lên bộ nền.

Pass của tenant chèn SỚM — sau bước strip URL/markdown, TRƯỚC `_ROMAN_RE`/`_CODE_RE`. Hai
lẽ: `_CODE_RE` đọc mọi thứ trông giống mã theo từng chữ, nên đặt muộn thì tenant không thể
dạy agent đọc `NPTTL-A12`; và văn bản THAY RA vẫn chảy qua mọi pass sau nên số/ngày/tiền
trong đó vẫn được đọc đúng.
"""

import pytest

from noble_agent.voice.tts._normalize import (
    normalize_for_voice,
    reset_tenant_overrides,
    set_tenant_overrides,
)


@pytest.fixture(autouse=True)
def _sach():
    reset_tenant_overrides()
    yield
    reset_tenant_overrides()


def test_khong_co_lop_tenant_thi_khong_doi_gi():
    truoc = normalize_for_voice("Dự án NCLB")
    reset_tenant_overrides()

    assert normalize_for_voice("Dự án NCLB") == truoc


def test_muc_tenant_duoc_ap():
    set_tenant_overrides({"XYZW": "Khu Đô Thị Mẫu"})

    assert "Khu Đô Thị Mẫu" in normalize_for_voice("Dự án XYZW đang mở bán")


def test_tenant_thang_muc_reading_cua_nen():
    """Nền có `Vietcombank → việt com bank`. Tenant đặt lại thì bản của tenant ra."""
    set_tenant_overrides({"Vietcombank": "vietcombank đọc kiểu khác"})

    ra = normalize_for_voice("Thanh toán qua Vietcombank")

    assert "vietcombank đọc kiểu khác" in ra
    assert "việt com bank" not in ra


def test_tenant_thang_muc_abbrev_cua_nen():
    """Nền có `NCLB → Noble Crystal Long Biên`. Pass tenant chạy TRƯỚC nên nó ăn token, và
    pass abbrev sau đó không còn `NCLB` nào để tìm."""
    set_tenant_overrides({"NCLB": "Noble Crystal Long Biên giai đoạn hai"})

    assert "Noble Crystal Long Biên giai đoạn hai" in normalize_for_voice("Căn ở NCLB")


def test_khoa_viet_hoa_phan_biet_hoa_thuong():
    """`strict_upper`: khoá viết HOA toàn bộ chỉ khớp văn bản viết HOA. Không có luật này
    thì `HD → hợp đồng` viết lại cả chữ `hd` viết thường."""
    set_tenant_overrides({"HD": "hợp đồng"})

    assert "hợp đồng" in normalize_for_voice("Xem HD nhé")
    assert "hợp đồng" not in normalize_for_voice("mã hd nhé")


def test_khoa_viet_thuong_khong_phan_biet_hoa_thuong():
    set_tenant_overrides({"Sunshine": "săn sai"})

    assert "săn sai" in normalize_for_voice("khu sunshine")


def test_khoa_trong_giong_ma_van_khop():
    """Bài này chứng minh VỊ TRÍ pass. Đặt muộn thì `_CODE_RE` đã đánh vần `NPTTL-A12`
    thành từng chữ trước khi map của tenant được xem tới, và bài này đỏ."""
    set_tenant_overrides({"NPTTL-A12": "căn A mười hai toà Tây Thăng Long"})

    assert "căn A mười hai toà Tây Thăng Long" in normalize_for_voice("Căn NPTTL-A12 còn hàng")


def test_van_ban_thay_ra_van_duoc_doc_so():
    """Đặt sớm không mất gì: output vẫn chảy qua các pass số phía sau."""
    set_tenant_overrides({"XYZW": "toà 12"})

    assert "mười hai" in normalize_for_voice("Dự án XYZW")


def test_muc_nen_cung_khoa_bi_vo_hieu_hoa():
    """Vô hiệu mục nền CÙNG KHOÁ, không phải vô hiệu cả bộ nền.

    Pass tenant chạy trước, nhưng văn bản THAY RA vẫn chảy qua hai map nền. Không gỡ mục
    nền cùng khoá thì bản phiên âm của tenant bị chính mục nền viết lại — đo được: tenant
    đặt `Vietcombank → vietcombank đọc kiểu khác` ra `việt com bank đọc kiểu khác`.
    """
    set_tenant_overrides({"Vietcombank": "vietcombank đọc kiểu khác"})

    assert normalize_for_voice("qua Vietcombank") == "qua vietcombank đọc kiểu khác"


def test_muc_nen_khac_khoa_van_ap_len_output_cua_tenant():
    """Mặt còn lại: CHỈ khoá của tenant bị gỡ. Mọi luật nền khác vẫn áp lên output — đó
    chính là thứ làm số/ngày/tiền trong bản thay ra vẫn đọc đúng."""
    set_tenant_overrides({"XYZW": "trả qua Techcombank"})

    assert "tếch com bank" in normalize_for_voice("Dự án XYZW")


async def test_facade_nap_tu_dien_cua_tenant(monkeypatch):
    """Nối dây phải có bài canh: quên lời gọi này thì `_normalize` dùng nền trần và không
    có triệu chứng nào ngoài việc agent đọc sai."""
    from noble_agent.agent import base, facade
    from noble_agent.storage.agent_config_store import PublishedConfig
    from noble_agent.voice.tts import _normalize

    async def _pc(_tenant_id, **_kw):
        return PublishedConfig(
            version=1,
            config={"name": "Mai", "tts_normalization": {"XYZW": "Khu Đô Thị Mẫu"}},
        )

    monkeypatch.setattr(facade, "read_published_config", _pc)
    monkeypatch.setattr(base, "build_agent_def_from_config", lambda *a, **k: object())

    await facade._agent_def_from_db("t_demo", "chat")

    assert _normalize._TENANT_MAP == {"XYZW": "Khu Đô Thị Mẫu"}
