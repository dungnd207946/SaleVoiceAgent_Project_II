# Speaker Registry + Fast Barge-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Danh tính người nói sống trọn phiên trong một registry (thay vì bị xoá mỗi turn), enroll chỉ nhận mẫu đã kiểm chứng bằng cụm nhất quán, và probe barge-in dùng cửa sổ tích luỹ để verdict về từ ~0.25s thay vì 0.8s.

**Architecture:** `SpeakerRegistry` (N danh tính, mỗi danh tính một `CentroidSet`) thay chỗ một `CentroidSet` bị `reset()` hai lần mỗi turn. `SpeakerTracker` giữ vai trò cắt cửa sổ + gọi embed, nhưng đổi từ span rời sang hai chế độ: probe tích luỹ trên đường nóng (chỉ đọc) và cụm cửa sổ trượt ở `finalize()` trên đường nguội (nơi duy nhất được ghi centroid). `base_session` giữ nguyên đường verdict → interrupt, chỉ đổi nguồn sinh verdict, drop rule, và bỏ hai lời gọi `reset()`.

**Tech Stack:** Python 3.11+, numpy, pydantic-settings, pytest (`asyncio_mode=auto`), sherpa-onnx (`SpeakerEmbedder`, đã có).

**Spec:** [docs/superpowers/specs/2026-09-03-speaker-registry-fast-barge-in-design.md](../specs/2026-09-03-speaker-registry-fast-barge-in-design.md)

## Global Constraints

- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Chạy `make lint` trước mỗi commit.
- Pytest `asyncio_mode=auto` — test coroutine **không** cần `@pytest.mark.asyncio`.
- Ba ngưỡng thực thi đều suy ra từ `SPEAKER_MATCH_THRESHOLD`: probe mốc `i` = `MATCH + BONUS[i]`; nhận diện ở final = `MATCH`; ghi centroid = `MATCH + ADAPT_MARGIN`.
- Fail-open tuyệt đối: không nhận diện được ⇒ lùi về hành vi không-lọc, **không bao giờ** lùi về khoá cứng.
- Đường nóng (probe) **chỉ đọc**, không bao giờ ghi centroid. Ghi chỉ xảy ra trong `finalize()`.
- Hành vi khi `ADDRESSEE_GATE_MODE=off` phải giữ nguyên: verdict không khớp → `vad.set_speaking()`, agent nói tiếp liền mạch, **không** khựng.
- Không tạo branch mới, không push, không merge. Commit local trên branch hiện tại (`sql-agent`).
- Giữ prefix `[Speaker]` ở mọi log để bộ màu vàng/tím trong `logging_config.py` (`_SPK_NOMATCH_MARKS = ("non-speaker", "unknown")`) tiếp tục nhận diện được.

---

### Task 1: Config — bộ env mới, parser CSV, fail-loud

**Files:**
- Modify: `src/noble_agent/config.py:209-223` (khối speaker/SPV)
- Modify: `.env:178-199`, `.env.example` (khối tương ứng)
- Test: `tests/unit/test_config_gate_speaker.py`

**Interfaces:**
- Consumes: `UnifiedSettings` (pydantic-settings) đã có.
- Produces:
  - Fields: `spv_probe_marks_sec: str`, `spv_probe_bonus: str`, `spv_probe_tail_window_sec: float`, `spv_probe_tail_hop_sec: float`, `spv_enroll_window_sec: float`, `spv_enroll_hop_sec: float`, `spv_enroll_consensus_sim: float`, `spv_enroll_min_cluster: int`, `spv_adapt_margin: float`, `spv_max_identities: int`, `spv_mismatch_streak_max: int`, `spv_utt_cap_sec: float`
  - `parse_probe_schedule(marks_csv: str, bonus_csv: str, match_threshold: float) -> tuple[tuple[float, ...], tuple[float, ...]]` — module-level trong `config.py`, trả `(marks, thresholds)` với `thresholds[i] = match_threshold + bonus[i]`
  - Xoá: `speaker_interrupt_min_sec`, `spv_chunk_sec`, `speaker_embed_window_sec`

- [ ] **Step 1: Write the failing test**

Thêm vào `tests/unit/test_config_gate_speaker.py`:

```python
import pytest

from noble_agent.config import parse_probe_schedule


def test_spv_registry_defaults():
    assert _default("spv_probe_marks_sec") == "0.25,0.4,0.6,0.9,1.3"
    assert _default("spv_probe_bonus") == "0.15,0.1,0.05,0,0"
    assert _default("spv_probe_tail_window_sec") == 1.5
    assert _default("spv_probe_tail_hop_sec") == 1.0
    assert _default("spv_enroll_window_sec") == 1.5
    assert _default("spv_enroll_hop_sec") == 0.75
    assert _default("spv_enroll_consensus_sim") == 0.5
    assert _default("spv_enroll_min_cluster") == 2
    assert _default("spv_adapt_margin") == 0.1
    assert _default("spv_max_identities") == 4
    assert _default("spv_mismatch_streak_max") == 2
    assert _default("spv_utt_cap_sec") == 30.0
    assert _default("spv_max_centroids") == 10


def test_removed_fields_are_gone():
    for name in ("speaker_interrupt_min_sec", "spv_chunk_sec", "speaker_embed_window_sec"):
        assert name not in UnifiedSettings.model_fields


def test_parse_probe_schedule_applies_bonus_to_base_threshold():
    marks, thresholds = parse_probe_schedule("0.25,0.4,0.6", "0.15,0.1,0", 0.5)
    assert marks == (0.25, 0.4, 0.6)
    assert thresholds == pytest.approx((0.65, 0.6, 0.5))


def test_parse_probe_schedule_rejects_length_mismatch():
    with pytest.raises(ValueError, match="cùng số phần tử"):
        parse_probe_schedule("0.25,0.4", "0.15", 0.5)


def test_parse_probe_schedule_rejects_non_increasing_marks():
    with pytest.raises(ValueError, match="tăng dần"):
        parse_probe_schedule("0.4,0.25", "0,0", 0.5)


def test_parse_probe_schedule_rejects_empty():
    with pytest.raises(ValueError, match="rỗng"):
        parse_probe_schedule("", "", 0.5)


def test_parse_probe_schedule_rejects_threshold_out_of_range():
    with pytest.raises(ValueError, match="ngoài khoảng"):
        parse_probe_schedule("0.25,0.4", "0.6,0.5", 0.5)  # 0.5+0.6 = 1.1 > 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_config_gate_speaker.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_probe_schedule'`

- [ ] **Step 3: Write the parser and fields**

Trong `src/noble_agent/config.py`, thêm module-level function (đặt ngay trên `class UnifiedSettings`):

```python
def parse_probe_schedule(
    marks_csv: str, bonus_csv: str, match_threshold: float
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """CSV → (mốc probe, ngưỡng probe). Ngưỡng = match_threshold + bonus[i].

    CSV chứ không phải list[float]: pydantic-settings đòi cú pháp JSON cho kiểu
    list, nên "0.25,0.4" trong .env sẽ nổ khi parse.
    """
    marks = tuple(float(x) for x in marks_csv.split(",") if x.strip())
    bonus = tuple(float(x) for x in bonus_csv.split(",") if x.strip())
    if not marks or not bonus:
        raise ValueError("SPV_PROBE_MARKS_SEC / SPV_PROBE_BONUS không được rỗng")
    if len(marks) != len(bonus):
        raise ValueError(
            f"SPV_PROBE_MARKS_SEC ({len(marks)}) và SPV_PROBE_BONUS ({len(bonus)}) phải cùng số phần tử"
        )
    if any(b <= a for a, b in zip(marks, marks[1:], strict=True)):
        raise ValueError(f"SPV_PROBE_MARKS_SEC phải tăng dần nghiêm ngặt: {marks}")
    thresholds = tuple(match_threshold + b for b in bonus)
    if any(not (0.0 < t <= 1.0) for t in thresholds):
        raise ValueError(f"ngưỡng probe ngoài khoảng (0, 1]: {thresholds}")
    return marks, thresholds
```

Trong `UnifiedSettings`, **xoá** ba dòng `speaker_interrupt_min_sec`, `spv_chunk_sec`, `speaker_embed_window_sec`, và thay khối `# ── Parallel SPV ──` bằng:

```python
    # ── Speaker registry + fast barge-in (spec 2026-09-03) ────────────────────
    # Ba ngưỡng thực thi đều suy ra từ speaker_match_threshold: probe mốc i =
    # MATCH + bonus[i]; nhận diện ở final = MATCH; ghi centroid = MATCH + adapt_margin.
    spv_probe_marks_sec: str = "0.25,0.4,0.6,0.9,1.3"  # mốc embed tích luỹ từ đầu utterance
    spv_probe_bonus: str = "0.15,0.1,0.05,0,0"  # siết thêm cho từng mốc (cửa sổ ngắn → chặt hơn)
    spv_probe_tail_window_sec: float = 1.5  # hết chuỗi mốc → cửa sổ TRƯỢT dài bấy nhiêu
    spv_probe_tail_hop_sec: float = 1.0  # nhịp trượt giai đoạn đuôi
    spv_enroll_window_sec: float = 1.5  # cửa sổ trượt khi enroll
    spv_enroll_hop_sec: float = 0.75  # bước trượt (chồng lấn 50%)
    spv_enroll_consensus_sim: float = 0.5  # thang RIÊNG: hai lát cùng câu nói, không neo vào MATCH
    spv_enroll_min_cluster: int = 2  # cụm nhỏ hơn → không enroll (fail-open, để tập rỗng)
    spv_adapt_margin: float = 0.1  # siết thêm khi GHI centroid; 0 = hành vi spec 2026-08-28
    spv_max_identities: int = 4  # cap FIFO danh tính mỗi phiên
    spv_max_centroids: int = 10  # cap FIFO centroid mỗi danh tính
    spv_mismatch_streak_max: int = 2  # số final "không khớp ai" liên tiếp trước khi bỏ asker
    spv_utt_cap_sec: float = 30.0  # cap PCM giữ cho một utterance
```

Thêm validator vào `UnifiedSettings` (fail-loud lúc khởi động):

```python
    @model_validator(mode="after")
    def _validate_probe_schedule(self):
        if self.speaker_mode != "off":
            parse_probe_schedule(self.spv_probe_marks_sec, self.spv_probe_bonus, self.speaker_match_threshold)
        return self
```

Nếu `model_validator` chưa được import, thêm vào dòng import pydantic: `from pydantic import Field, model_validator`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_config_gate_speaker.py -v`
Expected: PASS (toàn bộ file)

- [ ] **Step 5: Cập nhật .env và .env.example**

Trong cả hai file, xoá ba dòng `SPEAKER_INTERRUPT_MIN_SEC=...`, `SPV_CHUNK_SEC=...` (nếu có), `SPEAKER_EMBED_WINDOW_SEC=...`, rồi thêm dưới `SPEAKER_MATCH_THRESHOLD`:

```bash
# Speaker registry + fast barge-in (spec 2026-09-03).
# Ngưỡng gốc là SPEAKER_MATCH_THRESHOLD ở trên; hai dòng BONUS/MARGIN chỉ siết thêm.
SPV_PROBE_MARKS_SEC=0.25,0.4,0.6,0.9,1.3   # mốc embed tích luỹ; mốc đầu = độ trễ ngắt tốt nhất
SPV_PROBE_BONUS=0.15,0.1,0.05,0,0          # siết thêm cho từng mốc, phải cùng số phần tử
SPV_PROBE_TAIL_WINDOW_SEC=1.5              # hết mốc → cửa sổ trượt (bắt người chen giữa utterance)
SPV_PROBE_TAIL_HOP_SEC=1.0
SPV_ENROLL_WINDOW_SEC=1.5                  # cửa sổ trượt khi enroll
SPV_ENROLL_HOP_SEC=0.75
SPV_ENROLL_CONSENSUS_SIM=0.5               # 2 cửa sổ coi là cùng giọng khi cosine ≥ ngưỡng này
SPV_ENROLL_MIN_CLUSTER=2                   # cụm nhỏ hơn → KHÔNG enroll (thà rỗng còn hơn rác)
SPV_ADAPT_MARGIN=0.1                       # siết thêm khi GHI centroid; 0 = tắt
SPV_MAX_IDENTITIES=4                       # cap danh tính mỗi phiên
SPV_MAX_CENTROIDS=10
SPV_MISMATCH_STREAK_MAX=2                  # van thoát khi danh tính asker sai
SPV_UTT_CAP_SEC=30
```

- [ ] **Step 6: Lint + commit**

```bash
make lint
git add src/noble_agent/config.py .env .env.example tests/unit/test_config_gate_speaker.py
git commit -m "feat(spv): config cho speaker registry + probe tích luỹ

Thêm 12 field SPV mới + parse_probe_schedule (CSV → mốc/ngưỡng, fail-loud
lúc khởi động). Xoá speaker_interrupt_min_sec / spv_chunk_sec /
speaker_embed_window_sec — ngữ nghĩa đã đổi, giữ tên cũ là bẫy cho phiên sau."
```

---

### Task 2: `SpeakerRegistry` — N danh tính sống cả phiên

**Files:**
- Modify: `src/noble_agent/voice/speaker_tracker.py` (thêm `ObserveResult` + `SpeakerRegistry`; `CentroidSet` giữ nguyên)
- Test: `tests/unit/test_speaker_registry.py` (tạo mới)

**Interfaces:**
- Consumes: `CentroidSet(threshold=..., max_centroids=...)`, `_normalize`, `_cosine` — đã có trong cùng file.
- Produces:
  ```python
  @dataclass
  class ObserveResult:
      identity: int | None
      is_new: bool
      best_sim: float

  class SpeakerRegistry:
      def __init__(self, *, match_threshold: float, adapt_margin: float,
                   max_identities: int, max_centroids: int) -> None
      @property
      def empty(self) -> bool
      @property
      def asker(self) -> int | None
      def identify(self, emb: np.ndarray) -> tuple[int | None, float]
      def match_asker(self, emb: np.ndarray, threshold: float) -> tuple[bool, float]
      def observe(self, embs: list[np.ndarray], *, allow_new: bool) -> ObserveResult
      def set_asker(self, identity: int) -> None
      def drop_asker(self) -> None
  ```

- [ ] **Step 1: Write the failing test**

Tạo `tests/unit/test_speaker_registry.py`:

```python
import numpy as np

from noble_agent.voice.speaker_tracker import SpeakerRegistry


def _vec(*xs: float) -> np.ndarray:
    return np.array(xs, dtype=np.float32)


A = _vec(0.0, 1.0)  # giọng A
B = _vec(1.0, 0.0)  # giọng B (trực giao với A)


def _reg(*, margin=0.1, max_identities=4, max_centroids=10) -> SpeakerRegistry:
    return SpeakerRegistry(
        match_threshold=0.5,
        adapt_margin=margin,
        max_identities=max_identities,
        max_centroids=max_centroids,
    )


class TestRegistryBasics:
    def test_empty_registry_matches_everyone(self) -> None:
        """Floor mở: chưa ai giữ lượt thì mọi người ngắt được (ngữ nghĩa auto-greeting)."""
        r = _reg()
        assert r.empty
        assert r.asker is None
        ok, sim = r.match_asker(A, 0.5)
        assert ok and sim == 1.0

    def test_observe_creates_identity_and_identify_finds_it(self) -> None:
        r = _reg()
        res = r.observe([A], allow_new=True)
        assert res.is_new and res.identity is not None
        ident, sim = r.identify(A)
        assert ident == res.identity and sim > 0.99

    def test_identify_returns_none_below_threshold(self) -> None:
        r = _reg()
        r.observe([A], allow_new=True)
        ident, sim = r.identify(B)
        assert ident is None and sim < 0.5

    def test_set_asker_scopes_match_asker_to_one_identity(self) -> None:
        r = _reg()
        a = r.observe([A], allow_new=True).identity
        r.observe([B], allow_new=True)
        r.set_asker(a)
        assert r.match_asker(A, 0.5)[0] is True
        assert r.match_asker(B, 0.5)[0] is False


