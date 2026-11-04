# Speaker Registry + Fast Barge-in — Design

**Date:** 2026-09-03
**Status:** Approved (brainstorm 2026-09-03)
**Scope:** Thay vòng đời danh tính và cơ chế cắt cửa sổ của SpeakerTracker
(spec 2026-08-28). Danh tính chuyển từ "một `CentroidSet` bị reset mỗi turn" sang
"registry N danh tính sống cả phiên + con trỏ asker". Cửa sổ probe chuyển từ span
rời sang tích luỹ. Enroll chuyển từ cắt mù sang lọc cụm nhất quán. Rollback bằng
git, không có env switch.

Tiền đề: [2026-08-28-parallel-speaker-verification-design.md](2026-08-28-parallel-speaker-verification-design.md)
— engine chunk-song-song, `SpeakerEmbedder`, đường verdict → interrupt, drop rule
ở final. Spec này giữ khung đó và thay ba thứ bên trong.

## 1. Bài toán

Ba lỗi quan sát được trên bản 2026-08-28, xác nhận bằng log phiên thật và đọc code:

**1.1 — Enroll mù biến audio tồi thành chuẩn danh tính.** `_enroll` cắt utterance
thành cửa sổ 3s không chồng lấn rồi `add()` vô điều kiện: không kiểm SNR, không so
các cửa sổ với nhau, không phân biệt audio thu lúc agent đang phát. Câu 2.95s cho
đúng **một** centroid — không có gì để đối chiếu, sai là sai trọn. Spec cũ §2.7 tin
rằng "chỉ chunk đã match mới được thêm vào tập → giọng người lạ không lọt vào",
nhưng chính **lần khởi tạo là vô điều kiện**, và ở `multi` lần khởi tạo đó lặp lại
mỗi turn.

**1.2 — Trượt một lần là khoá cả turn (tự khoá).** `enroll-on-match` chỉ bồi centroid
**khi đã khớp**. Centroid gốc lệch → chunk đầu trượt → không được bồi → mọi chunk sau
trượt theo. Không có đường tự sửa. Kèm theo, drop rule ở final dùng **bằng chứng âm**
("không khớp asker" → drop), mà centroid tồi cho ra đúng dấu hiệu đó, nên lỗi enroll
biến thành mất câu nói: agent nói hết turn, người dùng không thoát ra được.
Bằng chứng thực nghiệm: `enrolled 1 centroid(s) from 2.31s utterance` rồi 1 giây sau,
cùng một người, `chunk#0 0.57s → non-speaker (sim=0.018)`.

**1.3 — Verdict không thể về trước 0.8s.** Chunk là span **rời nhau**
(`_maybe_cut` cắt xong `_buf.clear()`), nên verdict đầu tiên không tồn tại trước mốc
`speaker_interrupt_min_sec`. Mỗi lần trượt phải trả thêm trọn một nhịp nữa, trên một
lát audio mới cũng chỉ 0.8s — **độ tin cậy không tăng theo thời gian**, khác hẳn cơ
chế `SpeakerFloor` trước `a2d2791` vốn embed buffer lớn dần nên tự lành sau ~0.2s.

Đo thật (CPU, sherpa ONNX local, `3dspeaker_campplus_zh-cn`): embed 0.3s → **4.1ms**;
0.5s → 5.8ms; 0.8s → 7.3ms; 1.5s → 11.7ms; 3.0s → 20.1ms. Toàn bộ độ trễ 0.8s hiện
nay là **chờ gom audio**, không phải chờ tính toán. Quy tắc "đúng 1 embed inflight"
và nhịp cắt 0.8/2s đang tiết kiệm đúng thứ rẻ nhất và trả giá bằng thứ đắt nhất.

## 2. Yêu cầu đã chốt

1. **Đổi người giữa cuộc gọi phải chạy đúng** — A hỏi turn 1, B hỏi turn 2, A quay
   lại turn 3 thì A được nhận ra ngay, không phải học lại từ đầu.
2. **Không bao giờ enroll nhầm** — thà không có danh tính còn hơn có danh tính rác.
3. **Ngắt nhanh khi đúng danh tính** — rút ngắn thời gian *xác định* danh tính; hành
   động trước khi biết danh tính (speculative pause) **không** nằm trong scope.
