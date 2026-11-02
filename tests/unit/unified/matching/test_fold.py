from noble_agent.data.project_matching import fold


def test_normalize_lowers_and_collapses():
    assert fold.normalize_text("  Noble   Crystal  ") == "noble crystal"


def test_strip_tones_is_public_and_ascii_folds():
    """Public vì filter khu vực của provider Postgres cần fold dấu THUẦN (không
    kèm consonant-fold) để khớp với `translate()` phía SQL."""
    assert fold.strip_tones("Mỹ Đình") == "my dinh"
    assert fold.strip_tones("Tây Hồ") == "tay ho"


def test_vietnamese_strips_tones():
    assert fold.fold_vietnamese("hồ") == fold.fold_vietnamese("ho")
    assert fold.fold_vietnamese("Tây") == fold.fold_vietnamese("tay")


def test_vietnamese_folds_l_n_confusion():
    # Northern ASR often swaps l<->n: "Long" heard as "Nong"
    assert fold.fold_vietnamese("long") == fold.fold_vietnamese("nong")


def test_vietnamese_folds_s_x_and_ch_tr():
    assert fold.fold_vietnamese("sa") == fold.fold_vietnamese("xa")
    assert fold.fold_vietnamese("tra") == fold.fold_vietnamese("cha")


def test_fold_text_routes_ascii_to_metaphone():
    # crystal / cristal share a metaphone code
    assert fold.fold_text("crystal") == fold.fold_text("cristal")


def test_fold_text_mixed_brand_and_location():
    # whole-string fold is stable for the same words in the same order
    assert fold.fold_text("noble crystal tay ho") == fold.fold_text("noble crystal tây hồ")
