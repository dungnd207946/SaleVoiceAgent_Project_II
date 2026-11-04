# Tách STT/TTS thành service thường trú qua WebSocket

**Ngày:** 2026-06-26
**Nhánh:** `feat/seperate-service`
**Trạng thái:** Design — chờ lập kế hoạch triển khai

## 1. Vấn đề

LiveKit agents chạy theo mô hình **process-pool**: `prewarm_fnc` (`transport/livekit/worker.py::_prewarm`)
chạy *một lần mỗi job-process*, không phải một lần toàn server. `num_idle_processes`
chỉ giữ ấm sẵn N process; khi số cuộc gọi đồng thời vượt N, LiveKit spawn process
mới → mỗi process lại gọi `vieneu._load_tts()` (GPU) + `sherpa._get_recognizer()` (CPU).

Hệ quả:

1. **Tốn VRAM:** mỗi job-process giữ một bản model TTS vieneu riêng trên GPU →
   N cuộc gọi đồng thời = N bản model trong VRAM.
2. **Cold-call:** process spawn ngoài pool phải warmup lại từ đầu dù boot đã warmup
   các process idle.

`soniox` và `elevenlabs` không gặp vấn đề này vì chúng là **API từ xa qua WebSocket** —
model sống ở dịch vụ bên ngoài, agent chỉ là client.

## 2. Mục tiêu

Tách `sherpa` (STT) và `vieneu` (TTS) thành **2 service thường trú độc lập**, load model
đúng **một lần**, và để mỗi agent job-process kết nối vào qua **WebSocket** — đúng pattern
mà `soniox`/`elevenlabs` đang dùng. URL của 2 service cấu hình qua `.env` để sau này có
thể deploy 2 service trên **server GPU khác** với server chạy agent worker.

### Ngoài phạm vi (v1)

- SileroVAD, GenderDetector, SmartTurn, FlatStore vẫn load trong worker (CPU, nhẹ hơn,
  không phải nguồn gốc vấn đề VRAM mà người dùng nêu).
- Pool K bản model TTS song song (chỉ thiết kế protocol để sau thêm được — xem §8).
- Reconnect tự động khi WS rớt giữa phiên (v1: log + degrade; xem §7).

## 3. Quyết định thiết kế (đã chốt)

| Quyết định | Lựa chọn | Lý do |
|---|---|---|
| Transport | **WebSocket** | Khớp y hệt pattern `elevenlabs.py`; service-to-service không cần NAT/jitter của WebRTC. |
| Topology | **2 service riêng** (`santa-stt` CPU, `santa-tts` GPU) | Scale/restart/deploy độc lập; STT không chiếm GPU; mỗi service đơn nhiệm dễ test. |
| Concurrency TTS | **1 model + hàng đợi tuần tự** (`_inference_lock` sẵn có) | VRAM tối thiểu. TTS streaming theo clause nên burst ngắn; đủ cho tải hotline. Pool K là nâng cấp sau. |
| Deploy | **Service riêng trong docker-compose** + console scripts | Model lên GPU 1 lần; agent worker không đụng GPU. URL `.env`-driven để tách máy. |

## 4. Kiến trúc

### 4.1 Cấu trúc file

```
src/noble_agent/voice/service/
  __init__.py
  protocol.py        # schema frame dùng chung + hằng số
  stt_server.py      # WS server bọc sherpa._get_recognizer() singleton
  tts_server.py      # WS server bọc vieneu._load_tts() singleton

src/noble_agent/voice/stt/remote.py   # RemoteSTT  — client, implements STTBase
src/noble_agent/voice/tts/remote.py   # RemoteTTS  — client, implements stream()
```

### 4.2 Tái sử dụng code hiện có

- **STT server:** logic decode của `SherpaSTT` (per-session `recognizer.create_stream()`,
  vòng decode trên thread nền, `on_partial`/`on_final`) **chuyển sang server-side**. Mỗi WS
  connection = 1 `OnlineStream`; recognizer singleton dùng chung qua `_get_recognizer()`.
- **TTS server:** mỗi request gọi `tts.stream(text)` của `AsyncVieNeuTTS`/`VieNeuTTS` dưới
  `_inference_lock` toàn cục sẵn có; stream PCM ra WS.
