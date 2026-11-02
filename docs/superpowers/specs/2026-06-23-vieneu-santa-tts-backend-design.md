# Design: Switch TTS backend to VieNeu + `NobleX-AI/santa-tts`

**Date:** 2026-06-23
**Status:** Approved (brainstorming → spec)
**Author:** Luna voice-agent team

## Goal

Replace the current ElevenLabs TTS backend with the local VieNeu backend running the
fine-tuned voice model `NobleX-AI/santa-tts`, cloning the **luna** voice from the
local reference audio. Output stays PCM int16 24 kHz mono — identical to the existing
TTS contract, so no transport/pipeline change downstream.

## Verified facts (grounding)

| Topic | Fact |
|---|---|
| vieneu install | Optional extra `tts-vieneu` (`vieneu>=2.4` resolves to **3.0.5**, `llama-cpp-python`, `neucodec>=0.0.5`). Not currently installed. |
| santa-tts repo | Full **safetensors** `Qwen3ForCausalLM` fine-tune. **No GGUF**, **no `voices.json`**. |
| Load path | `Vieneu(mode="standard", backbone_repo="NobleX-AI/santa-tts", backbone_device="cuda", gguf_filename=None, hf_token=...)` → transformers branch (`AutoTokenizer` + `AutoModelForCausalLM.to(device)`). **`gguf_filename` MUST be `None`** — its default `"VieNeu-TTS-v2-Q4-K-M.gguf"` forces the GGUF branch even for a safetensors repo. |
| Voice cloning | `infer_stream(text, voice={"codes":..., "text":...})`. A preset voice dict comes from `get_preset_voice(name)` after `_load_voices_from_file(presets.json)`. |
| Reference encode | `encode_reference(wav)` calls `codec.encode_code()`. The runtime codec `neuphonic/neucodec-onnx-decoder-int8` (`NeuCodecOnnx`) is **decode-only** — no `encode_code`. Encoding a wav → codes requires the full torch codec `neuphonic/neucodec`. |
| Existing reference | `src/noble_agent/voice/tts/reference/`: `luna.wav`, `gemini.wav`, `voices.json` in `{name: {wav, text, source_run, ...}}` format (NOT vieneu preset format). |
| Hardware | RTX 5060 Ti 16 GB, CUDA available (torch 2.11+cu130). Backbone (0.3B) on GPU; ONNX int8 decoder is CPU-only by design. |
| **Top risk** | `use_chat_format` is True only when `backbone_repo` ends with `pnnbao-ump/VieNeu-TTS`. `santa-tts` → **False** → non-chat prompt template. If santa-tts was fine-tuned from a chat-format base, output will be garbage. Must verify by listening; mitigate with an override flag. |

## Architecture & data flow

### Offline (run once, re-run when the reference changes)

```
reference/voices.json  ({name: {wav, text}})
  → scripts/build_vieneu_voices.py
  → Vieneu(mode="standard", backbone_repo="", codec_repo="neuphonic/neucodec",
           codec_device="cuda", gguf_filename=None)        # codec only, no backbone download
  → for each voice: encode_reference(reference/<wav>) → codes (list[int])
  → write reference/presets.json   (vieneu format)
```

`presets.json` shape:
```json
{
  "meta": {"spec": "vieneu.voice.presets", "spec_version": "1.0", "source": "NobleX-AI santa reference"},
  "default_voice": "luna",
  "presets": {
    "luna":   {"codes": [/* ints */], "text": "<luna transcript from voices.json>"},
    "gemini": {"codes": [/* ints */], "text": "<gemini transcript>"}
  }
}
```
- `backbone_repo=""` skips backbone loading (the library guards with `if backbone_repo:`), so the script only pays for the codec.
- Idempotent: overwrites `presets.json` each run.

### Runtime (per process start)

```
Vieneu(mode="standard",
       backbone_repo=settings.vieneu_backbone_repo,        # NobleX-AI/santa-tts
       backbone_device=settings.vieneu_backbone_device,    # cuda
       gguf_filename=None,                                  # force transformers branch
       codec_repo=settings.vieneu_codec_repo,              # neucodec-onnx-decoder-int8
       codec_device=settings.vieneu_codec_device,          # cpu
       hf_token=settings.hf_token)
  → tts._load_voices_from_file(settings.vieneu_presets_path)   # reference/presets.json
  → voice = tts.get_preset_voice(settings.vieneu_voice_id or default)   # "luna"
  → (optional) override tts.use_chat_format if settings.vieneu_use_chat_format is set
```

