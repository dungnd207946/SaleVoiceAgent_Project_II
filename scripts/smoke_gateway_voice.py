#!/usr/bin/env python3
"""SaaS slice #2 — gateway VOICE smoke client (provider → gateway → LiveKit → worker).

Drives the exact path a provider backend uses for voice: open a WS to the
per-tenant gateway `/v1/voice` with a Bearer credential, send an identity
handshake, stream PCM16 16 kHz mono audio (a raw headerless `.pcm`), and collect
the agent audio the worker relays back out of the LiveKit room. The received
audio is written to a `.wav` (24 kHz — TTS output rate) so you can listen.

What a PASS proves:
  - gateway authorizes + mints a dispatch token + joins the LiveKit room;
  - a worker registered as `agent-<tenant>` gets dispatched and joins;
  - the return relay works (agent audio bytes arrive back on the ws) — the
    worker's auto-greeting alone exercises this, independent of STT;
  - streaming the .pcm exercises the forward relay (provider audio → room → STT).

Single-domain auth (2026-08-10): tenant no longer lives in the Host/subdomain —
the gateway resolves it from the Bearer API key via the Portal
runtime-credentials API (GATEWAY_CREDENTIALS_API_URL).

Prereqs:
  1. A provider API key issued by the Portal for the tenant under test.
  2. Gateway:
       GATEWAY_CREDENTIALS_API_URL=http://<portal>/api/v1/agent/runtime-credentials noble-gateway
  3. A LiveKit worker as the VOICE transport, registered agent-<tenant>:
       TRANSPORT_BACKEND=livekit TENANT_MATERIALIZE_DIR="$HOME/.cache/noble/tenants" noble-agent
     ⚠️ It registers `agent-<TENANT_ID>` (default agent-noble). Ensure no OTHER
        worker on the shared LiveKit Cloud registers the same name (call theft).

Usage:
  python scripts/smoke_gateway_voice.py <credential> [--pcm PATH] [--secs N] [--out FILE]
    <credential>  the provider API key from the Portal
    --pcm PATH    raw PCM16 mono 16 kHz to stream (default: scripts/load_test/v2/fixture_16k.pcm)
    --secs N      total seconds to run before hanging up (default: 20)
    --out FILE    write received agent audio here (default: /tmp/gateway_voice_out.wav)
"""
import asyncio
import json
import os
import sys
import wave

import websockets

_IN_RATE = 16000  # provider → gateway (matches gateway AudioSource + worker STT)
_OUT_RATE = 24000  # gateway → provider (worker TTS output rate)
_FRAME_MS = 20
_FRAME_BYTES = int(_IN_RATE * (_FRAME_MS / 1000.0)) * 2  # 20 ms of 16-bit mono @16k = 640 B


def _arg(flag, default):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


async def _send_audio(ws, pcm_path, stop_evt):
    """Stream the .pcm in realtime-paced 20 ms frames, then silence until stop."""
    data = b""
    if pcm_path and os.path.exists(pcm_path):
        with open(pcm_path, "rb") as f:
            data = f.read()
        print(f"→ streaming {len(data)} B ({len(data)/2/_IN_RATE:.1f}s) from {pcm_path}")
    else:
        print(f"→ no pcm at {pcm_path!r}; streaming silence (return-path only)")
    silence = b"\x00" * _FRAME_BYTES
    off = 0
    try:
        while not stop_evt.is_set():
            if off < len(data):
                frame = data[off : off + _FRAME_BYTES]
                off += _FRAME_BYTES
                if len(frame) < _FRAME_BYTES:
                    frame = frame + b"\x00" * (_FRAME_BYTES - len(frame))
            else:
                frame = silence
            await ws.send(frame)
            await asyncio.sleep(_FRAME_MS / 1000.0)
    except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
        pass


async def _recv(ws, wav_out, stats, stop_evt):
    try:
        async for raw in ws:
            if isinstance(raw, (bytes, bytearray)):
                stats["audio_bytes"] += len(raw)
                stats["audio_frames"] += 1
                wav_out.writeframes(raw)
            else:
                try:
                    msg = json.loads(raw)
                    print(f"   [control] {msg}")
                except ValueError:
                    print(f"   [text] {raw[:120]}")
    except websockets.exceptions.ConnectionClosed as e:
        c = e.rcvd.code if e.rcvd else "?"
        r = e.rcvd.reason if e.rcvd else ""
        print(f"   [ws closed {c} {r!r}]")
    finally:
        stop_evt.set()


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--") and a not in
            (_arg("--pcm", None), _arg("--secs", None), _arg("--out", None))]
    if not args:
        print(__doc__)
        return 2
    cred = args[0]
    pcm = _arg("--pcm", "scripts/load_test/v2/fixture_16k.pcm")
    secs = float(_arg("--secs", "20"))
    out = _arg("--out", "/tmp/gateway_voice_out.wav")

    uri = "ws://localhost:9200/v1/voice"
    headers = {"Authorization": f"Bearer {cred}"}
    print(f"→ connecting {uri}  (Bearer {cred[:12]}…, tenant resolved server-side from the credential)")

    stats = {"audio_bytes": 0, "audio_frames": 0}
    wav_out = wave.open(out, "wb")
    wav_out.setnchannels(1)
    wav_out.setsampwidth(2)
    wav_out.setframerate(_OUT_RATE)
    stop_evt = asyncio.Event()

    try:
        async with websockets.connect(uri, additional_headers=headers, open_timeout=10, max_size=None) as ws:
            # handshake: identity + call_id (gateway → LiveKit participant metadata)
            await ws.send(json.dumps({"identity": {"full_name": "Voice Smoke", "phone": "0912345629"},
                                      "call_id": "voice-smoke-1"}))
            recv_t = asyncio.create_task(_recv(ws, wav_out, stats, stop_evt))
            send_t = asyncio.create_task(_send_audio(ws, pcm, stop_evt))
            try:
                await asyncio.wait_for(stop_evt.wait(), timeout=secs)
            except asyncio.TimeoutError:
                pass
            stop_evt.set()
            send_t.cancel()
            recv_t.cancel()
            for t in (send_t, recv_t):
                try:
                    await t
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
    except websockets.exceptions.ConnectionClosed as e:
        code = e.rcvd.code if e.rcvd else "?"
        print(f"✗ connection closed {code} ({e.rcvd.reason if e.rcvd else ''})")
        wav_out.close()
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"✗ {type(e).__name__}: {e}")
        wav_out.close()
        return 1

    wav_out.close()
    got = stats["audio_bytes"]
    secs_audio = got / 2 / _OUT_RATE
    print(f"\n{'✓' if got else '✗'} voice roundtrip: received {stats['audio_frames']} agent-audio frames "
          f"= {got} B ({secs_audio:.1f}s @ {_OUT_RATE}Hz) → {out}")
    print("   PASS = agent audio came back through the LiveKit room bridge." if got
          else "   FAIL = no agent audio. Check: worker registered agent-<tenant>? dispatched into the room?")
    return 0 if got else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