class TestRegistryObserveBranches:
    def test_confident_match_writes_centroids(self) -> None:
        r = _reg()
        ident = r.observe([A], allow_new=True).identity
        near_a = _vec(0.1, 0.995)  # sim ~0.995 ≥ 0.5 + 0.1
        res = r.observe([near_a], allow_new=True)
        assert res.identity == ident and res.is_new is False
        assert len(r._identities[ident]) == 2  # đã ghi thêm

    def test_grey_zone_identifies_but_does_not_write(self) -> None:
        """0.5 ≤ sim < 0.6: nhận là người cũ (được ngắt lời) nhưng KHÔNG sửa danh tính."""
        r = _reg()
        ident = r.observe([A], allow_new=True).identity
        grey = _vec(0.85, 0.53)
        grey = grey / np.linalg.norm(grey)  # cos với A ≈ 0.53 → vùng xám
        res = r.observe([grey], allow_new=True)
        assert res.identity == ident and res.is_new is False
        assert len(r._identities[ident]) == 1  # KHÔNG ghi

    def test_new_voice_creates_second_identity(self) -> None:
        r = _reg()
        first = r.observe([A], allow_new=True).identity
        res = r.observe([B], allow_new=True)
        assert res.is_new and res.identity != first

    def test_allow_new_false_returns_none_instead_of_creating(self) -> None:
        """single mode: giọng lạ KHÔNG được tạo danh tính mới, nếu không cap FIFO
        sẽ đẩy chính danh tính phiên ra ngoài."""
        r = _reg(max_identities=1)
        first = r.observe([A], allow_new=True).identity
        res = r.observe([B], allow_new=False)
        assert res.identity is None and res.is_new is False
        assert r.identify(A)[0] == first  # danh tính phiên còn nguyên


class TestRegistryDriftGuard:
    def test_grey_zone_samples_never_widen_the_set(self) -> None:
        """Regression cho ADAPT_MARGIN: mẫu vùng biên liên tiếp không được nới tập.
        Nếu ngưỡng ghi = ngưỡng đọc, mỗi mẫu biên lại làm bàn đạp cho mẫu kế và
        danh tính trôi dần tới mức ai nói cũng khớp."""
        r = _reg()
        ident = r.observe([A], allow_new=True).identity
        grey = _vec(0.85, 0.53)
        grey = grey / np.linalg.norm(grey)
        for _ in range(10):
            r.observe([grey], allow_new=True)
        assert len(r._identities[ident]) == 1
        assert r.identify(B)[0] is None  # giọng trực giao vẫn không lọt


class TestRegistryCaps:
    def test_identity_cap_evicts_oldest(self) -> None:
        r = _reg(max_identities=2)
        first = r.observe([_vec(1.0, 0.0, 0.0)], allow_new=True).identity
        r.observe([_vec(0.0, 1.0, 0.0)], allow_new=True)
        r.observe([_vec(0.0, 0.0, 1.0)], allow_new=True)
        assert r.identify(_vec(1.0, 0.0, 0.0))[0] is None  # first đã bị đẩy ra
        assert first is not None

    def test_centroid_cap_per_identity(self) -> None:
        r = _reg(max_centroids=3)
        ident = r.observe([A], allow_new=True).identity
        for _ in range(5):
            r.observe([A], allow_new=True)
        assert len(r._identities[ident]) == 3


class TestRegistryDropAsker:
    def test_drop_asker_reopens_the_floor(self) -> None:
        r = _reg()
        ident = r.observe([A], allow_new=True).identity
        r.set_asker(ident)
        r.drop_asker()
        assert r.asker is None
        assert r.identify(A)[0] is None  # danh tính đã bị xoá hẳn
        assert r.match_asker(B, 0.5)[0] is True  # floor mở lại
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_speaker_registry.py -v`
Expected: FAIL — `ImportError: cannot import name 'SpeakerRegistry'`

- [ ] **Step 3: Implement `ObserveResult` + `SpeakerRegistry`**

Thêm vào `src/noble_agent/voice/speaker_tracker.py`, ngay dưới `class CentroidSet` (thêm `from dataclasses import dataclass` vào phần import):

```python
@dataclass
class ObserveResult:
    """Kết quả nhận diện một utterance. KHÔNG chứa quyết định trao lượt —
    'ai giữ lượt' là việc của session (xem base_session drop rule)."""

    identity: int | None
    is_new: bool
    best_sim: float


class SpeakerRegistry:
    """N danh tính sống trọn phiên + con trỏ asker.

    Thay chỗ "một CentroidSet bị reset() mỗi turn" của spec 2026-08-28: ở đó mỗi
    turn dựng lại danh tính từ MỘT utterance duy nhất, nên mỗi turn là một canh
    bạc enroll và người cũ quay lại phải học lại từ đầu.

    Ngưỡng GHI chặt hơn ngưỡng ĐỌC (adapt_margin): match() lấy MAX cosine trên
    toàn tập, nên nếu hai ngưỡng bằng nhau thì mỗi mẫu vùng biên lại nới rộng
    biên, và biên mới làm bàn đạp cho lần nới kế — danh tính trôi dạt cho tới khi
    ai nói cũng khớp.
    """

    def __init__(
        self, *, match_threshold: float, adapt_margin: float, max_identities: int, max_centroids: int
    ) -> None:
        self._match_threshold = match_threshold
        self._write_threshold = match_threshold + adapt_margin
        self._max_identities = max(1, max_identities)
        self._max_centroids = max_centroids
        self._identities: dict[int, CentroidSet] = {}
        self._order: deque[int] = deque()  # FIFO eviction order
        self._next_id = 0
        self._asker: int | None = None

    @property
    def empty(self) -> bool:
        return not self._identities

    @property
    def asker(self) -> int | None:
        return self._asker

    def identify(self, emb: np.ndarray) -> tuple[int | None, float]:
        best_id, best_sim = None, 0.0
        for ident, cset in self._identities.items():
            _, sim = cset.match(emb)
            if sim > best_sim:
                best_id, best_sim = ident, sim
        if best_id is None or best_sim < self._match_threshold:
            return None, best_sim
        return best_id, best_sim

    def match_asker(self, emb: np.ndarray, threshold: float) -> tuple[bool, float]:
        """Fail-open: chưa có asker ⇒ floor mở, mọi người ngắt được (auto-greeting)."""
        if self._asker is None or self._asker not in self._identities:
            return True, 1.0
        _, sim = self._identities[self._asker].match(emb)
        return sim >= threshold, sim

    def observe(self, embs: list[np.ndarray], *, allow_new: bool) -> ObserveResult:
        if not embs:
            return ObserveResult(identity=None, is_new=False, best_sim=0.0)
        ident, sim = self.identify(embs[0])
        if ident is not None:
            if sim >= self._write_threshold:  # chắc chắn → được phép sửa danh tính
                for e in embs:
                    self._identities[ident].add(e)
            return ObserveResult(identity=ident, is_new=False, best_sim=sim)
        if not allow_new:
            return ObserveResult(identity=None, is_new=False, best_sim=sim)
        return ObserveResult(identity=self._create(embs), is_new=True, best_sim=sim)

    def _create(self, embs: list[np.ndarray]) -> int:
        ident = self._next_id
        self._next_id += 1
        cset = CentroidSet(threshold=self._match_threshold, max_centroids=self._max_centroids)
        for e in embs:
            cset.add(e)
        self._identities[ident] = cset
        self._order.append(ident)
        while len(self._order) > self._max_identities:
            evicted = self._order.popleft()
            self._identities.pop(evicted, None)
            if self._asker == evicted:
                self._asker = None
        return ident

    def set_asker(self, identity: int) -> None:
        if identity in self._identities:
            self._asker = identity

    def drop_asker(self) -> None:
        """Van thoát: danh tính asker rõ ràng không mô tả được người đang nói —
        xoá nó và để floor mở còn hơn giữ một chuẩn sai (spec §4.3)."""
        if self._asker is not None:
            self._identities.pop(self._asker, None)
            if self._asker in self._order:
                self._order.remove(self._asker)
            logger.info("[Speaker] asker identity dropped — floor reopened")
            self._asker = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_speaker_registry.py -v`
Expected: PASS — 12 test

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/voice/speaker_tracker.py tests/unit/test_speaker_registry.py
git commit -m "feat(spv): SpeakerRegistry — N danh tính sống cả phiên

Thay 'một CentroidSet reset mỗi turn' bằng registry + con trỏ asker. Ngưỡng
ghi chặt hơn ngưỡng đọc (adapt_margin) chặn trôi dạt danh tính; allow_new=False
bảo vệ danh tính phiên của mode single khỏi cap FIFO."
```

---

### Task 3: `SpeakerTracker` — probe cửa sổ tích luỹ

**Files:**
- Modify: `src/noble_agent/voice/speaker_tracker.py` (`SpeakerTracker.__init__`, thay `_next_cut_bytes`/`_maybe_cut`/`_label_chunk`)
- Test: `tests/unit/test_speaker_tracker.py` (thay `TestSpeakerTrackerCadence` và `_tracker` helper)

