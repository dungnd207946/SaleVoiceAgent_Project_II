# Telephony — Noble Voice Agent ↔ FreePBX/Asterisk

Tài liệu này mô tả cấu hình và quy trình triển khai module `src/telephony/` để tích hợp **Noble Voice Agent** với tổng đài **FreePBX/Asterisk** qua giao thức **AudioSocket (TCP)** và **ARI (REST + WebSocket)**.

Phạm vi: toàn bộ đường đi cuộc gọi từ **hotline 1800 6112 → FreePBX (voip.noble.vn) → Agent** và ngược lại.

---

## 1. Kiến trúc tổng quan

```
                    PSTN / SIP trunk
                          │  (DID 18006112)
                          ▼
 ┌────────────────────────────────────────────────┐
 │ FreePBX / Asterisk  (voip.noble.vn)            │
 │                                                │
 │  Inbound Route(18006112)                       │
 │      │                                         │
 │      ▼ Custom Destination                      │
 │  [noble-voice-agent] dialplan                  │
 │      │   Answer → DENOISE → AGC → JITTERBUFFER │
 │      ▼                                         │
 │  AudioSocket(${UUID}, <agent_host>:8090)       │
 │                                                │
 │  (optional) ARI WebSocket /ari/events          │
 │     app=noble-voice-agent  (port 8088)         │
 └────────────┬───────────────────────┬───────────┘
              │ TCP (TLV frames)      │ WebSocket (JSON events)
              │ slin 16-bit 8 kHz     │ StasisStart / StasisEnd
              ▼                       ▼
 ┌────────────────────────────────────────────────┐
 │ Noble Voice Agent (Python)                     │
 │                                                │
 │  telephony/audiosocket.py   (TCP :8090)        │
 │      │ TYPE_UUID 0x01 → call_id                │
 │      │ TYPE_AUDIO 0x10 → 320 B / 20 ms         │
 │      ▼                                         │
 │  telephony/session.py TelephonySession          │
 │      │  resampler.py:  8k → 16k (STT)          │
 │      │  webrtc-noise-gain NS+AGC (10 ms)       │
 │      │  VAD Silero → STT → LLM → TTS           │
 │      │  resampler.py:  24k → 8k (slin)         │
 │      │  pacing 20 ms/frame + 100 ms warmup     │
 │      ▼                                         │
 │  AudioSocket write_audio_frame()               │
 │                                                │
 │  telephony/ari_client.py    (optional)         │
 │      Lấy caller number khi StasisStart         │
 │      rồi gọi /channels/{id}/continue           │
 └────────────────────────────────────────────────┘
```

### Các file chính

| File | Vai trò |
|------|---------|
| `audiosocket.py` | TCP server :8090, đọc/ghi TLV frames (type/length/value). `TCP_NODELAY` bật. |
| `session.py` | `TelephonySession` và `TelephonyManager`. Một connection = một cuộc gọi. |
| `resampler.py` | 8k↔16k↔24k qua **soxr HQ** (fallback scipy → numpy), có pre-emphasis + bandpass 200–3400 Hz cho path TTS→8k. |
| `ari_client.py` | WebSocket ARI để nhận `StasisStart` (lấy `caller.number`) và auto-reconnect. |

### Sample-rate chain

| Chặng | Rate | Frame | Ghi chú |
|------|------|-------|---------|
| Asterisk wire | 8 kHz slin16 | 320 B / 20 ms | `audiosocket_format=slin` |
| STT / VAD | 16 kHz PCM16 | variable | Resample 8→16 |
| TTS output | 24 kHz PCM16 | chunk | VieNeu / ElevenLabs |
| Agent → Asterisk | 8 kHz slin16 | 320 B / 20 ms | Resample 24→8 + bandpass |
| Silence keepalive | 8 kHz | 320 B / 20 ms | `rng.normal(0,32)` comfort noise, khi `_tts_active=False` |

---

## 2. Biến môi trường (`.env`)

Khối telephony trong `.env` (tham khảo `.env.example` dòng 71–83):

