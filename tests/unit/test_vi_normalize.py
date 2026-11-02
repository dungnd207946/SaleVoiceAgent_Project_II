"""Unit tests for Vietnamese voice normalization."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from noble_agent.voice.tts._normalize import _int_to_vi, normalize_for_voice


class TestIntToVietnamese:
    def test_single_digits(self):
        assert _int_to_vi(0) == "không"
        assert _int_to_vi(5) == "năm"
        assert _int_to_vi(9) == "chín"

    def test_teens(self):
        assert _int_to_vi(10) == "mười"
        assert _int_to_vi(15) == "mười lăm"
        assert _int_to_vi(19) == "mười chín"

    def test_tens(self):
        assert _int_to_vi(20) == "hai mươi"
        assert _int_to_vi(21) == "hai mươi mốt"
        assert _int_to_vi(35) == "ba mươi lăm"
        assert _int_to_vi(99) == "chín mươi chín"

    def test_hundreds(self):
        assert _int_to_vi(100) == "một trăm"
        assert _int_to_vi(105) == "một trăm lẻ năm"
        assert _int_to_vi(250) == "hai trăm năm mươi"

    def test_thousands(self):
        assert _int_to_vi(1000) == "một nghìn"
        assert _int_to_vi(2048) == "hai nghìn không trăm bốn mươi tám"
        assert _int_to_vi(85000) == "tám mươi lăm nghìn"

    def test_millions(self):
        assert _int_to_vi(1000000) == "một triệu"
        assert _int_to_vi(3500000) == "ba triệu năm trăm nghìn"

    def test_negative(self):
        assert _int_to_vi(-5) == "âm năm"


class TestPriceExpansion:
    def test_ty(self):
        result = normalize_for_voice("Giá 3.5 tỷ")
        assert "ba tỷ rưỡi" in result.lower()  # colloquial: half a unit → "rưỡi"

    def test_trieu(self):
        result = normalize_for_voice("Phí 800 triệu")
        assert "tám trăm triệu" in result.lower()

    def test_comma_decimal(self):
        result = normalize_for_voice("Giá từ 2,8 tỷ")
        assert "hai tỷ tám trăm triệu" in result.lower()  # colloquial: read the true value

    def test_integer_ty(self):
        result = normalize_for_voice("Khoảng 5 tỷ")
        assert "năm tỷ" in result.lower()


class TestUnitExpansion:
    def test_m2(self):
        result = normalize_for_voice("Diện tích 85m2")
        assert "mét vuông" in result

    def test_m2_unicode(self):
        result = normalize_for_voice("Căn hộ 120m²")
        assert "mét vuông" in result

    def test_decimal_comma_with_unit(self):
        """'120,1 m2' must read as one number, not '120 [pause] 1 mét vuông'."""
        result = normalize_for_voice("Diện tích 120,1 m2 rất rộng")
        assert "một trăm hai mươi phẩy một mét vuông" in result
        assert "," not in result  # no comma → no TTS pause

    def test_decimal_comma_bare_metre(self):
        result = normalize_for_voice("Mặt tiền 5,65m")
        assert "năm phẩy sáu mươi lăm mét" in result
        assert "," not in result

    def test_dot_thousands_with_unit_unchanged(self):
        """Dot as a thousands separator must stay 'bảy nghìn hai trăm'."""
        result = normalize_for_voice("Rộng 7.200 m2")
        assert "bảy nghìn hai trăm mét vuông" in result


class TestSlash:
    def test_address_slash_not_and(self):
        """'anh/chị' polite address must not become 'anh và chị'."""
        result = normalize_for_voice("anh/chị muốn xem căn nào ạ")
        assert "anh chị muốn xem" in result
        assert "và" not in result

    def test_word_slash_no_tren(self):
        """A word/word slash still must not be read as 'trên'."""
        result = normalize_for_voice("nghệ thuật/văn hóa")
        assert "/" not in result
        assert "nghệ thuật văn hóa" in result

    def test_percent(self):
        result = normalize_for_voice("Lãi suất 8.5%")
        assert "phần trăm" in result

    def test_km(self):
        result = normalize_for_voice("Cách 15km")
        assert "ki lô mét" in result


class TestAbbreviations:
    """Known abbreviations expand to full words; unknown ones spell out."""

    def test_cccd_known(self):
        result = normalize_for_voice("Cần CCCD để xác minh")
        assert "căn cước công dân" in result

    def test_gpxd_known(self):
        result = normalize_for_voice("Đã có GPXD")
        assert "giấy phép xây dựng" in result

    def test_cdt_known(self):
        result = normalize_for_voice("CĐT uy tín")
        assert "chủ đầu tư" in result

    def test_bds_known(self):
        result = normalize_for_voice("Thị trường BĐS")
        assert "bất động sản" in result

    def test_unknown_abbrev_spelled_out(self):
        """Unknown ALL-CAPS abbreviation gets spelled letter-by-letter."""
        result = normalize_for_voice("Hệ thống HVAC hiện đại")
        # HVAC → "hát vê a xê"
        assert "HVAC" not in result
        assert "hát" in result  # H
        assert "vê" in result  # V

    def test_unknown_two_letter(self):
        result = normalize_for_voice("Mã QR trên app")
        assert "QR" not in result
        assert "quy" in result  # Q
        assert "rờ" in result  # R

    def test_short_words_not_affected(self):
        """Single uppercase letter or lowercase words should not be expanded."""
        result = normalize_for_voice("Tòa A rất đẹp")
        # "A" is only 1 char — regex requires 2+ so it stays
        assert "Tòa A" in result

    def test_parenthesized_abbrev_removed(self):
        result = normalize_for_voice("Dự án Noble Crystal Long Biên (NCLB) rất đẹp")
        assert "(NCLB)" not in result
        assert "NCLB" not in result
        assert "Noble Crystal Long Biên" in result
        assert "rất đẹp" in result

    def test_parenthesized_multiple(self):
        result = normalize_for_voice("Chủ đầu tư (CĐT) đã có giấy phép xây dựng (GPXD)")
        assert "(CĐT)" not in result
        assert "(GPXD)" not in result

    def test_parenthesized_keeps_non_abbrev(self):
        """Parentheses with lowercase or mixed content should stay."""
        result = normalize_for_voice("Noble (dự án cao cấp) tại Hà Nội")
        assert "(dự án cao cấp)" in result


class TestAllCapsProperNames:
    """Tên riêng viết HOA không bị đánh vần — DB tenant lưu tên dự án HOA TOÀN BỘ."""

    def test_project_name_not_spelled(self):
        result = normalize_for_voice("Bên em có dự án NOBLE CRYSTAL TÂY HỒ ạ")
        assert "Noble Crystal TÂY HỒ" in result
        assert "nờ o bê lờ e" not in result

    def test_short_english_words_in_phrase(self):
        """Cụm HOA cứu cả token ngắn: "SKY"/"CITY"/"BAY" đều ≤ 4 chữ."""
        result = normalize_for_voice("Còn SUNSHINE SKY CITY và SUNSHINE BAY RETREAT")
        assert "Sunshine Sky City" in result
        assert "Sunshine Bay Retreat" in result

    def test_long_name_alone_not_spelled(self):
        """Đứng lẻ thì vế độ dài + nguyên âm đỡ."""
        assert "Vinhomes" in normalize_for_voice("So với VINHOMES thì rẻ hơn")

    def test_abbrev_beside_caps_name_still_spelled(self):
        """Viết tắt lạ đứng lẻ giữa câu chữ thường vẫn đánh vần."""
        result = normalize_for_voice("Hệ thống HVAC của NOBLE PALACE TÂY HỒ")
        assert "hát vê a xê" in result
        assert "Noble Palace" in result

    def test_usd_expanded(self):
        assert "đô la Mỹ" in normalize_for_voice("Giá 5000 USD")


class TestSpecialCharacters:
    def test_url_removed(self):
        result = normalize_for_voice("Xem tại https://noble.vn/project chi tiết")
        assert "https" not in result
        assert "chi tiết" in result

    def test_markdown_code_removed(self):
        result = normalize_for_voice("Giá `3.5 tỷ` cho căn")
        assert "`" not in result

    def test_special_chars_stripped(self):
        result = normalize_for_voice("★ Ưu đãi đặc biệt ●")
        assert "★" not in result
        assert "●" not in result
        assert "Ưu đãi đặc biệt" in result

    def test_empty_string(self):
        assert normalize_for_voice("") == ""

    def test_whitespace_collapsed(self):
        result = normalize_for_voice("Giá   từ   3.5  tỷ")
        assert "  " not in result


class TestPlainNumbers:
    def test_two_digit(self):
        result = normalize_for_voice("Tầng 15 tòa A")
        assert "mười lăm" in result

    def test_keeps_single_digit(self):
        # Single digits should stay as-is (regex requires 2+ digits)
        result = normalize_for_voice("Có 3 phòng ngủ")
        assert "3" in result

    def test_large_number(self):
        result = normalize_for_voice("Tổng 413 căn")
        assert "bốn trăm mười ba" in result


class TestCombined:
    def test_real_estate_sentence(self):
        text = "Căn hộ 85m2 giá 3.5 tỷ, tầng 15, đã có GPXD"
        result = normalize_for_voice(text)
        assert "mét vuông" in result
        assert "tỷ" in result
        assert "giấy phép xây dựng" in result
        assert "m2" not in result
        assert "GPXD" not in result


class TestRobustness:
    """A long digit run (LLM repetition loop / malformed input) must not crash or
    hang — normalize runs synchronously before tts.stream(), so a hang blocks the
    audio event loop and a crash kills the turn."""

    def test_long_digit_run_with_unit_no_crash(self):
        # Was ValueError: int() string-conversion limit (>4300 digits) via _PRICE_RE
        normalize_for_voice("9" * 6000 + " tỷ")

    def test_long_dotted_number_no_hang(self):
        # Was ~2.3s O(n²) backtracking after de-grouping into one huge digit run
        import time

        t0 = time.perf_counter()
        normalize_for_voice("1" + ".234" * 2000)
        assert time.perf_counter() - t0 < 1.0

    def test_long_bare_digit_run_no_hang(self):
        import time

        t0 = time.perf_counter()
        normalize_for_voice("9" * 6000)
        assert time.perf_counter() - t0 < 1.0