- **Client:** `RemoteSTT`/`RemoteTTS` mirror gần như nguyên `voice/stt/elevenlabs.py` và
  `voice/tts/elevenlabs.py` (cùng dùng `websockets`, cùng callback / async generator).

### 4.3 Điểm mấu chốt: worker tự động không load model nặng

`voice/prewarm.py::prewarm_voice_models()` **đã gate** theo `settings.stt_backend == "sherpa"`
và `settings.tts_backend == "vieneu"`. Worker chạy `STT_BACKEND=remote` / `TTS_BACKEND=remote`
→ prewarm **tự động bỏ qua** load model nặng. Model nặng chỉ sống trong 2 service process.
Không cần sửa `prewarm.py`.

## 5. Wire protocol (WebSocket)

Quy ước chung: **binary frame = audio PCM thô**, **text frame = JSON control**. Thư viện
`websockets` phân biệt binary/text ở tầng frame nên không cần đóng gói thêm.

### 5.1 STT — endpoint `/stt`

- Client → Server:
  - **binary**: PCM int16, 16kHz, mono (đúng nội dung `STTBase.send(pcm_bytes)`).
  - **text** `{"type":"eos"}`: client gọi `stop()`.
- Server → Client (text JSON):
  - `{"type":"partial","text": "..."}` → `on_partial(text)`
  - `{"type":"final","text": "..."}` → `on_final(text)`

### 5.2 TTS — endpoint `/tts`

- Client → Server (text JSON):
  - `{"type":"synthesize","text":"...","voice":"<optional voice_id>"}`
  - `{"type":"cancel"}`: barge-in — hủy lần synth đang chạy.
- Server → Client:
  - **binary**: PCM int16, 24kHz, mono — stream **từng chunk ngay khi sinh** (không buffer
    cả câu, giữ TTFA).
  - **text** `{"type":"end"}`: kết thúc một lần synthesize.

**Cancel (barge-in) — bắt buộc đúng:** `RemoteTTS.stream` là async generator; khi consumer
dừng (`pause_tts` → loop kéo thoát → `GeneratorExit`), block `finally` gửi `{"type":"cancel"}`.
Server nhận cancel → thoát vòng `tts.stream` → **nhả `_inference_lock` ngay**, tránh giữ GPU
vô ích trong khi caller đã ngắt lời. WS giữ **thường trú per-session** (1 synth/lần, khớp bản
chất tuần tự của turn) để tránh handshake mỗi turn.

## 6. Tích hợp & fallback

### 6.1 Đăng ký backend `remote`

- STT: thêm builder `"remote"` vào map trong `server/base_session.py::_init_stt`.
- TTS: thêm builder `"remote"` vào map trong `voice/voice_agent.py::_create_tts`.

### 6.2 Fallback — ưu tiên cloud trước local-in-worker

Rớt về model local **trong worker** = tái hiện đúng vấn đề VRAM/warmup đang giải, nên thứ tự
fallback đặt **cloud trước, local làm last-resort**:

```python
# voice/fallback.py
STT_FALLBACK_CHAIN = ["remote", "soniox", "sherpa"]
TTS_FALLBACK_CHAIN = ["remote", "elevenlabs", "vieneu"]
```

`resolve_order(configured, chain)` giữ nguyên ngữ nghĩa (config làm head, phần còn lại của
chain theo thứ tự):

- `STT_BACKEND=remote` → `remote → soniox → sherpa` (cloud trước, local cuối cùng).
- `STT_BACKEND=sherpa` (giữ tương thích cũ) → `sherpa → remote → soniox`: vẫn rớt về
  soniox như trước, chỉ chèn thêm `remote` fail-fast nếu service tắt.
- `TTS_BACKEND=remote` → `remote → elevenlabs → vieneu`.
- `TTS_BACKEND=vieneu` (cũ) → `vieneu → remote → elevenlabs`.

**Chốt chặn cứng:** image của agent worker **không cài** extra `stt-sherpa`/`tts-vieneu` →
builder local raise `ImportError` → bị skip → worker **không bao giờ** load GPU model kể cả ở
nhánh last-resort. Local chỉ chạy được trên chính image của service (có cài extra).

## 7. Vòng đời, lỗi & bảo mật

