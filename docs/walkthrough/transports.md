# Transports — 4 lối vào cùng hội tụ về NobleAgent

Noble Voice Agent có **4 transport** (Browser WebRTC, Text chat, Telephony, LiveKit RTC). Điểm mấu chốt cho kỹ sư mới: **mọi transport cuối cùng đều gọi cùng một hàm — `NobleAgent.stream_response`** ([facade.py:343](src/noble_agent/agent/facade.py#L343)). Cái *khác nhau* giữa chúng chỉ là **codec audio + cách vào/ra I/O** (Opus 48 kHz, PCM16, G.711 8 kHz, μ-law…), còn "bộ não" (system prompt + tool + RAG + lịch sử Redis) là **một**.

Vì vậy khi sửa logic hội thoại bạn chỉ sửa ở agent core; khi sửa audio/kết nối bạn sửa ở lớp transport. Hai mối quan tâm này được tách sạch.

## Sơ đồ hội tụ

```
  Browser WebRTC ─┐   (Opus 48k → 16k → VAD → STT)
  Text chat /chat ─┤   (text thuần, không audio)
  Telephony PSTN ──┤   (G.711 8k ↔ 16k/24k)      ──►  VoiceAgent / run_text_turn
  LiveKit RTC ─────┘   (μ-law ↔ PCM16)                        │
                                                              ▼
                                              NobleAgent.stream_response  (facade.py:343)
                                                              │
                                                              ▼
                                              TurnRunner.handle_turn  →  agent core
                                              (system prompt + tools + RAG + Redis state)
```

Voice (WebRTC / Telephony / LiveKit) đi qua `VoiceAgent`, và `VoiceAgent._llm` **chính là** `NobleAgent` — tạo ở [voice_agent.py:158](src/noble_agent/voice/voice_agent.py#L158), gọi vào core ở [voice_agent.py:476](src/noble_agent/voice/voice_agent.py#L476). Text chat cầm thẳng `NobleAgent` và gọi ở [text_chat.py:156](src/noble_agent/server/text_chat.py#L156).

## Điểm phân nhánh khởi động

CLI `noble-agent` chạy `main()` ([__main__.py:55](src/noble_agent/__main__.py#L55)). Hai cổng gác:

1. **`USE_UNIFIED_AGENT` phải = true** — nếu không sẽ `SystemExit` ([__main__.py:63](src/noble_agent/__main__.py#L63)). Legacy multi-agent đã bị gỡ.
2. **Route theo `TRANSPORT_BACKEND`** ([__main__.py:73](src/noble_agent/__main__.py#L73)):
   - `livekit` → `run_worker()` ([__main__.py:74](src/noble_agent/__main__.py#L74)) — chạy LiveKit worker, **đăng ký OUTBOUND lên livekit-server, KHÔNG mở public listener**.
   - còn lại (mặc định `aiortc`) → `run_server()` ([__main__.py:78](src/noble_agent/__main__.py#L78)) — mở WebSocket server bind `ws_port`.

Cờ `--transport=livekit|aiortc` được ép vào env `TRANSPORT_BACKEND` trước khi config đọc ([__main__.py:18](src/noble_agent/__main__.py#L18)).

`run_server()` ([http.py:966](src/noble_agent/server/http.py#L966)) → `_run_server_async()` ([http.py:973](src/noble_agent/server/http.py#L973)): init storage, Phoenix tracing, **prewarm voice models**, reconcile Qdrant, warm project registry, rồi `websockets.serve(handler, ws_host, ws_port, ...)` ([http.py:1017](src/noble_agent/server/http.py#L1017)).

---

## 1. Browser WebRTC

- **Luồng:** trình duyệt mở WebSocket → `handler` ([ws_handler.py:60](src/noble_agent/server/ws_handler.py#L60)) → `_handle_session` ([ws_handler.py:74](src/noble_agent/server/ws_handler.py#L74)) tạo `Session` ([ws_handler.py:93](src/noble_agent/server/ws_handler.py#L93)). WebSocket chỉ dùng cho signaling (SDP + JSON control); audio đi qua aiortc `RTCPeerConnection`.
- **Codec/resample:** Opus 48 kHz (từ browser) → resample 48→16 kHz → VAD → STT; TTS 24 kHz → 48 kHz → Opus trả về. Track ra là `ServerAudioTrack`.
- **Session class:** `Session(BaseSession)` ([session.py:68](src/noble_agent/server/session.py#L68)); tạo `RTCPeerConnection` + track ([session.py:77](src/noble_agent/server/session.py#L77)). SDP offer/answer qua `negotiate()` ([session.py:150](src/noble_agent/server/session.py#L150)), kích hoạt khi client gửi `rtc_offer` ([ws_handler.py:129](src/noble_agent/server/ws_handler.py#L129)). Audio vào qua `handle_audio` → hàng đợi → `BaseSession.start_pipeline` ([session.py:105](src/noble_agent/server/session.py#L105)).
- **Điểm gọi agent core:** `BaseSession` tạo `self.agent = VoiceAgent(...)` ([base_session.py:95](src/noble_agent/server/base_session.py#L95)); pipeline gọi `agent.handle_utterance(text)` ([base_session.py:799](src/noble_agent/server/base_session.py#L799)) và lời chào `agent.greet` ([base_session.py:784](src/noble_agent/server/base_session.py#L784)). Bên trong `VoiceAgent` gọi `NobleAgent.stream_response` ([voice_agent.py:476](src/noble_agent/voice/voice_agent.py#L476)).

## 2. Text chat tester (`/chat`)

- **Luồng:** cùng WebSocket server; `handler` nhận diện path `/chat` qua `is_chat_path` ([text_chat.py:32](src/noble_agent/server/text_chat.py#L32)) tại [ws_handler.py:89](src/noble_agent/server/ws_handler.py#L89) và rẽ sang `handle_text_session` ([text_chat.py:210](src/noble_agent/server/text_chat.py#L210)) — **bỏ qua hoàn toàn STT/TTS/RTC**. Trang tĩnh `chat.html` phục vụ ở [http.py:929](src/noble_agent/server/http.py#L929). Mỗi tab = một `session_id` (resume qua `?session=`).
- **Codec/resample:** không có audio (text thuần). Có tuỳ chọn TTS thử nghiệm: token → `SentenceBuffer` → synth từng câu → PCM16 binary frame ([text_chat.py:127](src/noble_agent/server/text_chat.py#L127)), dùng đúng factory `VoiceAgent._create_tts`.
- **Session class:** không có class riêng; `handle_text_session` giữ vòng lặp message + một `NobleAgent` cho mỗi kết nối.
- **Điểm gọi agent core:** `_create_llm` → `NobleAgent.create` ([text_chat.py:43](src/noble_agent/server/text_chat.py#L43)); mỗi lượt `run_text_turn` ([text_chat.py:48](src/noble_agent/server/text_chat.py#L48)) gọi thẳng `llm.stream_response(...)` ([text_chat.py:156](src/noble_agent/server/text_chat.py#L156)). Vì cùng facade nên text chat "nói" đúng persona/tool/RAG như voice — đây là lý do nó là tester đáng tin.

## 3. Telephony (PSTN qua Asterisk)

- **Luồng:** khách gọi hotline → FreePBX inbound → Asterisk ARI (`StasisStart`) bắt số gọi đến, rồi dialplan vào `AudioSocket(...)`. `TelephonyManager` ([session.py:589](src/noble_agent/telephony/session.py#L589)) chạy `AudioSocketServer` (TCP) + `ARIClient` ([session.py:628](src/noble_agent/telephony/session.py#L628)); mỗi cuộc gọi = một `TelephonySession` ([session.py:115](src/noble_agent/telephony/session.py#L115)), `session_id = tel-{call_id}`.
- **Codec/resample:** AudioSocket TCP mang G.711/slin **8 kHz**. Vào: `resample_8k_to_16k` cho STT/VAD ([session.py:321](src/noble_agent/telephony/session.py#L321)). Ra: TTS 24 kHz → `resample_tts_to_8k`, cắt frame 320 byte (20 ms), pace ~18 ms ([session.py:382](src/noble_agent/telephony/session.py#L382)). Có silence-keepalive để Asterisk không rớt kết nối ([session.py:355](src/noble_agent/telephony/session.py#L355)).
- **Session class:** `TelephonySession` — **KHÔNG** kế thừa `BaseSession`; nó tự dựng pipeline (VAD/STT/`VoiceAgent`) và tạo `VoiceAgent` ở [session.py:141](src/noble_agent/telephony/session.py#L141).
- **Điểm gọi agent core:** STT final → `_trigger_agent` → `_run_agent` → `agent.handle_utterance(text)` ([session.py:448](src/noble_agent/telephony/session.py#L448)) → `NobleAgent.stream_response`. Số điện thoại người gọi được seed profile từ Mongo trước `agent.start()`.

## 4. LiveKit RTC (SIP/PSTN qua LiveKit rooms)

- **Luồng:** worker do framework `livekit.agents` điều phối. `run_worker` ([worker.py:210](src/noble_agent/transport/livekit/worker.py#L210)) gọi `agents.cli.run_app(WorkerOptions(...))` ([worker.py:220](src/noble_agent/transport/livekit/worker.py#L220)) — đăng ký lên `livekit_url`, **không bind cổng public** (chỉ có internal health port). Mỗi job: `entrypoint` ([worker.py:164](src/noble_agent/transport/livekit/worker.py#L164)) chờ caller rồi tạo `RoomSession` ([worker.py:197](src/noble_agent/transport/livekit/worker.py#L197)).
- **Codec/resample:** μ-law ↔ PCM16 qua `AgentAudioIO` + `codec_utils`. Cấu hình sample rate độc lập: input = `stt_sample_rate` (16 kHz), output = `tts_sample_rate` (24 kHz) ([worker.py:192](src/noble_agent/transport/livekit/worker.py#L192)).
- **Session class:** `RoomSession(BaseSession)` ([room_session.py:40](src/noble_agent/transport/livekit/room_session.py#L40)); chờ audio track của caller, bọc `AgentAudioIO`, đưa iterator + AudioOutput vào `start_pipeline` ([room_session.py:107](src/noble_agent/transport/livekit/room_session.py#L107)). Event pipeline (transcript/tool/metrics) đẩy qua data channel cho `static/livekit.html`.
- **Điểm gọi agent core:** giống Browser WebRTC — dùng chung `BaseSession` nên `self.agent = VoiceAgent` ([base_session.py:95](src/noble_agent/server/base_session.py#L95)) → `agent.handle_utterance` ([base_session.py:799](src/noble_agent/server/base_session.py#L799)) → `NobleAgent.stream_response`. Lời chào tự động chạy như `_agent_task` để caller có thể ngắt lời ([room_session.py:127](src/noble_agent/transport/livekit/room_session.py#L127)).

---

## Lưu ý PHẢI giữ

- **aiortc bind `ws_port`, LiveKit thì KHÔNG.** `run_server` mở `websockets.serve(..., ws_port, ...)` ([http.py:1017](src/noble_agent/server/http.py#L1017)); LiveKit worker chỉ đăng ký outbound lên `livekit_url` qua `WorkerOptions` ([worker.py:220](src/noble_agent/transport/livekit/worker.py#L220)) và không có public listener. Đây là lý do route ở [__main__.py:73](src/noble_agent/__main__.py#L73) tồn tại: nếu cả hai cùng chạy `run_server` thì container `agent-lk` sẽ tranh `ws_port` với `agent` dưới `network_mode: host`.
- **Telephony KHÔNG có speaker verify (và không kế thừa `BaseSession`).** Speaker policy chỉ nằm trong `BaseSession` (aiortc + LiveKit). `TelephonySession` tự dựng pipeline riêng ([session.py:115](src/noble_agent/telephony/session.py#L115)) nên mọi tính năng chỉ có ở `BaseSession` (speaker floor, STT input gate…) đều không áp cho điện thoại.
- **Prewarm khác nhau giữa 2 transport.** aiortc prewarm một lần lúc boot trong `_run_server_async` ([http.py:1004](src/noble_agent/server/http.py#L1004)) — chạy trên serving loop bằng `await`. LiveKit prewarm **mỗi job-subprocess** trong `_prewarm` ([worker.py:69](src/noble_agent/transport/livekit/worker.py#L69)) — chạy trên loop tạm bằng `asyncio.run`, nên **phải `close_mongo()` sau khi warm** ([worker.py:141](src/noble_agent/transport/livekit/worker.py#L141)) để không để lại motor client bám vào loop đã đóng (nếu quên → "Event loop is closed" ở mọi query Mongo live sau đó).