4. **Giữ nguyên hành vi mặc định khi `ADDRESSEE_GATE_MODE=off`**: verdict không khớp
   → `vad.set_speaking()`, agent nói tiếp **liền mạch**, không khựng. `pause_playback`
   vẫn chỉ thuộc đường addressee gate.
5. **Mọi tham số cửa sổ và ngưỡng phải tune được qua `.env`.**
6. Fail-**open** ở mọi điểm không chắc chắn: không nhận diện được ⇒ lùi về hành vi
   không-lọc (như `SPEAKER_MODE=off`), không bao giờ lùi về khoá cứng.

## 3. Kiến trúc

### 3.1 `SpeakerRegistry` — mới, trong `voice/speaker_tracker.py`

Thay vai trò của "một `CentroidSet` + `reset()` mỗi turn". `CentroidSet` giữ nguyên
làm đơn vị con (một danh tính = một `CentroidSet`).

```python
class SpeakerRegistry:
    def __init__(self, *, match_threshold: float, adapt_margin: float,
                 max_identities: int, max_centroids: int) -> None

    @property
    def empty(self) -> bool                      # chưa có danh tính nào → floor mở
    @property
    def asker(self) -> int | None                # id danh tính đang giữ lượt

    def identify(self, emb) -> tuple[int | None, float]
        """Quét toàn registry, trả (id khớp nhất, sim). None nếu sim < match_threshold."""

    def match_asker(self, emb, threshold: float) -> tuple[bool, float]
        """Chỉ so với danh tính asker. Registry rỗng hoặc chưa có asker → (True, 1.0)
        (fail-open, giữ ngữ nghĩa floor-open của auto-greeting)."""

    def observe(self, embs: list[np.ndarray], *, allow_new: bool) -> ObserveResult
        """Đường nguội: nhận diện + ghi centroid theo margin. KHÔNG đụng asker.
        embs = các centroid của cụm nhất quán (§4.2). Xem bảng phân nhánh §4.2.
        allow_new=False (mode single đã có danh tính) → không tạo danh tính mới,
        trả identity=None thay vì đẩy danh tính phiên ra khỏi cap FIFO."""

    def set_asker(self, identity: int) -> None
        """Trao lượt. Session gọi SAU khi áp drop rule (§4.3) — registry không tự
        quyết ai giữ lượt."""

    def drop_asker(self) -> None
        """Van thoát: xoá danh tính asker khỏi registry khi nó bị nghi là sai (§4.3)."""
```

**Tách bạch trách nhiệm (quan trọng):** `observe()` chỉ trả lời *"người này là ai"* và
bồi centroid; *"ai được giữ lượt"* là quyết định của session vì nó phụ thuộc trạng thái
hội thoại (agent đang nói hay không). Gộp hai việc vào `observe()` sẽ khiến người chen
ngang mid-turn tự động cướp lượt trước khi drop rule kịp chạy.

- Cap `max_identities` (FIFO): registry đầy thì danh tính cũ nhất rơi.
- Cap `max_centroids` mỗi danh tính (FIFO, `CentroidSet` sẵn có).
- **Không có `reset()` per-turn.** Registry sống trọn phiên; turn chỉ đổi con trỏ
  `asker`. Đây là thay đổi ngữ nghĩa cốt lõi so với 2026-08-28.

### 3.2 `SpeakerTracker` — sửa

**Bỏ:** `_next_cut_bytes`, `_speaker_seen`, nhịp fast/slow, `_maybe_cut` kiểu span
rời, `_enroll` cắt mù 3s, `enroll-on-match`, `_TAIL_MIN_SEC` + nhánh embed đuôi
trong `finalize`, `reset()`/`_enroll_gen`.

**Giữ:** `begin_utterance()`, `feed(pcm)`, quy tắc 1-inflight cho probe, gen-guard
chống verdict land muộn (`_gen`), snapshot PCM đồng bộ lúc `finalize()`
(`_final_utt_pcm` — fix `297fd3f`, vẫn cần vì `observe` chạy sau nhiều await).

**Thêm:**