- **Service startup:** load singleton một lần (`_get_recognizer()` / `_load_tts()`) — đây
  chính là warmup; log readiness sau khi load xong. Bind `0.0.0.0:<port>` để máy khác kết nối.
- **Client connect:** `start()` mở WS tới `*_SERVICE_URL`. Lỗi connect → fallback chain xử lý
  (STT) / raise để `_create_tts` thử backend kế (TTS).
- **WS rớt giữa phiên (v1):** STT ngừng phát callback + log; TTS coi như lỗi stream → kích
  hoạt interrupt. Reconnect tự động để pha sau.
- **Bảo mật (tùy chọn, mặc định tắt):**
  - `VOICE_SERVICE_AUTH_TOKEN` rỗng = tắt. Khi đặt: client gửi header
    `Authorization: Bearer <token>`; server từ chối kết nối thiếu/sai token.
  - TLS qua `wss://` do reverse-proxy (nginx/caddy) đảm nhiệm; service nói WS thuần phía trong.

## 8. Cấu hình (`.env`)

| Biến | Mặc định | Vai trò |
|---|---|---|
| `STT_BACKEND` | `sherpa` | Đặt `remote` ở agent worker để dùng service. |
| `TTS_BACKEND` | `vieneu` | Đặt `remote` ở agent worker để dùng service. |
| `STT_SERVICE_URL` | `ws://127.0.0.1:8770/stt` | URL WS đầy đủ client kết nối. Đổi sang `ws://<gpu-host>:8770/stt` / `wss://stt.noblex.vn/stt` khi tách máy. |
| `TTS_SERVICE_URL` | `ws://127.0.0.1:8771/tts` | Như trên cho TTS. |
| `STT_SERVICE_HOST` | `0.0.0.0` | Bind host của STT server. |
| `STT_SERVICE_PORT` | `8770` | Bind port của STT server. |
| `TTS_SERVICE_HOST` | `0.0.0.0` | Bind host của TTS server. |
| `TTS_SERVICE_PORT` | `8771` | Bind port của TTS server. |
| `VOICE_SERVICE_AUTH_TOKEN` | (rỗng) | Bearer token tùy chọn; rỗng = không xác thực. |

URL là **đầy đủ** và không giả định localhost → tách 2 service sang máy GPU riêng chỉ là đổi
giá trị `.env`, không sửa code.

## 9. Deploy

- Console scripts trong `pyproject.toml`: `noble-stt-service`, `noble-tts-service`
  (kèm `python -m noble_agent.voice.service.stt_server` / `tts_server`).
- `docker-compose.deploy.yml`: thêm 2 service `santa-stt` (CPU) + `santa-tts` (GPU, reserve GPU)
  cạnh `agent`/`agent-lk`; `agent-lk` đặt `STT_BACKEND=remote`/`TTS_BACKEND=remote` và URL trỏ
  service nội bộ.
- Khi tách máy GPU: compose phía agent bỏ 2 service đó, chỉ trỏ `*_SERVICE_URL` sang máy GPU.

## 10. Testing & latency

- **Unit:**
  - `protocol.py` encode/decode frame.
  - `RemoteSTT`/`RemoteTTS` round-trip với một WS server in-process trên port ephemeral,
    **fake recognizer/tts** inject qua monkeypatch `_get_recognizer`/`_load_tts` (không cần
    GPU/model thật → chạy được trong `make test-unit`).
  - Server handler: cancel nhả lock; eos đóng stream; auth token chặn đúng.
- **Latency (skill latency-discipline):** loopback WS thêm ~sub-ms→low-ms; giữ streaming
  frame-by-frame để TTFA không đổi. Chạy `scripts/benchmark_latency.py` trước/sau để chứng minh
  không hồi quy. Lưu ý queueing TTS dưới tải đồng thời (đánh đổi đã chọn ở §3).
- **Smoke (`src/noble_agent/SMOKE.md`):** chạy sau khi đụng turn loop / transport boundary.

## 11. Nâng cấp tương lai (không làm v1)

- Pool K bản model TTS: server giữ K instance + K lock, round-robin request. Protocol §5
  không đổi → client không cần sửa.
- Reconnect tự động phía client khi WS rớt giữa phiên.
- Đưa VAD/FlatStore ra service chung nếu sau này cũng thành nút thắt.