**Interfaces:**
- Consumes: `SpeakerRegistry.match_asker(emb, threshold)` (Task 2).
- Produces:
  ```python
  class SpeakerTracker:
      def __init__(self, *, embed, registry: SpeakerRegistry, sample_rate: int,
                   probe_marks_sec: tuple[float, ...], probe_thresholds: tuple[float, ...],
                   probe_tail_window_sec: float, probe_tail_hop_sec: float,
                   enroll_window_sec: float, enroll_hop_sec: float,
                   enroll_consensus_sim: float, enroll_min_cluster: int,
                   min_enroll_sec: float, utt_cap_sec: float, single_identity: bool,
                   on_verdict, spawn_bg) -> None
      def begin_utterance(self) -> None
      def feed(self, pcm: bytes) -> None
  ```
  `on_verdict(label, sim, idx)` giữ nguyên chữ ký cũ — `base_session._on_speaker_verdict` không đổi.

- [ ] **Step 1: Write the failing test**

Thay `_tracker` helper trong `tests/unit/test_speaker_tracker.py` bằng:

```python
from noble_agent.voice.speaker_tracker import SpeakerRegistry, SpeakerTracker


def _tracker(
    embedder,
    *,
    registry=None,
    marks=(0.25, 0.5),
    thresholds=(0.65, 0.5),
    tail_window=1.5,
    tail_hop=1.0,
    on_verdict=None,
    single_identity=False,
) -> SpeakerTracker:
    return SpeakerTracker(
        embed=embedder,
        registry=registry
        or SpeakerRegistry(match_threshold=0.5, adapt_margin=0.1, max_identities=4, max_centroids=10),
        sample_rate=SR,
        probe_marks_sec=marks,
        probe_thresholds=thresholds,
        probe_tail_window_sec=tail_window,
        probe_tail_hop_sec=tail_hop,
        enroll_window_sec=1.5,
        enroll_hop_sec=0.75,
        enroll_consensus_sim=0.5,
        enroll_min_cluster=2,
        min_enroll_sec=1.0,
        utt_cap_sec=30.0,
        single_identity=single_identity,
        on_verdict=on_verdict,
        spawn_bg=_spawn,
    )
```

Thay `class TestSpeakerTrackerCadence` bằng:

```python
class TestProbeAccumulating:
    async def test_probe_windows_are_cumulative_from_utterance_start(self) -> None:
        """Mốc sau phải CHỨA audio của mốc trước — đây là tính chất khiến độ tin cậy
        tăng theo thời gian, thứ mà span rời 0.8s của bản cũ không có."""
        emb = FakeEmbedder([OTHER, OTHER])
        t = _tracker(emb, marks=(0.25, 0.5), thresholds=(0.65, 0.5))
        reg = t._registry
        reg.set_asker(reg.observe([SPK], allow_new=True).identity)
        t.begin_utterance()
        t.feed(_pcm(0.25))
        await asyncio.sleep(0)
        t.feed(_pcm(0.25))
        await asyncio.sleep(0)
        assert emb.calls == [int(0.25 * BPS), int(0.5 * BPS)]

    async def test_first_probe_fires_at_first_mark_not_at_800ms(self) -> None:
        emb = FakeEmbedder([SPK])
        t = _tracker(emb, marks=(0.25, 0.5), thresholds=(0.65, 0.5))
        t.begin_utterance()
        t.feed(_pcm(0.25))
        await asyncio.sleep(0)
        assert emb.calls == [int(0.25 * BPS)]

    async def test_probe_stops_after_a_decisive_match(self) -> None:
        """Quyết được thì dừng chuỗi mốc — không probe thừa."""
        emb = FakeEmbedder([SPK, SPK])
        t = _tracker(emb, marks=(0.25, 0.5), thresholds=(0.65, 0.5))
        reg = t._registry
        reg.set_asker(reg.observe([SPK], allow_new=True).identity)
        t.begin_utterance()
        t.feed(_pcm(0.25))
        await asyncio.sleep(0)
        t.feed(_pcm(0.25))
        await asyncio.sleep(0)
        assert len(emb.calls) == 1

    async def test_per_mark_threshold_is_applied(self) -> None:
        """Cùng một sim: trượt ngưỡng chặt của mốc 0, qua ngưỡng lỏng của mốc 1.
        Đây là thứ cho phép quyết sớm mà không quyết ẩu."""
        labels: list[str] = []

        async def _record(label: str, sim: float, idx: int) -> None:
            labels.append(label)

        emb = FakeEmbedder([SPK, SPK])
        t = _tracker(emb, marks=(0.25, 0.5), thresholds=(1.0, 0.3), on_verdict=_record)
        reg = t._registry
        half = _vec(0.7071, 0.7071)  # cos với SPK ≈ 0.707: < 1.0 nhưng > 0.3
        reg.set_asker(reg.observe([half], allow_new=True).identity)
        t.begin_utterance()
        t.feed(_pcm(0.25))
        await asyncio.sleep(0)
        t.feed(_pcm(0.25))
        await asyncio.sleep(0)
        assert labels == ["non-speaker", "speaker"]

    async def test_tail_switches_to_sliding_window(self) -> None:
        """Hết chuỗi mốc → cửa sổ TRƯỢT: tích luỹ tiếp sẽ trộn giọng người lạ nói
        trước với khách chen sau thành một embedding lai."""
        emb = FakeEmbedder([OTHER, OTHER, OTHER])
        t = _tracker(emb, marks=(0.25,), thresholds=(0.65,), tail_window=1.0, tail_hop=1.0)
        reg = t._registry
        reg.set_asker(reg.observe([SPK], allow_new=True).identity)
        t.begin_utterance()
        t.feed(_pcm(0.25))
        await asyncio.sleep(0)
        t.feed(_pcm(1.0))
        await asyncio.sleep(0)
        assert emb.calls[-1] == int(1.0 * BPS)  # trượt, KHÔNG phải 1.25s tích luỹ
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_speaker_tracker.py -k Probe -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'registry'`

- [ ] **Step 3: Rewrite the probe engine**

Trong `SpeakerTracker`, thay `__init__` và bỏ `_next_cut_bytes`/`_maybe_cut`/`_label_chunk` cũ:

```python
    def __init__(
        self,
        *,
        embed: Callable[[bytes], Awaitable[np.ndarray | None]],
        registry: SpeakerRegistry,
        sample_rate: int,
        probe_marks_sec: tuple[float, ...],
        probe_thresholds: tuple[float, ...],
        probe_tail_window_sec: float,
        probe_tail_hop_sec: float,
        enroll_window_sec: float,
        enroll_hop_sec: float,
        enroll_consensus_sim: float,
        enroll_min_cluster: int,
        min_enroll_sec: float,
        utt_cap_sec: float,
        single_identity: bool,
        on_verdict: Callable[[str, float, int], Awaitable[None]] | None,
        spawn_bg: Callable[[Awaitable], asyncio.Task],
    ) -> None:
        self._embed = embed
        self._registry = registry
        self._bps = sample_rate * 2  # PCM16 mono
        self._marks = probe_marks_sec
        self._thresholds = probe_thresholds
        self._tail_window = probe_tail_window_sec
        self._tail_hop = probe_tail_hop_sec
        self._enroll_window = enroll_window_sec
        self._enroll_hop = enroll_hop_sec
        self._consensus_sim = enroll_consensus_sim
        self._min_cluster = enroll_min_cluster
        self._min_enroll_sec = min_enroll_sec
        self._utt_cap = int(utt_cap_sec * self._bps)
        self._single_identity = single_identity
        self._on_verdict = on_verdict
        self._spawn_bg = spawn_bg

        self._utt_pcm = bytearray()  # toàn bộ utterance hiện tại
        self._labels: list[str] = []
        self._sims: list[float] = []
        self._mark_idx = 0  # mốc kế tiếp trong self._marks
        self._decided = False  # đã quyết trong chuỗi mốc chưa
        self._next_tail_sec = 0.0  # mốc trượt kế tiếp (giai đoạn đuôi)
        self._gen = 0
        self._inflight: asyncio.Task | None = None
        self._final_utt_pcm: bytes | None = None
        self._final_sims: list[float] = []

    def begin_utterance(self) -> None:
        """Utterance mới: reset lịch probe. Embed inflight của utterance trước tự
        discard qua gen-guard khi land."""
        self._gen += 1
        self._utt_pcm = bytearray()
        self._labels = []
        self._sims = []
        self._mark_idx = 0
        self._decided = False
        self._next_tail_sec = 0.0

    def feed(self, pcm: bytes) -> None:
        self._utt_pcm.extend(pcm)
        if len(self._utt_pcm) > self._utt_cap:
            del self._utt_pcm[: len(self._utt_pcm) - self._utt_cap]
        self._maybe_probe()

    def _elapsed_sec(self) -> float:
        return len(self._utt_pcm) / self._bps

    def _maybe_probe(self) -> None:
        if self._inflight is not None:
            return
        now = self._elapsed_sec()
        if not self._decided and self._mark_idx < len(self._marks):
            mark = self._marks[self._mark_idx]
            if now >= mark:
                seg = bytes(self._utt_pcm[: int(mark * self._bps)])  # TÍCH LUỸ từ đầu
                threshold = self._thresholds[self._mark_idx]
                self._mark_idx += 1
                self._next_tail_sec = mark + self._tail_hop
                self._inflight = self._spawn_bg(self._probe(seg, threshold, self._gen))
            return
        # Giai đoạn đuôi: cửa sổ TRƯỢT, không tích luỹ tiếp — tích luỹ sẽ trộn
        # giọng người nói trước với người chen sau thành một embedding lai.
        if self._next_tail_sec <= 0.0:
            self._next_tail_sec = now + self._tail_hop
            return
        if now >= self._next_tail_sec:
            width = int(min(self._tail_window, now) * self._bps)
            seg = bytes(self._utt_pcm[-width:])
            threshold = self._thresholds[-1]
            self._next_tail_sec = now + self._tail_hop
            self._inflight = self._spawn_bg(self._probe(seg, threshold, self._gen))

    async def _probe(self, seg: bytes, threshold: float, gen: int) -> None:
        try:
            try:
                emb = await self._embed(seg)
            except Exception:  # noqa: BLE001 — embed fail → nhãn unknown, không ngắt
                logger.warning("[Speaker] embed raised, probe → unknown", exc_info=True)
                emb = None
            if gen != self._gen:
                logger.info("[Speaker] stale probe verdict discarded (utterance moved)")
                return
            if emb is None:
                label, sim = "unknown", float("nan")
            else:
                ok, sim = self._registry.match_asker(emb, threshold)
                label = "speaker" if ok else "non-speaker"
                if ok:
                    self._decided = True
            idx = len(self._labels)
            self._labels.append(label)
            self._sims.append(sim)
            logger.info(
                "[Speaker] probe#%d %.2fs → %s (sim=%.3f, thr=%.2f)",
                idx,
                len(seg) / self._bps,
                label,
                sim,
                threshold,
            )
            if self._on_verdict is not None:
                await self._on_verdict(label, sim, idx)
        finally:
            self._inflight = None
            if gen == self._gen:
                self._maybe_probe()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_speaker_tracker.py -k Probe -v`
