# Audio Pipeline — mic → VAD → STT → LLM → TTS → speaker

Seam này là **luồng audio full-duplex** của Noble Voice Agent: từ lúc mic của khách gửi PCM vào cho tới lúc giọng Luna phát ra loa, và ngược lại (khách nói chen ngang → cắt agent). Toàn bộ điều phối nằm trong `BaseSession` — lớp **transport-agnostic** dùng chung cho cả hai transport có audio: aiortc (browser WebRTC) và LiveKit RTC. Transport chỉ bơm vào một `audio_input` (async iterator PCM16) + một `audio_output` sink; mọi thứ còn lại (VAD, STT feed, gate, speaker verify, gọi `VoiceAgent`, interrupt, idle timer) là của `BaseSession`.

Lưu ý phạm vi: **speaker verification / floor control chỉ chạy trong `base_session`** (aiortc + livekit). Đường **telephony không dùng** các cơ chế speaker này. Resample (48↔16 kHz phía mic, 24↔48 kHz phía loa, μ-law/G.711 phía telephony) do lớp transport lo trước khi frame chạm `BaseSession`; seam này làm việc trên PCM16 16 kHz ở đầu vào và PCM16 `tts_sample_rate` ở đầu ra.

```
                         ┌──────────────────────── BaseSession ────────────────────────┐
   mic (khách)           │                                                              │
   PCM16 48kHz           │  process_audio_frame():                                      │
      │  (transport      │   ┌── VAD (Silero) ──┐   ┌── STT input gate ──┐              │
      │   resample 48→16)│   │ state machine    │   │ off / rms / vad    │              │
      ▼                  │   │ + interrupt      │   │ + pre-roll         │              │
  audio_input ──────────►│──►│ detect           │──►│ + keepalive silence│──► stt.send  │
  (async iter PCM16)     │   └──────────────────┘   └────────────────────┘      │       │
                         │        │ INTERRUPTED           SpeakerTracker.feed()   ▼       │
                         │        ▼                       (chunk → embed →   Streaming  │
                         │   _handle_interrupt /           _on_speaker_verdict) STT      │
                         │   (có tracker: chỉ                                  │on_final │
                         │    vad.set_speaking())                              ▼         │
                         │                                          (opt) Smart Turn     │
                         │                                          endpoint gate        │
                         │                                               │               │
                         │                                               ▼               │
                         │                            _trigger_agent_for_text → _run_agent│
                         │                                               │               │
                         │                                               ▼               │
                         │              VoiceAgent.handle_utterance:                      │
                         │              LLM stream ─► SentenceBuffer ─► TTS               │
                         │              (llm_producer)   (clause)   (_synth_ahead/_pacer) │
                         │                                               │ PCM frames     │
   speaker (khách) ◄─────│◄──────────────────────────────────────── _send_agent_audio    │
   PCM16 48kHz           │  (transport resample 24→48)                                   │
                         └──────────────────────────────────────────────────────────────┘
```

## Giải thích từng bước

### 1. Transport bơm frame vào — điểm vào duy nhất

