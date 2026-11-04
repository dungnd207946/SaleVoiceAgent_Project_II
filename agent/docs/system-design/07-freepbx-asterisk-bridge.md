# 07 — FreePBX / Asterisk Bridge

> How a phone call enters the agent: PSTN → SIP trunk → FreePBX inbound route → Asterisk dialplan with `Stasis` + `AudioSocket` → Noble Voice Agent on TCP :8090. Two protocols on the wire: **AudioSocket** (TCP, TLV-framed slin 8 kHz PCM16) for audio and **ARI** (HTTP + WebSocket JSON) for caller metadata. Both are needed; AudioSocket alone doesn't expose caller-number.

Read [`00-architecture-overview.md`](00-architecture-overview.md) and [`03-tts-and-audio.md`](03-tts-and-audio.md) §3 first.

---

## 1. End-to-end call flow

```
                       PSTN / SIP trunk
                            │  (DID 1800 6112)
                            ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ FreePBX / Asterisk  (voip.noble.vn)                          │
 │                                                              │
 │  Inbound Route(18006112)                                     │
 │      │                                                       │
 │      ▼  Custom Destination                                   │
 │  [noble-voice-agent] dialplan                                │
 │      │   Answer → Wait 0.3s → Stasis(noble-voice-agent)      │
 │      │   Set AS_UUID = MD5(UNIQUEID‖EPOCH) → UUID-formatted  │
 │      │   AudioSocket(${AS_UUID}, <agent_host>:8090)          │
 │      ▼                                                       │
 │  ARI WS /ari/events  (port 8088)                             │
 │     app=noble-voice-agent                                    │
 └─────────────┬───────────────────────────┬──────────────────┘
               │ TCP (TLV frames)          │ WS (JSON events)
               │ slin 16-bit, 8 kHz        │ StasisStart / End
               ▼                           ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ Noble Voice Agent (Python)                                   │
 │                                                              │
 │  telephony/audiosocket.py     (TCP :8090)                    │
 │    │ TYPE_UUID  0x01 → call_id  (UUID first frame)           │
 │    │ TYPE_AUDIO 0x10 → 320 B / 20 ms                          │
 │    │ TYPE_HANGUP 0x00 → end                                  │
 │    │ TYPE_ERROR 0xFF → bail                                  │
 │    ▼                                                         │
 │  telephony/session.py TelephonySession                       │
 │    resampler.py: 8k→16k (STT side)                           │
 │    webrtc-noise-gain NS+AGC over 10 ms frames                │
 │    VAD Silero → STT → LLM → sentence buffer → TTS            │
 │    resampler.py: 24k→8k + bandpass + pre-emphasis (TTS out)  │
 │    pacing 20 ms/frame + 100 ms warmup                        │
 │    ▼                                                         │
 │  AudioSocket write_audio_frame()                             │
 │                                                              │
 │  telephony/ari_client.py   (optional but recommended)        │
 │    StasisStart event → caller.number → enrich session        │
 │    POST /channels/{id}/continue (release back to dialplan)   │
 └──────────────────────────────────────────────────────────────┘
```

Two ports on the agent side: **8090 (TCP) inbound media** and outbound HTTP requests to **8088 (ARI)**. Asterisk drives the call; the agent is a passive callee for AudioSocket and an HTTP client for ARI.

---

## 2. Dialplan reference

These blocks live in FreePBX's custom dialplan (`/etc/asterisk/extensions_custom.conf`) or a dedicated `extensions_noble.conf` included from `extensions.conf`.

### 2.1 Inbound — DID → agent

```ini
[noble-voice-agent]
exten => s,1,NoOp(=== Noble Voice Agent inbound - caller=${CALLERID(num)} ===)
 same => n,Answer()
 same => n,Wait(0.3)
 same => n,Stasis(noble-voice-agent)
 same => n,Set(UH=${MD5(${UNIQUEID}${EPOCH})})
 same => n,Set(AS_UUID=${UH:0:8}-${UH:8:4}-${UH:12:4}-${UH:16:4}-${UH:20:12})
 same => n,AudioSocket(${AS_UUID},47.129.187.61:8090)
 same => n,Hangup()
```