Expected: PASS — 5 test

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/voice/speaker_tracker.py tests/unit/test_speaker_tracker.py
git commit -m "feat(spv): probe cửa sổ tích luỹ thay span rời 0.8s

Verdict đầu tiên về từ mốc 0.25s thay vì 0.8s, và mốc sau chứa audio mốc
trước nên độ tin cậy tăng theo thời gian. Hết chuỗi mốc chuyển cửa sổ trượt
để bắt người chen giữa utterance."
```

---

### Task 4: `finalize()` — cụm nhất quán + `UtteranceVerdict`

**Files:**
- Modify: `src/noble_agent/voice/speaker_tracker.py` (thay `finalize`, xoá `_enroll`/`enroll_from_utterance`/`reset`/`_enroll_gen`/`_TAIL_MIN_SEC`)
- Test: `tests/unit/test_speaker_tracker.py` (thay `TestSpeakerTrackerEnrollment`, `TestSpeakerTrackerFinalize`, `TestSpeakerTrackerEnrollEpoch`, `TestSpeakerTrackerEnrollSnapshot`)

**Interfaces:**
- Consumes: `SpeakerRegistry.observe(embs, allow_new=...)` (Task 2), `_cosine` (đã có).
- Produces:
  ```python
  @dataclass
  class UtteranceVerdict:
      identity: int | None
      is_new: bool
      cluster_size: int
      best_sim: float
      probe_labels: list[str]

  class SpeakerTracker:
      async def finalize(self) -> UtteranceVerdict
  ```

- [ ] **Step 1: Write the failing test**

Thay các class enrollment cũ trong `tests/unit/test_speaker_tracker.py` bằng:

```python
class TestConsensusEnroll:
    async def test_consistent_windows_enroll_all(self) -> None:
        emb = FakeEmbedder([SPK, SPK, SPK])
        t = _tracker(emb)
        t.begin_utterance()
        t.feed(_pcm(3.0))
        v = await t.finalize()
        assert v.cluster_size >= 2 and v.is_new and v.identity is not None

    async def test_outlier_window_is_excluded_from_the_cluster(self) -> None:
        """W2 lạc loài (trực giao) không được thành centroid — đây là chốt chống
        'audio tồi biến thành chuẩn danh tính' của bản 2026-08-28."""
        emb = FakeEmbedder([SPK, OTHER, SPK])
        t = _tracker(emb)
        t.begin_utterance()
        t.feed(_pcm(3.0))
        v = await t.finalize()
        assert v.cluster_size == 2
        assert t._registry.identify(SPK)[0] == v.identity
        assert t._registry.identify(OTHER)[0] is None  # giọng lạ không lọt vào danh tính

    async def test_no_consensus_enrolls_nothing_and_leaves_registry_untouched(self) -> None:
        """Ba cửa sổ đôi một khác nhau → không biết giọng nào là khách → không ghi gì.
        Tập rỗng = floor mở = fail-OPEN, ngược với centroid rác khoá cứng cả turn."""
        v1, v2, v3 = _vec(1.0, 0.0, 0.0), _vec(0.0, 1.0, 0.0), _vec(0.0, 0.0, 1.0)
        emb = FakeEmbedder([v1, v2, v3])
        t = _tracker(emb)
        t.begin_utterance()
        t.feed(_pcm(3.0))
        v = await t.finalize()
        assert v.identity is None and v.cluster_size < 2
        assert t._registry.empty

    async def test_utterance_shorter_than_min_enroll_skips_enrollment(self) -> None:
        emb = FakeEmbedder([SPK])
        t = _tracker(emb)
        t.begin_utterance()
        t.feed(_pcm(0.6))
        v = await t.finalize()
        assert v.identity is None and t._registry.empty

    async def test_single_identity_does_not_create_a_second(self) -> None:
        emb = FakeEmbedder([SPK, SPK, OTHER, OTHER])
        t = _tracker(emb, single_identity=True)
        t.begin_utterance()
        t.feed(_pcm(2.0))
        first = await t.finalize()
        t.begin_utterance()
        t.feed(_pcm(2.0))
        second = await t.finalize()
        assert first.identity is not None
        assert second.identity is None and second.is_new is False


class TestFinalizeRaceGuard:
    async def test_finalize_binds_to_the_utterance_it_closed(self) -> None:
        """Regression ec1b432/297fd3f: begin_utterance() giữa chừng finalize không
        được kéo nhãn/PCM của utterance kế vào verdict đang chốt."""
        emb = FakeEmbedder([SPK, SPK, SPK])
        t = _tracker(emb)
        t.begin_utterance()
        t.feed(_pcm(3.0))
        task = asyncio.ensure_future(t.finalize())
        await asyncio.sleep(0)
        t.begin_utterance()  # utterance mới chen vào
        t.feed(_pcm(0.1))
        v = await task
        assert v.probe_labels is not None  # không nổ, không lấy nhãn utterance mới
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_speaker_tracker.py -k "Consensus or FinalizeRace" -v`
Expected: FAIL — `AttributeError: 'SpeakerTracker' object has no attribute '_registry'` hoặc `finalize` trả `list`

- [ ] **Step 3: Implement consensus enrollment**

Thêm `UtteranceVerdict` dưới `ObserveResult`, và thay `finalize`/`_enroll` trong `SpeakerTracker`:

```python
@dataclass
class UtteranceVerdict:
    identity: int | None
    is_new: bool
    cluster_size: int
    best_sim: float
    probe_labels: list[str]