```bash
# ── Telephony: Asterisk/FreePBX ─────────────────────────────
TELEPHONY_ENABLED=true              # Bật AudioSocket server khi app khởi động
ASTERISK_HOST=voip.noble.vn         # Hostname FreePBX
ASTERISK_ARI_PORT=8088              # ARI HTTP/WS port (mặc định 8088)
ASTERISK_ARI_SCHEME=http            # http | https
ASTERISK_ARI_USERNAME=noble-agent
ASTERISK_ARI_PASSWORD=              # BẮT BUỘC nếu muốn bật ARI; để trống = skip ARI
ASTERISK_ARI_APP=noble-voice-agent  # Tên Stasis app
AUDIOSOCKET_HOST=0.0.0.0            # Bind all interfaces
AUDIOSOCKET_PORT=8090
TELEPHONY_RECORD_CALLS=false
TELEPHONY_RECORDINGS_DIR=data/recordings
```

Các setting bổ sung trong `src/config.py` (đã có giá trị mặc định, chỉnh khi cần):

```python
asterisk_sip_trunk          = "NobleX-88801441"   # PJSIP trunk cho outbound
asterisk_outbound_callerid  = "18006112"
asterisk_sip_server         = "103.15.222.9:44444"
telephony_sample_rate       = 8000
audiosocket_format          = "slin"              # chưa hỗ trợ slin16 native

# Bảo vệ echo / ngắt lời (dùng cho cả WebRTC + telephony) — xem §5.4
vad_interrupt_confirm_chunks = 3       # VAD_INTERRUPT_CONFIRM_CHUNKS: chunk 32 ms liên tiếp có tiếng
barge_in_rms_threshold       = 1500.0  # BARGE_IN_RMS_THRESHOLD: sàn RMS khi audio agent đang phát; 0 = tắt

# Idle timeout (Approach 2)
idle_reprompt_delay         = 10.0
idle_goodbye_delay          = 5.0
idle_disconnect_delay       = 2.0
```

> **Quan trọng:** Nếu không set `ASTERISK_ARI_PASSWORD`, app vẫn chạy AudioSocket bình thường nhưng sẽ **không có số điện thoại caller** (log: `[TEL] ARI client skipped`). Khi đó profile khách hàng lưu theo `call_id` thay vì số.

---

## 3. Setup FreePBX — Các bước đã thực hiện

Môi trường đã verify (ngày 2026-04-14, tham chiếu `project_freepbx_integration.md`):

- FreePBX admin UI: `https://voip.noble.vn`
- Hotline / DID: `1800 6112` (DID `18006112`)
- Agent chạy local Mac, ngrok TCP tunnel `0.tcp.ap.ngrok.io:19965` → `localhost:8090`
- Dialplan custom context: `noble-voice-agent`
- Inbound Route `NobleX-18006112` → **Custom Destination** → `noble-voice-agent,s,1`

### 3.1 Kiểm tra module Asterisk

Vào Asterisk CLI (`asterisk -rvvv` trên server FreePBX):

```bash
module show like app_audiosocket       # BẮT BUỘC
module show like res_audiosocket
module show like func_speex             # Cần cho DENOISE/AGC
module show like res_ari
module show like res_ari_channels
```

Nếu module chưa load:

```bash
asterisk -rx "module load app_audiosocket.so"
asterisk -rx "module load res_audiosocket.so"
asterisk -rx "module load func_speex.so"
```

Đưa vào `/etc/asterisk/modules.conf` để tự load khi restart.

> Asterisk **≥16** mới có `app_audiosocket`. Asterisk **≥20** mới có slin16/24/48 (nhưng argument format còn bug, **giữ slin 8 kHz**).

### 3.2 Custom dialplan

File: `/etc/asterisk/extensions_custom.conf` (FreePBX không ghi đè file này).