Step-by-step:

1. **Answer + 0.3 s wait** — gives Asterisk's RTP path time to settle. Without this you can lose the first 100–200 ms of caller speech.
2. **`Stasis(noble-voice-agent)`** — yields control to ARI. Our `ari_client.py` consumes the `StasisStart` event, reads `caller.number`, then calls `POST /channels/{id}/continue` to return the channel to the dialplan. **Without this hop, the agent has no caller-number metadata** — AudioSocket alone doesn't expose it.
3. **MD5 → UUID format** — `AS_UUID` is the call_id used by AudioSocket's `TYPE_UUID 0x01` first frame. Format must be `8-4-4-4-12` hex with hyphens; we slice the MD5 hex string.
4. **`AudioSocket(${AS_UUID}, host:8090)`** — opens TCP to agent, streams audio both directions until either side closes.
5. **`Hangup`** — clean up after AudioSocket returns.

### 2.2 Outbound — `Originate` from agent → caller

```ini
[noble-agent-outbound]
exten => s,1,NoOp(=== Noble Voice Agent outbound ===)
 same => n,Answer()
 same => n,Wait(0.3)
 same => n,Set(UH=${MD5(${UNIQUEID}${EPOCH})})
 same => n,Set(AS_UUID=${UH:0:8}-${UH:8:4}-${UH:12:4}-${UH:16:4}-${UH:20:12})
 same => n,AudioSocket(${AS_UUID},47.129.187.61:8090)
 same => n,Hangup()
```

Same shape as inbound. The agent's outbound flow uses ARI's `POST /channels` to originate a call, with `app=noble-voice-agent` so Stasis catches the answered leg, then continues to this `[noble-agent-outbound]` context.

Detail of outbound flow → `scripts/make_outbound_call.py` and `src/noble_agent/server/outbound_endpoints.py`.

### 2.3 Audio quality tuning (optional, FreePBX side)

If callers complain about volume, hiss, or echo, add **per-channel audio processing** *before* `Stasis`:

```ini
exten => s,1,NoOp(=== Noble Voice Agent inbound ===)
 same => n,Set(JITTERBUFFER(adaptive)=200,40,40)
 same => n,Set(DENOISE(rx)=on)
 same => n,Set(AGC(rx)=4096)              ; gain target
 same => n,Answer()
 same => n,Wait(0.3)
 same => n,Stasis(noble-voice-agent)
 ...
```

But: WebRTC-noise-gain inside the agent (`telephony/session.py`) does NS+AGC over 10 ms frames already. **Don't double-process** — pick one side. Default ships with agent-side processing on, FreePBX-side off.

---

## 3. AudioSocket protocol

TCP, framed, big-endian.

### 3.1 Frame format

```
 Offset  Field    Size     Notes
 0       type     1 byte   see table below
 1       length   2 bytes  big-endian (struct ">BH")
 3       value    L bytes  payload, see per-type
```

| Type | Hex | Direction | Payload |
|---|---|---|---|
| `HANGUP` | `0x00` | Either | empty (length=0) — close connection |
| `UUID` | `0x01` | Asterisk → Agent | 16-byte raw UUID (hyphens stripped). **Always the first frame.** |
| `SILENCE` | `0x02` | Either | empty — comfort silence; we don't use this in TX |
| `AUDIO` | `0x10` | Either | 320 B PCM16 LE 8 kHz mono = 20 ms |
| `ERROR` | `0xFF` | Either | error byte; bail |

### 3.2 Rules

1. **Asterisk sends `TYPE_UUID` first.** If the agent receives any other type before UUID, it logs and disconnects (`audiosocket.py:87`).
2. **Audio frames are always exactly 320 B.** No partial frames. The pacing layer ensures TX side respects this.
3. **TCP_NODELAY is set on accept.** Without it, Nagle delays the 20 ms cadence into ~40 ms blobs and audio sounds "underwater".
4. **Comfort noise on agent side** keeps the TCP stream warm during silence. Asterisk drops idle sockets after ~5 s otherwise.
5. **Hangup is bidirectional.** Either side sends `TYPE_HANGUP`; the other replies with the same type and closes.

