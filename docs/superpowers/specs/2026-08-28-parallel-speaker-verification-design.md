# Parallel Speaker Verification (SpeakerTracker) — Design

**Date:** 2026-08-28
**Status:** Approved (brainstorm 2026-08-27→28)
**Scope:** Thay ruột speaker verification của CẢ HAI mode `single` và `multi` bằng một
engine chunk-song-song duy nhất. Xoá engine cũ (SpeakerFloor + episode 0.8s +
`_verify_speaker` re-embed cuối turn). Rollback bằng git, không có env switch.

## 1. Bài toán

Luồng hiện tại hoạt động tuần tự: VAD → STT → gom đủ 0.8s đầu → embed → so với
**một** embedding (asker/centroid) → pass thì ngắt, fail thì đợi hết turn re-embed
3s cuối ở `_on_final`. Hệ quả:

- Người lạ chen trước, khách chen sau: 0.8s đầu fail → phải đợi tới final mới
  biết khách thật sự muốn ngắt → agent nói đè lên khách nhiều giây.
- Chỉ 1 embedding đại diện danh tính → nhạy với biến thiên giọng (to/nhỏ/xa mic).
- Không có dấu vết per-chunk để quan sát/tune threshold.

## 2. Yêu cầu đã chốt

1. Đường SPV chạy **song song** với STT trên cùng audio đã qua input gate.
2. Nhịp cắt chunk **thích ứng theo verdict**: chưa gặp `speaker` trong utterance
   → cắt mỗi `speaker_interrupt_min_sec` (0.8s); ngay sau chunk `speaker` đầu tiên
   → cắt mỗi `SPV_CHUNK_SEC` (2s). Reset nhịp mỗi utterance mới.
3. Mỗi chunk so với **tập centroid** (max cosine); match ≥1 centroid → `speaker`.
4. Interrupt bắn **ngay tại chunk `speaker` đầu tiên** khi agent đang nói —
   qua addressee gate nếu bật (soft-pause → classifier DIRECTED/SIDE_TALK),
   gate tắt thì `_handle_interrupt()` thẳng. Không đợi final.
5. Final STT kèm **chuỗi nhãn per-chunk** (`speaker`/`non-speaker`/`unknown`) —
   dùng cho (a) quyết định drop final, (b) quan sát.
6. Vòng đời centroid theo mode:
   - **multi**: danh tính sống theo TURN. Câu mở turn (agent idle) enroll vô điều
     kiện (cửa sổ 3s) + chunk match trong turn bồi đắp thêm; `reset()` khi turn
     kết thúc. Turn sau ai hỏi cũng được.
   - **single**: danh tính sống cả PHIÊN. Utterance đầu tiên của phiên enroll vô
     điều kiện; chunk match ở mọi utterance sau bồi đắp; không bao giờ reset.
7. Cap `SPV_MAX_CENTROIDS` (10), FIFO. Chặn nhiễm: từ sau khởi tạo, chỉ chunk đã
   match mới được thêm vào tập → giọng người lạ không lọt vào.

## 3. Kiến trúc

### 3.1 File mới: `src/noble_agent/voice/speaker_tracker.py`

Hai class thuần logic (unit-test không cần model, giống tinh thần `SpeakerVerifier` cũ):

**`CentroidSet`**
- `add(emb)` — normalize + append; đầy `max_centroids` → bỏ cái cũ nhất (FIFO).
- `match(emb) -> (bool, float)` — max cosine trên toàn tập; `>= threshold` → match.
- `reset()` — xoá sạch (multi: turn end; single: không gọi trong phiên).
- `empty: bool` — tập rỗng ⇒ mọi chunk mặc nhiên `speaker` (giữ ngữ nghĩa
  floor-open/auto-greeting hiện tại: chưa ai làm chủ thì người đầu tiên chen được ngắt).

**`SpeakerTracker`**
- `begin_utterance()` — session gọi tại chunk STT đầu tiên của utterance
  (điểm `_stt_audio_start == 0` hiện tại). Reset nhịp cắt về 0.8s, xoá chuỗi nhãn.
- `feed(pcm)` — nhận đúng các chunk đã qua `_input_gate.gate()` (silence keepalive
  không bao giờ vào đây). Tích lũy buffer, cắt tại điểm cắt kế tiếp:
  - Chunk là các span **rời nhau** (không phải cửa sổ trượt, không cộng dồn).
  - Điểm cắt kế = 0.8s khi utterance chưa có chunk `speaker`; = 2.0s sau đó.
  - Tại điểm cắt: embed off-loop (`asyncio.to_thread` local / HTTP remote qua
    `SpeakerEmbedder` sẵn có) → `CentroidSet.match()` → ghi nhãn vào chuỗi →
    callback `on_verdict(label, sim, chunk_idx)`.
  - **Đúng 1 embed inflight mỗi phiên.** Embed chậm hơn nhịp cắt → audio dồn lại
    nhập vào chunk kế (chunk kế dài ra, không xếp hàng, không nổ chi phí).