```ini
;; ──────────────────────────────────────────────────────────────
;; Noble Voice Agent — AudioSocket context
;; ──────────────────────────────────────────────────────────────
[noble-voice-agent]
exten => s,1,NoOp(=== Noble Voice Agent inbound ===)
 same => n,Answer()
 same => n,Wait(0.3)
 ; ── Audio quality enhancements (chỉ áp cho caller rx) ────────
 same => n,Set(DENOISE(rx)=on)
 same => n,Set(AGC(rx)=8000)
 same => n,Set(JITTERBUFFER(adaptive)=default)
 ; ── Connect to agent ─────────────────────────────────────────
 same => n,Set(AS_UUID=${CHANNEL(uniqueid)})
 same => n,AudioSocket(${AS_UUID},<AGENT_HOST>:<AGENT_PORT>)
 same => n,Hangup()

[noble-voice-agent-fallback]
exten => s,1,NoOp(=== Agent unreachable — fallback ===)
 same => n,Answer()
 same => n,Playback(tt-allbusy)
 same => n,Hangup()
```

Thay `<AGENT_HOST>:<AGENT_PORT>`:
- **Dev (ngrok):** `0.tcp.ap.ngrok.io:19965` (ví dụ)
- **Prod (VPS/EC2):** IP public của server + port `8090` (ví dụ `47.129.187.61:8090`)

Apply:

```bash
asterisk -rx "dialplan reload"
asterisk -rx "dialplan show noble-voice-agent"
```

### 3.3 Inbound Route (FreePBX UI)

`Connectivity → Inbound Routes → Add`:

| Field | Value |
|-------|-------|
| Description | `NobleX-18006112` |
| DID Number | `18006112` |
| Set Destination | **Custom Destinations → noble-voice-agent** |

Thêm Custom Destination (`Admin → Custom Destinations → Add`):

| Field | Value |
|-------|-------|
| Custom Destination | `noble-voice-agent,s,1` |
| Description | `Noble AI Agent entry` |
| Notes | — |

Bấm **Apply Config** sau khi lưu.

### 3.4 ARI user (optional — để lấy caller number)

`Settings → Asterisk REST Interface Users → Add`:

| Field | Value |
|-------|-------|
| Username | `noble-agent` |
| Password | `<strong-password>` → copy vào `.env` `ASTERISK_ARI_PASSWORD` |
| Read Only | **No** |

Bật `/etc/asterisk/ari.conf`:

```ini
[general]
enabled = yes
pretty = yes

[noble-agent]
type = user
read_only = no
password = <strong-password>
password_format = plain
```

Và trong `/etc/asterisk/http.conf`:

```ini
[general]
enabled = yes
bindaddr = 0.0.0.0
bindport = 8088
```

Reload: `asterisk -rx "core reload"`.

Verify từ agent host:

```bash
curl -u noble-agent:<password> http://voip.noble.vn:8088/ari/asterisk/info | jq .
```

### 3.5 Codec priority (đã chỉnh)

`Settings → Asterisk SIP Settings → Codecs`:

Ưu tiên thứ tự:
1. `ulaw` (G.711)
2. `alaw`
3. `g722` — để tương lai hỗ trợ wideband
4. `opus` (nếu trunk hỗ trợ)

> Với AudioSocket hiện tại chạy `slin 8 kHz`, chọn codec không ảnh hưởng đường đi nội bộ, chỉ ảnh hưởng codec trên trunk/SIP phone. Nhưng để sẵn cho upgrade sau này.

### 3.6 Firewall

Mở port trên server chạy agent:

- **TCP 8090** — AudioSocket (FreePBX → Agent)
- **TCP 8088** — ARI (nếu agent gọi về FreePBX). Thường chỉ open cho IP của agent.
- **TCP 8766** — WebSocket/HTTP UI (tùy chọn).

Nếu Agent nằm sau NAT (dev trên Mac):

```bash
ngrok tcp 8090
# lấy host:port như 0.tcp.ap.ngrok.io:19965 → dán vào extensions_custom.conf
```

---

## 4. Chạy Agent