### 3.3 Example — receive loop pseudocode

```python
async def serve_one(reader, writer):
    # 1. Mandatory UUID frame
    type_byte = await reader.readexactly(1)
    if type_byte[0] != TYPE_UUID:
        writer.close(); return
    length = struct.unpack(">H", await reader.readexactly(2))[0]
    call_id = (await reader.readexactly(length)).hex()  # 32-char string

    # 2. Audio loop
    while True:
        type_byte = await reader.readexactly(1)
        length = struct.unpack(">H", await reader.readexactly(2))[0]
        payload = await reader.readexactly(length)

        if type_byte[0] == TYPE_HANGUP:
            return  # cleanup
        elif type_byte[0] == TYPE_AUDIO:
            await session.feed_inbound(payload)  # 320 B PCM16 8 kHz
```

Real implementation: `src/noble_agent/telephony/audiosocket.py`.

---

## 4. ARI events

ARI = Asterisk REST Interface. HTTP + WebSocket on port 8088. The agent subscribes to events for the `noble-voice-agent` Stasis app:

```
WS  ws://voip.noble.vn:8088/ari/events?app=noble-voice-agent&api_key=user:pass
```

### 4.1 Events we care about

| Event | Why |
|---|---|
| `StasisStart` | Channel entered Stasis app. Read `channel.caller.number`, persist on session, then `POST /channels/{id}/continue` to release back to dialplan |
| `StasisEnd` | Channel left (cleanly). Mark session ended in MongoDB |
| `ChannelDestroyed` | Hangup. Same teardown; can fire without StasisEnd if call never reached Stasis |

### 4.2 The continue dance

Why split `Stasis` + `AudioSocket` instead of using AudioSocket alone?

> **AudioSocket frames don't carry caller metadata.** Just call_id + audio. To know the caller's number you need the SIP signaling — exposed via ARI.

Flow:

```
1. Asterisk: enters Stasis(noble-voice-agent)
2. Agent: receives StasisStart event with channel.caller.number = "0901234567"
3. Agent: stores caller_number → session_pending[call_id] in Redis
4. Agent: POST /channels/{channel_id}/continue → Asterisk resumes dialplan
5. Asterisk: runs AudioSocket(${AS_UUID}, ...)
6. Agent: AudioSocket TYPE_UUID frame arrives
7. Agent: looks up call_id → caller_number → assigns to TelephonySession
```

Steps 2–4 take ~30 ms. The 0.3 s `Wait()` after `Answer` covers this.

### 4.3 Auth

Basic-auth on the WS handshake. The user lives in `/etc/asterisk/ari.conf`:

```ini
[noble-voice-agent]
type = user
read_only = no
password = <strong_pw>
password_format = plain
```

Set `ASTERISK_ARI_USER=noble-voice-agent` and `ASTERISK_ARI_PASS=<strong_pw>` in agent `.env`.

### 4.4 Auto-reconnect

`ari_client.py` reconnects with exponential backoff (1 s → 30 s cap) on WS disconnect. Critical: Asterisk restarts kill the WS but not the SIP trunk; the agent keeps serving inbound AudioSocket frames while ARI catches up.

---

## 5. Sample-rate chain (telephony specific)

| Hop | Rate | Frame | Notes |
|---|---|---|---|
| Asterisk wire | 8 kHz slin16 | 320 B / 20 ms | Set `audiosocket_format=slin` (Asterisk 18+ default) |
| STT / VAD | 16 kHz PCM16 | variable | `resampler.py` 8→16, soxr HQ |
| LLM | text | — | (no audio) |
| TTS output | 24 kHz PCM16 | chunks | VieNeu / ElevenLabs |
| Agent → Asterisk | 8 kHz slin16 | 320 B / 20 ms | `resampler.py` 24→8 + bandpass + pre-emphasis |
| Silence keepalive | 8 kHz | 320 B / 20 ms | `np.random.normal(0, 32)` comfort noise when `_tts_active=False` |