- `finalize() -> list[str]` — gọi ở `_on_final`: đuôi chưa cắt ≥ 0.3s embed nốt
  thành chunk cuối; đợi embed inflight xong; trả chuỗi nhãn đầy đủ của utterance.
- `enroll_from_utterance()` — cắt buffer utterance (tracker TỰ GIỮ toàn bộ PCM
  của utterance hiện tại, cap `spv_max_centroids × speaker_embed_window_sec` ≈ 30s
  ≈ 1MB) thành cửa sổ `speaker_embed_window_sec` (3s); cửa sổ cuối ≥
  `speaker_min_enroll_sec` (1s) mới lấy; embed từng cửa sổ → `add()`. Chạy nền
  (fire-and-forget qua `_spawn_bg`).
- Enroll-on-match: chunk có nhãn `speaker` → embedding của chính chunk đó `add()`
  vào tập (cả hai mode).
- Embed lỗi/None → nhãn `unknown`: không ngắt, không enroll, loại khỏi phép đếm drop.

### 3.2 `base_session.py` — thay đổi

**Xoá:** `_begin_interrupt_episode`, `_evaluate_interrupt_candidate`,
`_interrupt_episode_active`, `_interrupt_embed_inflight`, `_verify_speaker`,
`_speaker_verifier`, `_speaker_floor`, `_floor_sim`, khối re-embed single/multi
trong `_on_final`, và `_utterance_pcm` (tracker tự giữ buffer; enrollment đọc
buffer utterance từ tracker).

**Thêm:** `self._speaker_tracker: SpeakerTracker | None` — tạo khi
`resolve_speaker_mode()` ∈ {`single`, `multi`}, cùng một class cho cả hai; mode
chỉ quyết định lifecycle reset (xem 3.3).

- `process_audio_frame`: chỗ đang extend `_utterance_pcm` → `tracker.feed(chunk)`;
  `begin_utterance()` tại điểm `_stt_audio_start == 0`.
- Nhánh `VADState.INTERRUPTED`: mode single/multi mới KHÔNG mở episode — chỉ
  `vad.set_speaking()` giữ máy trạng thái sống; quyết định ngắt hoàn toàn do
  verdict tracker. Mode `off` (+ addressee gate thuần) giữ đường cũ nguyên vẹn.
- Callback `on_verdict(label, sim, idx)`:
  - `speaker` + `_agent_is_speaking()` → addr gate bật: đi đường soft-pause hiện có
    (`_begin_addressee_pause_from_floor`, đổi tên phù hợp); gate tắt:
    `await _handle_interrupt()`.
  - `non-speaker` + agent đang nói → `vad.set_speaking()`, agent nói tiếp.
  - Agent không nói → không hành động (nhãn vẫn ghi chuỗi).
- `_on_final` (thứ tự filter giữ nguyên: hallucination → echo cooldown → speaker):
  1. `labels = await tracker.finalize()`.
  2. **Drop rule:** đếm `speaker` vs `non-speaker` (bỏ `unknown`): đa số
     non-speaker → drop; hòa hoặc không có nhãn → giữ (fail-open).
     Phạm vi: single — mọi final; multi — chỉ khi `_agent_is_speaking()` hoặc
     `_addr_paused` (agent idle = floor mở, nhận final bất kể nhãn).
  3. Quan sát: log `[Speaker] labels=[...] sims=[...] text=%r`; event
     `final_transcript` thêm field `speaker_labels` (client cũ ignore field lạ).
     Smart-turn hold gộp nhiều final: nhãn tính và log per-final; event của text
     gộp mang nhãn của final cuối.
- **Enrollment hook = `_trigger_agent_for_text`** (mọi final được nhận đều qua
  đây, cả mở turn lúc idle lẫn final cắt turn cũ — chạy SAU khi task cũ đã
  cancel + await xong nên không race với reset trong `finally`):
  - multi: `tracker.reset()` + `enroll_from_utterance()` — final này là câu mở
    turn mới, người nói nó là asker mới.
  - single: chỉ khi tập đang rỗng (utterance đầu phiên) → `enroll_from_utterance()`;
    về sau bồi đắp qua enroll-on-match.
- `_run_agent` `finally` (chỗ `clear_asker()` cũ, ~dòng 1287): multi →
  `tracker.reset()` (turn kết thúc tự nhiên → floor mở lại); single → không.

