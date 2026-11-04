"""Token-level streaming for VieNeu TTS — codec SINK + flag wiring (Phase 1).

All tests use a FAKE token stream + FAKE `_decode` (no model / GPU / vieneu lib weights).
The only real dependency is `vieneu.utils` (`extract_speech_ids`, `_linear_overlap_add`),
which is pure-python and importable without the model.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np


def _make_fake_tts():
    """A stand-in lib instance exposing only what the sink touches."""

    class FakeTTS:
        # Standard vieneu streaming attrs (vieneu/standard.py:34-38, base.py:23).
        streaming_overlap_frames = 1
        streaming_frames_per_chunk = 25
        streaming_lookforward = 10
        streaming_lookback = 100
        hop_length = 480
        streaming_stride_samples = 25 * 480

        def _decode(self, codes_str: str) -> np.ndarray:
            from vieneu.utils import extract_speech_ids

            n = len(extract_speech_ids(codes_str))
            return np.arange(n * self.hop_length, dtype=np.float32)

        def _apply_watermark(self, wav: np.ndarray) -> np.ndarray:
            return wav

    return FakeTTS()


def _seed_voice():
    return {"codes": [0, 1, 2], "text": ""}


def _token_fragments(n: int):
    return [f"<|speech_{i}|>" for i in range(n)]


class _CountingIter:
    """Wraps an iterable, exposing how many items have been pulled."""

    def __init__(self, items):
        self._it = iter(items)
        self.pulled = 0

    def __iter__(self):
        return self

    def __next__(self):
        val = next(self._it)
        self.pulled += 1
        return val


def test_sink_chunks_incrementally():
    from noble_agent.voice.tts.vieneu import stream_speech_tokens_to_audio

    tts = _make_fake_tts()
    src = _CountingIter(_token_fragments(120))

    frames = []
    first_pulled_at_first_yield = None
    for i, frame in enumerate(stream_speech_tokens_to_audio(tts, _seed_voice(), src)):
        if i == 0:
            first_pulled_at_first_yield = src.pulled
        frames.append(frame)

    # (a) incremental, not one-shot
    assert len(frames) > 1
    # (b) first frame yielded before the source iterator is exhausted (lazy)
    assert first_pulled_at_first_yield is not None
    assert first_pulled_at_first_yield < 120
    # (c) concatenated audio is non-trivial and float32
    audio = np.concatenate(frames)
    assert audio.dtype == np.float32
    assert audio.size > 0


def test_sink_stops_on_event():
    from noble_agent.voice.tts.vieneu import stream_speech_tokens_to_audio

    tts = _make_fake_tts()
    src = _CountingIter(_token_fragments(300))
    stop = threading.Event()

    n_decode_calls = {"n": 0}
    real_decode = tts._decode

    def counting_decode(codes_str):
        n_decode_calls["n"] += 1
        if n_decode_calls["n"] >= 2:
            stop.set()  # request barge-in after 2 decoded chunks
        return real_decode(codes_str)

    tts._decode = counting_decode

    frames = list(stream_speech_tokens_to_audio(tts, _seed_voice(), src, stop_event=stop))

    # Stopped early: did NOT drain the whole 300-fragment source.
    assert src.pulled < 300
    # Yielded the chunks decoded before/at the stop, then bailed.
    assert len(frames) <= 2


def test_sink_skips_trailing_flush_when_stopped_after_loop():
    """Event set right as the source exhausts → trailing flush is skipped."""
    from noble_agent.voice.tts.vieneu import stream_speech_tokens_to_audio

    tts = _make_fake_tts()
    stop = threading.Event()

    def short_source():
        # Fewer than one chunk → no in-loop yield; sets stop on exhaustion.
        for i in range(5):
            yield f"<|speech_{i}|>"
        stop.set()

    frames = list(stream_speech_tokens_to_audio(tts, _seed_voice(), short_source(), stop_event=stop))

    # Stopped post-loop → no trailing-remainder frame.
    assert frames == []


# ── Step 1.4: VieNeuTTS.stream() flag wiring + pause() ────────────────────────


def _bare_vieneu(monkeypatch, streaming: bool):
    """A VieNeuTTS without loading the model (bypass _load_tts)."""
    from noble_agent.voice.tts import vieneu as v

    tts = v.VieNeuTTS.__new__(v.VieNeuTTS)
    tts._tts = SimpleNamespace()
    tts._voice = _seed_voice()
    tts._stop_event = threading.Event()
    tts._lock = threading.Lock()
    monkeypatch.setattr(v.settings, "tts_streaming", streaming, raising=False)
    monkeypatch.setattr(v, "_normalize_for_vieneu", lambda t: t)
    return v, tts


def test_stream_uses_sink_when_streaming_on(monkeypatch):
    v, tts = _bare_vieneu(monkeypatch, streaming=True)

    src_called = {"n": 0}

    def fake_source(_tts, _voice, _text, *, stop_event):
        src_called["n"] += 1
        yield "<|speech_5|>"

    def fake_sink(_tts, _voice, _iter, *, stop_event=None):
        list(_iter)  # drain the source so it's wired through
        yield np.ones(4, dtype=np.float32)
        yield np.ones(4, dtype=np.float32)

    monkeypatch.setattr(v, "_local_token_source", fake_source)
    monkeypatch.setattr(v, "stream_speech_tokens_to_audio", fake_sink)

    out = list(tts.stream("xin chào"))

    assert src_called["n"] == 1
    assert all(isinstance(c, bytes) for c in out)
    assert len(out) == 2  # sentinel sink yielded twice → PCM bytes


def test_stream_uses_oneshot_when_off(monkeypatch):
    v, tts = _bare_vieneu(monkeypatch, streaming=False)

    infer_called = {"n": 0}

    def fake_infer_stream(text, voice=None):
        infer_called["n"] += 1
        yield np.ones(4, dtype=np.float32)

    tts._tts.infer_stream = fake_infer_stream

    # If streaming were wrongly chosen, this would blow up (no source patched).
    monkeypatch.setattr(
        v, "_local_token_source", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run"))
    )

    out = list(tts.stream("xin chào"))

    assert infer_called["n"] == 1
    assert all(isinstance(c, bytes) for c in out)


async def test_pause_sets_event(monkeypatch):
    # pause() is async on BOTH classes (VoiceAgent.pause_tts does `await tts.pause()`;
    # RemoteTTS.pause is async). A sync def would make `await None` raise TypeError,
    # swallowed + logged on every barge-in, leaving the in-worker stop_event unset.
    v, tts = _bare_vieneu(monkeypatch, streaming=True)
    assert not tts._stop_event.is_set()
    await tts.pause()
    assert tts._stop_event.is_set()

    # AsyncVieNeuTTS.pause delegates to the inner sync wrapper, also async.
    async_tts = v.AsyncVieNeuTTS.__new__(v.AsyncVieNeuTTS)
    async_tts._tts = tts
    tts._stop_event.clear()
    await async_tts.pause()
    assert tts._stop_event.is_set()


async def test_pause_tts_await_site_sets_vieneu_event(monkeypatch):
    """VoiceAgent.pause_tts does `await tts.pause()` — verify the real await site sets
    the vieneu stop_event with NO swallowed TypeError (the sync-pause regression)."""
    from noble_agent.voice.voice_agent import VoiceAgent

    v, tts = _bare_vieneu(monkeypatch, streaming=True)

    agent = VoiceAgent.__new__(VoiceAgent)
    agent._interrupted = False
    agent._tts = tts

    await agent.pause_tts()

    assert agent._interrupted is True
    assert tts._stop_event.is_set()


def test_stream_honors_caller_supplied_stop_event(monkeypatch):
    """A caller-supplied stop_event becomes the active one and skips empty chunks."""
    v, tts = _bare_vieneu(monkeypatch, streaming=True)
    caller_event = threading.Event()

    monkeypatch.setattr(v, "_local_token_source", lambda *a, **k: iter(()))

    def fake_sink(_tts, _voice, _iter, *, stop_event=None):
        assert stop_event is caller_event  # threaded through, not the internal one
        list(_iter)
        yield np.array([], dtype=np.float32)  # empty → skipped
        yield np.ones(4, dtype=np.float32)

    monkeypatch.setattr(v, "stream_speech_tokens_to_audio", fake_sink)

    out = list(tts.stream("hi", stop_event=caller_event))

    assert tts._stop_event is caller_event
    assert len(out) == 1  # the empty chunk was skipped


# ── Step 1 fix-pass: _local_token_source SOURCE (no model / no GPU) ───────────
#
# Drives the real `_local_token_source` with a fake `tts` whose `.backbone.generate`
# replays a token stream through the REAL streamer subclass. Catches:
#   C0 — the real `from vieneu_utils.phonemize_text import phonemize_batch` executes
#        (a wrong import path raises here);
#   C1 — the prompt tensor (first put) must be skipped (no prompt tokens emitted);
#   C2 — every yielded fragment is exactly ONE `<|speech_N|>` (fragment == frame).


def _make_source_fake_tts(monkeypatch, speech_ids, *, prompt_ids=(900, 901, 902), extra_non_speech_id=99):
    """Fake lib instance exposing only what `_local_token_source` touches.

    `generate(streamer=...)` replays: the prompt tensor (one put), then each token id
    one-at-a-time (mix of speech-token ids + one trailing non-speech/eos id), then end().
    """
    import torch

    # Stub the REAL phonemize fn at its source module so the function-local
    # `from vieneu_utils.phonemize_text import phonemize_batch` resolves to the stub
    # (no eSpeak data needed in CI). The import line itself still runs → a wrong
    # import path (C0) would raise ImportError here before the stub can help.
    import vieneu_utils.phonemize_text as _ph

    from noble_agent.voice.tts import vieneu as v

    monkeypatch.setattr(_ph, "phonemize_batch", lambda texts, **k: ["PH" for _ in texts])

    id_to_token = {sid: f"<|speech_{sid}|>" for sid in speech_ids}
    id_to_token[extra_non_speech_id] = "<|SPEECH_GENERATION_END|>"

    class FakeTokenizer:
        def convert_ids_to_tokens(self, idx):
            return id_to_token[int(idx)]

        def convert_tokens_to_ids(self, tok):
            return extra_non_speech_id

    class FakeBackbone:
        device = "cpu"

        def generate(self, prompt_tensor, *, streamer=None, **kwargs):
            streamer.put(prompt_tensor)  # prompt → must be skipped (C1)
            for sid in [*speech_ids, extra_non_speech_id]:  # one id per put
                streamer.put(torch.tensor([[sid]]))
            streamer.end()

    class FakeTTS:
        max_context = 4096
        default_emotion = None
        tokenizer = FakeTokenizer()
        backbone = FakeBackbone()

        def get_ref_phonemes(self, text):
            return "REF"

        def _apply_chat_template(self, codes, ref_ph, chunk_ph, emotion_tag=None):
            return list(prompt_ids)

    return v, FakeTTS()


def test_local_token_source_emits_one_speech_token_per_fragment(monkeypatch):
    # (a) runs end-to-end with NO exception (catches the C0 wrong-import regression).
    speech_ids = [10, 11, 12, 13, 14]
    v, fake_tts = _make_source_fake_tts(monkeypatch, speech_ids)

    stop = threading.Event()
    fragments = list(v._local_token_source(fake_tts, _seed_voice(), "xin chào", stop_event=stop))

    # (b) one <|speech_N|> per fragment, in order (fragment == frame; catches C2).
    assert fragments == [f"<|speech_{sid}|>" for sid in speech_ids]
    # (c) prompt + the non-speech/eos token are NOT emitted (catches C1 + speech-only).
    assert all(frag.startswith("<|speech_") for frag in fragments)
    assert "<|SPEECH_GENERATION_END|>" not in fragments
    assert len(fragments) == len(speech_ids)


def test_local_token_source_feeds_sink_incrementally(monkeypatch):
    # (d) feeding the fragments into the real sink yields >1 chunk, first chunk before
    #     the source is exhausted (incrementality survives the source → sink seam).
    speech_ids = list(range(120))
    v, fake_tts = _make_source_fake_tts(monkeypatch, speech_ids)
    sink_tts = _make_fake_tts()
    stop = threading.Event()

    source = _CountingIter(v._local_token_source(fake_tts, _seed_voice(), "xin chào", stop_event=stop))

    frames = []
    first_pulled_at_first_yield = None
    for i, frame in enumerate(v.stream_speech_tokens_to_audio(sink_tts, _seed_voice(), source)):
        if i == 0:
            first_pulled_at_first_yield = source.pulled
        frames.append(frame)

    assert len(frames) > 1
    assert first_pulled_at_first_yield is not None
    assert first_pulled_at_first_yield < len(speech_ids)


async def test_async_stream_drains_queue(monkeypatch):
    """AsyncVieNeuTTS.stream pumps the sync generator's chunks through the queue."""
    from noble_agent.voice.tts import vieneu as v

    async_tts = v.AsyncVieNeuTTS.__new__(v.AsyncVieNeuTTS)

    class _SyncFake:
        def stream(self, text, stop_event=None):
            yield b"\x01\x02"
            yield b"\x03\x04"

    async_tts._tts = _SyncFake()

    out = [chunk async for chunk in async_tts.stream("hi")]
    assert out == [b"\x01\x02", b"\x03\x04"]
