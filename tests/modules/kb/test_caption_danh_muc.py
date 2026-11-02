"""Ảnh khách để `tong_quan` thì VLM đoán thêm danh mục; ảnh khách đã phân loại thì tin họ."""

from portal.modules.kb import jobs as kb_jobs


def test_prompt_danh_muc_ton_tai_va_liet_ke_du_bay_nhan():
    from portal.modules.kb import prompts
    from portal.modules.kb.contracts import NHAN_DANH_MUC

    spec = prompts.get("caption_danh_muc")
    for nhan in NHAN_DANH_MUC.values():
        assert nhan in spec.prompt, f"prompt thiếu nhãn {nhan}"


def test_anh_tong_quan_dung_profile_danh_muc():
    assert kb_jobs._profile_caption("tong_quan") == "caption_danh_muc"


def test_anh_da_phan_loai_giu_profile_cu():
    assert kb_jobs._profile_caption("mat_bang") == "caption"