```bash
# 1. Cài dep (chỉ lần đầu)
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# Nên cài soxr để có anti-aliasing khi resample 24→8 kHz:
pip install soxr webrtc-noise-gain

# 2. Bật telephony trong .env
#    TELEPHONY_ENABLED=true
#    ASTERISK_ARI_PASSWORD=<...>   (nếu bật ARI)

# 3. Dev (Mac + ngrok)
ngrok tcp 8090                                # terminal 1
scripts/run.sh --no-reload                    # terminal 2

# 4. Prod (VPS)
scripts/run.sh --no-reload   # hoặc systemd service / tmux
```

Log mong đợi khi khởi động thành công:

```
[TEL] Telephony manager started
AudioSocket server listening on 0.0.0.0:8090
[TEL] ARI client connecting to voip.noble.vn:8088
ARI connected — listening for Stasis events (app=noble-voice-agent)
```

Log khi có cuộc gọi vào:

```
[TEL][ARI] StasisStart: channel_id=... caller=0912xxxxxx
AudioSocket connection from ('...', ...)
AudioSocket call started: call_id=<uuid> peer=...
[TEL] Call started: call_id=<uuid> session_id=tel-<uuid>
[TEL] STT started: soniox
```

---

## 5. Các đặc điểm kỹ thuật đã tích hợp

### 5.1 Giao thức AudioSocket (TLV)

```
┌────┬──────────┬────────────────┐
│ T  │  Length  │     Value      │
│ 1B │    2B    │   N bytes      │
└────┴──────────┴────────────────┘

T = 0x00 HANGUP
    0x01 UUID      (16 bytes binary or UTF-8 string)
    0x02 SILENCE
    0x10 AUDIO     (slin 16-bit 8 kHz mono, N=320 cho 20 ms)
    0xFF ERROR
```

- Frame đầu tiên Asterisk gửi **bắt buộc là UUID**. Agent parse 16 byte binary trước, fallback UTF-8, cuối cùng tự sinh `uuid4()` nếu payload invalid.
- `audiosocket.py:_handle_connection` set `TCP_NODELAY=1` để giảm 20–40 ms latency.
- `write_audio_frame()` không `await drain` trong hàm — caller (`session._send_audio`) tự drain theo nhịp.

### 5.2 Keepalive & pacing

- **Silence keepalive**: 320 B comfort noise (`σ≈32`, ~-60 dBFS) mỗi 20 ms khi không có TTS. Asterisk drop kết nối nếu không nhận frame nào trong ~5 s. Implement: `session.py::_silence_keepalive`.
- **TTS pacing** (`session.py::_send_audio`):
  - 5 frame đầu burst ngay (100 ms) để pre-fill jitter buffer Asterisk.
  - Từ frame 6 trở đi pacing theo clock anchor `send_start + idx*0.020`.
  - Cosine fade-in 15 ms cho chunk đầu mỗi utterance (tránh click).
  - Soft-knee compressor (threshold 55 %, ratio 3:1) thay cho hard clip.

### 5.3 Chuỗi xử lý audio input

```
slin 8k  ─ resample_8k_to_16k (soxr HQ)
         ─ webrtc-noise-gain NS=3, AGC=3  (10 ms frame)
         ─ VAD Silero 32 ms chunk  →  state machine
         ─ STT send()  →  on_partial / on_final
```

### 5.4 Chống false-interrupt (telephony dùng chung `SileroVAD` với WebRTC)

`INTERRUPTED` chỉ bật khi đủ `VAD_INTERRUPT_CONFIRM_CHUNKS` (3) chunk 32 ms liên tiếp có tiếng, và — chỉ khi audio agent **thật sự đang phát** (`vad.playback_active`, bật ở chunk TTS đầu tiên trong `_send_audio`) — mỗi chunk còn phải vượt sàn `BARGE_IN_RMS_THRESHOLD` (RMS int16, mặc định 1500; 0 = tắt). PSTN không có AEC nên echo TTS dội về là "tiếng nói" nhỏ: sàn này chặn nó. Bị chặn thì agent log `rejected by RMS floor` một lần/lượt — thấy log này ở cuộc gọi thật (khách nói nhỏ không ngắt được) thì hạ sàn. Telephony KHÔNG có `EchoCooldown` (chỉ WebRTC/LiveKit, và nó chỉ chắn STT final, không chắn interrupt). Khi bật `ADDRESSEE_GATE_MODE`, `INTERRUPTED` mở episode đo tiếng thay vì cancel ngay (spec addressee gate). Khi `INTERRUPTED` thật: `agent.interrupt()` + cancel agent task + `vad.set_idle()`.

