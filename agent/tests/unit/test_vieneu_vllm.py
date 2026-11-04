"""Unit tests for the `vieneu_vllm` client TTS backend (Phase 2, Step 2.2).

NO GPU / NO model / NO vLLM server — everything external is faked:
  * the codec-only lib instance + standalone tokenizer are stubbed so no model loads;
  * the sync HTTP SSE stream is monkeypatched to yield canned `data:` lines;
  * the Phase-1 sink `stream_speech_tokens_to_audio` is monkeypatched to a sentinel.

The tests pin the spike-verified `/v1/completions` payload shape, the SSE→fragment
parse, that the accumulated fragments feed the SAME sink, that PCM int16 bytes come
out, and that `pause()` sets the stop_event so the source stops + closes the stream.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

import noble_agent.voice.tts.vieneu_vllm as mod

# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeTokenizer:
    """Maps the santa-tts special tokens + speech tokens to deterministic ids."""

    _SPECIALS = {
        "<|TEXT_PROMPT_START|>": 1000,
        "<|TEXT_PROMPT_END|>": 1001,
        "<|SPEECH_GENERATION_START|>": 1002,
        "<|SPEECH_GENERATION_END|>": 1003,
        "<|TEXT_REPLACE|>": 1004,
        "<|SPEECH_REPLACE|>": 1005,
    }

    def convert_tokens_to_ids(self, token: str) -> int:
        return self._SPECIALS[token]

    def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
        # Deterministic, reversible-enough stand-in: 1 id per char, offset 2000,
        # BUT any embedded special token (e.g. the chat template's <|TEXT_REPLACE|>)
        # is emitted as its single special id so .index(...) splicing works.
        ids: list[int] = []
        i = 0
        while i < len(text):
            matched = None
            if text[i] == "<":
                for tok, tid in self._SPECIALS.items():
                    if text.startswith(tok, i):
                        matched = (tok, tid)
                        break
            if matched:
                ids.append(matched[1])
                i += len(matched[0])
            else:
                ids.append(2000 + ord(text[i]))
                i += 1
        return ids


class _FakeVoice(dict):
    pass


def _fake_voice() -> dict:
    return _FakeVoice(codes=[5, 6, 7], text="xin chào")


def _sse_lines() -> list[str]:
    """Canned SSE `data:` lines: 3 speech tokens then the terminator."""
    return [
        'data: {"choices":[{"text":"<|speech_11|>","finish_reason":null}]}',
        'data: {"choices":[{"text":"<|speech_22|>","finish_reason":null}]}',
        'data: {"choices":[{"text":"<|speech_33|>","finish_reason":null}]}',
        "data: [DONE]",
    ]


class _FakeResponse:
    """Minimal stand-in for a streaming `requests`/`httpx` response."""

    def __init__(self, lines: list[str]):
        self._lines = lines
        self.closed = False

    def iter_lines(self):
        yield from self._lines

    def close(self):
        self.closed = True

    def raise_for_status(self):
        pass


@pytest.fixture(autouse=True)
def _patch_externals(monkeypatch):
    """Stub the codec-only instance, tokenizer, and normalize so no model loads."""
    fake_tts = object()  # the sink is monkeypatched, so the instance is never used
    voice = _fake_voice()
    monkeypatch.setattr(mod, "_load_codec_only", lambda: (fake_tts, voice))
    monkeypatch.setattr(mod, "_get_tokenizer", lambda: _FakeTokenizer())
    monkeypatch.setattr(mod, "_normalize_for_vieneu", lambda t: t)
    # Phonemizer is heavy + needs eSpeak data — stub it.
    monkeypatch.setattr(mod, "_phonemize_ref", lambda t: f"PH({t})")
    monkeypatch.setattr(mod, "_phonemize_chunk", lambda t: f"PH({t})")
    # The construction-time liveness probe must not hit a real server in unit tests.
    monkeypatch.setattr(mod, "_probe_server_alive", lambda: None)
    # Reset the once-per-process probe cache so each test sees a clean gate.
    monkeypatch.setattr(mod, "_probed_ok", False)
    return {"tts": fake_tts, "voice": voice}


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_token_source_builds_payload_and_parses_sse(monkeypatch):
    """(a) prompt_token_ids built with the right special-token ids + the required
    vLLM payload knobs (min_tokens, stop_token_ids, skip_special_tokens=false,
    stream=true); (b) each SSE `data:` line yields its `<|speech_N|>` text."""
    captured: dict = {}

    def _fake_post(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return _FakeResponse(_sse_lines())

    monkeypatch.setattr(mod, "_post_completions", _fake_post)

    stop = threading.Event()
    fragments = list(mod._vllm_token_source("xin chào", stop_event=stop))

    assert fragments == ["<|speech_11|>", "<|speech_22|>", "<|speech_33|>"]

    payload = captured["payload"]
    # prompt is a list of ints (prompt_token_ids), not a string.
    assert isinstance(payload["prompt"], list)
    assert all(isinstance(i, int) for i in payload["prompt"])
    # Boundary special-token ids are present in the right structure.
    tok = _FakeTokenizer()
    assert payload["prompt"][0] == tok.convert_tokens_to_ids("<|TEXT_PROMPT_START|>")
    assert tok.convert_tokens_to_ids("<|TEXT_PROMPT_END|>") in payload["prompt"]
    assert tok.convert_tokens_to_ids("<|SPEECH_GENERATION_START|>") in payload["prompt"]
    # The verified vLLM request knobs.
    assert payload["stream"] is True
    assert payload["min_tokens"] == 50
    assert payload["stop_token_ids"] == [tok.convert_tokens_to_ids("<|SPEECH_GENERATION_END|>")]
    assert payload["skip_special_tokens"] is False
    from noble_agent.config import settings

    assert payload["max_tokens"] == settings.vieneu_vllm_max_tokens
    assert payload["temperature"] == 1.0
    assert payload["top_k"] == 50


def test_max_tokens_clamped_to_fit_context(monkeypatch):
    """A LONG prompt must not blow past max_model_len: max_tokens is clamped so
    `len(prompt) + max_tokens <= vieneu_vllm_max_model_len`. This is the offline
    guard for the live HTTP-400 'maximum context length' bug (no audio)."""
    from noble_agent.config import settings

    captured: dict = {}
    monkeypatch.setattr(
        mod,
        "_post_completions",
        lambda url, payload: captured.update(payload=payload) or _FakeResponse(_sse_lines()),
    )
    # Force a long prompt: phonemizer stub emits enough chars that 1-id-per-char
    # encode pushes len(prompt) close to max_model_len.
    long_text = "a" * (settings.vieneu_vllm_max_model_len - 100)
    monkeypatch.setattr(mod, "_phonemize_ref", lambda t: long_text)
    monkeypatch.setattr(mod, "_phonemize_chunk", lambda t: "")

    list(mod._vllm_token_source("xin chào", stop_event=threading.Event()))

    payload = captured["payload"]
    assert len(payload["prompt"]) + payload["max_tokens"] <= settings.vieneu_vllm_max_model_len
    assert payload["max_tokens"] >= 1  # never zero/negative


def test_max_tokens_uses_configured_when_prompt_short(monkeypatch):
    """A short prompt that easily fits leaves the configured max_tokens budget intact."""
    from noble_agent.config import settings

    captured: dict = {}
    monkeypatch.setattr(
        mod,
        "_post_completions",
        lambda url, payload: captured.update(payload=payload) or _FakeResponse(_sse_lines()),
    )

    list(mod._vllm_token_source("xin chào", stop_event=threading.Event()))

    payload = captured["payload"]
    # Short prompt → the clamp is a no-op → the configured budget is used as-is.
    assert payload["max_tokens"] == settings.vieneu_vllm_max_tokens
    assert len(payload["prompt"]) + payload["max_tokens"] <= settings.vieneu_vllm_max_model_len


def test_prompt_non_chat_by_default():
    """Default (vieneu_use_chat_format None/False) → the non-chat prompt structure:
    starts with <|TEXT_PROMPT_START|>, ends with the SGS marker + codes, and carries
    NO chat-wrapper replace tokens."""
    tok = _FakeTokenizer()
    voice = _fake_voice()
    ids = mod._build_prompt_token_ids(tok, voice, "xin chào")

    assert ids[0] == tok.convert_tokens_to_ids("<|TEXT_PROMPT_START|>")
    assert tok.convert_tokens_to_ids("<|TEXT_PROMPT_END|>") in ids
    assert tok.convert_tokens_to_ids("<|SPEECH_GENERATION_START|>") in ids
    # No chat wrapper: replace tokens are never emitted on the non-chat path.
    assert tok.convert_tokens_to_ids("<|TEXT_REPLACE|>") not in ids
    assert tok.convert_tokens_to_ids("<|SPEECH_REPLACE|>") not in ids


def test_prompt_chat_format_when_flag_set(monkeypatch):
    """vieneu_use_chat_format=True → the CHAT-format prompt, mirroring the library's
    _apply_chat_template chat branch: the `user: Convert the text to speech:...`
    wrapper is present, with [TPS]+phonemes+[TPE] spliced at <|TEXT_REPLACE|> and
    [SGS]+codes spliced at <|SPEECH_REPLACE|>. Both replace markers are consumed
    (not present in the final ids)."""
    from noble_agent.config import settings

    monkeypatch.setattr(settings, "vieneu_use_chat_format", True)

    tok = _FakeTokenizer()
    voice = _fake_voice()
    ids = mod._build_prompt_token_ids(tok, voice, "xin chào")

    tps = tok.convert_tokens_to_ids("<|TEXT_PROMPT_START|>")
    tpe = tok.convert_tokens_to_ids("<|TEXT_PROMPT_END|>")
    sgs = tok.convert_tokens_to_ids("<|SPEECH_GENERATION_START|>")
    text_replace = tok.convert_tokens_to_ids("<|TEXT_REPLACE|>")
    speech_replace = tok.convert_tokens_to_ids("<|SPEECH_REPLACE|>")

    # The chat wrapper prefix "user: Convert the text to speech:" is present.
    wrapper_ids = tok.encode("user: Convert the text to speech:", add_special_tokens=False)
    assert ids[: len(wrapper_ids)] == wrapper_ids
    # The text block was spliced in at the TEXT_REPLACE position.
    assert tps in ids and tpe in ids and sgs in ids
    # The replace markers are consumed, not left in the final ids.
    assert text_replace not in ids
    assert speech_replace not in ids
    # The codes tail follows SGS (chat branch: [SGS] + codes at the end).
    sgs_idx = ids.index(sgs)
    codes_ids = tok.encode("".join(f"<|speech_{i}|>" for i in voice["codes"]), add_special_tokens=False)
    assert ids[sgs_idx + 1 :] == codes_ids
    # Structurally different from the non-chat default.
    monkeypatch.setattr(settings, "vieneu_use_chat_format", None)
    non_chat = mod._build_prompt_token_ids(tok, voice, "xin chào")
    assert ids != non_chat


def test_min_tokens_clamped_below_max(monkeypatch):
    """When a near-limit prompt clamps max_tokens below the configured min_tokens,
    the payload must NOT send min_tokens > max_tokens (vLLM 400). min_tokens is
    clamped to <= max_tokens."""
    from noble_agent.config import settings

    captured: dict = {}
    monkeypatch.setattr(
        mod,
        "_post_completions",
        lambda url, payload: captured.update(payload=payload) or _FakeResponse(_sse_lines()),
    )
    # Prompt within min_tokens of the limit: a phoneme string sized so the built
    # prompt leaves < min_tokens (50) of headroom, but still fits the context.
    near_limit = "a" * (settings.vieneu_vllm_max_model_len - 75)
    monkeypatch.setattr(mod, "_phonemize_ref", lambda t: near_limit)
    monkeypatch.setattr(mod, "_phonemize_chunk", lambda t: "")

    list(mod._vllm_token_source("xin chào", stop_event=threading.Event()))

    payload = captured["payload"]
    assert payload["min_tokens"] <= payload["max_tokens"]
    assert len(payload["prompt"]) + payload["max_tokens"] <= settings.vieneu_vllm_max_model_len


def test_prompt_exceeds_context_raises(monkeypatch):
    """A prompt alone >= max_model_len is a misconfig that would 400 no matter the
    max_tokens floor — raise a clear error instead of firing a doomed request."""
    from noble_agent.config import settings

    monkeypatch.setattr(
        mod,
        "_post_completions",
        lambda url, payload: pytest.fail("a doomed request was fired for an over-budget prompt"),
    )
    over = "a" * (settings.vieneu_vllm_max_model_len + 50)
    monkeypatch.setattr(mod, "_phonemize_ref", lambda t: over)
    monkeypatch.setattr(mod, "_phonemize_chunk", lambda t: "")

    with pytest.raises(ValueError, match="exceeds.*max_model_len"):
        list(mod._vllm_token_source("xin chào", stop_event=threading.Event()))


def test_token_source_pause_stops_and_closes(monkeypatch):
    """A pre-set stop_event stops the source and closes the HTTP response (barge-in)."""
    resp = _FakeResponse(_sse_lines())
    monkeypatch.setattr(mod, "_post_completions", lambda url, payload: resp)

    stop = threading.Event()
    stop.set()  # barge-in before the first line

    fragments = list(mod._vllm_token_source("hi", stop_event=stop))

    assert fragments == []  # stopped before yielding anything
    assert resp.closed is True  # the HTTP stream was closed


def test_stream_feeds_sink_and_yields_pcm(monkeypatch):
    """The accumulated fragments feed the SAME Phase-1 sink, which yields float32
    frames that the backend converts to PCM int16 bytes."""
    monkeypatch.setattr(mod, "_post_completions", lambda url, payload: _FakeResponse(_sse_lines()))

    seen: dict = {}

    def _fake_sink(tts, voice, token_iter, *, stop_event=None):
        # Drain the source so we can assert the fragments arrived from the SSE parse.
        seen["fragments"] = list(token_iter)
        seen["tts"] = tts
        seen["voice"] = voice
        yield np.array([0.5, -0.5], dtype=np.float32)
        yield np.array([0.25], dtype=np.float32)

    monkeypatch.setattr(mod, "stream_speech_tokens_to_audio", _fake_sink)

    tts = mod.VieNeuVLLMTTS()
    chunks = list(tts.stream("xin chào"))

    assert seen["fragments"] == ["<|speech_11|>", "<|speech_22|>", "<|speech_33|>"]
    # PCM int16 little-endian: 2 frames → 4 bytes, 1 frame → 2 bytes.
    assert len(chunks) == 2
    assert all(isinstance(c, bytes) for c in chunks)
    assert len(chunks[0]) == 4
    assert len(chunks[1]) == 2


def test_stream_passes_through_caller_stop_event(monkeypatch):
    """A caller-supplied stop_event is threaded into both the source and the sink."""
    monkeypatch.setattr(mod, "_post_completions", lambda url, payload: _FakeResponse(_sse_lines()))

    seen: dict = {}

    def _fake_sink(tts, voice, token_iter, *, stop_event=None):
        seen["stop_event"] = stop_event
        list(token_iter)
        return
        yield  # pragma: no cover — make it a generator

    monkeypatch.setattr(mod, "stream_speech_tokens_to_audio", _fake_sink)

    caller_stop = threading.Event()
    tts = mod.VieNeuVLLMTTS()
    list(tts.stream("hi", stop_event=caller_stop))

    assert seen["stop_event"] is caller_stop


async def test_pause_sets_stop_event(monkeypatch):
    """`pause()` (async, matching RemoteTTS) sets the active stream's stop_event."""
    tts = mod.VieNeuVLLMTTS()
    # stream() binds the per-turn event; simulate an in-flight stream.
    tts._stop_event = threading.Event()
    await tts.pause()
    assert tts._stop_event.is_set()


