# Addressee Gate — chống "nói leo" trên đường voice

**Date:** 2026-08-12 · **Branch:** feat/share-agent · **Status:** approved by user

## Vấn đề

Interrupt hiện tại thuần năng lượng VAD: agent đang nói mà mic có tiếng người là
`_handle_interrupt()` cancel ngay ([base_session.py:454](../../../src/noble_agent/server/base_session.py)),
và MỌI final trong lúc agent nói đều trở thành turn mới (`_trigger_agent_for_text`).
Hệ quả: khách quay sang nói chuyện với người bên cạnh (side-talk) → agent tự ngắt
mình và trả lời luôn cuộc trò chuyện đó. Tắt interrupt thì agent nói không ngắt được.

Speaker verification / SpeakerFloor hiện có chỉ lọc **người khác** nói; không giải
được ca **chính khách** (cùng giọng) nói với người khác. Bài toán thật là
**addressee detection**: câu này nói với agent hay không — cần gate ở CẢ HAI chỗ:
lúc ngắt TTS và lúc nhận final.

## Hành vi đích

```
Agent đang nói + VAD thấy speech
  ├─ speech < ADDRESSEE_MIN_SPEECH_MS → bỏ qua (ho, "ừ", "dạ", tiếng động) — agent nói tiếp
  ├─ speech kéo dài → SOFT-PAUSE: pacer ngừng gửi frame + clear audio buffer transport
  │   (KHÔNG cancel agent task, KHÔNG hủy synth pipeline)
  ├─ chờ STT partial/final đầu tiên → classifier addressee:
  │   ├─ DIRECTED  → commit interrupt (cancel như _handle_interrupt cũ), xử lý câu mới
  │   └─ SIDE_TALK → resume: phát ACK "Em xin phép được nói tiếp ạ" trước, rồi phát lại
  │       TỪ ĐẦU clause đang dở; final bị drop, không vào history
  └─ classifier lỗi / quá ADDRESSEE_LLM_TIMEOUT_MS → mặc định DIRECTED
      (fail-open: thà ngắt oan còn hơn làm agent "điếc")

Agent KHÔNG nói + final đến → cùng classifier; SIDE_TALK → drop final.
  Gate nhánh idle bật/tắt riêng: ADDRESSEE_GATE_WHEN_IDLE (default false — rủi ro drop oan cao hơn).
```

Vì sao pause-rồi-resume không mất tự nhiên: pause chỉ xảy ra khi agent **đang nói**
và có tiếng người **kéo dài** đè lên. Khi agent im lặng gate vô hình (chỉ quyết drop
final hay không). Tiếng ngắn bị duration gate lọc — không khựng. Barge-in thật thì
pause chính là hành vi đúng. Ca duy nhất pause→resume là side-talk giữa lúc agent
nói — sale người thật cũng ngừng một nhịp ở đúng tình huống đó. Chỗ nối resume được
làm mềm bằng một câu ack xin phép (per user 2026-08-12): dùng lại đúng cơ chế
tool-ack hiện có — ưu tiên asset PCM pre-synth (thêm câu này vào
`scripts/gen_ack_assets.py`), thiếu asset thì live-TTS câu text.

## Classifier hai tầng (chọn qua env)

- **Heuristic** (0ms, 0 chi phí): backchannel VN ("ừ", "dạ", "vâng", "ok", "à"…)
  → SIDE_TALK; gọi tên agent / "em ơi" / "alo" → DIRECTED; gọi người khác
  ("anh ơi", "con ơi", tên riêng ≠ agent) → SIDE_TALK; còn lại → UNSURE.
- **LLM** (model nhỏ/nhanh, slot riêng pattern `NOBLE_SUMMARY_MODEL`): input =
  2–3 turn gần nhất + câu agent đang nói dở + transcript mới → verdict một token
  DIRECTED/SIDE_TALK. Chỉ tốn khi có barge-in (mode `llm`) hoặc khi heuristic
  UNSURE (mode `hybrid`).

Mode `off` giữ behavior hiện tại y nguyên (default an toàn khi rollout).

## Config — ghi vào `.env` khi implement

| Env | Default | Ý nghĩa |
|---|---|---|
| `ADDRESSEE_GATE_MODE` | `off` | `off` \| `heuristic` \| `llm` \| `hybrid` |
| `ADDRESSEE_MIN_SPEECH_MS` | `400` | Speech liên tục tối thiểu mới soft-pause |
| `ADDRESSEE_LLM_MODEL` | *(rỗng)* | Pin model cho verdict; rỗng → chain mặc định |
| `ADDRESSEE_LLM_TIMEOUT_MS` | `600` | Quá hạn → DIRECTED (fail-open) |
| `ADDRESSEE_GATE_WHEN_IDLE` | `false` | Áp gate cả khi agent không nói |
| `ADDRESSEE_RESUME_ACK_TEXT` | `Em xin phép được nói tiếp ạ.` | Câu ack phát trước khi resume; rỗng → resume thẳng không ack |