### 5.5 Spectral conditioning cho path TTS → 8 kHz

`resampler.resample_tts_to_8k` áp:
- **Pre-emphasis** `y[n]=x[n]-0.68·x[n-1]` (bù spectral tilt cho narrowband).
- **Bandpass 200–3400 Hz** (PSTN passband) trước khi downsample — cache `butter` SOS theo src-rate.
- **soxr HQ** 24k → 8k (anti-aliasing chuẩn).

Không có soxr: scipy.signal.resample_poly → numpy linear. Linear gây metallic/buzzing ở 24→8 — **khuyến cáo cài `soxr`**.

### 5.6 Idle timeout (3 trạng thái)

Timer bắt đầu **sau khi TTS phát xong** (không phải khi code return). `session.py:_start_idle_timer`:

| State | Delay | Hành động |
|-------|-------|-----------|
| 0 → 1 | `idle_reprompt_delay` (10 s) | Hỏi lại: "Dạ, {Anh/Chị} còn ở đây không ạ?" |
| 1 → 2 | `idle_goodbye_delay` (5 s) | Chào tạm biệt |
| 2 → hangup | `idle_disconnect_delay` (2 s) | Đóng writer → Asterisk hangup |

Danh xưng (Anh/Chị/Quý Khách) lấy từ `customer.gender` + `customer.name` trong Redis.

### 5.7 ARI flow

`StasisStart` event → lấy `channel.caller.number` → map `channel_id → phone`. Sau khi xử lý, gửi `POST /channels/{id}/continue` để channel quay lại dialplan (bước `AudioSocket(...)`).

Cleanup: `StasisEnd` **không xóa ngay** caller map (AudioSocket connect ~300 ms sau StasisEnd). Xóa sau 30 s timeout hoặc khi consumed bởi `_on_new_call`.

Vì UUID `AudioSocket` và `channel_id` ARI không khớp exact, `_on_new_call` fallback: lấy phone **gần nhất** trong map và consume nó.

### 5.8 Hallucination filter

`WhisperHallucinationFilter` lọc các câu whisper-style ("Cảm ơn đã xem.", "Phụ đề: …") vì STT cloud đôi khi hallucinate khi có nhiễu / im lặng kéo dài.

### 5.9 Gender detection + prompt refresh

`voice.gender_detector.GenderDetector` chạy trên ring buffer 4 s. Khi detect xong, lưu vào Redis rồi `agent.refresh_system_prompt()` để tái build system prompt (FAQ + xưng hô thay đổi).

### 5.10 Customer persistence

- **In-session:** `session_store.save_customer(session_id, ...)` — Redis TTL.
- **Persistent by phone:** snapshot cuối cuộc gọi lưu MongoDB `customers` collection theo `phone`. Cuộc gọi sau từ cùng số → preload profile (skip gender detection nếu đã có).

---

## 6. Kiểm thử & vận hành

### Test connection không cần Asterisk thật

```bash
# Gửi UUID + một audio frame giả
python tests/test_telephony_pipeline.py
python tests/test_telephony_protected.py
```

`test_telephony_protected.py` serve UI `/prompts` (SSE) giúp xem real-time system prompt khi FAQ/agent thay đổi — rất hữu ích để debug FAQ injection.

### Health check

```bash
curl http://localhost:8766/health/ready
# Check: Redis, MongoDB, Qdrant, LLM, embeddings
```

### Log hữu ích

- `logger.info` namespace `telephony.audiosocket`, `telephony.session`, `telephony.ari`
- Toàn bộ STT partial/final, VAD state, tool calls đã log ở level INFO.
- Khi debug audio: hạ `echo_cooldown_sec=0` để xem VAD interrupt raw.

