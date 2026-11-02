"""Unit tests for the init-time backend fallback helper (`voice/fallback.py`).

Pure-Python, no heavy imports — the seam is testable in isolation so the
unit suite collects without optional STT/TTS deps.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from noble_agent.voice.fallback import (
    STT_FALLBACK_CHAIN,
    TTS_FALLBACK_CHAIN,
    _start_first_available,
    resolve_order,
)

# ----------------------------------------------------------------------
# resolve_order
# ----------------------------------------------------------------------


def test_resolve_order_primary_head_stt() -> None:
    assert resolve_order("sherpa", STT_FALLBACK_CHAIN) == ["sherpa", "remote", "soniox"]


def test_resolve_order_configured_stays_head() -> None:
    assert resolve_order("soniox", STT_FALLBACK_CHAIN) == ["soniox", "remote", "sherpa"]


def test_resolve_order_tts_chain() -> None:
    # New chain: remote → vieneu_vllm → elevenlabs → vieneu (fast streaming server
    # preferred, local in-worker vieneu last-resort).
    assert resolve_order("vieneu", TTS_FALLBACK_CHAIN) == [
        "vieneu",
        "remote",
        "vieneu_vllm",
        "elevenlabs",
        "hotline_ws",
    ]


def test_resolve_order_tts_configured_stays_head() -> None:
    assert resolve_order("elevenlabs", TTS_FALLBACK_CHAIN) == [
        "elevenlabs",
        "remote",
        "vieneu_vllm",
        "vieneu",
        "hotline_ws",
    ]


def test_resolve_order_tts_vieneu_vllm_head() -> None:
    assert resolve_order("vieneu_vllm", TTS_FALLBACK_CHAIN) == [
        "vieneu_vllm",
        "remote",
        "elevenlabs",
        "vieneu",
        "hotline_ws",
    ]


def test_resolve_order_not_in_chain_is_single() -> None:
    assert resolve_order("qwen3asr", STT_FALLBACK_CHAIN) == ["qwen3asr"]


def test_resolve_order_remote_head_prefers_cloud_then_local_stt() -> None:
    assert resolve_order("remote", STT_FALLBACK_CHAIN) == ["remote", "soniox", "sherpa"]


def test_resolve_order_remote_head_prefers_cloud_then_local_tts() -> None:
    assert resolve_order("remote", TTS_FALLBACK_CHAIN) == [
        "remote",
        "vieneu_vllm",
        "elevenlabs",
        "vieneu",
        "hotline_ws",
    ]


# ----------------------------------------------------------------------
# _start_first_available
# ----------------------------------------------------------------------


async def test_start_first_available_primary_ok() -> None:
    sherpa_inst = AsyncMock()
    soniox_inst = AsyncMock()
    soniox_builder_calls = 0

    def _soniox():
        nonlocal soniox_builder_calls
        soniox_builder_calls += 1
        return soniox_inst

    builders = {"sherpa": lambda: sherpa_inst, "soniox": _soniox}
    on_exhausted = AsyncMock()

    result = await _start_first_available(["sherpa", "soniox"], builders, on_exhausted=on_exhausted)

    assert result is sherpa_inst
    sherpa_inst.start.assert_awaited_once()
    assert soniox_builder_calls == 0  # second backend never built
    on_exhausted.assert_not_awaited()


async def test_start_first_available_falls_through() -> None:
    sherpa_inst = AsyncMock()
    sherpa_inst.start = AsyncMock(side_effect=RuntimeError("sherpa down"))
    soniox_inst = AsyncMock()

    builders = {"sherpa": lambda: sherpa_inst, "soniox": lambda: soniox_inst}
    on_exhausted = AsyncMock()

    result = await _start_first_available(["sherpa", "soniox"], builders, on_exhausted=on_exhausted)

    assert result is soniox_inst
    soniox_inst.start.assert_awaited_once()
    on_exhausted.assert_not_awaited()


async def test_start_first_available_tears_down_failed_backend() -> None:
    """A backend that constructs OK but fails `start()` has its `stop()` awaited once."""
    sherpa_inst = AsyncMock()
    sherpa_inst.start = AsyncMock(side_effect=RuntimeError("sherpa down"))
    sherpa_inst.stop = AsyncMock()
    soniox_inst = AsyncMock()

    builders = {"sherpa": lambda: sherpa_inst, "soniox": lambda: soniox_inst}
    on_exhausted = AsyncMock()

    result = await _start_first_available(["sherpa", "soniox"], builders, on_exhausted=on_exhausted)

    assert result is soniox_inst
    sherpa_inst.stop.assert_awaited_once()
    soniox_inst.start.assert_awaited_once()
    on_exhausted.assert_not_awaited()


async def test_start_first_available_teardown_failure_does_not_break_fallback() -> None:
    """If the failed backend's `stop()` itself raises, fallback still proceeds."""
    sherpa_inst = AsyncMock()
    sherpa_inst.start = AsyncMock(side_effect=RuntimeError("sherpa down"))
    sherpa_inst.stop = AsyncMock(side_effect=RuntimeError("stop blew up"))
    soniox_inst = AsyncMock()

    builders = {"sherpa": lambda: sherpa_inst, "soniox": lambda: soniox_inst}
    on_exhausted = AsyncMock()

    result = await _start_first_available(["sherpa", "soniox"], builders, on_exhausted=on_exhausted)

    assert result is soniox_inst
    sherpa_inst.stop.assert_awaited_once()
    soniox_inst.start.assert_awaited_once()
    on_exhausted.assert_not_awaited()