```python
def _probe_offsets(self) -> list[float]     # marks + đuôi trượt, sinh từ config
async def _probe(self, upto_sec: float, gen: int) -> None
async def finalize(self) -> UtteranceVerdict
```

`UtteranceVerdict` (dataclass) thay `list[str]`:

```python
@dataclass
class UtteranceVerdict:
    identity: int | None      # ai đang nói; None = không đủ bằng chứng để nói gì
    is_new: bool              # danh tính vừa được tạo trong lượt này
    cluster_size: int         # số cửa sổ trong cụm nhất quán (0 = không có cụm)
    best_sim: float           # sim với danh tính khớp nhất TRƯỚC khi ghi
    probe_labels: list[str]   # nhãn probe theo thứ tự, chỉ để log/quan sát
```

Ba tổ hợp phân biệt được và drop rule §4.3 dựa vào cả ba:

| Tình huống | `identity` | `is_new` | `cluster_size` |
|---|---|---|---|
| Không có cụm nhất quán | `None` | `False` | `< MIN_CLUSTER` |
| Người cũ (chắc chắn hoặc vùng xám) | id cũ | `False` | `≥ MIN_CLUSTER` |
| Người mới | id mới | `True` | `≥ MIN_CLUSTER` |
| `single` đã có danh tính, giọng lạ | `None` | `False` | `≥ MIN_CLUSTER` |

### 3.3 `base_session.py` — sửa

- `__init__`: dựng `SpeakerRegistry` thay `CentroidSet`, truyền vào tracker.
- `_on_speaker_verdict(label, sim, idx)`: **giữ nguyên chữ ký và nguyên hành vi**
  (§2.4). Chỉ nguồn sinh verdict đổi từ chunk rời sang probe tích luỹ.
- `_on_final`: `labels = await finalize()` → `verdict = await finalize()`; drop rule
  viết lại theo §4.3; gọi `registry.set_asker()` ở đúng các nhánh được trao lượt.
- Thêm `self._mismatch_streak: int` (single-writer: `_on_final`) — đếm final liên
  tiếp không nhận diện được, van thoát §4.3. Đặt ở session chứ không ở registry vì
  nó đo *chất lượng của quyết định policy*, không phải trạng thái của tập danh tính.
- `_trigger_agent_for_text`: **xoá** khối `reset()` + `enroll_from_utterance()`
  (dòng ~987-991). Việc gán asker/ghi centroid đã xong trong `finalize()`.
- `_run_agent` `finally`: **xoá** `tracker.reset()` (dòng ~1140-1141). Turn kết thúc
  không còn xoá danh tính.
- Cảnh báo khởi động ở dòng ~233 so `speaker_interrupt_min_sec` với
  `addressee_min_speech_ms`: đổi vế trái sang **mốc probe cuối cùng** (thời điểm
  muộn nhất một verdict khớp có thể xuất hiện trong chuỗi mốc).

Mode `single` vs `multi` sau thay đổi này:

| | multi | single |
|---|---|---|
| Registry | tối đa `SPV_MAX_IDENTITIES` danh tính | ép `max_identities=1` |
| Đổi asker | có, ở ranh giới turn (§4.3) | không — danh tính đầu phiên giữ nguyên |
| Drop final | chỉ mid-turn (`_agent_is_speaking()` hoặc `_addr_paused`) | mọi final |

## 4. Luồng

### 4.1 Đường nóng — probe tích luỹ (chỉ đọc, không bao giờ ghi)

`feed()` tích luỹ vào `_utt_pcm` (cap `SPV_UTT_CAP_SEC`). Tại mỗi mốc trong
`SPV_PROBE_MARKS_SEC`, embed **toàn bộ audio từ đầu utterance tới mốc đó**:

```
utterance:  0 ─ 0.25 ─ 0.4 ─── 0.6 ───── 0.9 ────── 1.3s ──→ đuôi trượt
probe#0:    [═══]                                    ngưỡng MATCH + BONUS[0] = 0.65
probe#1:    [═════════]                              MATCH + BONUS[1] = 0.60
probe#2:    [═══════════════]                        0.55
probe#3:    [═══════════════════════]                0.50
probe#4:    [═══════════════════════════════]        0.50
đuôi:                              [1.5s trượt, hop 1.0s]  0.50
```