```

```python
    async def finalize(self) -> UtteranceVerdict:
        """Đường nguội: đợi probe inflight, cắt cửa sổ trượt, lọc cụm nhất quán,
        rồi observe() vào registry. Đây là nơi DUY NHẤT được ghi centroid.

        Chụp gen + list nhãn + PCM đồng bộ ở đầu hàm (fix ec1b432/297fd3f): finalize
        có await, nên một chunk đã qua gate có thể gọi begin_utterance() giữa chừng
        và rebind self._labels sang list của utterance kế.
        """
        gen = self._gen
        labels = self._labels
        pcm = bytes(self._utt_pcm)
        self._final_utt_pcm = pcm
        self._final_sims = self._sims
        while self._inflight is not None:
            inflight = self._inflight
            try:
                await inflight
            except Exception:  # noqa: BLE001 — task tự log lỗi của nó
                if self._inflight is inflight:
                    self._inflight = None
        empty = UtteranceVerdict(
            identity=None, is_new=False, cluster_size=0, best_sim=0.0, probe_labels=list(labels)
        )
        if len(pcm) < int(self._min_enroll_sec * self._bps):
            return empty
        windows = await self._embed_windows(pcm)
        cluster = self._largest_consensus(windows)
        if len(cluster) < self._min_cluster:
            logger.info(
                "[Speaker] no consensus cluster (%d/%d windows) — enroll skipped, floor stays open",
                len(cluster),
                len(windows),
            )
            return UtteranceVerdict(
                identity=None, is_new=False, cluster_size=len(cluster), best_sim=0.0, probe_labels=list(labels)
            )
        allow_new = not self._single_identity or self._registry.empty
        res = self._registry.observe(cluster, allow_new=allow_new)
        logger.info(
            "[Speaker] utterance → identity=%s new=%s cluster=%d/%d sim=%.3f",
            res.identity,
            res.is_new,
            len(cluster),
            len(windows),
            res.best_sim,
        )
        if gen != self._gen:
            logger.info("[Speaker] finalize on stale utterance — verdict still bound to it")
        return UtteranceVerdict(
            identity=res.identity,
            is_new=res.is_new,
            cluster_size=len(cluster),
            best_sim=res.best_sim,
            probe_labels=list(labels),
        )

    async def _embed_windows(self, pcm: bytes) -> list[np.ndarray]:
        """Cửa sổ TRƯỢT chồng lấn: câu 3s cho 3 mẫu đối chiếu chéo được, thay vì
        1 centroid duy nhất không có gì để kiểm chứng (bản 2026-08-28)."""
        win = int(self._enroll_window * self._bps)
        hop = max(1, int(self._enroll_hop * self._bps))
        out: list[np.ndarray] = []
        for start in range(0, max(1, len(pcm) - win + hop), hop):
            seg = pcm[start : start + win]
            if len(seg) < int(self._min_enroll_sec * self._bps):
                break
            try:
                emb = await self._embed(seg)
            except Exception:  # noqa: BLE001 — bỏ cửa sổ lỗi, cụm tính trên phần còn lại
                logger.warning("[Speaker] embed raised, enroll window skipped", exc_info=True)
                emb = None
            if emb is not None:
                out.append(emb)
        return out

    def _largest_consensus(self, embs: list[np.ndarray]) -> list[np.ndarray]:
        """Tập con lớn nhất mà MỌI cặp trong đó có cosine ≥ consensus_sim.

        n ≤ ~10 cửa sổ nên quét tham lam từ mỗi hạt giống là đủ; không cần
        clustering thật.
        """
        if len(embs) <= 1:
            return list(embs)
        best: list[int] = []
        for seed in range(len(embs)):
            group = [seed]
            for cand in range(len(embs)):
                if cand == seed:
                    continue
                if all(_cosine(embs[cand], embs[m]) >= self._consensus_sim for m in group):
                    group.append(cand)
            if len(group) > len(best):
                best = group
        return [embs[i] for i in best]
```

Xoá khỏi file: `_TAIL_MIN_SEC`, `enroll_from_utterance`, `_enroll`, `reset`, `_enroll_gen`, `centroids_empty`, và các property `labels`/`sims`/`final_sims` nếu không còn ai đọc (giữ `final_sims` nếu `base_session` còn dùng — Task 5 sẽ xoá chỗ đọc).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_speaker_tracker.py -v`
Expected: PASS toàn file (các test cũ về span rời đã được thay ở Task 3)

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/voice/speaker_tracker.py tests/unit/test_speaker_tracker.py
git commit -m "feat(spv): enroll bằng cụm nhất quán, finalize trả UtteranceVerdict

