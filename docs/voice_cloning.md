# Voice cloning — `tts-omnivoice`

`tts-omnivoice` can clone a voice from one reference audio clip. This is an
extension of the shared TTS WS protocol (see `remote_stt_tts_spect.md`) —
the `synthesize` message is unchanged; one new message type is added.

## How it works — enroll once, reuse by name

Cloning is **not** done fresh on every synthesis request. It is a two-step
flow:

1. **Enroll (one-time, ~1-3s of GPU work):** send one reference clip. The
   service builds a voice-clone prompt from it and registers the result under
   a name you choose (`voice_id`).
2. **Synthesize (every request, no extra cost):** reference the enrolled
   voice by name. The reference clip is never re-processed.

Enrolled voices are persisted to disk (`CUSTOM_VOICES_DIR` — the
`voices/omnivoice/` bind mount, see its README) and reloaded automatically on
service restart — enroll once, keep using the voice_id forever after.

## Protocol

```jsonc
// 1. Enroll
→ {"type": "enroll_voice", "voice_id": "khach_a", "ref_audio_b64": "<wav bytes, base64>", "ref_text": "..."}
← {"type": "enrolled", "voice_id": "khach_a"}          // success
← {"type": "error", "message": "..."}                   // failure

// 2. Synthesize with the enrolled voice — unchanged message shape
→ {"type": "synthesize", "text": "...", "voice": "khach_a"}
← (binary PCM16 frames) ... {"type": "end"}
```

- `ref_audio_b64`: the raw bytes of a `.wav` file, base64-encoded. The file
  lives on whatever machine runs the enrollment script — it is read locally
  and sent over the WebSocket; there is no separate "upload" location.
- `ref_text` (**required**): the transcript of `ref_audio_b64`. The cloning
  primitive (`create_voice_clone_prompt`) needs a matching transcript and this
  service has no ASR model loaded to auto-transcribe — provide it yourself.
- An unknown `voice` on `synthesize` falls back to the built-in speaker
  rather than erroring.

## Using it

```bash
# Enroll (see scripts/enroll_voice.py's in-file CONFIG block for the no-CLI way)
python scripts/enroll_voice.py --ref-audio clip.wav --voice-id khach_a \
    --ref-text "Nguyên văn transcript của clip.wav"

# Reuse
python scripts/try_tts.py --voice khach_a --text "..."
```

## Implementation notes

The `omnivoice` package has no built-in named-voice registry — it only offers
`OmniVoice.create_voice_clone_prompt()`, which returns a `VoiceClonePrompt`
with its own `.save(path)`/`.load(path)` (`torch.save`/`torch.load` under the
hood). `tts_server.py` builds the name → prompt registry itself: one
`<voice_id>.pt` file per enrolled voice under `CUSTOM_VOICES_DIR`, loaded into
an in-memory dict at boot. Enrollment (GPU work) runs in a worker thread, so
one enrollment in progress doesn't block other connections' synth requests.

The stateless gateway flow (`encode_reference` → `ref_codes`, see
`docs/spec-tts-endpoint.md`) is **not** implemented here — only the removed
`tts-vieneu-v3` had it.

## Known limitations

- No per-tenant isolation — all enrolled voices share one flat namespace
  (`voice_id` must be unique).
- No `remove_voice`/list-enrolled-voices endpoint — deleting a voice means
  removing its file from `CUSTOM_VOICES_DIR` by hand and restarting the
  service.