### Per utterance (unchanged)

`AsyncVieNeuTTS.stream(text) → VieNeuTTS.stream(text) → infer_stream(text, voice=self._voice)`
→ float32 chunks → `_f32_to_pcm16` → PCM int16 24 kHz bytes. The existing `stream()`
already passes `voice=self._voice`; only the loader that builds `self._voice` changes.

## Components

### a. New: `scripts/build_vieneu_voices.py`
- Input: `reference/voices.json` (the existing `{name:{wav,text}}` file).
- Loads full `neuphonic/neucodec` (torch, GPU) via `Vieneu(mode="standard", backbone_repo="", codec_repo="neuphonic/neucodec", codec_device=<cuda|cpu>, gguf_filename=None)`.
- For each entry: resolve wav path relative to the reference dir, `encode_reference()` → codes, `to_list()` to plain ints.
- Writes `reference/presets.json` with `default_voice` from a `--default` flag (default `luna`).
- Pure-ish transform isolated into a helper `build_presets(voices_dict, encode_fn, default_voice) -> dict` so it is unit-testable without the heavy codec.

### b. Modified: `src/noble_agent/voice/tts/vieneu.py`
- Rewrite the HF branch of `_load_tts` into a santa-aware loader that builds the `Vieneu(...)` call above, loads `presets.json`, resolves the voice, and applies the optional `use_chat_format` override.
- Keep the existing local-GGUF path untouched (not used by this change; out of scope).
- `VieNeuTTS.stream` / `AsyncVieNeuTTS` unchanged.

### c. Modified: `src/noble_agent/config.py` + `.env`
New / changed settings:
- `TTS_BACKEND=vieneu`
- `VIENEU_BACKBONE_REPO=NobleX-AI/santa-tts`
- `VIENEU_VOICE_ID=luna`
- `VIENEU_BACKBONE_DEVICE=cuda`
- `VIENEU_CODEC_REPO=neuphonic/neucodec-onnx-decoder-int8`
- `VIENEU_CODEC_DEVICE=cpu`
- `VIENEU_PRESETS_PATH` (default: `reference/presets.json` resolved relative to the tts module)
- `VIENEU_USE_CHAT_FORMAT` (default unset/None → use library default; `true`/`false` overrides)
- `HF_TOKEN` — reuse the existing setting (already used by the sherpa STT path).

### d. Dependency
`pip install -e ".[tts-vieneu]"` (extra already declared in `pyproject.toml`). `neucodec>=0.0.5` provides both the full encoder (offline) and the ONNX decoder (runtime). torch already present.

## Risk handling & verification

1. **`use_chat_format` (highest risk).** Default for santa-tts is non-chat. Mandatory verify step: generate one Vietnamese test sentence to a WAV with the luna voice and **listen**. If distorted/garbled, set `VIENEU_USE_CHAT_FORMAT=true` and regenerate. This is the gate before declaring the backend correct. The agent cannot judge audio quality — the user listens.
2. **VRAM.** 0.3B backbone on a 16 GB GPU is comfortable; confirm with `nvidia-smi` after first load.
3. **Codec encode availability.** Offline script uses the full torch codec; runtime uses the int8 decoder. No encoder needed at runtime → fast, light startup.

## Testing

- **Unit** (vieneu is heavy + optional → do not import it in unit tests; mock/inject):
  - `build_presets(...)` transform: given a fake `voices.json` dict and a stub `encode_fn`, asserts the output presets.json shape, default_voice, and that codes/text are carried through.
  - Loader config wiring: assert the `Vieneu(...)` kwargs assembled from settings (esp. `gguf_filename=None`, device, codec repo) — by patching the `Vieneu` factory and inspecting the call.
- **Smoke** (`src/noble_agent/SMOKE.md`): real TTS path end to end, listen to audio.
- Follow `testing-conventions` (pytest `asyncio_mode=auto`, markers, ruff).

## Out of scope
- The legacy local-GGUF loader path in `vieneu.py` (left as-is).
- ElevenLabs code removal — only the `TTS_BACKEND` default flips; ElevenLabs stays available as a backend.
- Any change to the audio resample / transport layers.

## Docs
Update `CLAUDE.md` TTS-backends section (vieneu now serves santa-tts via precomputed
`presets.json`, the build script, the new env vars) and append a Change Log row.