## Thay đổi code

| File | Thay đổi |
|---|---|
| `voice/addressee_gate.py` (mới) | Heuristic + LLM classifier — pure logic, unit-test không cần model |
| `voice/voice_agent.py` | Pacer soft-pause/resume: `asyncio.Event` `_paused`; buffer frames đã phát của clause hiện tại (bounded) để phát lại từ đầu clause; `pause_playback()` / `resume_playback()` tách khỏi `pause_tts()`; resume phát ack (pre-synth asset ưu tiên, fallback live TTS `ADDRESSEE_RESUME_ACK_TEXT`) trước khi phát lại clause |
| `server/base_session.py` | Tổng quát hóa interrupt-episode (pattern `_begin_interrupt_episode` của multi-speaker) cho mọi mode với bằng-chứng = duration + text; hook gate vào `_on_final` |
| `config.py` | 6 settings nhóm `ADDRESSEE_*` |
| `scripts/gen_ack_assets.py` | Thêm câu resume-ack vào bộ pre-synth (tùy chọn, fallback live TTS vẫn chạy) |
| `telephony/session.py` | Cùng hook, dùng chung logic base |
| `.env` | Ghi 6 biến với default như bảng trên |

Thứ tự gate trong `_on_final` (giữ nguyên các gate cũ đứng trước): hallucination
filter → echo cooldown → speaker verifier/floor → **addressee gate** → smart-turn.

## Invariants / ràng buộc

- Soft-pause KHÔNG set `_interrupted`, KHÔNG cancel `_agent_task` — llm_producer +
  synth-ahead tiếp tục chạy; chỉ pacer nín. Commit interrupt mới đi đường
  `_handle_interrupt` cũ (đủ trình tự pause_tts → cancel → clear → vad idle).
- Final bị drop vì SIDE_TALK không được ghi vào history (turn chưa từng bắt đầu).
- Speaker gate (multi mode) chạy TRƯỚC addressee gate và độc lập.
- `interrupt_mode` (`immediate`/`finish_current`) hiện có giữ nguyên semantics ở
  đường commit.
- Fail-open toàn tuyến: bất kỳ exception nào trong gate → DIRECTED + log.

## Rủi ro & test

- **Resume phát lại clause**: pacer giữ frames đã phát của clause hiện tại — bound
  vài giây; unit test pause giữa clause → resume phát lại từ frame 0.
- **Echo agent lọt mic**: echo cooldown + hallucination filter hiện có vẫn đứng
  trước gate; test không kích duration gate bằng chính giọng agent.
- **STT partial chậm (telephony)**: quá timeout → DIRECTED, tức behavior cũ.
- Unit: heuristic table-driven (backchannel/gọi tên/gọi người khác/UNSURE);
  classifier LLM stub; pacer pause/resume/commit. Integration: side-talk final bị
  drop + agent nói hết câu; barge-in thật vẫn ngắt < ngưỡng hiện tại.
- Chạy checklist `src/noble_agent/SMOKE.md` (chạm turn loop + transport).

## Amendment 2026-08-12 (chiều): context cho LLM verdict = dialogue ring trong session

Prompt LLM ban đầu chỉ có clause đang nói dở + câu user ngay trước — không đủ để phán
ca "khách trả lời câu hỏi agent vừa hỏi" vs "khách hỏi ý người nhà cùng nội dung".
User chọn phương án **ring buffer trong session** (không đọc Redis trên đường verdict):

- `BaseSession`/`TelephonySession` giữ `deque(maxlen=6)` các cặp `(role, text)`:
  user text append khi final được chấp nhận (SAU gate — final side-talk KHÔNG vào ring);
  agent text append lúc turn mới trigger (đọc `VoiceAgent.spoken_text_this_turn` của
  turn trước — interrupt giữa chừng thì ring giữ đúng phần ĐÃ phát ra loa).
- `VoiceAgent.spoken_text_this_turn`: tích lũy display-text các clause đã phát trong
  turn hiện tại (reset đầu `handle_utterance`); thay `current_clause_text` làm
  `agent_line` cho classifier — LLM thấy toàn bộ câu agent đang nói, không chỉ 1 clause.
- `classify()`/`_classify_llm` thêm `recent_dialogue: Sequence[tuple[str, str]]`;
  prompt render dạng transcript "Khách: …" / "<agent>: …", mỗi dòng cắt 200 ký tự.
  `last_user_text` giữ làm fallback khi ring rỗng. Summary text KHÔNG đưa vào (verdict
  là câu hỏi cục bộ; cap K=6 giữ prefill dưới ngân sách 600ms).