---

## 7. Các vấn đề đã gặp + đã xử lý

| Issue | Root cause | Fix đã apply |
|-------|-----------|--------------|
| macOS spawn pickle error với watchfiles | multiprocessing spawn không pickle được closure | `_runner.py` — chạy reload thủ công, dev dùng `--no-reload` |
| Asterisk drop kết nối sau 5 s | Không có frame audio về | `_silence_keepalive` gửi comfort noise 20 ms/lần khi `_tts_active=False` |
| STT/init làm trễ audio loop → TCP buffer overflow | Init chạy sau khi đọc frame | Start `_audio_loop` + `_silence_keepalive` **trước** khi init STT/agent |
| Buzzing khi TTS phát (resample 24k→8k) | numpy linear không anti-aliasing | `soxr HQ` + pre-emphasis + bandpass 200–3400 Hz |
| Metallic click đầu mỗi chunk TTS | Hard-clip + biên độ đột ngột | Soft-knee compressor + cosine fade-in 15 ms |
| Jitter đầu utterance | Asterisk jitter buffer chưa pre-fill | Burst 5 frame (100 ms) đầu rồi pacing chính xác 20 ms/frame |
| Caller number mất khi StasisEnd | Cleanup map quá sớm (AudioSocket connect sau 300 ms) | Delay cleanup 30 s + fallback "most recent entry" |
| False interrupt từ echo TTS | Mic nghe lại tiếng agent | 4-layer guard (cooldown + min playback + RMS + STT gate) |
| Whisper-style hallucinated transcript | STT sinh "Cảm ơn đã xem." khi im lặng | `WhisperHallucinationFilter` lọc trước khi trigger agent |

### Vấn đề còn tồn đọng (theo `project_freepbx_integration.md`)

- Echo từ TTS về mic qua PSTN trong một số thiết bị (cần test thêm AEC client-side).
- Latency end-to-end ~2 s (STT cloud + LLM TTFT + TTS TTFB + ngrok overhead).
- ngrok chỉ dùng dev — prod cần VPS/EC2 public IP.
- Chưa có call recording (`TELEPHONY_RECORD_CALLS=false`). Nếu bật, raw slin 8 kHz sẽ lưu vào `data/recordings/`.

---

## 8. Roadmap upgrade (chưa apply — tham chiếu `docs/plan/claude_plan_9_telephony_brainstorm.md`)

| Tier | Hạng mục | Impact | Effort |
|------|----------|--------|--------|
| 1 | Bật `DENOISE(rx)` + `AGC(rx)` + `JITTERBUFFER` trong dialplan | +20–30 % STT accuracy | 5 phút |
| 1 | Ưu tiên G.722 (wideband) trên trunk | +10–15 % chất lượng nguồn | 5 phút |
| 2 | Output jitter buffer 60 ms | Mượt TTS chunk biên | 4–6 h |
| 3 | slin16 AudioSocket native (type `0x12`) khi Asterisk fix bug | Bỏ hẳn resample 8→16 | 4–8 h |
| 3 | WebRTC trực tiếp vào Asterisk (`chan_pjsip` + Opus 48 kHz) | Wideband full-duplex | 2–3 ngày |

---

## 9. Tham chiếu

- **Code:** `src/telephony/{audiosocket,session,resampler,ari_client}.py`
- **Config:** `src/config.py` (các field `telephony_*`, `asterisk_*`, `audiosocket_*`, `echo_*`, `interrupt_*`, `idle_*`)
- **Brainstorm chi tiết:** `docs/plan/claude_plan_9_telephony_brainstorm.md`
- **Protocol:** https://docs.asterisk.org/Configuration/Channel-Drivers/AudioSocket/
- **ARI docs:** https://docs.asterisk.org/Asterisk_18_Documentation/API_Documentation/Asterisk_REST_Interface/
- **AVA reference:** https://github.com/hkjarral/AVA-AI-Voice-Agent-for-Asterisk
- **Asterisk PR #1492 (higher sample rates):** https://github.com/asterisk/asterisk/pull/1492
