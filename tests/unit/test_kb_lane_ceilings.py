"""Trần đồng thời của ba chặng nặng — số đo prod 2026-08-25 nằm trong spec."""

from portal.core.jobs import concurrency_of
from portal.modules.kb import jobs as kb_jobs  # noqa: F401 — import để register() chạy
from portal.modules.kb.contracts import KIND_CAPTION, KIND_INDEX, KIND_SYNC_PROJECT, KIND_THUMB


def test_thumb_rong_nhat_vi_thuan_cho_mang():
    assert concurrency_of(KIND_THUMB) == 8


def test_caption_theo_muc_dashscope_chiu_duoc():
    assert concurrency_of(KIND_CAPTION) == 6


def test_index_hep_hon_vi_embed_service_dung_chung_cpu():
    assert concurrency_of(KIND_INDEX) == 4


def test_viec_khac_van_mot_luot_mot_lan():
    assert concurrency_of(KIND_SYNC_PROJECT) == 1


def test_boc_chu_cung_co_tran_rieng():
    """Bóc chữ là việc CHỜ MẠNG (OCR từng trang), không phải CPU. Đo trên dữ liệu thật
    2026-08-25: mỗi việc 165-362 giây, và trần mặc định 1 làm 18 tài liệu mất gần một giờ."""
    from portal.modules.kb.contracts import KIND_ENRICH

    assert concurrency_of(KIND_ENRICH) == 4
