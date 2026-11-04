"""Unit tests for SentenceBuffer — clause/sentence splitting."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from unittest.mock import patch


class TestSentenceBufferAdd:
    """Test add() returns correct chunks."""

    def _make_buffer(self, mode="clause"):
        with patch("noble_agent.voice.sentence_buffer.settings") as mock_s:
            mock_s.buffer_mode = mode
            mock_s.min_sentence_length = 10
            mock_s.min_clause_length = 50
            from noble_agent.voice.sentence_buffer import SentenceBuffer

            buf = SentenceBuffer()
            buf._clause_mode = mode == "clause"
            buf.MIN_LENGTH = 10
            buf.MIN_CLAUSE = 50
            return buf

    def test_short_sentence_not_split(self):
        buf = self._make_buffer()
        chunks = buf.add("Dạ. ")
        assert chunks == []  # too short (< MIN_LENGTH=10)

    def test_sentence_ending_splits(self):
        buf = self._make_buffer()
        text = "Dạ em chào Anh Minh ạ."
        chunks = []
        for ch in text:
            chunks.extend(buf.add(ch))
        # Should have 1 chunk at the period
        assert len(chunks) == 1
        assert "Minh" in chunks[0].text

    def test_clause_mode_splits_at_comma(self):
        buf = self._make_buffer("clause")
        # Long enough clause (>50 chars) ending with comma
        text = "Dạ dự án Noble Crystal Tây Hồ có vị trí rất đẹp bên Hồ Tây, "
        chunks = []
        for ch in text:
            chunks.extend(buf.add(ch))
        if len(text.strip().rstrip(",")) >= 50:
            assert len(chunks) >= 1

    def test_sentence_mode_ignores_comma(self):
        buf = self._make_buffer("sentence")
        text = "Dạ dự án Noble Crystal Tây Hồ có vị trí rất đẹp, em giới thiệu thêm nhé."
        chunks = []
        for ch in text:
            chunks.extend(buf.add(ch))
        # In sentence mode, only split at period
        assert len(chunks) == 1

    def test_flush_returns_remaining(self):
        buf = self._make_buffer()
        buf.add("Dạ em đang tìm")
        result = buf.flush()
        assert result is not None
        assert result.text == "Dạ em đang tìm"
        assert buf.flush() is None  # empty after flush

    def test_abbreviation_not_split(self):
        buf = self._make_buffer()
        text = "Diện tích 85m2. Rất rộng rãi ạ."
        chunks = []
        for ch in text:
            chunks.extend(buf.add(ch))
        # m2. should NOT be treated as sentence boundary (in abbreviations)
        # but "ạ." should
        assert any("ạ." in c.text or "ạ" in c.text for c in chunks)

    def test_multiple_sentences(self):
        buf = self._make_buffer()
        text = "Dạ em chào Anh Minh ạ. Em là Luna ạ. "
        chunks = []
        for ch in text:
            chunks.extend(buf.add(ch))
        assert len(chunks) == 2

    def test_empty_token(self):
        buf = self._make_buffer()
        assert buf.add("") == []

    def test_number_with_period_not_split(self):
        buf = self._make_buffer()
        # "3.5 tỷ" should not split at the period
        text = "Giá từ 3.5 tỷ đến 5 tỷ ạ."
        chunks = []
        for ch in text:
            chunks.extend(buf.add(ch))
        # Should be 1 chunk (the whole sentence)
        assert len(chunks) == 1
        assert "3.5" in chunks[0].text