async def test_start_first_available_construct_failure_no_teardown() -> None:
    """A builder that raises during construction has no instance to tear down."""
    soniox_inst = AsyncMock()

    def _boom():
        raise RuntimeError("construct failed")

    builders = {"sherpa": _boom, "soniox": lambda: soniox_inst}
    on_exhausted = AsyncMock()

    result = await _start_first_available(["sherpa", "soniox"], builders, on_exhausted=on_exhausted)

    assert result is soniox_inst
    soniox_inst.start.assert_awaited_once()
    on_exhausted.assert_not_awaited()


async def test_start_first_available_all_fail() -> None:
    sherpa_inst = AsyncMock()
    sherpa_inst.start = AsyncMock(side_effect=RuntimeError("sherpa down"))
    soniox_inst = AsyncMock()
    soniox_inst.start = AsyncMock(side_effect=RuntimeError("soniox down"))

    builders = {"sherpa": lambda: sherpa_inst, "soniox": lambda: soniox_inst}
    on_exhausted = AsyncMock()

    result = await _start_first_available(["sherpa", "soniox"], builders, on_exhausted=on_exhausted)

    assert result is None
    on_exhausted.assert_awaited_once()


async def test_create_tts_builds_remote_backend(monkeypatch):
    """_create_tts với TTS_BACKEND=remote trả về RemoteTTS (không load vieneu)."""
    from noble_agent.config import settings
    from noble_agent.voice.tts.remote import RemoteTTS
    from noble_agent.voice.voice_agent import VoiceAgent

    monkeypatch.setattr(settings, "tts_backend", "remote")
    monkeypatch.setattr(RemoteTTS, "__init__", lambda self: None)
    tts = VoiceAgent._create_tts()
    assert isinstance(tts, RemoteTTS)


async def test_start_first_available_remote_down_falls_back_to_soniox() -> None:
    """STT_BACKEND=remote, service down → fallback to soniox (never reaches sherpa)."""
    order = resolve_order("remote", STT_FALLBACK_CHAIN)
    assert order == ["remote", "soniox", "sherpa"]

    remote_inst = AsyncMock()
    remote_inst.start = AsyncMock(side_effect=ConnectionRefusedError("service down"))
    soniox_inst = AsyncMock()
    sherpa_inst = AsyncMock()
    sherpa_builder_calls = 0

    def _sherpa():
        nonlocal sherpa_builder_calls
        sherpa_builder_calls += 1
        return sherpa_inst

    builders = {
        "remote": lambda: remote_inst,
        "soniox": lambda: soniox_inst,
        "sherpa": _sherpa,
    }
    on_exhausted = AsyncMock()

    result = await _start_first_available(order, builders, on_exhausted=on_exhausted)

    assert result is soniox_inst
    remote_inst.start.assert_awaited_once()
    soniox_inst.start.assert_awaited_once()
    assert sherpa_builder_calls == 0  # sherpa builder never called
    on_exhausted.assert_not_awaited()
