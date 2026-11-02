# Integrate hynt-bilingual STT (sherpa-onnx) into Noble Voice Agent

**Date:** 2026-06-22
**Status:** Approved (design)
**Scope:** Replace Soniox with the locally finetuned `hynt-bilingual` streaming Zipformer
transducer, served in-process via sherpa-onnx, by generalizing the existing `sherpa.py`
STT backend. Single implementation plan.

## Goal

Run the `hynt-bilingual` model (Vietnamese + English streaming Zipformer-30M RNN-T,
exported to sherpa-onnx ONNX) as the production STT for the hotline, with feature
extraction and chunking matched **exactly** to the model's training configuration so
runtime accuracy tracks the offline-measured WER (~1.96% on the hotline test set).

The model lives at `santa-voice-finetuning/models/hynt-bilingual/`; training details are in
`santa-voice-finetuning/finetune/configs/base_hynt.yaml` and `streaming.yaml`.

## Why the existing backend already covers most of this

The repo already ships a streaming sherpa-onnx backend at
`src/noble_agent_unified/voice/stt/sherpa.py` (`SherpaSTT`), selected by `STT_BACKEND=sherpa`.
It implements the full streaming integration: a shared `OnlineRecognizer` singleton, a
per-session `OnlineStream`, a background decode thread fed by a stdlib queue, PCM-int16 →
float32 conversion, partial/endpoint emission via `asyncio.run_coroutine_threadsafe`, and
the `STTBase` interface (`start` / `send` / `stop`, `on_partial` / `on_final`).

It is, however, hardcoded for a **different** (older Vietnamese-only) model. Integration is
therefore not "build a new backend" but "make the existing backend model-agnostic via config
and fix text post-processing". The streaming machinery, singleton, threading model, and
interface are reused unchanged.

## Feature / chunk matching (the core correctness requirement)

The model was trained with kaldi fbank: `frame_length_ms=25`, `frame_shift_ms=10`,
`num_mel_bins=80`, `snip_edges=false`, 16 kHz. These are **exactly the sherpa-onnx feature
extractor defaults**, so matching requires only:

| Training parameter | Value | How it's matched at runtime |
|---|---|---|
| frame_length | 25 ms | sherpa-onnx default — nothing to set |
| frame_shift | 10 ms | sherpa-onnx default — nothing to set |
| num_mel_bins | 80 | `feature_dim=80` in `from_transducer(...)` |
| sample_rate | 16000 | `sample_rate=16000` (`STT_SAMPLE_RATE`) |
| chunk-16-left-128 | baked into the ONNX export | `SHERPA_CHUNK_SIZE=16` (already default) |
| endpoint rule1/2/3 | 2.4 / 1.2 / 20.0 s | already the config defaults |

No feature normalization (CMVN) is applied at training inference time, and sherpa-onnx
fbank is stateless — so there is nothing extra to configure. The audio fed to the recognizer
must be float32 in [-1, 1] (the existing backend already does `int16 / 32768.0`).

## Changes

### 1. Generalize `voice/stt/sherpa.py`

**a. Config-driven model filenames.** Replace the hardcoded suffix
`epoch-31-avg-11-chunk-{c}-left-128.fp16` with a `SHERPA_MODEL_NAME` setting (e.g.
`epoch-20-avg-5-chunk-16-left-128` for fp32, or the same with `.int8` for the quantized
variant). The backend composes `encoder-{name}.onnx`, `decoder-{name}.onnx`,
`joiner-{name}.onnx`, and `tokens.txt` from `SHERPA_MODEL_DIR` + `SHERPA_MODEL_NAME`. This
selects fp32 vs int8 purely by editing `.env`, with no code change.

**b. Config-driven text post-processing.** `sherpa.py:184` currently does
`.strip().lower().capitalize()`, which destroys the punctuation (`. , ? !`) and English-token
casing that the bilingual model emits. Add `SHERPA_PRESERVE_CASE` (default `true`): when
true, post-processing is `.strip()` only — punctuation and casing are preserved verbatim.
When false, the legacy `.lower().capitalize()` behavior is retained for the old VN model.

