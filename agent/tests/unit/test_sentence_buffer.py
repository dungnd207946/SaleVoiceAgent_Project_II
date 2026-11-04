"""Test sentence buffer — Vietnamese patterns, clause mode, boundary detection."""

from noble_agent.voice.sentence_buffer import SentenceBuffer


class TestGreetingNotSplit:
    def test_greeting_stays_intact(self):
        buf = SentenceBuffer()
        tokens = [
            "Dạ",
            " em",
            " chào",
            " chị",
            " Linh",
            " ạ,",
            " em",
            " là",
            " Luna,",
            " Chuyên",
            " viên",
            " tư",
            " vấn",
            " Noble",
            " ạ.",
        ]
        chunks = []
        for t in tokens:
            chunks.extend(buf.add(t))
        assert len(chunks) == 1
        assert "Luna" in chunks[0].text
        assert "Dạ" in chunks[0].text


class TestMultipleSentences:
    def test_two_sentences(self):
        buf = SentenceBuffer()
        text = "Dạ em chào Quý Khách ạ. Em có thể giúp gì ạ?"
        tokens = [(" " + t if i > 0 else t) for i, t in enumerate(text.split(" "))]
        chunks = []
        for t in tokens:
            chunks.extend(buf.add(t))
        r = buf.flush()
        if r:
            chunks.append(r)
        assert len(chunks) == 2


class TestFlush:
    def test_flush_returns_remainder(self):
        buf = SentenceBuffer()
        buf.add("Dạ em đang kiểm tra")
        r = buf.flush()
        assert r is not None
        assert r.text == "Dạ em đang kiểm tra"

    def test_flush_empty(self):
        buf = SentenceBuffer()
        assert buf.flush() is None