- So bằng `registry.match_asker(emb, threshold_i)`.
- **Quyết được thì dừng chuỗi mốc ngay tại đó**, phát `on_verdict(label, sim, idx)`
  đúng như hôm nay: `speaker` → interrupt (hoặc soft-pause nếu addressee gate bật);
  `non-speaker` → `vad.set_speaking()`, agent nói tiếp; `unknown` (embed fail) →
  fail-closed, không ngắt.
- **Hết chuỗi mốc → chuyển sang cửa sổ trượt** `SPV_PROBE_TAIL_WINDOW_SEC` mỗi
  `SPV_PROBE_TAIL_HOP_SEC`. Bắt buộc phải trượt chứ không tích luỹ tiếp: khi người lạ
  nói trước và khách chen sau trong **cùng** utterance, cửa sổ tích luỹ cho ra giọng
  lai và không khớp ai cả.
- Quy tắc 1-inflight giữ nguyên: probe đang chạy thì mốc kế bị bỏ qua, mốc sau đó
  nhìn audio dài hơn nên không mất mát.
- Ngưỡng siết theo độ dài (`SPV_PROBE_BONUS`) là điều kiện để quyết sớm không thành
  quyết ẩu: cửa sổ 0.25s phải khớp chặt hơn hẳn cửa sổ 0.9s.

Chi phí: 5 lần embed ≈ 35ms CPU rải trong 1.3s, cộng ~12ms mỗi 1.0s ở giai đoạn đuôi.

### 4.2 Đường nguội — cụm nhất quán + ghi danh tính (chỉ chạy ở `finalize()`)

```
finalize() → đợi probe inflight → snapshot _final_utt_pcm
  ↓
cắt cửa sổ trượt SPV_ENROLL_WINDOW_SEC, bước SPV_ENROLL_HOP_SEC → W1..Wn
(utterance < SPEAKER_MIN_ENROLL_SEC → bỏ qua toàn bộ đường này)
  ↓
embed W1..Wn → ma trận cosine chéo
  ↓
cụm nhất quán lớn nhất: tập con lớn nhất mà mọi cặp trong đó có
cosine ≥ SPV_ENROLL_CONSENSUS_SIM
  ↓
├─ |cụm| < SPV_ENROLL_MIN_CLUSTER  → UtteranceVerdict(identity=None, cluster_size=k)
│     registry KHÔNG bị đụng, asker giữ nguyên như trước
│
└─ có cụm → E = medoid của cụm → registry.observe(cụm, allow_new=...)
      │
      ├─ sim ≥ MATCH + ADAPT_MARGIN   người cũ, chắc chắn
      │     identity = id  +  GHI toàn bộ centroid của cụm vào id
      │
      ├─ MATCH ≤ sim < MATCH+MARGIN   vùng xám
      │     identity = id
      │     KHÔNG ghi gì — mẫu vừa đủ giống không được phép định nghĩa lại danh tính
      │
      └─ sim < MATCH                  người mới
            allow_new=True  → tạo danh tính mới + ghi cụm vào đó
            allow_new=False → identity = None  (single đã có danh tính phiên)
```

`allow_new = (mode == "multi") or registry.empty`. Ràng buộc này bảo vệ `single`: nếu
cứ tạo danh tính mới thì cap FIFO `max_identities=1` sẽ **đẩy chính danh tính phiên ra
ngoài**, phá đúng thứ mà `single` tồn tại để giữ.

Việc trao lượt (`set_asker`) **không** xảy ra ở đây — xem §4.3.

Hai điểm phải giữ đúng:

- **Ngưỡng ghi chặt hơn ngưỡng đọc** (`ADAPT_MARGIN`). `CentroidSet.match()` lấy
  **max** cosine trên toàn tập, nên nếu ngưỡng ghi = ngưỡng đọc thì mỗi mẫu vùng biên
  lại nới rộng biên, và biên mới làm bàn đạp cho lần nới tiếp — danh tính trôi dạt cho
  tới khi ai nói cũng khớp. Đây là chế độ hỏng **ngược** với §1.2 và cũng phải chặn.
