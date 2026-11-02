"""Unit tests for the addressee gate (chống nói leo) — config, heuristic, dispatch."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from noble_agent.voice.addressee_gate import EpisodeTracker, Verdict, _render_dialogue, classify, classify_heuristic


class TestConfigDefaults:
    def test_addressee_settings_exist_with_safe_defaults(self) -> None:
        from noble_agent.config import UnifiedSettings

        s = UnifiedSettings(_env_file=None)
        assert s.addressee_gate_mode == "off"
        assert s.addressee_min_speech_ms == 400
        assert s.addressee_llm_model == ""
        assert s.addressee_llm_timeout_ms == 600
        assert s.addressee_gate_when_idle is False
        assert s.addressee_resume_ack_text == "Em nói tiếp nhé."


class TestClassifyHeuristic:
    @pytest.mark.parametrize(
        "text",
        ["ừ", "Dạ", "vâng ạ", "ờ ờ", "ok", "à vâng", "dạ dạ"],
    )
    def test_backchannel_is_side_talk(self, text: str) -> None:
        assert classify_heuristic(text) is Verdict.SIDE_TALK

    @pytest.mark.parametrize(
        "text",
        ["em ơi cho anh hỏi", "alo alo", "Luna ơi", "này em, giá căn 2 ngủ sao", "em, ơi cho anh hỏi"],
    )
    def test_calling_agent_is_directed(self, text: str) -> None:
        assert classify_heuristic(text, agent_name="Luna") is Verdict.DIRECTED

    @pytest.mark.parametrize(
        "text",
        ["anh ơi con khóc kìa", "mẹ ơi ra ăn cơm", "bà ơi cầm hộ cái túi"],
    )
    def test_calling_someone_else_is_side_talk(self, text: str) -> None:
        assert classify_heuristic(text, agent_name="Luna") is Verdict.SIDE_TALK

    @pytest.mark.parametrize(
        "text",
        ["thế dự án đó bao nhiêu tiền", "cái căn hai phòng ngủ ấy", "tôi thấy cũng được đấy"],
    )
    def test_plain_sentence_is_unsure(self, text: str) -> None:
        assert classify_heuristic(text, agent_name="Luna") is Verdict.UNSURE

    def test_empty_text_is_unsure(self) -> None:
        assert classify_heuristic("   ") is Verdict.UNSURE


class TestEpisodeTracker:
    def test_sustained_speech_crosses_threshold(self) -> None:
        t = EpisodeTracker(min_speech_ms=400, chunk_ms=32)
        results = [t.feed(True) for _ in range(13)]  # 13 × 32ms = 416ms
        assert results[-1] == "pause"
        assert all(r is None for r in results[:-1])

    def test_short_blip_then_silence_resets(self) -> None:
        t = EpisodeTracker(min_speech_ms=400, chunk_ms=32, silence_reset_ms=320)
        for _ in range(5):  # 160ms speech — dưới ngưỡng
            assert t.feed(True) is None
        results = [t.feed(False) for _ in range(10)]  # 320ms silence
        assert results[-1] == "reset"

    def test_pause_fires_once(self) -> None:
        t = EpisodeTracker(min_speech_ms=64, chunk_ms=32)
        assert t.feed(True) is None
        assert t.feed(True) == "pause"
        assert t.feed(True) is None  # đã pause — không bắn lại

    def test_reset_allows_new_episode(self) -> None:
        t = EpisodeTracker(min_speech_ms=64, chunk_ms=32)
        t.feed(True)
        assert t.feed(True) == "pause"
        t.reset()
        t.feed(True)
        assert t.feed(True) == "pause"


def _mock_settings(mode: str):
    s = type("S", (), {})()
    s.addressee_gate_mode = mode
    s.addressee_llm_model = ""
    s.addressee_llm_timeout_ms = 600
    s.agent_model = ""
    s.summary_model = ""
    s.llm_enable_thinking = False
    s.openai_reasoning_effort = "none"
    return s


class TestClassifyDispatch:
    async def test_mode_off_always_directed(self) -> None:
        with patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("off")):
            assert await classify("anh ơi con khóc kìa") is Verdict.DIRECTED

    async def test_mode_heuristic_unsure_fails_open_to_directed(self) -> None:
        with patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("heuristic")):
            assert await classify("thế giá bao nhiêu nhỉ") is Verdict.DIRECTED

    async def test_mode_heuristic_side_talk_detected(self) -> None:
        with patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("heuristic")):
            assert await classify("anh ơi con khóc kìa") is Verdict.SIDE_TALK

    async def test_mode_hybrid_unsure_falls_to_llm(self) -> None:
        with (
            patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("hybrid")),
            patch(
                "noble_agent.voice.addressee_gate._classify_llm",
                new=AsyncMock(return_value=Verdict.SIDE_TALK),
            ) as mock_llm,
        ):
            assert await classify("thế giá bao nhiêu nhỉ") is Verdict.SIDE_TALK
            mock_llm.assert_awaited_once()

    async def test_mode_hybrid_heuristic_hit_skips_llm(self) -> None:
        with (
            patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("hybrid")),
            patch("noble_agent.voice.addressee_gate._classify_llm", new=AsyncMock()) as mock_llm,
        ):
            assert await classify("em ơi") is Verdict.DIRECTED
            mock_llm.assert_not_awaited()

    async def test_llm_exception_fails_open_to_directed(self) -> None:
        with (
            patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("llm")),
            patch(
                "noble_agent.voice.addressee_gate._classify_llm",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            assert await classify("bất kỳ câu gì") is Verdict.DIRECTED

    async def test_llm_unsure_fails_open_to_directed(self) -> None:
        with (
            patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("llm")),
            patch(
                "noble_agent.voice.addressee_gate._classify_llm",
                new=AsyncMock(return_value=Verdict.UNSURE),
            ),
        ):
            assert await classify("câu mơ hồ") is Verdict.DIRECTED

    async def test_recent_dialogue_forwarded_to_classify_llm(self) -> None:
        with (
            patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("llm")),
            patch(
                "noble_agent.voice.addressee_gate._classify_llm",
                new=AsyncMock(return_value=Verdict.DIRECTED),
            ) as mock_llm,
        ):
            ring = (("user", "giá bao nhiêu"), ("agent", "dạ để em xem lại"))
            assert await classify("ok", recent_dialogue=ring) is Verdict.DIRECTED
            mock_llm.assert_awaited_once()
            _, kwargs = mock_llm.call_args
            assert kwargs["recent_dialogue"] == ring


class TestRenderDialogue:
    """`_render_dialogue` — pure render helper cho dialogue-ring context (2026-08-12 chiều)."""

    def test_empty_input_returns_empty_string(self) -> None:
        assert _render_dialogue((), "Luna") == ""

    def test_user_role_maps_to_khach_label(self) -> None:
        result = _render_dialogue((("user", "giá bao nhiêu vậy"),), "Luna")
        assert result == "Khách: giá bao nhiêu vậy"

    def test_non_user_role_maps_to_agent_name(self) -> None:
        result = _render_dialogue((("agent", "dạ để em xem lại"),), "Luna")
        assert result == "Luna: dạ để em xem lại"

    def test_multiple_entries_render_one_line_each_in_order(self) -> None:
        result = _render_dialogue(
            (("user", "giá bao nhiêu"), ("agent", "dạ để em xem"), ("user", "ok cảm ơn")),
            "Luna",
        )
        assert result == "Khách: giá bao nhiêu\nLuna: dạ để em xem\nKhách: ok cảm ơn"

    def test_each_line_truncated_to_200_chars(self) -> None:
        long_text = "a" * 250
        result = _render_dialogue((("user", long_text),), "Luna")
        assert result == f"Khách: {'a' * 200}"

    def test_missing_agent_name_defaults_to_luna(self) -> None:
        assert _render_dialogue((("agent", "hi"),), "") == "Luna: hi"


class TestParseLlmVerdict:
    def test_parse_variants(self) -> None:
        from noble_agent.voice.addressee_gate import _parse_verdict

        assert _parse_verdict("SIDE_TALK") is Verdict.SIDE_TALK
        assert _parse_verdict("side talk.") is Verdict.SIDE_TALK
        assert _parse_verdict("DIRECTED") is Verdict.DIRECTED
        assert _parse_verdict(" directed\n") is Verdict.DIRECTED
        assert _parse_verdict("không rõ") is Verdict.UNSURE
        assert _parse_verdict("") is Verdict.UNSURE