Bandpass 200–3400 Hz + pre-emphasis 0.95 are non-negotiable for the 24→8 path. Disable them and the line will sound "tinny" because high frequencies fold back as aliasing.

Detail: [`03-tts-and-audio.md`](03-tts-and-audio.md) §3.

---

## 6. Network requirements

| Direction | Port | Purpose |
|---|---|---|
| Asterisk → Agent | TCP 8090 | AudioSocket |
| Agent → Asterisk | TCP 8088 | ARI HTTP |
| Agent → Asterisk | TCP 8088 (WS) | ARI events |

Latency: aim for <30 ms between Asterisk and agent. Cross-region (HCM ↔ Singapore EC2) is feasible but tail latency hurts barge-in feel. Same-AZ EC2 is preferred.

Firewall rules (security group on agent box):

```
Inbound  TCP 8090   from <asterisk_public_ip>/32   AudioSocket
Outbound TCP 8088   to   <asterisk_public_ip>/32   ARI
```

Don't open 8090 to the internet — the protocol has no auth, anyone can speak audio frames at it. UUID is a 128-bit secret in practice but not a security boundary.

---

## 7. Operational checks

### 7.1 Test inbound

```bash
# From a phone, call 1800 6112. Expect:
# - Ring → answer within 1 s
# - "Em chào anh chị, Noble nghe đây ạ"
# - User can speak, agent responds within ~1.5 s
```

### 7.2 Test outbound

```bash
python scripts/make_outbound_call.py --to 0901234567 --message "test goi ra"
```

Watches ARI for the answered leg, then runs the dialog from `[noble-agent-outbound]`.

### 7.3 Tap traffic

```bash
# On agent box:
sudo tcpdump -i eth0 -nn 'tcp port 8090' -X | head -50
# Should see TYPE_UUID (0x01) then TYPE_AUDIO (0x10) every 20 ms.
```

### 7.4 Asterisk-side checks

```
asterisk -rvvv
> stasis show apps                 # noble-voice-agent should be subscribed
> core show channels               # active calls
> core show channeltype audiosocket
```

---

## 8. Common debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| Caller answered, hears silence | AudioSocket connection refused | Confirm agent listens on 8090 (`ss -tlnp \| grep 8090`); check security group |
| Agent has no caller-number | ARI not connected | Check `ASTERISK_ARI_USER/PASS`; logs show "ARI WS connected" at startup |
| Audio glitches every 20 ms | TCP_NODELAY off (Nagle batching) | Verify `audiosocket.py` sets `TCP_NODELAY` on accept (line should mention `socket.IPPROTO_TCP, socket.TCP_NODELAY, 1`) |
| 5-second mid-call disconnect | Asterisk dropped idle socket | Comfort noise loop not running; check `_tts_active` flips back to False between turns |
| Pop / click at start of agent speech | Pacing warmup misconfigured | `_warmup_frames` should default to 5 (= 100 ms); verify in `session.py` |
| `ChannelDestroyed` without `StasisEnd` | Caller hung up before Stasis | Normal; clean up on either |
| Echo / agent hears itself | NS+AGC wrong side, OR Asterisk has DENOISE on too | Pick one; don't run both |
| Phone audio "tinny" / static | Bandpass / pre-emphasis missing | `resampler.py:_resample_24k_to_8k` order: pre-emph → soxr → bandpass |
| First frame has wrong UUID | MD5 → UUID slice off-by-one | Verify dialplan slices: `${UH:0:8}-${UH:8:4}-${UH:12:4}-${UH:16:4}-${UH:20:12}` |

---

## 9. References

- AudioSocket protocol: https://wiki.asterisk.org/wiki/display/AST/AudioSocket
- ARI docs: https://wiki.asterisk.org/wiki/display/AST/Asterisk+REST+Interface
- `docs/freebpx-setup.md` — operational FreePBX setup notes (Vietnamese)
- `docs/runbooks/runpod.md` §5 — why telephony stays off RunPod + LiveKit SIP bridge patterns

Continue → [`08-api-contracts-websocket-http.md`](08-api-contracts-websocket-http.md) for the browser-side equivalent.