- Trade-off chấp nhận: ring không sống qua reconnect (Redis thì có) — verdict đầu sau
  reconnect nghèo context, fail-open vẫn bảo vệ; greeting không vào ring.

## Amendment 2026-08-12 (tối): ghép SPEAKER_MODE=multi + addressee gate

V1 loại trừ nhau: mode multi thì SpeakerFloor chiếm nhánh INTERRUPTED và gate không
tham gia → chính khách (asker) side-talk vẫn được honor barge-in ngay — bug "nói leo"
còn nguyên khi bật multi (root-cause vụ "không thấy LLM call trong Phoenix": floor
honor + cancel agent trước khi final tới, gate rơi vào nhánh idle đang off).

Ghép chuỗi trong `_evaluate_interrupt_candidate` (base_session, chỉ mode multi):

- **Non-asker (khác giọng)**: giữ nguyên — floor chặn, agent nói tiếp.
- **Asker (hoặc floor-open)** + gate bật + agent đang nói: thay vì `_handle_interrupt()`
  ngay → đi THẲNG vào `_addressee_soft_pause()` (+ set `_addr_episode_active`,
  `vad.set_speaking()` để tiếp tục nhận sự kiện). KHÔNG chạy lại EpisodeTracker:
  bằng chứng duration đã có sẵn — floor chỉ resolve sau khi interrupter nói
  ≥ `speaker_interrupt_min_sec` (0.8s) > `ADDRESSEE_MIN_SPEECH_MS` (400ms).
  Từ đó flow verdict như thường: partial → classify → SIDE_TALK resume-ack /
  DIRECTED commit; deadline fail-open giữ nguyên.
- Guard chống re-entry: đang `_addr_paused` thì floor-episode mới resolve asker
  lần nữa phải no-op (không re-arm deadline — timer cũ sẽ bị leak và commit sớm).
- Gate tắt (`off`) hoặc agent không nói: giữ nguyên `_handle_interrupt()` cũ.
- Telephony không có multi mode — không đổi.
- Test `test_multi_speaker_floor_takes_priority_over_addressee` đổi semantics:
  floor vẫn SỞ HỮU routing INTERRUPTED + nhận diện giọng, nhưng asker-resolution
  giờ nạp vào gate thay vì honor thẳng.

## Amendment 2026-08-12 (đêm): verdict chờ STT FINAL — bỏ classify trên partial

User phát hiện chuỗi lỗ hổng của verdict-trên-partial: (1) câu hỗn hợp
("con đi ăn cơm ngay cho bố, bên em giá căn hộ như thế nào") bị phán SIDE_TALK
trên nửa đầu → final chứa câu hỏi thật bị drop; (2) side-talk kéo dài tạo vòng
pause→resume→re-pause giật cục + spam ack, mỗi vòng một LLM call. Quyết định:
**đơn giản hóa — pause giữ đến khi STT chốt final, classify đúng MỘT lần trên
nguyên văn final**, resume hay interrupt quyết tại đó.

- **BỎ**: classify từ partial (`_on_partial` hết spawn), `_classify_addressee`,
  `_addr_verdict_task`/`_addr_verdict_inflight`, block await-in-flight trong
  `_on_final`, và nhu cầu verdict-text cache. `_addr_episode_gen` GIỮ (epoch
  guard của `_evaluate_interrupt_candidate` vẫn cần).
- **Deadline mới**: `ADDRESSEE_MAX_PAUSE_MS` (default 4000) thay công thức
  llm_timeout+1s — hết hạn mà chưa có final → fail-open DIRECTED (commit) như cũ.
  PHẢI < `_PAUSE_WATCHDOG_S` 5s của pacer (warning lúc init nếu vi phạm).
  `ADDRESSEE_LLM_TIMEOUT_MS` giữ nguyên vai trò bound cho request LLM.
- **`_on_final` khi đang pause**: classify inline trên final (nhánh có sẵn) —
  SIDE_TALK → resume-ack + replay + drop final; DIRECTED → commit + trả lời.
- **Prompt thêm luật câu hỗn hợp**: chứa CẢ side-talk LẪN nội dung hướng tới
  agent → DIRECTED (fail-open tinh thần cũ).
- Trade-off chấp nhận: interrupt thật chậm hơn ~1s (chờ final) nhưng agent vẫn
  im ngay từ lúc khách mở miệng; side-talk 1 câu = im trọn câu đó rồi xin phép
  nói tiếp — tự nhiên hơn giật cục. Side-talk nhiều câu → mỗi câu một chu kỳ
  pause/resume (cadence theo utterance, chấp nhận; ack-throttle để follow-up).
- Telephony mirror. Multi flow (floor → pause) không đổi.

## Ngoài phạm vi (YAGNI)

Không diarization realtime, không train model addressee riêng, không đụng chat
path / semcache, không resume giữa từ, không thay đổi speaker verification.