### 3.3 Khác biệt mode — chỉ nằm ở lifecycle

| | multi | single |
|---|---|---|
| Khởi tạo tập | mỗi câu mở turn | utterance đầu tiên của phiên |
| Bồi đắp | chunk match trong turn | chunk match mọi utterance |
| Reset | `_run_agent` finally | không |
| Drop final | chỉ mid-turn (speaking/paused) | mọi final |

### 3.4 Tương tác giữ nguyên

- Addressee gate: đường soft-pause/deadline/classifier không đổi — engine mới chỉ
  thay NGUỒN kích hoạt (verdict chunk thay cho episode 0.8s). Epoch-guard
  `_addr_episode_gen` vẫn áp cho verdict landing muộn (stamp trước await embed,
  so sau khi land).
- Billing: mỗi embed ghi `speaker_verify` (audio_sec + wall_ms + units=1) như
  `_embed_current_utterance` hiện tại.
- Barge-in RMS floor (`BARGE_IN_RMS_THRESHOLD`), echo cooldown, hallucination
  filter, smart-turn: không đổi.
- `SpeakerEmbedder` (local sherpa / remote HTTP) + prewarm: giữ nguyên.

## 4. Config

| Env | Field | Default | Ghi chú |
|---|---|---|---|
| `SPV_CHUNK_SEC` | `spv_chunk_sec` | `2.0` | Nhịp cắt SAU khi đã gặp speaker |
| `SPV_MAX_CENTROIDS` | `spv_max_centroids` | `10` | Cap FIFO tập centroid |

Tái dùng (không đổi ý nghĩa): `speaker_interrupt_min_sec` (0.8 — nhịp nhanh),
`speaker_embed_window_sec` (3.0 — cửa sổ enroll), `speaker_match_threshold` (0.5),
`speaker_min_enroll_sec` (1.0), `SPEAKER_MODE` (`off`/`single`/`multi`).
Đuôi finalize tối thiểu 0.3s là hằng số trong tracker, không cần env.

## 5. Error handling

- Embed fail/None → nhãn `unknown`: interrupt **fail-closed** (không ngắt),
  drop final **fail-open** (giữ), enroll bỏ qua.
- Tập centroid rỗng (enrollment nền chưa xong khi barge-in đến) → chunk mặc
  nhiên `speaker` — fail-open đúng ngữ nghĩa floor-open hiện tại.
- Utterance quá ngắn (không có nhãn nào) → giữ final, không enroll (trừ khởi tạo:
  vẫn cần ≥ `speaker_min_enroll_sec`).
- Verdict landing sau khi turn/episode đã resolve → epoch-guard discard.

## 6. Testing

- **Unit `CentroidSet`:** match = max-cosine ≥ threshold; cap FIFO; reset; empty →
  mặc nhiên speaker.
- **Unit `SpeakerTracker`** (fake embedder, không model): nhịp 0.8s khi chưa gặp
  speaker → chuyển 2s sau chunk speaker đầu; reset nhịp mỗi utterance; 1-inflight
  + dồn audio vào chunk kế; finalize đuôi ≥0.3s; chuỗi nhãn đúng span;
  enroll-on-match; enroll_from_utterance cắt cửa sổ 3s.
- **Session (test_base_session):** chunk speaker → soft-pause/interrupt tức thì;
  non-speaker → agent nói tiếp; người lạ chen trước + khách chen sau → ngắt giữa
  utterance ở nhịp 0.8s; drop final đa số non-speaker; multi reset theo turn
  (turn sau người khác hỏi được); single giữ danh tính cả phiên; embed fail →
  không ngắt + final fail-open; auto-greeting (tập rỗng) vẫn ngắt được.
- Xoá `tests/unit/test_speaker_floor.py`; viết lại nhóm speaker trong
  `tests/unit/test_base_session.py`; file mới `tests/unit/test_speaker_tracker.py`.
- `make test-unified` + SMOKE.md mục speaker (smoke thủ công 2 người nói thật).

## 7. Files đụng

- `src/noble_agent/voice/speaker_tracker.py` (mới)
- `src/noble_agent/server/base_session.py`
- `src/noble_agent/config.py`
- `src/noble_agent/voice/speaker_verifier.py` (xoá `SpeakerVerifier`/`SpeakerFloor`,
  giữ `SpeakerEmbedder` + model loading — cân nhắc đổi tên file thành
  `speaker_embedder.py` nếu import sites ít)
- `tests/unit/test_speaker_tracker.py` (mới), `tests/unit/test_speaker_floor.py`
  (xoá), `tests/unit/test_base_session.py`
- `src/noble_agent/SMOKE.md`, `CLAUDE.md` changelog + `docs/CHANGELOG-agent.md`