**c. Decoding method.** Keep the existing hotwords logic untouched: empty
`SHERPA_HOTWORDS_FILE` → `greedy_search` (fastest, the model's default decoding method);
a non-empty hotwords file → `modified_beam_search` with biasing. For hynt-bilingual the
hotwords file starts empty (the model already learned the hotline brand vocabulary). Hotwords
remain opt-in for later tuning.

The recognizer singleton, background decode thread, `STTBase` interface, and callback wiring
are **unchanged**.

### 2. Model files

Copy `santa-voice-finetuning/models/hynt-bilingual/` (fp32 + int8 `.onnx` triplets and
`tokens.txt`) into `santa-hotline-agent/models/hynt-bilingual/`. Add `models/` to
`.gitignore` (these are large binary artifacts, like the existing gitignored model data).
`SHERPA_MODEL_DIR` uses the relative path `models/hynt-bilingual` so the agent is
self-contained for Docker/deploy.

### 3. Activation config (`.env`)

```
STT_BACKEND=sherpa
SHERPA_MODEL_DIR=models/hynt-bilingual
SHERPA_MODEL_NAME=epoch-20-avg-5-chunk-16-left-128   # drop .int8 = fp32; append .int8 = quantized
SHERPA_PRESERVE_CASE=true
SHERPA_HOTWORDS_FILE=                                  # empty → greedy_search
SHERPA_CHUNK_SIZE=16
```

New settings to add to `config.py` (`UnifiedSettings`): `sherpa_model_name: str`,
`sherpa_preserve_case: bool = True`. Existing `sherpa_model_dir`, `sherpa_chunk_size`,
`sherpa_num_threads`, `sherpa_rule1/2/3`, `sherpa_hotwords_file`, `sherpa_hotwords_score`
are reused as-is.

## Verification

1. **Model-match parity.** Run one audio file through the new backend and compare the
   transcript with `santa-voice-finetuning`'s eval script on the same file and same model.
   Matching text proves feature extraction and chunking are aligned with training.
2. **Latency.** `make bench` (benchmark_latency.py) for TTFT on the real-time path. Start
   with fp32; if p95 misses target, switch `SHERPA_MODEL_NAME` to the `.int8` variant and
   re-measure. (See the `latency-discipline` skill.)
3. **Unit test.** Assert the backend composes the correct ONNX paths from
   `SHERPA_MODEL_DIR` + `SHERPA_MODEL_NAME`, and that `preserve_case=true` keeps punctuation
   and English casing while `false` reproduces the legacy lowercasing. (See
   `testing-conventions`.)
4. **Smoke.** Run `src/noble_agent_unified/SMOKE.md` for the STT / turn-loop path.

## Risks / notes

- **Telephony narrowband.** PSTN audio arrives at 8 kHz and is resampled to 16 kHz before
  STT (`telephony/resampler.py`). The model expects 16 kHz, so this is functionally fine, but
  real-world telephone WER may exceed the 1.96% measured on a wideband TTS corpus. This is a
  data-domain limitation, not an integration defect.
- **tokens.txt mismatch.** Must use hynt-bilingual's 2834-piece `tokens.txt`; using the old
  model's tokens would silently corrupt output.
- **CLAUDE.md maintenance.** Per the repo's Self-Maintenance Rules, update the pluggable-STT
  section (sherpa now serves hynt-bilingual, new env vars) and append a Change Log row in the
  same commit.

## Out of scope

- Removing or migrating the other STT backends (Soniox/ElevenLabs/Qwen) — they stay
  selectable via `STT_BACKEND`.
- Re-exporting or re-training the model.
- Hotwords tuning for the new BPE vocabulary (deferred; opt-in path is preserved).
