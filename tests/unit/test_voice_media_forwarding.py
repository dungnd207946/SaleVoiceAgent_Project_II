"""Does the VOICE path send image (media items[]) and text together to the client?

Drives one turn where the LLM calls `send_media` (which returns an items[] payload)
then speaks, and inspects everything published via `_send_json` (the data-channel seam).

Expectation (per docs/api/noblex-app-dev-guide.md §3.1/§4.3): voice streams BOTH the
spoken text AND the media items[] to the app. Chat does this by forwarding the tool
`result` in the `tool_done` event (server/text_chat.py). This test checks voice parity.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

_MEDIA_RESULT = json.dumps(
    {
        "ok": True,
        "project": "NCTH",
        "items": [
            {
                "type": "image",
                "url": "https://agent-cms.noble.vn/api/v1/projects/media/abc/download?inline=true",
                "thumb": "https://agent-cms.noble.vn/api/v1/projects/media/abc/thumbnail",
                "medium": "https://agent-cms.noble.vn/api/v1/projects/media/abc/medium",
            }
        ],
        "count": 1,
    },
    ensure_ascii=False,
)


def _build_agent():
    from noble_agent.config import settings
    from noble_agent.metrics import MetricsCollector
    from noble_agent.voice.voice_agent import VoiceAgent

    settings.tool_ack_probability = 1.0
    settings.tool_ack_cooldown_s = 0.0

    agent = VoiceAgent.__new__(VoiceAgent)
    agent._send_audio = AsyncMock()
    agent._send_json = AsyncMock()
    agent._interrupted = False
    agent._metrics = MetricsCollector()
    agent._billing = None  # billing metering off by default (fix round 2, Task 7)
    agent._last_ack_monotonic = 0.0
    mock_tts = MagicMock()

    async def _fake_stream(_text: str):
        yield b"\x00" * 320

    mock_tts.stream = _fake_stream
    agent._tts = mock_tts
    agent._ack_assets = []
    return agent


def _make_send_media_llm():
    async def fake_stream_response(
        user_text, on_token, on_tool_start=None, on_tool_done=None, interrupt_check=None, on_agent_switch=None
    ):
        if on_tool_start:
            on_tool_start("send_media", {})
        if on_tool_done:
            on_tool_done("send_media", _MEDIA_RESULT)  # dispatcher passes the items[] payload here
        on_token("Dạ, em gửi hình phối cảnh cho mình tham khảo nhé.")
        return "Dạ, em gửi hình phối cảnh cho mình tham khảo nhé."

    m = MagicMock()
    m.stream_response = fake_stream_response
    return m


async def _run_turn():
    agent = _build_agent()
    agent._llm = _make_send_media_llm()
    await agent.handle_utterance("cho em xem phối cảnh dự án với")
    await asyncio.sleep(0.05)  # drain fire-and-forget _send_json tasks (ensure_future)
    return [c.args[0] for c in agent._send_json.call_args_list]


@pytest.mark.asyncio
async def test_voice_emits_text_for_a_media_turn() -> None:
    events = await _run_turn()
    text_events = [e for e in events if e.get("type") in ("transcript", "agent_speaking") and e.get("text")]
    assert text_events, f"expected voice to emit spoken/transcript text; events={[e.get('type') for e in events]}"


@pytest.mark.asyncio
async def test_voice_forwards_media_items_alongside_text() -> None:
    """Image + text together: a `media` event carrying items[] AND spoken text in one turn."""
    events = await _run_turn()
    types = [e.get("type") for e in events]

    # §4.3: dedicated `media` event whose payload IS the §4.1 media payload (items[]).
    media_events = [e for e in events if e.get("type") == "media" and e.get("items")]
    assert media_events, f"voice did NOT emit a `media` event with items[] — image dropped. Events: {types}"
    assert media_events[0]["items"][0]["medium"].endswith("/medium")  # §4.1 payload forwarded intact

    # ...and the spoken text is still delivered in the same turn.
    text_events = [e for e in events if e.get("type") in ("transcript", "agent_speaking") and e.get("text")]
    assert text_events, f"expected spoken/transcript text alongside media. Events: {types}"


@pytest.mark.asyncio
async def test_voice_no_media_event_for_empty_items() -> None:
    """A no_media / empty-items tool result must NOT produce a `media` event."""
    from noble_agent.voice.voice_agent import VoiceAgent  # noqa: F401  (ensure import path valid)

    agent = _build_agent()

    async def fake_stream_response(
        user_text, on_token, on_tool_start=None, on_tool_done=None, interrupt_check=None, on_agent_switch=None
    ):
        if on_tool_done:
            on_tool_done("send_media", json.dumps({"ok": False, "items": [], "note": "no_media"}))
        on_token("Dạ hiện dự án này chưa có hình ạ.")
        return "Dạ hiện dự án này chưa có hình ạ."

    m = MagicMock()
    m.stream_response = fake_stream_response
    agent._llm = m
    await agent.handle_utterance("cho xem hình")
    await asyncio.sleep(0.05)
    events = [c.args[0] for c in agent._send_json.call_args_list]
    assert not [e for e in events if e.get("type") == "media"], "empty items[] must not emit a media event"