def test_construct_probes_server_and_raises_when_down(monkeypatch):
    """A down vLLM server (probe raises) must make construction RAISE, so the
    init-time fallback chain moves on to elevenlabs/vieneu instead of returning a
    dead backend (mid-session fallback does not exist). The probe runs BEFORE the
    codec load so we don't pay the codec load when the server is unreachable."""
    probe_called = {"n": 0}

    def _probe_down():
        probe_called["n"] += 1
        raise RuntimeError("connection refused")

    monkeypatch.setattr(mod, "_probe_server_alive", _probe_down)
    # If the codec load runs, it would call the (faked) _load_codec_only; assert it
    # is NOT reached by failing if it is.
    monkeypatch.setattr(mod, "_load_codec_only", lambda: pytest.fail("codec loaded despite server down"))

    with pytest.raises(RuntimeError, match="connection refused"):
        mod.VieNeuVLLMTTS()
    assert probe_called["n"] == 1


def test_construct_succeeds_when_probe_ok(monkeypatch):
    """Probe OK → construction proceeds (codec loads, no raise)."""
    calls = {"probe": 0}
    monkeypatch.setattr(mod, "_probe_server_alive", lambda: calls.update(probe=calls["probe"] + 1))

    tts = mod.VieNeuVLLMTTS()

    assert calls["probe"] == 1
    assert tts is not None