- **Cụm rỗng không xoá được danh tính đang có.** Một câu nói tồi chỉ đơn giản là không
  đóng góp gì, khác hẳn `reset()` + enroll đè của bản cũ.

`SPV_ENROLL_CONSENSUS_SIM` là thang **riêng**, không neo vào `SPEAKER_MATCH_THRESHOLD`:
nó đo hai lát của **cùng một câu nói**, thu trong cùng điều kiện, nên kỳ vọng giống
nhau cao hơn hẳn so với việc so một mẫu mới với centroid cũ.

### 4.3 Drop rule ở final — đổi sang bằng chứng dương

Phạm vi giữ nguyên: `single` — mọi final; `multi` — chỉ khi `_agent_is_speaking()`
hoặc `_addr_paused` (agent idle = floor mở, nhận final bất kể danh tính).

Kiểm **theo đúng thứ tự này** — nhánh 1 phải đứng trước mọi nhánh khác:

| # | Điều kiện | Hành động |
|---|---|---|
| 1 | `registry.asker is None` (chưa ai giữ lượt) | **Giữ** + `set_asker(identity)` nếu có. Floor đang mở — đây là ca khách ngắt auto-greeting, câu đầu phiên **không bao giờ** được drop |
| 2 | `identity is None` (không đủ bằng chứng) | **Giữ** — fail-open; `_mismatch_streak += 1` |
| 3 | `identity == registry.asker` | **Giữ** (đã ngắt ở probe, hoặc ngắt muộn tại đây); `_mismatch_streak = 0` |
| 4 | `identity` là danh tính **khác** | **Drop** — bằng chứng dương rằng người khác chen ngang. Asker **không** đổi |
| 5 | `is_new=True` | **Drop** mid-turn, nhưng danh tính đã được tạo → turn sau, khi agent im, họ hỏi là được nhận ngay |

Nhánh 4 và 5 chỉ drop **mid-turn**; khi agent im thì phạm vi ở trên đã cho final đi
thẳng và nhánh 1/3 trao lượt bình thường. Đó chính là chỗ "đổi người giữa cuộc" xảy ra:
**ranh giới turn, không phải giữa turn**.

**Van thoát tự sửa:** `_mismatch_streak ≥ SPV_MISMATCH_STREAK_MAX` liên tiếp →
`registry.drop_asker()` + reset streak. Danh tính asker rõ ràng không mô tả được
người đang nói, nên xoá nó đi và để floor mở còn hơn giữ một chuẩn sai. Streak reset
về 0 mỗi khi có final khớp asker. Đây là đường thoát mà bản 2026-08-28 hoàn toàn
không có — chính chỗ khiến một lần enroll hỏng khoá cứng tới hết turn.

Event `final_transcript` giữ field `speaker_labels` (nay là `verdict.probe_labels`,
client cũ không đổi) và **thêm** `speaker_id` (`int | None`).

## 5. Config

Ba ngưỡng thực thi đều suy ra từ **một ngưỡng gốc** `SPEAKER_MATCH_THRESHOLD`, nên
tune một chỗ là cả hệ dịch theo đúng tương quan.