Cửa sổ trượt 1.5s/hop 0.75s cho nhiều mẫu đối chiếu chéo; chỉ cụm lớn nhất
được enroll, cửa sổ lạc loài bị loại. Không có cụm ≥ MIN_CLUSTER → không ghi
gì, để tập rỗng (fail-open) thay vì biến audio tồi thành chuẩn danh tính."
```

---

### Task 5: `base_session` — wiring registry, bỏ hai `reset()`

**Files:**
- Modify: `src/noble_agent/server/base_session.py:48` (import), `:168-184` (dựng tracker), `:984-991` (xoá enrollment hook), `:1140-1141` (xoá reset cuối turn), `:233-246` (cảnh báo khởi động)
- Test: `tests/unit/test_base_session.py`

**Interfaces:**
- Consumes: `SpeakerRegistry`, `SpeakerTracker.__init__` (Task 2, 3), `parse_probe_schedule` (Task 1).
- Produces: `BaseSession._speaker_registry: SpeakerRegistry | None`; `_on_speaker_verdict(label, sim, idx)` **giữ nguyên chữ ký và hành vi**.

- [ ] **Step 1: Write the failing test**

Thêm vào `tests/unit/test_base_session.py`:

```python
class TestRegistryLifecycle:
    async def test_identity_survives_turn_end(self) -> None:
        """Bỏ reset() cuối turn: danh tính KHÔNG bị xoá khi agent nói xong.
        Regression cho lỗi 'mỗi turn tung xúc xắc lại'."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-reg")
            reg = session._speaker_registry
            ident = reg.observe([np.array([0.0, 1.0], dtype=np.float32)], allow_new=True).identity
            reg.set_asker(ident)
            await session._run_agent("xin chào")
            assert reg.asker == ident
            assert not reg.empty

    async def test_trigger_agent_no_longer_resets_or_enrolls(self) -> None:
        """Enrollment đã chuyển vào finalize(); _trigger_agent_for_text không được
        đụng vào danh tính nữa."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-reg2")
            assert not hasattr(session._speaker_tracker, "reset")
            assert not hasattr(session._speaker_tracker, "enroll_from_utterance")

    async def test_verdict_non_speaker_keeps_agent_talking(self) -> None:
        """ADDRESSEE_GATE_MODE=off: không khớp → agent nói tiếp liền mạch, KHÔNG khựng."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            c["settings"].addressee_gate_mode = "off"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-reg3")
            session._agent_task = asyncio.ensure_future(asyncio.sleep(5))
            session._handle_interrupt = AsyncMock()
            session.agent.pause_playback = MagicMock()
            session.vad.set_speaking = MagicMock()
            await session._on_speaker_verdict("non-speaker", 0.1, 0)
            session._handle_interrupt.assert_not_awaited()
            session.agent.pause_playback.assert_not_called()
            session.vad.set_speaking.assert_called_once()
            session._agent_task.cancel()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_base_session.py -k RegistryLifecycle -v`
Expected: FAIL — `AttributeError: 'BaseSession' object has no attribute '_speaker_registry'`

- [ ] **Step 3: Rewire base_session**

Dòng 48 — đổi import:

```python
from noble_agent.voice.speaker_tracker import SpeakerRegistry, SpeakerTracker
```

Dòng 168-184 — thay khối dựng tracker:

```python
        self._speaker_tracker: SpeakerTracker | None = None
        self._speaker_registry: SpeakerRegistry | None = None
        self._mismatch_streak = 0  # single-writer: _on_final (van thoát §4.3)
        if self._speaker_mode in ("single", "multi"):
            marks, thresholds = parse_probe_schedule(
                settings.spv_probe_marks_sec, settings.spv_probe_bonus, settings.speaker_match_threshold
            )
            single = self._speaker_mode == "single"
            self._speaker_registry = SpeakerRegistry(
                match_threshold=settings.speaker_match_threshold,
                adapt_margin=settings.spv_adapt_margin,
                # single: đúng MỘT danh tính cho cả phiên.
                max_identities=1 if single else settings.spv_max_identities,
                max_centroids=settings.spv_max_centroids,
            )
            self._speaker_tracker = SpeakerTracker(
                embed=self._spv_embed,
                registry=self._speaker_registry,
                sample_rate=settings.stt_sample_rate,
                probe_marks_sec=marks,
                probe_thresholds=thresholds,
                probe_tail_window_sec=settings.spv_probe_tail_window_sec,
                probe_tail_hop_sec=settings.spv_probe_tail_hop_sec,
                enroll_window_sec=settings.spv_enroll_window_sec,
                enroll_hop_sec=settings.spv_enroll_hop_sec,
                enroll_consensus_sim=settings.spv_enroll_consensus_sim,
                enroll_min_cluster=settings.spv_enroll_min_cluster,
                min_enroll_sec=settings.speaker_min_enroll_sec,
                utt_cap_sec=settings.spv_utt_cap_sec,
                single_identity=single,
                on_verdict=self._on_speaker_verdict,
                spawn_bg=self._spawn_bg,
            )
```

Thêm `parse_probe_schedule` vào import dòng 39:

```python
from noble_agent.config import parse_probe_schedule, resolve_speaker_mode, settings
```

Dòng 233-246 — cảnh báo khởi động, đổi vế trái sang mốc probe cuối:

```python
        if (
            self._speaker_tracker is not None
            and self._addr_gate_enabled
            and marks[-1] * 1000 < settings.addressee_min_speech_ms
        ):
            _warn_once(
                "spv_probe_last_mark_vs_addressee_min_speech_ms",
                "mốc probe cuối (%.0fms) < addressee_min_speech_ms (%dms) — "
                "floor->gate soft-pause skips the EpisodeTracker on the assumption that "
                "probe resolution already proves enough overlap-speech; that premise is "
                "voided by this config.",
                marks[-1] * 1000,
                settings.addressee_min_speech_ms,
            )
```

Dòng 984-991 — **xoá hẳn** khối `if self._speaker_tracker is not None:` chứa `reset()` + `enroll_from_utterance()` trong `_trigger_agent_for_text`.

Dòng 1140-1141 — **xoá hẳn** hai dòng `if self._speaker_tracker is not None and self._speaker_mode == "multi": self._speaker_tracker.reset()` trong `_run_agent` finally.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_base_session.py -k "RegistryLifecycle or Speaker" -v`
Expected: PASS (test drop-rule cũ vẫn đỏ — Task 6 sửa)

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/server/base_session.py tests/unit/test_base_session.py
git commit -m "refactor(spv): base_session dùng SpeakerRegistry, bỏ reset mỗi turn

Danh tính không còn bị xoá ở _trigger_agent_for_text và _run_agent finally —
enrollment đã chuyển vào finalize(). _on_speaker_verdict giữ nguyên hành vi:
không khớp thì agent nói tiếp liền mạch."
```

---

### Task 6: Drop rule 5 nhánh + van thoát mismatch streak

**Files:**
- Modify: `src/noble_agent/server/base_session.py:822-849` (khối speaker trong `_on_final`)
- Test: `tests/unit/test_base_session.py` (thay `TestParallelSpeakerFinal`)

**Interfaces:**
- Consumes: `UtteranceVerdict` (Task 4), `SpeakerRegistry.asker/set_asker/drop_asker` (Task 2).
- Produces: event `final_transcript` mang thêm `speaker_id: int | None`, giữ `speaker_labels`.

- [ ] **Step 1: Write the failing test**

Thay `class TestParallelSpeakerFinal` bằng:

```python
from noble_agent.voice.speaker_tracker import UtteranceVerdict


def _verdict(identity=None, is_new=False, cluster=2, sim=0.9, labels=None):
    return UtteranceVerdict(
        identity=identity,
        is_new=is_new,
        cluster_size=cluster,
        best_sim=sim,
        probe_labels=labels or ["speaker"],
    )


class TestFinalDropRule:
    async def test_first_utterance_of_call_is_never_dropped(self) -> None:
        """Nhánh 1: khách ngắt auto-greeting — chưa ai giữ lượt nên floor mở.
        Bản nháp spec từng drop đúng ca này."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop1")
            session._agent_task = asyncio.ensure_future(asyncio.sleep(5))
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=7, is_new=True))
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("bên em có dự án gì")
            session._trigger_agent_for_text.assert_awaited_once()
            session._agent_task.cancel()

    async def test_asker_final_is_kept_and_streak_resets(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop2")
            reg = session._speaker_registry
            ident = reg.observe([np.array([0.0, 1.0], dtype=np.float32)], allow_new=True).identity
            reg.set_asker(ident)
            session._mismatch_streak = 1
            session._agent_task = asyncio.ensure_future(asyncio.sleep(5))
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=ident))
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("cho anh hỏi thêm")
            session._trigger_agent_for_text.assert_awaited_once()
            assert session._mismatch_streak == 0
            session._agent_task.cancel()

    async def test_other_identity_mid_turn_is_dropped(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop3")
            reg = session._speaker_registry
            a = reg.observe([np.array([0.0, 1.0], dtype=np.float32)], allow_new=True).identity
            b = reg.observe([np.array([1.0, 0.0], dtype=np.float32)], allow_new=True).identity
            reg.set_asker(a)
            session._agent_task = asyncio.ensure_future(asyncio.sleep(5))
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=b))
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("người khác chen vào")
            session._trigger_agent_for_text.assert_not_awaited()
            assert reg.asker == a  # asker KHÔNG đổi
            session._agent_task.cancel()

    async def test_unidentified_final_is_kept_and_bumps_streak(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop4")
            reg = session._speaker_registry
            ident = reg.observe([np.array([0.0, 1.0], dtype=np.float32)], allow_new=True).identity
            reg.set_asker(ident)
            session._agent_task = asyncio.ensure_future(asyncio.sleep(5))
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=None, cluster=0))
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("không nhận diện được")
            session._trigger_agent_for_text.assert_awaited_once()
            assert session._mismatch_streak == 1
            session._agent_task.cancel()

    async def test_streak_limit_drops_asker_and_reopens_floor(self) -> None:
        """Van thoát: danh tính asker sai thì xoá nó đi, đừng khoá cứng người đang nói."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            c["settings"].spv_mismatch_streak_max = 2
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop5")
            reg = session._speaker_registry
            ident = reg.observe([np.array([0.0, 1.0], dtype=np.float32)], allow_new=True).identity
            reg.set_asker(ident)
            session._trigger_agent_for_text = AsyncMock()
            for _ in range(2):
                session._agent_task = asyncio.ensure_future(asyncio.sleep(5))
                session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=None, cluster=0))
                await session._on_final("vẫn không nhận ra")
                session._agent_task.cancel()
            assert reg.asker is None
            assert session._mismatch_streak == 0

    async def test_final_event_carries_speaker_id(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-drop6")
            session._speaker_tracker.finalize = AsyncMock(
                return_value=_verdict(identity=3, labels=["speaker", "non-speaker"])
            )
            sent: list[dict] = []
            session._send_event = AsyncMock(side_effect=lambda m: sent.append(m))
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("xin chào")
            evt = [m for m in sent if m["type"] == "final_transcript"][0]
            assert evt["speaker_id"] == 3
            assert evt["speaker_labels"] == ["speaker", "non-speaker"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_base_session.py -k FinalDropRule -v`
Expected: FAIL — `AttributeError: 'list' object has no attribute 'identity'`

- [ ] **Step 3: Rewrite the drop rule**

Thay khối `if self._speaker_tracker is not None:` (dòng ~822-849) trong `_on_final`:

```python
        if self._speaker_tracker is not None and self._speaker_registry is not None:
            verdict = await self._speaker_tracker.finalize()
            reg = self._speaker_registry
            logger.info(
                "[Speaker] final identity=%s new=%s cluster=%d sim=%.3f labels=%s text=%r",
                verdict.identity,
                verdict.is_new,
                verdict.cluster_size,
                verdict.best_sim,
                verdict.probe_labels,
                text,
            )
            await self._send_event(
                {
                    "type": "final_transcript",
                    "text": text,
                    "speaker_labels": verdict.probe_labels,
                    "speaker_id": verdict.identity,
                }
            )
            # Phạm vi drop: single = mọi final; multi = chỉ mid-turn (floor đang có chủ).
            enforce = self._speaker_mode == "single" or self._agent_is_speaking() or self._addr_paused
            if reg.asker is None:
                # Nhánh 1 — floor mở (đầu phiên / sau drop_asker): KHÔNG BAO GIỜ drop.
                # Đây là ca khách ngắt auto-greeting; drop ở đây là mất câu mở cuộc gọi.
                if verdict.identity is not None:
                    reg.set_asker(verdict.identity)
                self._mismatch_streak = 0
            elif verdict.identity is None:
                # Nhánh 2 — không đủ bằng chứng: fail-open, nhưng đếm để còn thoát ra.
                self._mismatch_streak += 1
                if self._mismatch_streak >= settings.spv_mismatch_streak_max:
                    logger.info(
                        "[Speaker] %d final liên tiếp không nhận diện được — bỏ asker, mở lại floor",
                        self._mismatch_streak,
                    )
                    reg.drop_asker()
                    self._mismatch_streak = 0
            elif verdict.identity == reg.asker:
                # Nhánh 3 — đúng người đang giữ lượt.
                self._mismatch_streak = 0
            elif enforce:
                # Nhánh 4/5 — danh tính khác (hoặc người mới) chen ngang giữa turn.
                # Danh tính mới đã được tạo trong finalize(), nên turn sau khi agent
                # im họ hỏi là được nhận ngay: đổi người xảy ra ở RANH GIỚI turn.
                logger.info(
                    "[Speaker] Dropped final — identity %s ≠ asker %s: %r", verdict.identity, reg.asker, text
                )
                if self._addr_paused:
                    self.agent.resume_playback()
                    self._addr_reset_episode()
                if self._agent_is_speaking():
                    self.vad.set_speaking()
                return
            else:
                # Agent đang im: floor mở cho người kế tiếp.
                reg.set_asker(verdict.identity)
                self._mismatch_streak = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_base_session.py -v`
Expected: PASS toàn file

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/server/base_session.py tests/unit/test_base_session.py
git commit -m "feat(spv): drop rule bằng chứng dương + van thoát mismatch streak

Chỉ drop khi nhận diện ĐƯỢC một danh tính khác asker, thay vì drop mọi thứ
không khớp asker — bằng chứng âm khiến một lần enroll hỏng nuốt luôn câu nói.
Câu đầu phiên (floor mở) không bao giờ bị drop; N final liên tiếp không nhận
diện được thì bỏ asker và mở lại floor."
```

---

### Task 7: Integration đổi người giữa cuộc + docs

**Files:**
- Test: `tests/unit/test_base_session.py` (thêm `TestSpeakerHandover`)
- Modify: `src/noble_agent/SMOKE.md:259-293`, `CLAUDE.md` (bảng Change Log + mục gotcha), `docs/CHANGELOG-agent.md`

**Interfaces:**
- Consumes: toàn bộ Task 1-6.
- Produces: không có API mới.

- [ ] **Step 1: Write the failing test**

```python
class TestSpeakerHandover:
    async def test_a_then_b_then_a_recognises_a_again(self) -> None:
        """Yêu cầu §2.1 — đổi người giữa cuộc. Bản 2026-08-28 không thể pass:
        reset() mỗi turn xoá sạch danh tính A trước khi A quay lại."""
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-handover")
            reg = session._speaker_registry
            a_vec = np.array([0.0, 1.0], dtype=np.float32)
            b_vec = np.array([1.0, 0.0], dtype=np.float32)
            session._trigger_agent_for_text = AsyncMock()

            # Turn 1 — A mở cuộc (floor mở).
            session._speaker_tracker.finalize = AsyncMock(
                return_value=_verdict(identity=reg.observe([a_vec], allow_new=True).identity, is_new=True)
            )
            await session._on_final("A hỏi câu đầu")
            a_id = reg.asker
            assert a_id is not None

            # Turn 2 — B nói khi agent IM: được trao lượt.
            b_id = reg.observe([b_vec], allow_new=True).identity
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=b_id, is_new=True))
            await session._on_final("B hỏi câu tiếp")
            assert reg.asker == b_id

            # Turn 3 — A quay lại: PHẢI nhận ra danh tính cũ, không tạo mới.
            ident, sim = reg.identify(a_vec)
            assert ident == a_id and sim > 0.9
            session._speaker_tracker.finalize = AsyncMock(return_value=_verdict(identity=a_id))
            await session._on_final("A hỏi lại")
            assert reg.asker == a_id
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/unit/test_base_session.py -k SpeakerHandover -v`
Expected: PASS (Task 1-6 đã đủ; test này chốt yêu cầu đầu bài)

- [ ] **Step 3: Chạy toàn bộ suite speaker**

Run: `pytest tests/unit/test_speaker_registry.py tests/unit/test_speaker_tracker.py tests/unit/test_base_session.py tests/unit/test_config_gate_speaker.py -v`
Expected: PASS. Nếu có test cũ còn tham chiếu `spv_chunk_sec` / `speaker_embed_window_sec` / `speaker_interrupt_min_sec` (xem `tests/unit/test_base_session.py:59-64`), cập nhật mock settings sang bộ field mới.

- [ ] **Step 4: Cập nhật SMOKE.md**

Trong `src/noble_agent/SMOKE.md`, mục "Speaker verification", thay các bước tham chiếu chunk cũ và thêm:

```markdown
5. **Đổi người giữa cuộc (multi):** A hỏi → agent trả lời → B hỏi ở turn kế (agent
   im) → B được trao lượt → A hỏi lại ở turn sau → log `[Speaker] final identity=<id A>`
   phải trỏ về ĐÚNG id của A ở bước đầu, `new=False`.
6. **Ngắt lời nhanh:** nói đè khi agent đang nói — log `[Speaker] probe#0 0.25s → speaker`
   xuất hiện trong ~0.3s và agent im ngay. Dòng probe **màu vàng** = khớp, **màu tím** =
   không khớp (bộ màu ở `server/logging_config.py`).
7. **Enroll fail-open:** nói một câu rất nhiễu → log `no consensus cluster ... enroll skipped`
   → lượt sau vẫn ngắt lời được bình thường (floor mở), KHÔNG bị khoá cứng.
```

- [ ] **Step 5: Cập nhật CLAUDE.md + CHANGELOG**

Thêm entry lên **đầu** bảng trong `docs/CHANGELOG-agent.md` và bản 1-2 câu lên đầu bảng `## Change Log` của `CLAUDE.md` (xoá entry thứ 11):

```markdown
| 2026-09-03 | SpeakerRegistry: danh tính sống cả phiên (bỏ `reset()` mỗi turn), enroll chỉ nhận cụm cửa sổ nhất quán (không cụm → không enroll, fail-open), probe đổi sang cửa sổ tích luỹ từ mốc 0.25s, drop rule dùng bằng chứng dương + van thoát mismatch-streak. | Enroll mù từ câu ngắt lời tạo centroid rác khoá cứng cả turn (khách thật không ngắt được, final còn bị drop); span rời 0.8s khiến verdict không thể về sớm và độ tin cậy không tăng theo thời gian. |
```

Trong `CLAUDE.md` mục **Gotchas**, thêm:

```markdown
- **Ngưỡng GHI centroid phải chặt hơn ngưỡng ĐỌC (`SPV_ADAPT_MARGIN`).** `CentroidSet.match()`
  lấy MAX cosine trên toàn tập, nên nếu hai ngưỡng bằng nhau thì mỗi mẫu vùng biên lại nới
  rộng biên và biên mới làm bàn đạp cho lần nới kế — danh tính trôi dạt tới mức ai nói cũng
  khớp. Đặt `SPV_ADAPT_MARGIN=0` là quay về đúng hành vi đó.
- **Speaker fail-OPEN, không fail-closed.** Không nhận diện được ⇒ tập rỗng ⇒ floor mở ⇒ ai
  cũng ngắt được (như `SPEAKER_MODE=off`). Đừng "sửa" thành chặn hết: bản 2026-08-28 enroll
  mù rồi khoá cứng, và triệu chứng là khách thật không ngắt được suốt turn.
```

- [ ] **Step 6: Lint, full test, commit**

```bash
make lint
make test-unit
git add tests/unit/test_base_session.py src/noble_agent/SMOKE.md CLAUDE.md docs/CHANGELOG-agent.md
git commit -m "test(spv): đổi người giữa cuộc + docs cho speaker registry

Integration test A→B→A chốt yêu cầu đổi người giữa cuộc (bản cũ không pass được
vì reset() mỗi turn). SMOKE.md thêm 3 bước; CLAUDE.md ghi 2 gotcha ngưỡng
ghi/đọc và fail-open."
```

---

## Sau khi xong

Chạy smoke thủ công theo `src/noble_agent/SMOKE.md` mục "Speaker verification" với audio thật 2 người — các test trên dùng embedding giả, **không** chứng minh được ngưỡng thực tế đúng. Mong đợi khi tune trên máy thật:

- `SPV_PROBE_BONUS` là thứ chỉnh đầu tiên nếu ngắt lời bị nhận nhầm ở mốc sớm.
- `SPV_ENROLL_CONSENSUS_SIM` chỉnh nếu log `no consensus cluster` xuất hiện quá thường (ngưỡng quá cao) hoặc centroid vẫn lệch (quá thấp).
- `SPEAKER_MATCH_THRESHOLD` là ngưỡng gốc — chỉnh nó dịch cả ba tầng cùng lúc, ưu tiên hơn chỉnh lẻ từng bonus.
