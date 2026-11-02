"""Nhãn danh mục nằm ở DÒNG CUỐI của caption. Nó vào text embed, không vào filter —
nên đoán sai chỉ đổi thứ hạng, không giấu mất ảnh."""

from portal.modules.kb.contracts import NHAN_DANH_MUC, normalize_caption, split_caption


def test_khong_co_dong_nhan_thi_giu_nguyen():
    assert split_caption("Phòng ngủ hiện đại.") == ("Phòng ngủ hiện đại.", [])


def test_mot_nhan():
    mo_ta, nhan = split_caption("Phòng ngủ hiện đại.\nDanh mục: nội thất")
    assert mo_ta == "Phòng ngủ hiện đại."
    assert nhan == ["nội thất"]


def test_hai_nhan():
    _, nhan = split_caption("Bể bơi ngoài trời.\nDanh mục: tiện ích, ngoại thất")
    assert nhan == ["tiện ích", "ngoại thất"]


def test_nhan_la_ngoai_so_bi_loai():
    mo_ta, nhan = split_caption("Ảnh sảnh.\nDanh mục: bể bơi, nội thất")
    assert nhan == ["nội thất"]
    assert mo_ta == "Ảnh sảnh."


def test_nhan_giua_cau_khong_tinh():
    """Chỉ dòng CUỐI mới là nhãn — không thì một câu tả có chữ đó bị cắt mất."""
    goc = "Danh mục: đây là một câu tả bình thường."
    assert split_caption(goc) == (goc, [])


def test_caption_rong():
    assert split_caption("") == ("", [])


def test_normalize_cat_nhan_thu_ba():
    ra = normalize_caption("Ảnh.\nDanh mục: nội thất, tiện ích, ngoại thất")
    assert ra == "Ảnh.\nDanh mục: nội thất, tiện ích"


def test_normalize_bo_dong_khi_khong_nhan_nao_hop_le():
    assert normalize_caption("Ảnh.\nDanh mục: bể bơi") == "Ảnh."


def test_so_nhan_phu_tron_bay_danh_muc():
    from portal.modules.kb.contracts import MEDIA_VISUAL_REAL_ESTATE

    assert set(NHAN_DANH_MUC) == set(MEDIA_VISUAL_REAL_ESTATE)