| Env | Field | Default | Ý nghĩa |
|---|---|---|---|
| `SPEAKER_MATCH_THRESHOLD` | `speaker_match_threshold` | `0.5` | **Ngưỡng gốc** — độ khắt khe tổng thể |
| `SPV_PROBE_MARKS_SEC` | `spv_probe_marks_sec` | `0.25,0.4,0.6,0.9,1.3` | Mốc embed tích luỹ từ đầu utterance |
| `SPV_PROBE_BONUS` | `spv_probe_bonus` | `0.15,0.1,0.05,0,0` | Siết thêm cho từng mốc; phải cùng số phần tử với trên |
| `SPV_PROBE_TAIL_WINDOW_SEC` | `spv_probe_tail_window_sec` | `1.5` | Hết chuỗi mốc → cửa sổ trượt dài bấy nhiêu |
| `SPV_PROBE_TAIL_HOP_SEC` | `spv_probe_tail_hop_sec` | `1.0` | Nhịp trượt giai đoạn đuôi |
| `SPV_ENROLL_WINDOW_SEC` | `spv_enroll_window_sec` | `1.5` | Cửa sổ trượt khi enroll |
| `SPV_ENROLL_HOP_SEC` | `spv_enroll_hop_sec` | `0.75` | Bước trượt (chồng lấn 50%) |
| `SPV_ENROLL_CONSENSUS_SIM` | `spv_enroll_consensus_sim` | `0.5` | Cosine tối thiểu để hai cửa sổ coi là cùng giọng |
| `SPV_ENROLL_MIN_CLUSTER` | `spv_enroll_min_cluster` | `2` | Cụm nhỏ hơn → bỏ enroll, để tập rỗng |
| `SPV_ADAPT_MARGIN` | `spv_adapt_margin` | `0.1` | Siết thêm khi **ghi** centroid; `0` = hành vi spec cũ |
| `SPV_MAX_IDENTITIES` | `spv_max_identities` | `4` | Cap danh tính mỗi phiên (FIFO); `single` ép về 1 |
| `SPV_MAX_CENTROIDS` | `spv_max_centroids` | `10` | *(giữ)* Cap centroid mỗi danh tính |
| `SPV_MISMATCH_STREAK_MAX` | `spv_mismatch_streak_max` | `2` | Số final "không khớp ai" liên tiếp trước khi bỏ asker |
| `SPV_UTT_CAP_SEC` | `spv_utt_cap_sec` | `30` | Cap PCM giữ cho một utterance |
| `SPEAKER_MIN_ENROLL_SEC` | `speaker_min_enroll_sec` | `1.0` | *(giữ)* Utterance ngắn hơn → không enroll |

Ngưỡng suy ra: probe mốc `i` = `MATCH + BONUS[i]`; nhận diện ở final = `MATCH`;
ghi centroid = `MATCH + ADAPT_MARGIN`.

**Xoá (thay thế bởi bộ trên):**

| Env bỏ | Vì sao |
|---|---|
| `SPEAKER_INTERRUPT_MIN_SEC` | Mốc probe đầu tiên thay vai trò "audio tối thiểu trước khi quyết" |
| `SPV_CHUNK_SEC` | Không còn span rời; giai đoạn đuôi dùng `TAIL_HOP` |
| `SPEAKER_EMBED_WINDOW_SEC` | Tách thành `SPV_ENROLL_WINDOW_SEC` + `SPV_UTT_CAP_SEC` |

Xoá hẳn thay vì giữ tên cũ mang nghĩa mới — tên cũ với ngữ nghĩa mới là bẫy cho phiên
sau. `.env`, `.env.example`, `config.py`, `tests/unit/test_config_gate_speaker.py`,
`tests/unit/test_base_session.py` cập nhật cùng commit.

Hai list khai báo dạng CSV (`str` trong `UnifiedSettings`), parse sang
`tuple[float, ...]` bằng một `field_validator` — không dùng `list[float]` trực tiếp vì
pydantic-settings đòi cú pháp JSON cho kiểu list và `0.25,0.4` trong `.env` sẽ nổ.

**Fail-loud lúc khởi động** (raise trong validator, không âm thầm dùng mặc định):
`len(PROBE_MARKS) != len(PROBE_BONUS)`; list rỗng; mốc không tăng dần nghiêm ngặt;
bất kỳ `MATCH + BONUS[i]` nào vượt ra ngoài `(0, 1]`.

## 6. Error handling

| Tình huống | Hành vi |
|---|---|
| Embed fail/None ở probe | Nhãn `unknown` — không ngắt (fail-closed), mốc kế thử lại |
| Embed fail/None ở enroll | Bỏ cửa sổ đó, cụm tính trên các cửa sổ còn lại |
| Registry rỗng / chưa có asker | `match_asker` → `(True, 1.0)` — floor mở, ai cũng ngắt được |
| Không có cụm nhất quán | Không đụng registry; asker giữ nguyên; final fail-open (giữ) |
| Utterance < `SPEAKER_MIN_ENROLL_SEC` | Không enroll; probe vẫn chạy bình thường |
| Verdict land sau khi turn/episode đã resolve | Gen-guard `_gen` + epoch-guard `_addr_episode_gen` discard (giữ nguyên) |
| `_mismatch_streak` chạm trần | `drop_asker()` → lùi về floor mở |