Transport gọi `start_pipeline(audio_input, audio_output, event_sink)`; vòng lặp `async for frame in audio_input` đẩy từng frame vào `process_audio_frame`, dừng khi stream hết hoặc `stop()` được gọi. Đây là chỗ duy nhất audio caller chạm vào pipeline. Xem [base_session.py:300](src/noble_agent/server/base_session.py#L300) và vòng lặp tại [base_session.py:311](src/noble_agent/server/base_session.py#L311).

### 2. VAD chạy TRƯỚC — dồn frame thành chunk 32ms và chạy state machine

`process_audio_frame` gom byte vào `_vad_buf` rồi cắt thành các chunk cố định `VAD_CHUNK_BYTES` (32ms @ 16kHz), đưa từng chunk qua `self.vad.process_chunk`. **VAD phải chạy trước STT gate** vì kết quả VAD vừa dùng để phát hiện interrupt vừa nuôi cờ cho gate ở mode `vad`. Xem [base_session.py:410](src/noble_agent/server/base_session.py#L410) (docstring nói rõ "VAD first") và vòng cắt chunk [base_session.py:414](src/noble_agent/server/base_session.py#L414).

`SileroVAD` là wrapper quanh model Silero (wheel `silero-vad==6.2.1`, nạp 1 lần/process rồi `deepcopy` per phiên — xem `_load_shared_model`) + state machine 3 trạng thái `IDLE → SPEAKING → INTERRUPTED`: chỉ quyết barge-in, endpoint câu nói là việc của STT; `INTERRUPTED` latch tới khi `set_speaking()`/`set_idle()`. `process_chunk` trả `is_speech`/`state`; ngưỡng nói là `vad_threshold`. Khi agent đang phát (`SPEAKING`) mà nghe đủ `INTERRUPT_CONFIRM_CHUNKS` chunk liên tiếp có tiếng → chuyển sang `INTERRUPTED`; nếu audio agent **thật sự đang phát** (`playback_active`, session bật ở chunk TTS đầu tiên, `set_idle()` tắt) thì mỗi chunk còn phải vượt sàn `BARGE_IN_RMS_THRESHOLD` (RMS int16, lọc echo residual; 0 = tắt; log INFO một lần/lượt khi chặn) — trước khi audio phát không có echo nên không áp sàn. Xem [silero.py:73](src/noble_agent/voice/vad/silero.py#L73), logic interrupt [silero.py:114](src/noble_agent/voice/vad/silero.py#L114) và sàn RMS [silero.py:125](src/noble_agent/voice/vad/silero.py#L125).

### 3. Nuôi cờ VAD-gate + phát hiện interrupt

Ngay trong vòng chunk: nếu gate ở mode `vad`, mỗi quyết định `is_speech` được đẩy vào `_input_gate.feed_vad` [base_session.py:567](src/noble_agent/server/base_session.py#L567). Nếu state là `INTERRUPTED` [base_session.py:584](src/noble_agent/server/base_session.py#L584): **có `SpeakerTracker` (mode `single`/`multi`) thì VAD KHÔNG tự quyết** — chỉ `vad.set_speaking()` để máy trạng thái sống tiếp, còn pause/interrupt do verdict per-chunk của tracker quyết qua `_on_speaker_verdict` (bước 9) [base_session.py:588](src/noble_agent/server/base_session.py#L588); không có tracker mà bật addressee gate → `_begin_addressee_episode`; không cả hai → `_handle_interrupt` ngay.

### 4. STT input gate — off / rms / vad + pre-roll + keepalive silence

Sau VAD, mỗi frame gốc đi qua `self._input_gate.gate(data)` để quyết định có forward tới STT không. `SttInputGate` có 3 mode: `off` (passthrough), `rms` (ngưỡng năng lượng qua `ConsecutiveFramesGate`), `vad` (dùng cờ Silero + hangover). Ở cạnh lên (đóng→mở) gate xả các chunk `pre-roll` đã giữ lại để không cắt cụt đầu câu. Xem `gate()` tại [stt_input_gate.py:69](src/noble_agent/voice/stt_input_gate.py#L69) và mode-select [stt_input_gate.py:61](src/noble_agent/voice/stt_input_gate.py#L61).

Khi gate **đóng nhưng còn utterance đang chờ**, `keepalive(len)` trả về frame silence (zeros) để bơm vào STT, giúp endpoint trailing-silence của recognizer vẫn fire — silence này đi thẳng tới `stt.send`, **không** chạm `SpeakerTracker`. Xem chỗ gọi keepalive [base_session.py:602](src/noble_agent/server/base_session.py#L602) và định nghĩa [stt_input_gate.py:86](src/noble_agent/voice/stt_input_gate.py#L86). Chỉ frame thật mới vào vòng forward: chunk STT đầu tiên của utterance mở `tracker.begin_utterance()` [base_session.py:609](src/noble_agent/server/base_session.py#L609), mọi chunk sau đó `tracker.feed(chunk)` [base_session.py:611](src/noble_agent/server/base_session.py#L611) rồi `await self.stt.send(chunk)` [base_session.py:617](src/noble_agent/server/base_session.py#L617).

### 5. Streaming STT — backend cắm-được, callback on_partial/on_final

`self.stt` là một backend cài `STTBase` (interface `start`/`send`/`stop` + callback `on_partial`/`on_final`) — xem contract [base.py:10](src/noble_agent/voice/stt/base.py#L10). Các backend hiện có: `soniox` / `sherpa` / `elevenlabs` / `qwen3asr` / `remote` (client WS tới service thường trú). `send()` là chỗ frame PCM chảy vào; khi recognizer chốt câu nó gọi `_on_final`. Xem callback partial [base_session.py:528](src/noble_agent/server/base_session.py#L528) và final [base_session.py:531](src/noble_agent/server/base_session.py#L531).

### 6. Init-time fallback chain của STT (remote → soniox → sherpa)

STT được dựng trong `start()` qua `_init_stt`: build backend theo `resolve_order(settings.stt_backend, STT_FALLBACK_CHAIN)` — backend cấu hình luôn là head, phần còn lại của chain theo sau. `_start_first_available` build + `start()` từng cái, cái đầu tiên `start()` không raise sẽ phục vụ cả session; chain cạn → `stt=None` + phát event `error` đúng một lần. Xem `_init_stt` [base_session.py:209](src/noble_agent/server/base_session.py#L209), thứ tự chain [fallback.py:26](src/noble_agent/voice/fallback.py#L26), `resolve_order` [fallback.py:30](src/noble_agent/voice/fallback.py#L30), vòng thử [fallback.py:59](src/noble_agent/voice/fallback.py#L59).

### 7. on_final — lọc, verify speaker, rồi (tùy chọn) Smart Turn

`_on_final` reset idle timer, dừng keepalive (`notify_final`), ghi latency STT, rồi chạy loạt guard: `WhisperHallucinationFilter`, `EchoCooldown`. Sau đó `SpeakerTracker.finalize()` quyết định drop theo majority-drop trên chuỗi nhãn per-chunk, cả hai mode single/multi (bước 9). Xem [base_session.py:531](src/noble_agent/server/base_session.py#L531), khối speaker ở `_on_final` [base_session.py:822](src/noble_agent/server/base_session.py#L822).

Nếu bật Smart Turn (`smart_turn_enabled`), transcript chưa đi thẳng tới LLM: lấy 8s audio gần nhất từ `_audio_ring`, chạy `_smart_turn.predict`; prob dưới ngưỡng `smart_turn_threshold` → treo text vào `_pending_finals` + hẹn `_reset_hold_timer` (chờ khách nói tiếp), đủ ngưỡng → nối các pending lại rồi tiếp tục. Xem khối Smart Turn [base_session.py:578](src/noble_agent/server/base_session.py#L578). Detector là ONNX singleton, cắt/pad về đúng 8s trước inference — xem [smart_turn.py:55](src/noble_agent/voice/turn_detection/smart_turn.py#L55).

### 8. Kích hoạt agent turn — cắt turn cũ nếu còn chạy

`_trigger_agent_for_text` là ranh giới: nếu còn `_agent_task` đang chạy thì cancel nó (interrupt + clear audio output), rồi tạo task mới `asyncio.ensure_future(self._run_agent(text))`. `_run_agent` clear residual audio, `vad.set_speaking()` (vũ trang phát hiện barge-in), bật echo cooldown, gọi `self.agent.handle_utterance(text)`. Xem [base_session.py:596](src/noble_agent/server/base_session.py#L596) và `_run_agent` [base_session.py:793](src/noble_agent/server/base_session.py#L793).

### 9. SpeakerTracker (single + multi) + deferred barge-in

`SpeakerTracker` (`voice/speaker_tracker.py`) chạy **song song** với STT, cắt audio đã qua input gate thành chunk rời nhau và gắn nhãn từng chunk — không còn "episode" 0.8s chờ rồi mới quyết định. `process_audio_frame` gọi `begin_utterance()` tại chunk STT đầu tiên [base_session.py:609](src/noble_agent/server/base_session.py#L609) rồi `feed(chunk)` mỗi frame đã qua gate [base_session.py:611](src/noble_agent/server/base_session.py#L611). Nhịp cắt thích ứng: 0.8s (`speaker_interrupt_min_sec`) khi utterance chưa gặp chunk `speaker`, chuyển sang `SPV_CHUNK_SEC` (2.0s) ngay sau chunk `speaker` đầu tiên — xem `feed` [speaker_tracker.py:134](src/noble_agent/voice/speaker_tracker.py#L134). Tại mỗi điểm cắt: embed off-loop → so với `CentroidSet.match()` (max cosine ≥ `speaker_match_threshold`) [speaker_tracker.py:59](src/noble_agent/voice/speaker_tracker.py#L59) → callback `_on_speaker_verdict` [base_session.py:671](src/noble_agent/server/base_session.py#L671): verdict `speaker` khi agent đang nói → addressee gate bật thì soft-pause [base_session.py:721](src/noble_agent/server/base_session.py#L721), gate tắt thì `_handle_interrupt` ngay — không đợi buffer 0.8s hay final; verdict `non-speaker` khi agent đang nói → `vad.set_speaking()`, agent nói tiếp.

`_on_final` gọi `tracker.finalize()` để lấy chuỗi nhãn cả utterance (kèm đuôi ≥0.3s chưa cắt) [base_session.py:823](src/noble_agent/server/base_session.py#L823), rồi áp **majority-drop**: đa số chunk `non-speaker` → drop, hoà/rỗng → giữ (fail-open); phạm vi enforce là mọi final ở mode `single`, chỉ mid-turn (agent đang nói hoặc đang pause) ở mode `multi` [base_session.py:837](src/noble_agent/server/base_session.py#L837). Nhãn được gửi kèm event `final_transcript` (`speaker_labels`) — similarity chỉ ghi log server (đọc từ `tracker.final_sims`, ảnh chụp lúc finalize), không nằm trên event [base_session.py:834](src/noble_agent/server/base_session.py#L834). Vòng đời centroid khác nhau giữa hai mode: `multi` reset + enroll lại mỗi turn mới ở `_trigger_agent_for_text` [base_session.py:988](src/noble_agent/server/base_session.py#L988) và reset lần nữa khi turn kết thúc tự nhiên ở `_run_agent` finally [base_session.py:1140](src/noble_agent/server/base_session.py#L1140); `single` chỉ enroll một lần lúc tập centroid còn rỗng (utterance đầu phiên) rồi bồi đắp qua enroll-on-match, không bao giờ reset [base_session.py:990](src/noble_agent/server/base_session.py#L990). `CentroidSet`/`SpeakerTracker` là logic vector thuần, không đụng model — xem class [speaker_tracker.py:34](src/noble_agent/voice/speaker_tracker.py#L34) và [speaker_tracker.py:69](src/noble_agent/voice/speaker_tracker.py#L69). Embed vẫn qua `SpeakerEmbedder` (giữ nguyên trong `speaker_verifier.py`), off-loop qua `asyncio.to_thread`, remote-default hoặc sherpa CAM++ local.

### 10. VoiceAgent: LLM stream → SentenceBuffer → TTS

`VoiceAgent.handle_utterance` chạy hai coroutine song song bằng `asyncio.gather`: `llm_producer` (nguồn) và `_pacer` (đích). Xem [voice_agent.py:333](src/noble_agent/voice/voice_agent.py#L333) và `gather` [voice_agent.py:672](src/noble_agent/voice/voice_agent.py#L672).

`llm_producer` gọi `self._llm.stream_response(...)`; mỗi token vào callback `on_token`, được đẩy qua `buf.add(token)` (SentenceBuffer) và các clause hoàn chỉnh rơi vào `tts_queue`. Xem [voice_agent.py:382](src/noble_agent/voice/voice_agent.py#L382), `on_token` [voice_agent.py:385](src/noble_agent/voice/voice_agent.py#L385).

`SentenceBuffer` cắt stream token thành clause/sentence: mode `sentence` chỉ tách ở `.!?`, mode `clause` tách thêm ở `,;–` khi clause đủ dài — có xử lý viết tắt (`Dr.`, `TP.`, `tỷ.`…) và số thập phân (`7.200`) để không tách nhầm. Xem `add` [sentence_buffer.py:102](src/noble_agent/voice/sentence_buffer.py#L102) và `_find_boundary` [sentence_buffer.py:131](src/noble_agent/voice/sentence_buffer.py#L131).

### 11. Prefetch clause — _synth_ahead (nguồn) + _pacer (đích)

Để không bị khựng ở mỗi ranh giới clause (mỗi clause là một lần synth riêng, ~300ms TTFB), TTS được tách nguồn↔đích. `_synth_ahead` kéo `SentenceChunk` theo thứ tự, synth clause N+1 **trong khi** pacer đang phát clause N; look-ahead depth 1 vì `ready_queue = asyncio.Queue(maxsize=1)` (tối đa 2 clause được buffer). Mỗi clause được synth qua `_iter_clause_audio` (pcm_data passthrough cho bridge-phrase, hoặc live `self._tts.stream()`). Xem `_synth_ahead` [voice_agent.py:506](src/noble_agent/voice/voice_agent.py#L506), `ready_queue` [voice_agent.py:503](src/noble_agent/voice/voice_agent.py#L503), `_iter_clause_audio` [voice_agent.py:307](src/noble_agent/voice/voice_agent.py#L307).

`_pacer` lấy từng clause đã sẵn sàng, gửi event `agent_speaking`, đo `e2e.ttfa` ở frame đầu, rồi `await self._send_audio(chunk)` — backpressure của `capture_frame` giữ nhịp realtime. Xem `_pacer` [voice_agent.py:552](src/noble_agent/voice/voice_agent.py#L552) và chỗ gửi audio [voice_agent.py:635](src/noble_agent/voice/voice_agent.py#L635). `_send_audio` chính là `BaseSession._send_agent_audio` → `audio_output.send` (transport resample 24→48 rồi ra loa) — xem [base_session.py:182](src/noble_agent/server/base_session.py#L182).

### 12. Init-time fallback chain của TTS (remote → elevenlabs → vieneu)

`VoiceAgent._create_tts` build TTS theo `resolve_order(settings.tts_backend, TTS_FALLBACK_CHAIN)`; builder đầu tiên construct không raise sẽ thắng (vieneu load model eager lúc construct nên lỗi load bị bắt tại đây). Backend lạ (ngoài chain) map về vieneu; tất cả fail → re-raise exception cuối (TTS bắt buộc phải có, không im lặng None). Xem `_create_tts` [voice_agent.py:161](src/noble_agent/voice/voice_agent.py#L161) và chain [fallback.py:27](src/noble_agent/voice/fallback.py#L27).

### 13. Barge-in / interrupt — cắt agent đang nói

`_handle_interrupt` theo đúng thứ tự: `agent.pause_tts()` (dừng sản xuất TTS tại nguồn) → cancel `_agent_task` → `audio_output.clear()` (bỏ audio đã buffer để khách nín nghe ngay) → `vad.set_idle()`. Xem [base_session.py:466](src/noble_agent/server/base_session.py#L466). `pause_tts` set cờ `_interrupted` để vòng `_synth_ahead`/`_pacer` thoát ở lần lặp kế, và gọi hook `pause()` của TTS backend (đóng WS remote) — xem [voice_agent.py:231](src/noble_agent/voice/voice_agent.py#L231). Trong pacer, khi thấy `_interrupted` nó gửi `agent_interrupted` và `_drain_and_cancel_synth()` để cancel task synth-ahead không deadlock — xem [voice_agent.py:557](src/noble_agent/voice/voice_agent.py#L557).

## Invariant / lưu ý PHẢI giữ

- **VAD chạy trước STT gate.** Trong `process_audio_frame`, vòng VAD (nuôi cờ vad-gate + phát hiện interrupt) chạy xong rồi mới tới `_input_gate.gate()`. Đảo thứ tự sẽ làm mode `vad` mất cờ và interrupt trễ. Xem [base_session.py:410](src/noble_agent/server/base_session.py#L410).

- **Fallback chỉ ở init-time, KHÔNG mid-session.** Fallback chain chỉ trigger khi backend construct/start lỗi lúc khởi tạo; một backend lên healthy rồi chết giữa call KHÔNG kích hoạt fallback. Xem docstring [fallback.py:9](src/noble_agent/voice/fallback.py#L9).

- **on_done / agent_done luôn fire.** `_pacer` gửi `agent_done` trong nhánh cuối kể cả khi bị interrupt; `_run_agent` chạy `finally` (echo cooldown done, `vad.set_idle()`, `clear_asker()`, arm idle timer) dù thành công/exception/cancel. Xem `agent_done` [voice_agent.py:670](src/noble_agent/voice/voice_agent.py#L670) và `_run_agent` finally [base_session.py:805](src/noble_agent/server/base_session.py#L805).

- **In-order playback + look-ahead depth 1.** `ready_queue` bounded `maxsize=1` nên tối đa 2 clause buffer (1 đang phát, 1 sẵn sàng); pacer luôn gửi frame theo đúng thứ tự clause. `_last_completed_id` chỉ cập nhật khi clause phát trọn (không interrupt giữa chừng). Xem [voice_agent.py:503](src/noble_agent/voice/voice_agent.py#L503) và [voice_agent.py:637](src/noble_agent/voice/voice_agent.py#L637).

- **PCM per-utterance nằm TRONG `SpeakerTracker`, anchored per-utterance.** `BaseSession` không còn giữ buffer audio cho speaker: `begin_utterance()` (chunk thật đầu tiên, `_stt_audio_start == 0.0`) rebind `_utt_pcm` rỗng, mỗi `feed(chunk)` extend nó, cap theo `utt_cap_sec`; keepalive silence không đi qua `feed`. Nhờ vậy embed đúng span vừa nói, tránh trailing silence / echo / đuôi speaker trước. Xem `feed` [speaker_tracker.py:145](src/noble_agent/voice/speaker_tracker.py#L145) và cap [speaker_tracker.py:148](src/noble_agent/voice/speaker_tracker.py#L148).

- **Enrollment dùng ảnh chụp lúc `finalize()`, không phải buffer live.** Giữa `finalize()` và enrollment (`_trigger_agent_for_text`) có nhiều await — drain embed inflight, embed đuôi, `classify()` của addressee gate — nên một chunk đã qua gate của giọng KHÁC có thể gọi `begin_utterance()` xen vào và xoá `_utt_pcm`. `finalize()` vì thế chụp đồng bộ cả PCM lẫn list sims ngay ở đầu hàm; `enroll_from_utterance()` tiêu ảnh chụp đó (một lần) rồi mới rơi về buffer live. Xem snapshot trong `finalize` [speaker_tracker.py:218](src/noble_agent/voice/speaker_tracker.py#L218) và `enroll_from_utterance` [speaker_tracker.py:261](src/noble_agent/voice/speaker_tracker.py#L261).

- **STT gate keepalive silence để endpoint fire.** Khi gate đóng mà còn utterance pending, bơm silence (zeros) vào STT để endpoint trailing-silence của recognizer vẫn fire — nếu không, mode `rms`/`vad` sẽ nuốt đúng khoảng lặng mà recognizer cần và final không bao giờ được phát. `_on_final` gọi `notify_final()` để dừng keepalive. Xem [stt_input_gate.py:86](src/noble_agent/voice/stt_input_gate.py#L86), chỗ gọi [base_session.py:434](src/noble_agent/server/base_session.py#L434), notify_final [base_session.py:533](src/noble_agent/server/base_session.py#L533).
