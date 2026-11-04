# tts_omnivoice — OmniVoice TTS microservice

Serves **`NobleX-AI/santa-tts-omnivoice`** by default — our own LoRA finetune of
`k2-fsa/OmniVoice` on the santa voice (the same clips as `santa-tts-v3`). The
repo is **private**, so `HF_TOKEN` is required. Set `OMNIVOICE_MODEL_REPO` to
`thanhhai03/OmniVoice-Luna-vi` to serve the previous Luna voice instead, or to a
local directory to serve unpublished weights.

⚠️ **License: CC-BY-NC-4.0 (non-commercial).** This applies to **both**
checkpoints. The restriction is inherited from the shared base model's training
data (Emilia dataset) and **cannot be relaxed downstream** — switching to our own
finetune does not escape it, because the base is the same. Do not deploy this
service for commercial/production traffic without separate legal confirmation.
Use for internal evaluation/testing only until that confirmation exists. The
bundled audio tokenizer also carries its own separate license (Boson Higgs Audio
2 Community License).

## What this is

Single-speaker Vietnamese TTS (the "santa" voice), masked-diffusion architecture
(Qwen3-0.6B backbone, 8 codebooks @ 25Hz) — see
[our model card](https://huggingface.co/NobleX-AI/santa-tts-omnivoice) for the
finetune details, or
[Luna-vi's](https://huggingface.co/thanhhai03/OmniVoice-Luna-vi) for the shared
architecture and benchmark numbers.

Trained on **spoken-form** transcripts ("tếch com bank", not "Techcombank"), so
written-form input must be normalized first. The service does NOT do it — the
caller does (odyssey-agent runs `normalize_for_voice` before every synth).

**Not truly streaming.** `omnivoice`'s `.generate()` produces the whole
utterance in one call (the diffusion architecture refines every audio-token
position simultaneously across denoising steps — there's no "early part done
first" the way autoregressive models have). This service still speaks the
`remote` WS protocol (binary PCM chunks then `{"type":"end"}`), but the first
chunk only arrives once the *entire* utterance has finished generating — so
TTFB ≈ total synthesis time. RTF is nonetheless very low (README reports
0.025–0.035; ~0.05–0.16 measured here depending on `OMNIVOICE_NUM_STEP`).

## `OMNIVOICE_NUM_STEP` — quality vs. speed

Number of diffusion denoising steps. More steps = higher quality, slower;
fewer = faster, lower quality. Default `16` (the model card's own
recommendation — "quality first"). Drop to `4` only if latency-bound; below 4
quality falls off sharply. This does not require a different checkpoint —
it's a runtime knob on the same weights.

## No mid-generation cancellation

Because `.generate()` is one blocking call, a client disconnecting mid-synth
does not stop the GPU work already in flight. The worker thread
finishes and its result is simply discarded.