Nguyên tắc xuyên suốt: **không nhận diện được ⇒ lùi về không-lọc**, không bao giờ lùi
về khoá cứng.

## 7. Ảnh hưởng phụ

- **Billing:** số lần embed mỗi utterance tăng từ ~2 lên ~5 (probe) + ~2-4 (enroll).
  Mỗi lần vẫn ghi `speaker_verify` (`audio_sec` + `wall_ms` + `units=1`) như hôm nay,
  nên `units` trên hoá đơn sẽ tăng ~3-4×. Wall-time tuyệt đối vẫn nhỏ (~50-80ms/utterance).
- **Log:** giữ định dạng `[Speaker] ...` để bộ màu vàng/tím ở `logging_config.py`
  (`_SPK_NOMATCH_MARKS`) tiếp tục nhận diện được — dòng probe phải chứa `non-speaker`
  / `unknown` khi không khớp. Thêm một dòng tổng kết ở final in `identity`, `best_sim`,
  `cluster_size`.
- **Không đổi:** `SpeakerEmbedder` + prewarm, barge-in RMS floor, echo cooldown,
  hallucination filter, smart-turn, toàn bộ đường addressee gate.

## 8. Testing

**Unit `SpeakerRegistry`** (fake embedding, không model):
- `identify` trả danh tính max-cosine; dưới ngưỡng → `None`.
- `observe`: ba nhánh chắc-chắn / vùng-xám / người-mới; vùng xám **không** ghi.
- Cap FIFO danh tính và cap FIFO centroid.
- `match_asker` fail-open khi rỗng / chưa có asker.
- `drop_asker` đưa về floor mở.
- **Regression trôi dạt:** chuỗi mẫu vùng biên liên tiếp không được nới rộng tập
  (đúng thứ `ADAPT_MARGIN` sinh ra để chặn).

**Unit `SpeakerTracker`:**
- Probe bắn đúng các mốc; cửa sổ **tích luỹ** (mốc sau chứa audio mốc trước).
- Ngưỡng theo mốc áp đúng phần tử `BONUS`.
- Quyết được → dừng chuỗi mốc, không probe thừa.
- Hết mốc → chuyển cửa sổ trượt đúng `TAIL_WINDOW`/`TAIL_HOP`.
- 1-inflight: probe chậm hơn nhịp mốc thì mốc kế bị bỏ, không xếp hàng.
- Cụm nhất quán: chọn cụm lớn nhất; loại cửa sổ lạc loài; `< MIN_CLUSTER` → `identity=None`.
- `finalize` gắn đúng utterance đang chốt khi utterance mới bắt đầu giữa chừng
  (regression của `ec1b432`/`297fd3f` — giữ nguyên gen-guard + snapshot).

**Session (`test_base_session`):**
- Probe khớp asker → interrupt tức thì; addressee gate bật → soft-pause.
- Probe không khớp → **agent nói tiếp, không khựng** (chốt yêu cầu §2.4).
- Người lạ nói trước + khách chen sau cùng utterance → giai đoạn đuôi bắt được.
- Drop rule 4 nhánh §4.3.
- `_mismatch_streak` chạm trần → `drop_asker` → final kế được nhận.
- **Đổi người giữa cuộc:** A turn 1 → B turn 2 → A turn 3 nhận lại đúng danh tính A
  (đây là yêu cầu §2.1, bản cũ không thể pass).
- Danh tính **không** bị xoá khi turn kết thúc (regression cho việc bỏ hai `reset()`).
- **Câu đầu phiên ngắt auto-greeting KHÔNG bị drop** (nhánh 1 §4.3) — regression trực
  tiếp cho lỗi đang gặp; bản nháp spec này từng sai đúng chỗ đó.
- `single`: `allow_new=False` sau danh tính đầu → giọng lạ cho `identity=None`, danh
  tính phiên không bị cap FIFO đẩy ra.

**Smoke thủ công:** cập nhật mục "Speaker verification" trong `src/noble_agent/SMOKE.md`
— thêm bước đổi người giữa cuộc và bước kiểm dòng log probe (vàng = khớp, tím = không).
