# Outbound Call & SMS — Setup Guide

> Updated: 2026-04-24. Scope: everything beyond the inbound hotline 1800 6112.
> Production agent: `47.129.187.61:8090`. Dev host: local Mac + ngrok.

This doc captures the whole outbound-call + SMS stack added on top of the
existing inbound hotline (`docs/freebpx-setup.md`).

---

## TL;DR

| Feature | Status | How |
|---|---|---|
| Inbound hotline 1800 6112 | ✅ Production | Dialplan `[noble-voice-agent]` → AudioSocket :8090 |
| Outbound call (agent dials a mobile) | ✅ Working | ARI originate `Local/<phone>@from-internal` → FreePBX Outbound Route → trunk → `[noble-agent-outbound]` → AudioSocket |
| SMS via SIP MESSAGE through trunk | ❌ Not delivered | `res_pjsip_messaging` returns 202 but TANTHANHAN-VN trunk does not route MESSAGE to an SMS gateway |
| SMS via HTTP provider | ✅ Ready, awaiting API key | `src/noble_agent/services/sms_service.py` supports `esms` (Vihat) + `speedsms` backends |
| Admin web UI | ✅ New | `static/livekit.html` has a "Gọi cho tôi" card backed by `POST /api/call-me` |

---

## 1. Architecture

### 1.1 Production vs dev

Dialplan on FreePBX is identical in both modes except for the AudioSocket host:

```ini
; extensions_custom.conf — production
[noble-voice-agent]                  ; INBOUND
exten => s,1,NoOp(...)
 same => n,Answer()
 same => n,Wait(0.3)
 same => n,Stasis(noble-voice-agent) ; emits StasisStart so agent captures caller phone
 same => n,Set(UH=${MD5(${UNIQUEID}${EPOCH})})
 same => n,Set(AS_UUID=${UH:0:8}-${UH:8:4}-${UH:12:4}-${UH:16:4}-${UH:20:12})
 same => n,AudioSocket(${AS_UUID},47.129.187.61:8090)
 same => n,Hangup()

[noble-agent-outbound]               ; OUTBOUND (no Stasis needed — see §2)
exten => s,1,NoOp(...)
 same => n,Answer()
 same => n,Wait(0.3)
 same => n,Set(UH=${MD5(${UNIQUEID}${EPOCH})})
 same => n,Set(AS_UUID=${UH:0:8}-${UH:8:4}-${UH:12:4}-${UH:16:4}-${UH:20:12})
 same => n,AudioSocket(${AS_UUID},47.129.187.61:8090)
 same => n,Hangup()
```

**Production** keeps `47.129.187.61:8090` — agent runs on that VPS.

**Dev on local Mac** swaps the IP in both blocks (or just outbound) for an
ngrok TCP tunnel address:

```bash
ngrok tcp 8090
# → Forwarding tcp://0.tcp.ap.ngrok.io:17696 -> localhost:8090
```

Then edit the same dialplan file via FreePBX UI → Admin → Config Edit, replace
`47.129.187.61:8090` with `0.tcp.ap.ngrok.io:17696`, **Apply Config** (mandatory
— FreePBX caches the compiled dialplan; without Apply, the file change is inert).

**Production still works unchanged when the VPS is up.** Only restriction: the
dialplan IP must match whatever host is listening on port 8090. Reverting the
IP back to production after a dev session is a `sed` + Apply Config away.

### 1.2 Outbound call flow

```
[Web/API]  →  POST /api/call-me {phone}
              └─ scripts/run_telephony.py admin HTTP (port 8767)
              └─ OR src/noble_agent/server/http.py (aiortc mode)
                   ↓
ARIClient.originate_channel(phone)
                   ↓
HTTP POST /ari/channels
  endpoint  : Local/<phone>@from-internal  ◄── NOT PJSIP/<phone>@<trunk>
  callerId  : "Noble Agent" <18006112>
  context   : noble-agent-outbound
  extension : s, priority 1
                   ↓
Asterisk spins Local channel
  • Leg A enters [from-internal]
    → FreePBX Outbound Route matches `_0.` pattern
    → substitutes callerID (NOT 1800) if Route config says so
    → picks trunk `NobleX-88801441`
    → dials out via PJSIP → provider → mobile carrier → callee
  • Leg B waits for answer, then jumps into [noble-agent-outbound]
                   ↓
Callee answers ─── leg B runs Answer → Wait → AudioSocket(...)
                   ↓
TCP connect to <agent-host>:8090
                   ↓
TelephonySession starts
  • caller_number matched from _caller_map (pre-populated by originate_channel)
  • VAD → STT → LLM → TTS → back over AudioSocket
```

### 1.3 Why `Local/...@from-internal` (not `PJSIP/...@trunk`)

Direct `PJSIP/<phone>@NobleX-88801441` skips FreePBX's routing pipeline:

- CID `18006112` (toll-free hotline) is sent as-is → VN mobile carriers
  auto-reject with SIP 4xx → Asterisk reports `cause=21 (Call Rejected)`.
- No Outbound Route CID override, no dial-pattern normalization, no trunk
  selection fallback.

`Local/<phone>@from-internal` routes through `[from-internal]` — the same
context real extensions use when dialing out. FreePBX Outbound Routes then:

1. Match the dial pattern (`_0XXXXXXXXX` for VN mobile),
2. Substitute CID per Route config (or strip-and-replace with a provisioned
   DID),
3. Pick the configured trunk and send a properly formed INVITE.

This mirrors what any internal softphone would do when a user dials out —
carriers accept it because the CID is a legitimate DID.

---

## 2. Running the stack

### 2.1 Two terminals

```bash
# Terminal 1 — LiveKit worker (browser WebRTC demo)
conda activate test-voice-alt
python -m noble_agent dev

# Terminal 2 — Telephony (AudioSocket + ARI + admin HTTP)
conda activate test-voice-alt
python scripts/run_telephony.py
```

Expected log (terminal 2):

```
AudioSocket server listening on 0.0.0.0:8090
[TEL] ARI client connecting to voip.noble.vn:8088
ARI connected — listening for Stasis events (app=noble-voice-agent)
[TEL] Telephony manager started
Admin HTTP listening on http://127.0.0.1:8767
```

### 2.2 Outbound call — 3 ways

**(a) Web UI** — open <http://127.0.0.1:8767/>:
The LiveKit page now has a "Gọi cho tôi" card. Enter a mobile number → click
button → agent calls it, pick up to hear the greeting.

**(b) CLI**:

```bash
python scripts/make_outbound_call.py 0942866939
```

**(c) HTTP directly** (from another machine / curl):

```bash
curl -X POST http://<agent-host>:8767/api/call-me \
     -H "Content-Type: application/json" \
     -d '{"phone":"0942866939"}'
```

### 2.3 Live event debugging

When a call doesn't land, subscribe to the full ARI event stream:

```bash
python scripts/debug_ari_events.py --call 0942866939 --mode app --seconds 60
```

`--mode app` bypasses dialplan and puts the channel directly into the Stasis
app — emits `ChannelCreated / Dial / ChannelStateChange / StasisStart /
ChannelHangupRequest` so you see exactly where the call stalls.

Common cause codes (Q.850):

| Cause | Meaning | Likely fix |
|---|---|---|
| 3 | No route to destination | Invalid number format, trunk offline |
| 16 | Normal clearing | OK if after answer; = hangup |
| 17 | User busy | Callee busy |
| 21 | Call rejected | Phone filter (Silence Unknown), carrier rejects 1800 CID — use different CID |
| 34 | Congestion | Trunk out of channels |

---

## 3. SMS

### 3.1 What doesn't work

Sending SIP MESSAGE through the existing TANTHANHAN-VN trunk. Asterisk
accepts the request with HTTP 202, but the trunk provider does not route
MESSAGE to a cellular SMS gateway. Verified: test SIM `0942866939` received
nothing despite multiple 202 Accepted responses.

### 3.2 What works — HTTP provider

`src/noble_agent/services/sms_service.py` exposes one function:

```python
from noble_agent.services.sms_service import send_sms
ok, detail = await send_sms("0942866939", "Hello", backend="esms")
```

Backends:

| Backend | Requires | Notes |
|---|---|---|
| `dry_run` | — | Logs payload only. Safe default. |
| `sip` | `ASTERISK_ARI_PASSWORD` | Accepted by ARI (202) but not delivered with TANTHANHAN trunk. Kept for future trunk upgrade. |
| `esms` | `SMS_ESMS_API_KEY` + `SMS_ESMS_SECRET_KEY` | [eSMS.vn](https://esms.vn) — most common VN. Supports brandname + Zalo ZNS. |
| `speedsms` | `SMS_SPEEDSMS_TOKEN` | [SpeedSMS.vn](https://speedsms.vn) — simpler alternative. |

### 3.3 eSMS setup (recommended)

1. Register at <https://esms.vn> → log in to dashboard.
2. Menu → **Quản lý tài khoản** → **API** → copy `ApiKey` + `SecretKey`.
3. Top up ≥ 50,000 VND (bank transfer or VNPay) to activate.
4. Paste into `.env`:

   ```bash
   SMS_BACKEND=esms
   SMS_ESMS_API_KEY=<key>
   SMS_ESMS_SECRET_KEY=<secret>
   SMS_ESMS_TYPE=1         # 1=random sender (works immediately)
                           # 2=brandname (requires 2-3 day approval)
                           # 8=brandname OTP (cheapest)
   SMS_ESMS_UNICODE=0      # 0=no diacritics (160c/sms), 1=with diacritics (70c/sms)
   ```

5. Test:

   ```bash
   python scripts/send_test_sms.py 0942866939 "Test Noble SMS"
   # → OK  esms accepted: SMSID=xxxxx
   ```

   Recipient receives within 5-30 seconds.

### 3.4 Why not FreePBX's SMS module?

FreePBX `/admin/config.php?display=sms` is the SMS Connector module. It's a
thin wrapper around SMS providers — Sangoma (SIPStation/VI), Bandwidth,
Telnyx, VoIP.ms, Flowroute. None of those provide Vietnamese DIDs or SMS
routing to VN carriers. Vietnamese SMS market is dominated by HTTP providers
(eSMS, Stringee, SpeedSMS, FPT SMS) that expose REST APIs independent of PBX.
Bridging PBX → those APIs adds latency without gain. Direct HTTP is cleaner.

---

## 4. Config reference (`.env`)

```bash
# Telephony core (already set)
TELEPHONY_ENABLED=true
ASTERISK_ARI_PASSWORD=NobleAgent2026!
ASTERISK_HOST=voip.noble.vn           # default
ASTERISK_ARI_PORT=8088                # default
ASTERISK_ARI_USERNAME=noble-agent     # default
ASTERISK_ARI_APP=noble-voice-agent    # default

# Outbound call
ASTERISK_SIP_TRUNK=NobleX-88801441
ASTERISK_OUTBOUND_CALLERID=18006112
ASTERISK_OUTBOUND_CONTEXT=noble-agent-outbound
ASTERISK_OUTBOUND_TIMEOUT=30

# Admin HTTP (port 8767)
TELEPHONY_ADMIN_ENABLED=true
TELEPHONY_ADMIN_HOST=127.0.0.1        # use 0.0.0.0 to expose externally
TELEPHONY_ADMIN_PORT=8767

# SMS
SMS_ENABLED=true
SMS_BACKEND=dry_run                   # dry_run | sip | esms | speedsms
SMS_FROM=18006112
SMS_ESMS_API_KEY=
SMS_ESMS_SECRET_KEY=
SMS_ESMS_BRANDNAME=
SMS_ESMS_TYPE=1
SMS_ESMS_UNICODE=0
SMS_SPEEDSMS_TOKEN=
SMS_SPEEDSMS_SENDER=
SMS_SPEEDSMS_TYPE=2
```

All settings live in `src/noble_agent/config.py` (`Settings` class).

---

## 5. Files changed / added

| File | Role |
|---|---|
| `src/noble_agent/config.py` | 14 new fields (outbound trunk, admin HTTP, SMS) |
| `src/noble_agent/telephony/ari_client.py` | `originate_channel()` (Local/from-internal) + `send_sip_message()` + verbose event logging |
| `src/noble_agent/telephony/session.py` | Module-level `_telephony_manager` singleton (registered in `start()`) |
| `src/noble_agent/services/sms_service.py` | Pluggable SMS service (4 backends) |
| `src/noble_agent/server/http.py` | `POST /api/call-me` endpoint (aiortc mode) |
| `scripts/run_telephony.py` | AudioSocket + ARI + **admin HTTP on port 8767** (livekit mode) |
| `scripts/make_outbound_call.py` | CLI outbound call |
| `scripts/send_test_sms.py` | CLI SMS, all backends |
| `scripts/debug_ari_events.py` | Full ARI event stream watcher + originate |
| `static/livekit.html` | New "Gọi cho tôi" card calling `POST /api/call-me` |
| `.env`, `.env.example` | New config blocks for outbound + SMS + admin |

---

## 6. Troubleshooting

### Agent's log empty after `make_outbound_call.py`

→ FreePBX dialplan not reloaded. Apply Config on FreePBX UI (red button).
  Verify with `asterisk -rx "dialplan show noble-agent-outbound"` via SSH if
  you have access, or trigger another originate and watch
  `scripts/debug_ari_events.py --mode app` output.

### `cause=21 Call Rejected` every time

→ Either the phone has Silence Unknown Callers on, or the CID is being
  rejected. Check with `debug_ari_events.py --mode app` — the `ChannelCreated`
  event shows the CID being sent. If it's `18006112`, verify FreePBX trunk
  "CID Options" is `Allow Any CID` AND that Outbound Route substitutes the
  CID to a mobile DID (trunk CID policy may still override).

### "originate returns state=Down then channel disappears"

→ Normal when using `--mode context` and outbound dialplan has no `Stasis()`.
  State transitions happen outside our ARI app subscription. Use `--mode app`
  for full event visibility.

### Admin HTTP port 8767 already in use

→ Set `TELEPHONY_ADMIN_PORT=8768` (or any free port) in `.env`.

### `MongoDB unavailable — session metrics not persisted`

→ Local MongoDB not running. Metrics persistence is optional; call itself
  works fine. Start Mongo with `docker compose up -d mongo` or ignore.