def test_probe_runs_once_per_process(monkeypatch):
    """The `/health` probe is a one-time process-level liveness gate: the resident
    TTS service builds a fresh client per WS connection (per clause), so re-probing
    each time is a redundant round-trip. Once it succeeds, later constructions skip
    the probe."""
    monkeypatch.setattr(mod, "_probed_ok", False)
    calls = {"probe": 0}
    monkeypatch.setattr(mod, "_probe_server_alive", lambda: calls.update(probe=calls["probe"] + 1))

    mod.VieNeuVLLMTTS()
    mod.VieNeuVLLMTTS()
    mod.VieNeuVLLMTTS()

    assert calls["probe"] == 1


def test_probe_failure_still_raises_and_reprobes(monkeypatch):
    """A down server must keep failing every construction until it comes up
    (startup fail-fast preserved): a FAILED probe does NOT cache, so the next
    construction probes again. Only success is cached."""
    monkeypatch.setattr(mod, "_probed_ok", False)
    calls = {"probe": 0}

    def _probe_down():
        calls["probe"] += 1
        raise RuntimeError("connection refused")

    monkeypatch.setattr(mod, "_probe_server_alive", _probe_down)
    monkeypatch.setattr(mod, "_load_codec_only", lambda: pytest.fail("codec loaded despite server down"))

    with pytest.raises(RuntimeError, match="connection refused"):
        mod.VieNeuVLLMTTS()
    with pytest.raises(RuntimeError, match="connection refused"):
        mod.VieNeuVLLMTTS()

    assert calls["probe"] == 2  # failure was NOT cached → re-probed


async def test_async_wrapper_drains_queue(monkeypatch):
    """AsyncVieNeuVLLMTTS bridges the sync generator to an async iterator."""
    monkeypatch.setattr(mod, "_post_completions", lambda url, payload: _FakeResponse(_sse_lines()))

    def _fake_sink(tts, voice, token_iter, *, stop_event=None):
        list(token_iter)
        yield np.array([0.5], dtype=np.float32)

    monkeypatch.setattr(mod, "stream_speech_tokens_to_audio", _fake_sink)

    tts = mod.AsyncVieNeuVLLMTTS()
    chunks = [c async for c in tts.stream("hi")]

    assert len(chunks) == 1
    assert isinstance(chunks[0], bytes)
