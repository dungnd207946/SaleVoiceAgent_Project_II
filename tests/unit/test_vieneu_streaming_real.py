"""Real-tokenizer round-trip for the streamer ↔ extract_speech_ids invariant (Hazard 1).

`@pytest.mark.bench` (opt-in): needs the real model + tokenizer + GPU. Skipped in
`make test-unit`. Run on the GPU box with `pytest tests/unit/test_vieneu_streaming_real.py -m bench`.

Pins, on the REAL model + tokenizer (what the offline unit test cannot reach):
  * the `_SpeechTokenStreamer` emits exactly the speech ids a one-shot `_infer_torch`
    produces for the same prompt — id-for-id equality under deterministic `do_sample=False`
    (catches a prompt leak / token batching / a wrong-token regression on the real tokenizer);
  * fragments arrive INCREMENTALLY (first well before last) — a future buffering regression
    that re-collapses TTFA into TTFB-==-total fails here on the GPU box.
"""

from __future__ import annotations

import threading
import time

import pytest


def _bench_requested(config) -> bool:
    """True only when the run explicitly opts into bench (`-m bench`)."""
    markexpr = config.getoption("-m") or ""
    return "bench" in markexpr


@pytest.fixture(autouse=True)
def _skip_unless_bench(request):
    # `make test-unit` runs without `-m bench`; this test needs the real model + GPU,
    # so skip it there. Run explicitly with `pytest ... -m bench` on the GPU box.
    if not _bench_requested(request.config):
        pytest.skip("bench-only (real model + GPU); run with -m bench")


@pytest.mark.bench
def test_streamer_roundtrips_speech_ids():
    import torch
    from vieneu.utils import extract_speech_ids
    from vieneu_utils.phonemize_text import phonemize_batch

    from noble_agent.voice.tts import vieneu as v

    tts, voice = v._load_tts()
    text = "Xin chào quý khách."

    # ── One-shot reference (deterministic) ───────────────────────────────────
    ref_phonemes = tts.get_ref_phonemes(voice["text"])
    chunk_phonemes = phonemize_batch([text], skip_normalize=True)[0]
    prompt_ids = tts._apply_chat_template(voice["codes"], ref_phonemes, chunk_phonemes, emotion_tag=tts.default_emotion)
    # `_infer_torch` samples (non-deterministic), so reproduce its prompt → generate
    # round-trip with `do_sample=False` for a stable reference id list.
    speech_end_id = tts.tokenizer.convert_tokens_to_ids("<|SPEECH_GENERATION_END|>")
    prompt_tensor = torch.tensor(prompt_ids).unsqueeze(0).to(tts.backbone.device)
    with torch.no_grad():
        out = tts.backbone.generate(
            prompt_tensor,
            max_length=tts.max_context,
            eos_token_id=speech_end_id,
            do_sample=False,
            use_cache=True,
            min_new_tokens=50,
        )
    oneshot_str = tts.tokenizer.decode(
        out[0, prompt_tensor.shape[-1] :].cpu().numpy().tolist(), add_special_tokens=False
    )
    oneshot_ids = extract_speech_ids(oneshot_str)
    assert oneshot_ids, "one-shot reference produced no speech ids"

    # ── Streamed source (same prompt, deterministic) ─────────────────────────
    stop = threading.Event()
    fragments: list[str] = []
    arrival_t: list[float] = []
    t0 = time.monotonic()
    for frag in v._local_token_source(tts, voice, text, stop_event=stop, do_sample=False):
        fragments.append(frag)
        arrival_t.append(time.monotonic() - t0)

    # (1) each fragment is exactly ONE <|speech_N|> (fragment == frame; C2).
    assert all(extract_speech_ids(f) and len(extract_speech_ids(f)) == 1 for f in fragments), (
        "a fragment did not carry exactly one <|speech_N|> — streamer batched tokens"
    )

    # (2) id-for-id equality with the deterministic one-shot run (C1 prompt-skip + C2).
    streamed_ids = extract_speech_ids("".join(fragments))
    assert streamed_ids == oneshot_ids, (
        f"streamed ids != one-shot ids\n streamed[:8]={streamed_ids[:8]}\n one-shot[:8]={oneshot_ids[:8]}"
    )

    # (3) incremental arrival: first fragment well before the last (TTFA preserved).
    assert len(arrival_t) >= 2
    assert arrival_t[0] < arrival_t[-1] * 0.5, (
        f"first fragment at {arrival_t[0]:.3f}s vs last {arrival_t[-1]:.3f}s — buffering regression"
    )
