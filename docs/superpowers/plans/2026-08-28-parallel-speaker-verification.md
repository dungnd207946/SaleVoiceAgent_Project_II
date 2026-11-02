# Parallel Speaker Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thay engine speaker-verification của cả hai mode `single`/`multi` bằng đường SPV chunk-song-song với STT: nhịp cắt thích ứng (0.8s → 2s sau khi chốt speaker), so multi-centroid, interrupt tức thì tại chunk speaker đầu tiên, final kèm chuỗi nhãn per-chunk.

**Architecture:** File mới `voice/speaker_tracker.py` chứa `CentroidSet` (tập centroid, max-cosine match, cap FIFO) và `SpeakerTracker` (máy cắt chunk + gắn nhãn, 1 embed inflight, enroll-on-match) — thuần logic, embedder và scheduler được inject nên unit-test không cần model. `base_session.py` cắt sang engine mới trong một task nguyên tử (trạng thái trung gian nào cũng gãy nên không chẻ nhỏ hơn được), rồi xoá `SpeakerVerifier`/`SpeakerFloor`/episode-0.8s.

**Tech Stack:** Python 3.11+, asyncio, numpy, pytest (`asyncio_mode=auto`), sherpa-onnx/remote HTTP embedder (đã có sẵn qua `SpeakerEmbedder` — không đổi).

**Spec:** `docs/superpowers/specs/2026-08-28-parallel-speaker-verification-design.md`

## Global Constraints

- Branch làm việc: `sql-agent`. **KHÔNG** đụng `develop`, không push, không tạo branch mới.
- Ruff: line-length 120, rules `E,F,W,I,UP,B,SIM`. Chạy `make lint` trước mỗi commit.
- Pytest: `asyncio_mode=auto` — test async không cần decorator.
- Giữ nguyên `SpeakerEmbedder` + model loading trong `speaker_verifier.py` (không rename file).
- Task nền PHẢI giữ strong-ref (`_spawn_bg` / `_bg_tasks`) — gotcha repo: asyncio chỉ giữ weakref.
- Env mới: `SPV_CHUNK_SEC` (default 2.0), `SPV_MAX_CENTROIDS` (default 10). Tái dùng nguyên nghĩa: `speaker_interrupt_min_sec` (0.8), `speaker_embed_window_sec` (3.0), `speaker_match_threshold` (0.5), `speaker_min_enroll_sec` (1.0), `SPEAKER_MODE`.
- ~30 unit test fail sẵn do .env/data-artifact (memory: unit-suite-env-dependent-failures) — trước khi đổ lỗi cho thay đổi của mình, so với baseline: `git stash && pytest tests/unit -x -q > /tmp/base.txt; git stash pop`.
- **Chú ý working tree:** `src/noble_agent/server/base_session.py` và `src/noble_agent/voice/speaker_verifier.py` có thể đang có sửa đổi dở của user từ trước — trước Task 1, chạy `git status`; nếu còn bẩn, DỪNG và hỏi user commit/stash trước.

---

### Task 1: `CentroidSet`

**Files:**
- Create: `src/noble_agent/voice/speaker_tracker.py`
- Test: `tests/unit/test_speaker_tracker.py`

**Interfaces:**
- Consumes: không gì (thuần numpy).
- Produces: `CentroidSet(threshold: float, max_centroids: int)` với `.add(emb) -> None`, `.match(emb) -> tuple[bool, float]` (tập rỗng → `(True, 1.0)`), `.reset() -> None`, `.empty: bool`, `__len__`. Task 2/3 dùng đúng các tên này.

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/test_speaker_tracker.py
"""Unit tests for the parallel speaker-verification engine (spec 2026-08-28).

Pure-logic tests: no model, no settings — embedder/scheduler are injected fakes.
"""

from __future__ import annotations

import numpy as np

from noble_agent.voice.speaker_tracker import CentroidSet


def _vec(*xs: float) -> np.ndarray:
    return np.array(xs, dtype=np.float32)


class TestCentroidSet:
    def test_empty_set_matches_anything(self) -> None:
        cs = CentroidSet(threshold=0.5, max_centroids=10)
        assert cs.empty
        ok, sim = cs.match(_vec(1.0, 0.0))
        assert ok is True and sim == 1.0

    def test_match_is_max_cosine_over_all_centroids(self) -> None:
        cs = CentroidSet(threshold=0.9, max_centroids=10)
        cs.add(_vec(1.0, 0.0))   # xa query
        cs.add(_vec(0.0, 1.0))   # trùng query → max thắng
        ok, sim = cs.match(_vec(0.0, 1.0))
        assert ok is True
        assert sim == pytest.approx(1.0)

    def test_below_threshold_rejects(self) -> None:
        cs = CentroidSet(threshold=0.9, max_centroids=10)
        cs.add(_vec(1.0, 0.0))
        ok, sim = cs.match(_vec(0.0, 1.0))  # trực giao → cosine 0
        assert ok is False
        assert sim == pytest.approx(0.0)

    def test_cap_evicts_oldest_fifo(self) -> None:
        cs = CentroidSet(threshold=0.9, max_centroids=2)
        cs.add(_vec(1.0, 0.0))          # sẽ bị đẩy ra
        cs.add(_vec(0.0, 1.0))
        cs.add(_vec(-1.0, 0.0))         # đẩy centroid đầu ra
        assert len(cs) == 2
        ok, _ = cs.match(_vec(1.0, 0.0))  # chỉ còn (0,1) và (-1,0) → không match
        assert ok is False

    def test_reset_empties(self) -> None:
        cs = CentroidSet(threshold=0.5, max_centroids=10)
        cs.add(_vec(1.0, 0.0))
        cs.reset()
        assert cs.empty
```

Nhớ thêm `import pytest` đầu file (dùng `pytest.approx`).

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/unit/test_speaker_tracker.py -v`
Expected: FAIL — `ModuleNotFoundError: noble_agent.voice.speaker_tracker`

- [ ] **Step 3: Implement `CentroidSet`**

```python
# src/noble_agent/voice/speaker_tracker.py
"""Parallel speaker-verification engine (spec 2026-08-28).

CentroidSet + SpeakerTracker are pure chunk/vector logic — no model, no
settings import. The session injects an async ``embed`` callable and a
``spawn_bg`` scheduler, so unit tests run entirely on fakes.
"""

from __future__ import annotations

import logging
from collections import deque

import numpy as np

logger = logging.getLogger(__name__)


def _normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class CentroidSet:
    """Tập centroid đại diện MỘT danh tính. Match = max cosine ≥ threshold.

    Tập rỗng ⇒ mọi embedding mặc nhiên match (floor-open: chưa ai làm chủ thì
    người đầu tiên chen được quyền — giữ ngữ nghĩa auto-greeting hiện tại).
    Cap FIFO qua deque(maxlen): đầy thì centroid cũ nhất tự rơi.
    """

    def __init__(self, *, threshold: float, max_centroids: int) -> None:
        self._threshold = threshold
        self._centroids: deque[np.ndarray] = deque(maxlen=max_centroids)

    @property
    def empty(self) -> bool:
        return not self._centroids

    def __len__(self) -> int:
        return len(self._centroids)

    def add(self, emb: np.ndarray) -> None:
        self._centroids.append(_normalize(emb))

    def reset(self) -> None:
        self._centroids.clear()

    def match(self, emb: np.ndarray) -> tuple[bool, float]:
        if not self._centroids:
            return True, 1.0
        best = max(_cosine(c, emb) for c in self._centroids)
        return best >= self._threshold, best
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `pytest tests/unit/test_speaker_tracker.py -v`
Expected: 5 PASS

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/voice/speaker_tracker.py tests/unit/test_speaker_tracker.py
git commit -m "feat(speaker): CentroidSet — multi-centroid identity with FIFO cap"
```

---

### Task 2: `SpeakerTracker` — máy cắt chunk + gắn nhãn

**Files:**
- Modify: `src/noble_agent/voice/speaker_tracker.py` (append)
- Test: `tests/unit/test_speaker_tracker.py` (append)

**Interfaces:**
- Consumes: `CentroidSet` (Task 1).
- Produces (Task 4 dùng đúng chữ ký này):
  - `SpeakerTracker(*, embed, centroids, sample_rate, fast_chunk_sec, slow_chunk_sec, enroll_window_sec, min_enroll_sec, utt_cap_sec, on_verdict, spawn_bg)`
    - `embed: Callable[[bytes], Awaitable[np.ndarray | None]]`
    - `on_verdict: Callable[[str, float, int], Awaitable[None]] | None` — nhận `(label, sim, chunk_idx)`, label ∈ {"speaker","non-speaker","unknown"}
    - `spawn_bg: Callable[[Awaitable], asyncio.Task]` — scheduler giữ strong-ref (session truyền `self._spawn_bg`)
  - `.begin_utterance() -> None`, `.feed(pcm: bytes) -> None` (sync), `.finalize() -> list[str]` (async), `.labels: list[str]`, `.sims: list[float]`
- Enrollment (`enroll_from_utterance`, `reset`, `centroids_empty`) là Task 3.

**Ngữ nghĩa phải đúng spec:**
- Chunk là span **rời nhau**. Điểm cắt kế = `fast_chunk_sec` (0.8s) khi utterance CHƯA có chunk `speaker`; = `slow_chunk_sec` (2s) sau đó. `begin_utterance()` reset nhịp về fast.
- **Đúng 1 embed inflight**: embed đang chạy thì audio dồn tiếp vào buffer, lúc cắt lấy TOÀN BỘ buffer (chunk kế dài ra), không xếp hàng.
- Enroll-on-match: chunk `speaker` được `add()` vào tập — **CHỈ khi match thật** (tập không rỗng trước match). Tập rỗng → nhãn "speaker" mặc nhiên nhưng KHÔNG add (danh tính chỉ được claim qua enrollment ở final — Task 3/4).
- Gen-guard: embed land sau khi `begin_utterance()` của utterance mới → discard hoàn toàn (không nhãn, không verdict, không enroll).
- `finalize()`: đợi inflight (kể cả re-cut dây chuyền), đuôi ≥ 0.3s (`_TAIL_MIN_SEC`) embed nốt thành chunk cuối, trả copy chuỗi nhãn.
- Embed trả None/raise → nhãn `"unknown"`, sim `nan`, vẫn bắn verdict.

- [ ] **Step 1: Viết test fail (fake embedder điều khiển được)**

Append vào `tests/unit/test_speaker_tracker.py`:

```python
import asyncio

from noble_agent.voice.speaker_tracker import SpeakerTracker

SR = 16000
BPS = SR * 2  # bytes / second (PCM16 mono)


def _pcm(sec: float) -> bytes:
    return b"\x01\x00" * int(sec * SR)


class FakeEmbedder:
    """Trả embedding theo kịch bản; đếm span đã nhận để assert nhịp cắt."""

    def __init__(self, script: list[np.ndarray | None]) -> None:
        self.script = list(script)
        self.calls: list[int] = []  # độ dài byte từng segment đã embed
        self.release = asyncio.Event()
        self.release.set()  # mặc định không chặn

    async def __call__(self, pcm: bytes) -> np.ndarray | None:
        self.calls.append(len(pcm))
        await self.release.wait()
        return self.script.pop(0) if self.script else None


def _spawn(coro):
    return asyncio.ensure_future(coro)


def _tracker(embedder, *, threshold=0.5, max_centroids=10, on_verdict=None) -> SpeakerTracker:
    return SpeakerTracker(
        embed=embedder,
        centroids=CentroidSet(threshold=threshold, max_centroids=max_centroids),
        sample_rate=SR,
        fast_chunk_sec=0.8,
        slow_chunk_sec=2.0,
        enroll_window_sec=3.0,
        min_enroll_sec=1.0,
        utt_cap_sec=30.0,
        on_verdict=on_verdict,
        spawn_bg=_spawn,
    )


SPK = _vec(0.0, 1.0)   # giọng khách
OTHER = _vec(1.0, 0.0)  # giọng người lạ (trực giao)


class TestSpeakerTrackerCadence:
    async def test_fast_cadence_until_speaker_then_slow(self) -> None:
        # Tập có sẵn centroid SPK. Kịch bản: 2 chunk lạ rồi khách nói.
        emb = FakeEmbedder([OTHER, OTHER, SPK, SPK])
        t = _tracker(emb)
        t._centroids.add(SPK)
        t.begin_utterance()
        # 3 lần 0.8s đầu: cắt ở nhịp fast (mỗi lần đủ 0.8s là cắt ngay)
        for _ in range(3):
            t.feed(_pcm(0.8))
            await asyncio.sleep(0)  # cho embed task chạy
            await asyncio.sleep(0)
        assert t.labels == ["non-speaker", "non-speaker", "speaker"]
        # Sau chunk speaker: 0.8s nữa KHÔNG đủ cắt (nhịp đã chuyển 2s)
        t.feed(_pcm(0.8))
        await asyncio.sleep(0)
        assert len(emb.calls) == 3
        # ... đủ 2s thì cắt
        t.feed(_pcm(1.2))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(emb.calls) == 4
        assert t.labels[-1] == "speaker"

    async def test_begin_utterance_resets_cadence_and_labels(self) -> None:
        emb = FakeEmbedder([SPK, SPK])
        t = _tracker(emb)
        t._centroids.add(SPK)
        t.begin_utterance()
        t.feed(_pcm(0.8))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert t.labels == ["speaker"]
        t.begin_utterance()  # utterance mới
        assert t.labels == []
        t.feed(_pcm(0.8))  # nhịp lại là fast 0.8s
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert t.labels == ["speaker"]


class TestSpeakerTrackerInflight:
    async def test_single_inflight_backlog_folds_into_next_chunk(self) -> None:
        emb = FakeEmbedder([OTHER, OTHER])
        emb.release.clear()  # chặn embed #1
        t = _tracker(emb)
        t._centroids.add(SPK)
        t.begin_utterance()
        t.feed(_pcm(0.8))   # cắt #1, inflight treo
        t.feed(_pcm(0.8))   # KHÔNG cắt (inflight) — dồn buffer
        t.feed(_pcm(0.8))   # vẫn dồn
        assert len(emb.calls) == 1
        emb.release.set()   # thả embed #1
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # sau khi land, backlog 1.6s ≥ 0.8s → cắt #2 lấy TOÀN BỘ 1.6s
        assert len(emb.calls) == 2
        assert emb.calls[1] == int(1.6 * BPS)


class TestSpeakerTrackerVerdictAndGuard:
    async def test_on_verdict_called_with_label_sim_idx(self) -> None:
        seen: list[tuple[str, int]] = []

        async def on_verdict(label: str, sim: float, idx: int) -> None:
            seen.append((label, idx))

        emb = FakeEmbedder([OTHER])
        t = _tracker(emb, on_verdict=on_verdict)
        t._centroids.add(SPK)
        t.begin_utterance()
        t.feed(_pcm(0.8))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert seen == [("non-speaker", 0)]

    async def test_stale_embed_discarded_after_new_utterance(self) -> None:
        emb = FakeEmbedder([SPK])
        emb.release.clear()
        t = _tracker(emb)
        t._centroids.add(SPK)
        t.begin_utterance()
        t.feed(_pcm(0.8))       # inflight treo
        t.begin_utterance()      # utterance mới TRƯỚC khi embed land
        emb.release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert t.labels == []    # verdict cũ bị discard

    async def test_embed_failure_labels_unknown(self) -> None:
        emb = FakeEmbedder([None])
        t = _tracker(emb)
        t._centroids.add(SPK)
        t.begin_utterance()
        t.feed(_pcm(0.8))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert t.labels == ["unknown"]

    async def test_empty_set_labels_speaker_but_does_not_enroll(self) -> None:
        emb = FakeEmbedder([SPK])
        t = _tracker(emb)  # tập RỖNG
        t.begin_utterance()
        t.feed(_pcm(0.8))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert t.labels == ["speaker"]
        assert t._centroids.empty  # KHÔNG enroll-on-match khi match mặc nhiên

    async def test_enroll_on_match_adds_chunk_embedding(self) -> None:
        emb = FakeEmbedder([SPK])
        t = _tracker(emb)
        t._centroids.add(SPK)
        t.begin_utterance()
        t.feed(_pcm(0.8))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(t._centroids) == 2  # centroid gốc + chunk vừa match


class TestSpeakerTrackerFinalize:
    async def test_finalize_embeds_tail_and_waits_inflight(self) -> None:
        emb = FakeEmbedder([SPK, SPK])
        t = _tracker(emb)
        t._centroids.add(SPK)
        t.begin_utterance()
        t.feed(_pcm(0.8))    # chunk #1
        t.feed(_pcm(0.5))    # đuôi 0.5s ≥ 0.3s → finalize phải embed nốt
        labels = await t.finalize()
        assert labels == ["speaker", "speaker"]
        assert len(emb.calls) == 2

    async def test_finalize_drops_tiny_tail(self) -> None:
        emb = FakeEmbedder([SPK])
        t = _tracker(emb)
        t._centroids.add(SPK)
        t.begin_utterance()
        t.feed(_pcm(0.8))
        t.feed(_pcm(0.1))    # đuôi < 0.3s → bỏ
        labels = await t.finalize()
        assert labels == ["speaker"]
        assert len(emb.calls) == 1
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/unit/test_speaker_tracker.py -v -k "Cadence or Inflight or Verdict or Finalize"`
Expected: FAIL — `ImportError: cannot import name 'SpeakerTracker'`

- [ ] **Step 3: Implement `SpeakerTracker` (phần chunk engine)**

Append vào `src/noble_agent/voice/speaker_tracker.py` (sau `CentroidSet`; thêm import `asyncio` và `from collections.abc import Awaitable, Callable` lên đầu file):

```python
_TAIL_MIN_SEC = 0.3  # finalize(): đuôi ngắn hơn thì bỏ, không gắn nhãn


class SpeakerTracker:
    """Máy cắt chunk + gắn nhãn speaker song song với STT (spec 2026-08-28).

    Nhận PCM đã qua input gate, cắt span rời nhau ở nhịp thích ứng
    (fast=0.8s khi chưa gặp speaker trong utterance → slow=2s sau đó),
    embed off-loop qua callable inject, so với CentroidSet, bắn verdict
    per-chunk. Đúng MỘT embed inflight — backlog dồn vào chunk kế.
    """

    def __init__(
        self,
        *,
        embed: Callable[[bytes], Awaitable[np.ndarray | None]],
        centroids: CentroidSet,
        sample_rate: int,
        fast_chunk_sec: float,
        slow_chunk_sec: float,
        enroll_window_sec: float,
        min_enroll_sec: float,
        utt_cap_sec: float,
        on_verdict: Callable[[str, float, int], Awaitable[None]] | None,
        spawn_bg: Callable[[Awaitable], asyncio.Task],
    ) -> None:
        self._embed = embed
        self._centroids = centroids
        self._bps = sample_rate * 2  # PCM16 mono
        self._fast_chunk_sec = fast_chunk_sec
        self._slow_chunk_sec = slow_chunk_sec
        self._enroll_window_sec = enroll_window_sec
        self._min_enroll_sec = min_enroll_sec
        self._utt_cap = int(utt_cap_sec * self._bps)
        self._on_verdict = on_verdict
        self._spawn_bg = spawn_bg

        self._buf = bytearray()      # audio chưa gắn nhãn (từ điểm cắt trước)
        self._utt_pcm = bytearray()  # toàn bộ utterance hiện tại (cho enrollment)
        self._labels: list[str] = []
        self._sims: list[float] = []
        self._speaker_seen = False   # utterance này đã có chunk speaker chưa
        self._gen = 0                # epoch utterance — guard verdict land muộn
        self._inflight: asyncio.Task | None = None

    @property
    def labels(self) -> list[str]:
        return list(self._labels)

    @property
    def sims(self) -> list[float]:
        return list(self._sims)

    def begin_utterance(self) -> None:
        """Utterance mới: reset nhịp về fast, xoá nhãn/buffer. Embed inflight
        của utterance trước tự discard qua gen-guard khi land."""
        self._gen += 1
        self._buf.clear()
        self._utt_pcm = bytearray()
        self._labels = []
        self._sims = []
        self._speaker_seen = False

    def _next_cut_bytes(self) -> int:
        sec = self._slow_chunk_sec if self._speaker_seen else self._fast_chunk_sec
        return int(sec * self._bps)

    def feed(self, pcm: bytes) -> None:
        self._buf.extend(pcm)
        self._utt_pcm.extend(pcm)
        if len(self._utt_pcm) > self._utt_cap:
            del self._utt_pcm[: len(self._utt_pcm) - self._utt_cap]
        self._maybe_cut()

    def _maybe_cut(self) -> None:
        if self._inflight is not None or len(self._buf) < self._next_cut_bytes():
            return
        seg = bytes(self._buf)  # lấy TOÀN BỘ backlog — quy tắc 1-inflight
        self._buf.clear()
        self._inflight = self._spawn_bg(self._label_chunk(seg, self._gen))

    async def _label_chunk(self, seg: bytes, gen: int) -> None:
        try:
            emb = await self._embed(seg)
            if gen != self._gen:
                logger.info("[Speaker] stale chunk verdict discarded (utterance moved)")
                return
            if emb is None:
                label, sim = "unknown", float("nan")
            else:
                was_empty = self._centroids.empty
                ok, sim = self._centroids.match(emb)
                label = "speaker" if ok else "non-speaker"
                if ok:
                    self._speaker_seen = True
                    if not was_empty:
                        self._centroids.add(emb)  # enroll-on-match (match THẬT mới bồi)
            idx = len(self._labels)
            self._labels.append(label)
            self._sims.append(sim)
            logger.info(
                "[Speaker] chunk#%d %.2fs → %s (sim=%.3f, centroids=%d)",
                idx, len(seg) / self._bps, label, sim, len(self._centroids),
            )
            if self._on_verdict is not None:
                await self._on_verdict(label, sim, idx)
        finally:
            self._inflight = None
            if gen == self._gen:
                self._maybe_cut()  # backlog đủ dài thì cắt tiếp ngay

    async def finalize(self) -> list[str]:
        """Gọi ở STT final: đợi inflight (kể cả re-cut dây chuyền), embed nốt
        đuôi ≥ _TAIL_MIN_SEC, trả chuỗi nhãn đầy đủ của utterance."""
        while self._inflight is not None:
            inflight = self._inflight
            try:
                await inflight
            except Exception:  # noqa: BLE001 — task tự log lỗi của nó
                if self._inflight is inflight:
                    self._inflight = None
        if len(self._buf) >= int(_TAIL_MIN_SEC * self._bps):
            seg = bytes(self._buf)
            self._buf.clear()
            await self._label_chunk(seg, self._gen)
        else:
            self._buf.clear()
        return list(self._labels)
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `pytest tests/unit/test_speaker_tracker.py -v`
Expected: tất cả PASS (5 CentroidSet + 10 tracker). Nếu test cadence flaky vì số `asyncio.sleep(0)` không đủ cho embed task land, thêm 1 vòng `await asyncio.sleep(0)` trong test (embed fake có 2 await point).

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/voice/speaker_tracker.py tests/unit/test_speaker_tracker.py
git commit -m "feat(speaker): SpeakerTracker — adaptive-cadence parallel chunk labeling"
```

---

### Task 3: `SpeakerTracker` — enrollment + reset

**Files:**
- Modify: `src/noble_agent/voice/speaker_tracker.py`
- Test: `tests/unit/test_speaker_tracker.py` (append)

**Interfaces:**
- Produces (Task 4 dùng): `.enroll_from_utterance() -> None` (spawn nền, cắt buffer utterance thành cửa sổ `enroll_window_sec`, cửa sổ ≥ `min_enroll_sec` mới lấy), `.reset() -> None` (xoá tập centroid), `.centroids_empty: bool`.

- [ ] **Step 1: Viết test fail**

Append vào `tests/unit/test_speaker_tracker.py`:

```python
class TestSpeakerTrackerEnrollment:
    async def test_enroll_cuts_3s_windows(self) -> None:
        # 7s utterance → cửa sổ 3s + 3s + đuôi 1s (≥ min_enroll 1s) = 3 centroid
        emb = FakeEmbedder([SPK, SPK, SPK])
        t = _tracker(emb)
        t.begin_utterance()
        t._utt_pcm = bytearray(_pcm(7.0))  # nạp thẳng buffer, khỏi qua feed/cut
        t.enroll_from_utterance()
        for _ in range(8):
            await asyncio.sleep(0)
        assert len(t._centroids) == 3
        assert emb.calls[-3:] == [int(3.0 * BPS), int(3.0 * BPS), int(1.0 * BPS)]

    async def test_enroll_skips_window_below_min(self) -> None:
        # 3.5s → cửa sổ 3s + đuôi 0.5s < min_enroll 1s → chỉ 1 centroid
        emb = FakeEmbedder([SPK])
        t = _tracker(emb)
        t.begin_utterance()
        t._utt_pcm = bytearray(_pcm(3.5))
        t.enroll_from_utterance()
        for _ in range(4):
            await asyncio.sleep(0)
        assert len(t._centroids) == 1

    async def test_enroll_short_utterance_adds_nothing(self) -> None:
        emb = FakeEmbedder([SPK])
        t = _tracker(emb)
        t.begin_utterance()
        t._utt_pcm = bytearray(_pcm(0.5))  # < min_enroll 1s
        t.enroll_from_utterance()
        for _ in range(4):
            await asyncio.sleep(0)
        assert t._centroids.empty
        assert emb.calls == []

    async def test_reset_and_centroids_empty(self) -> None:
        emb = FakeEmbedder([])
        t = _tracker(emb)
        assert t.centroids_empty
        t._centroids.add(SPK)
        assert not t.centroids_empty
        t.reset()
        assert t.centroids_empty
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/unit/test_speaker_tracker.py -v -k Enrollment`
Expected: FAIL — `AttributeError: 'SpeakerTracker' object has no attribute 'enroll_from_utterance'`

- [ ] **Step 3: Implement**

Append vào class `SpeakerTracker`:

```python
    @property
    def centroids_empty(self) -> bool:
        return self._centroids.empty

    def reset(self) -> None:
        """Xoá tập centroid. Multi: gọi khi turn kết thúc (floor mở lại).
        Single: không bao giờ gọi trong phiên."""
        self._centroids.reset()

    def enroll_from_utterance(self) -> None:
        """Enroll danh tính từ utterance vừa chốt: cắt buffer thành cửa sổ
        enroll_window_sec (3s), cửa sổ cuối ≥ min_enroll_sec (1s) mới lấy,
        embed từng cửa sổ → add. Chạy nền — snapshot buffer NGAY (đồng bộ)
        trước khi utterance kế ghi đè (gotcha fire_and_forget của repo)."""
        pcm = bytes(self._utt_pcm)
        self._spawn_bg(self._enroll(pcm))

    async def _enroll(self, pcm: bytes) -> None:
        win = int(self._enroll_window_sec * self._bps)
        min_b = int(self._min_enroll_sec * self._bps)
        added = 0
        for start in range(0, len(pcm), win):
            seg = pcm[start : start + win]
            if len(seg) < min_b:
                break
            emb = await self._embed(seg)
            if emb is not None:
                self._centroids.add(emb)
                added += 1
        logger.info(
            "[Speaker] enrolled %d centroid(s) from %.2fs utterance (centroids=%d)",
            added, len(pcm) / self._bps, len(self._centroids),
        )
```

- [ ] **Step 4: Chạy toàn bộ file test, xác nhận pass**

Run: `pytest tests/unit/test_speaker_tracker.py -v`
Expected: tất cả PASS

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/voice/speaker_tracker.py tests/unit/test_speaker_tracker.py
git commit -m "feat(speaker): SpeakerTracker enrollment — 3s-window centroids + per-turn reset"
```

---

### Task 4: Cutover `base_session.py` + config

Task lớn nhất và NGUYÊN TỬ — engine cũ và mới không sống chung được (init/final-path đan nhau), nên toàn bộ swap + test đi trong một commit.

**Files:**
- Modify: `src/noble_agent/config.py` (thêm 2 field cạnh block speaker ~dòng 219)
- Modify: `src/noble_agent/server/base_session.py`
- Test: `tests/unit/test_base_session.py`

**Interfaces:**
- Consumes: `SpeakerTracker`/`CentroidSet` (Task 1–3, chữ ký ở đó).
- Produces: session method mới `_spv_embed(pcm: bytes) -> np.ndarray | None` (async), `_on_speaker_verdict(label: str, sim: float, idx: int) -> None` (async); event mới `{"type": "final_transcript", "text": ..., "speaker_labels": [...]}`.

- [ ] **Step 1: Config — thêm 2 field**

Trong `src/noble_agent/config.py`, ngay sau `speaker_embed_window_sec` (dòng ~219):

```python
    # ── Parallel SPV (spec 2026-08-28) — engine chunk-song-song cho single/multi ──
    spv_chunk_sec: float = 2.0  # nhịp cắt SAU khi utterance đã có chunk speaker (nhịp nhanh = speaker_interrupt_min_sec)
    spv_max_centroids: int = 10  # cap FIFO tập centroid mỗi danh tính
```

GIỮ `speaker_adapt_enabled`/`speaker_adapt_weight` tạm — xoá ở Task 5 cùng `SpeakerVerifier`.

- [ ] **Step 2: Viết test session mới (fail)**

Append vào `tests/unit/test_base_session.py`. Trước hết thêm các field mới vào `_patched_collaborators` (cạnh `mock_settings.speaker_interrupt_min_sec = 0.8`, dòng ~58):

```python
        mock_settings.speaker_match_threshold = 0.5
        mock_settings.speaker_min_enroll_sec = 1.0
        mock_settings.speaker_embed_window_sec = 3.0
        mock_settings.spv_chunk_sec = 2.0
        mock_settings.spv_max_centroids = 10
```

Rồi append class test (bắt chước cách các test khác trong file dựng session — dùng cùng helper dựng `BaseSession` mà file đang dùng, xem các test `test_verify_speaker_*` hiện có trước khi xoá chúng):

```python
class TestParallelSpeakerVerdict:
    """Spec 2026-08-28: verdict per-chunk điều khiển interrupt + drop final."""

    async def test_speaker_verdict_while_agent_speaking_interrupts(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._agent_task = asyncio.ensure_future(asyncio.sleep(30))
            session._handle_interrupt = AsyncMock()
            await session._on_speaker_verdict("speaker", 0.9, 0)
            session._handle_interrupt.assert_awaited_once()
            session._agent_task.cancel()

    async def test_speaker_verdict_routes_via_addressee_gate_when_enabled(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            c["settings"].addressee_gate_mode = "llm"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._agent_task = asyncio.ensure_future(asyncio.sleep(30))
            session._begin_addressee_pause_from_floor = AsyncMock()
            session._handle_interrupt = AsyncMock()
            await session._on_speaker_verdict("speaker", 0.9, 0)
            session._begin_addressee_pause_from_floor.assert_awaited_once()
            session._handle_interrupt.assert_not_awaited()
            session._agent_task.cancel()

    async def test_non_speaker_verdict_keeps_agent_talking(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._agent_task = asyncio.ensure_future(asyncio.sleep(30))
            session._handle_interrupt = AsyncMock()
            await session._on_speaker_verdict("non-speaker", 0.1, 0)
            session._handle_interrupt.assert_not_awaited()
            c["vad"].set_speaking.assert_called()
            session._agent_task.cancel()

    async def test_unknown_verdict_never_interrupts(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "single"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._agent_task = asyncio.ensure_future(asyncio.sleep(30))
            session._handle_interrupt = AsyncMock()
            await session._on_speaker_verdict("unknown", float("nan"), 0)
            session._handle_interrupt.assert_not_awaited()
            session._agent_task.cancel()

    async def test_verdict_when_agent_idle_is_noop(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._handle_interrupt = AsyncMock()
            await session._on_speaker_verdict("speaker", 0.9, 0)
            session._handle_interrupt.assert_not_awaited()


class TestParallelSpeakerFinal:
    async def test_final_majority_non_speaker_dropped(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "single"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._speaker_tracker.finalize = AsyncMock(
                return_value=["non-speaker", "non-speaker", "speaker"]
            )
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("ai đó nói chen")
            session._trigger_agent_for_text.assert_not_awaited()

    async def test_final_majority_speaker_kept_and_labeled(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "single"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._speaker_tracker.finalize = AsyncMock(
                return_value=["speaker", "speaker", "non-speaker"]
            )
            sent: list[dict] = []
            session._send_event = AsyncMock(side_effect=lambda m: sent.append(m))
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("bên em có dự án gì")
            session._trigger_agent_for_text.assert_awaited_once()
            final_evts = [m for m in sent if m.get("type") == "final_transcript"]
            assert final_evts and final_evts[0]["speaker_labels"] == ["speaker", "speaker", "non-speaker"]

    async def test_final_no_labels_fail_open(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "single"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._speaker_tracker.finalize = AsyncMock(return_value=[])
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("câu quá ngắn")
            session._trigger_agent_for_text.assert_awaited_once()

    async def test_final_multi_idle_not_enforced(self) -> None:
        # multi + agent idle = floor mở: final toàn non-speaker VẪN được nhận
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._speaker_tracker.finalize = AsyncMock(return_value=["non-speaker"])
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("người mới hỏi turn mới")
            session._trigger_agent_for_text.assert_awaited_once()

    async def test_drop_while_paused_resumes_playback(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "single"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._addr_paused = True
            session._speaker_tracker.finalize = AsyncMock(return_value=["non-speaker", "non-speaker"])
            session._trigger_agent_for_text = AsyncMock()
            await session._on_final("nhầm — không phải khách")
            session._trigger_agent_for_text.assert_not_awaited()
            c["agent"].resume_playback.assert_called_once()
            assert session._addr_paused is False


class TestParallelSpeakerLifecycle:
    async def test_trigger_multi_resets_then_enrolls(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._speaker_tracker.reset = MagicMock()
            session._speaker_tracker.enroll_from_utterance = MagicMock()
            await session._trigger_agent_for_text("câu hỏi mở turn")
            session._speaker_tracker.reset.assert_called_once()
            session._speaker_tracker.enroll_from_utterance.assert_called_once()
            if session._agent_task:
                session._agent_task.cancel()

    async def test_trigger_single_enrolls_only_when_empty(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "single"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._speaker_tracker.enroll_from_utterance = MagicMock()
            await session._trigger_agent_for_text("câu đầu phiên")  # tập rỗng → enroll
            session._speaker_tracker.enroll_from_utterance.assert_called_once()
            session._speaker_tracker._centroids.add(np.array([1.0, 0.0], dtype=np.float32))
            await session._trigger_agent_for_text("câu sau")  # đã có → không enroll
            session._speaker_tracker.enroll_from_utterance.assert_called_once()
            if session._agent_task:
                session._agent_task.cancel()

    async def test_run_agent_finally_resets_multi_only(self) -> None:
        async with _patched_collaborators() as c:
            c["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession

            session = BaseSession("sid-spv")
            session._speaker_tracker.reset = MagicMock()
            await session._run_agent("xin chào")
            session._speaker_tracker.reset.assert_called_once()
```

Ghi chú cho executor: pattern dựng session đúng của file này là `BaseSession("sid-x")` import inline BÊN TRONG context `_patched_collaborators` (xem `TestHandleInterrupt` dòng ~131) — settings phải được set TRƯỚC khi construct (như các test trên đã làm). Cần `import numpy as np` nếu file chưa có.

- [ ] **Step 3: Chạy test mới, xác nhận fail**

Run: `pytest tests/unit/test_base_session.py -v -k "ParallelSpeaker"`
Expected: FAIL — `AttributeError: _on_speaker_verdict` / `_speaker_tracker`

- [ ] **Step 4: Cutover `base_session.py`**

4a. **Imports** (~dòng 39-50): bỏ import `SpeakerVerifier`, `SpeakerFloor`; thêm:

```python
from noble_agent.voice.speaker_tracker import CentroidSet, SpeakerTracker
```

4b. **`__init__`** — thay block dòng 167-182 (`self._speaker_verifier = ...` đến `self._interrupt_embed_inflight = False`) bằng:

```python
        # Parallel SPV engine (spec 2026-08-28) — chung cho single/multi, chỉ
        # khác lifecycle reset (multi: per-turn, single: per-session).
        self._speaker_tracker: SpeakerTracker | None = None
        if self._speaker_mode in ("single", "multi"):
            self._speaker_tracker = SpeakerTracker(
                embed=self._spv_embed,
                centroids=CentroidSet(
                    threshold=settings.speaker_match_threshold,
                    max_centroids=settings.spv_max_centroids,
                ),
                sample_rate=settings.stt_sample_rate,
                fast_chunk_sec=settings.speaker_interrupt_min_sec,
                slow_chunk_sec=settings.spv_chunk_sec,
                enroll_window_sec=settings.speaker_embed_window_sec,
                min_enroll_sec=settings.speaker_min_enroll_sec,
                utt_cap_sec=settings.spv_max_centroids * settings.speaker_embed_window_sec,
                on_verdict=self._on_speaker_verdict,
                spawn_bg=self._spawn_bg,
            )
```

Sửa warn-once `speaker_interrupt_min_sec_vs_addressee_min_speech_ms` (~dòng 232): điều kiện `self._speaker_floor is not None` → `self._speaker_tracker is not None` (premise giữ nguyên: verdict đầu ở ≥0.8s > 400ms).

Xoá dòng 254 `self._utterance_pcm = bytearray()` (+ comment 251-253).

4c. **`process_audio_frame`**:
- Nhánh `VADState.INTERRUPTED` (~dòng 587-593) →

```python
            elif result["state"] == VADState.INTERRUPTED:
                if self._speaker_tracker is not None:
                    # Verdict-driven barge-in: giữ máy trạng thái VAD sống;
                    # chunk verdict kế tiếp của tracker quyết pause/interrupt.
                    self.vad.set_speaking()
                elif self._addr_gate_enabled:
                    self._begin_addressee_episode()
                else:
                    await self._handle_interrupt()
```

- Vòng gated-chunk (~dòng 606-621): thay 2 khối `_utterance_pcm` bằng tracker:

```python
            for chunk in chunks:
                if self._stt_audio_start == 0.0:
                    self._stt_audio_start = time.monotonic()
                    if self._speaker_tracker is not None:
                        self._speaker_tracker.begin_utterance()
                if self._speaker_tracker is not None:
                    self._speaker_tracker.feed(chunk)
                if self.billing is not None:
                    # (giữ nguyên comment + add_audio stt hiện có)
                    self.billing.add_audio("stt", audio_sec=len(chunk) / (settings.stt_sample_rate * 2))
                await self.stt.send(chunk)
```

- XOÁ toàn bộ khối multi-mode sau vòng lặp (~dòng 623-646, từ comment `# Multi mode: once we have enough...` đến `task.add_done_callback(...)`).

4d. **Xoá method**: `_begin_interrupt_episode` (~700-715), `_floor_sim` (~717-723), `_evaluate_interrupt_candidate` (~725-783), `_verify_speaker` (~1204-1237), `_embed_current_utterance` (~1183-1202).

4e. **Thêm 2 method mới** (đặt cạnh chỗ `_evaluate_interrupt_candidate` cũ):

```python
    async def _on_speaker_verdict(self, label: str, sim: float, idx: int) -> None:
        """Tracker chunk verdict → quyết barge-in NGAY, không đợi final.

        speaker + agent đang nói → soft-pause (gate bật) / interrupt thẳng.
        non-speaker/unknown → agent nói tiếp (unknown = embed fail: interrupt
        fail-closed). Agent không nói → chỉ ghi nhãn, không hành động.
        """
        if not self._agent_is_speaking():
            return
        if label != "speaker":
            self.vad.set_speaking()
            return
        if self._addr_paused:
            return  # đã soft-pause; classifier của final sẽ quyết
        if self._addr_gate_enabled:
            await self._begin_addressee_pause_from_floor()
        else:
            await self._handle_interrupt()

    async def _spv_embed(self, pcm: bytes) -> np.ndarray | None:
        """Embed một span PCM off-loop — inject vào SpeakerTracker."""
        if not pcm:
            return None
        _t0 = time.perf_counter()
        try:
            return await asyncio.to_thread(SpeakerEmbedder.get_instance().embed, pcm)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Speaker] embed error: %s", exc)
            return None
        finally:
            if self.billing is not None:
                self.billing.add_audio(
                    "speaker_verify",
                    audio_sec=len(pcm) / (settings.stt_sample_rate * 2),
                    wall_ms=(time.perf_counter() - _t0) * 1000.0,
                    units=1,
                )
```

(`SpeakerEmbedder` import sẵn có từ `speaker_verifier` — giữ.)

`_begin_addressee_pause_from_floor` GIỮ NGUYÊN tên + body; chỉ sửa docstring: nguồn kích hoạt giờ là chunk verdict của tracker (≥ `speaker_interrupt_min_sec` audio) thay vì floor-resolution.

4f. **`_on_final`** — thay HAI khối speaker (single ~898-902 và multi ~904-944) bằng MỘT khối:

```python
        if self._speaker_tracker is not None:
            labels = await self._speaker_tracker.finalize()
            sims = self._speaker_tracker.sims
            logger.info(
                "[Speaker] labels=%s sims=[%s] text=%r",
                labels, ", ".join(f"{s:.2f}" for s in sims), text,
            )
            await self._send_event({"type": "final_transcript", "text": text, "speaker_labels": labels})
            # Drop rule: đa số non-speaker → drop (hoà/không nhãn → giữ, fail-open).
            # Phạm vi: single = mọi final; multi = chỉ mid-turn (floor đang có chủ).
            enforce = (
                self._speaker_mode == "single" or self._agent_is_speaking() or self._addr_paused
            )
            non = labels.count("non-speaker")
            spk = labels.count("speaker")
            if enforce and non > spk:
                logger.info("[Speaker] Dropped final — majority non-speaker (%d/%d): %r", non, len(labels), text)
                if self._addr_paused:
                    # Chunk verdict đã soft-pause nhưng toàn cục utterance nói
                    # ngược lại → resume như một SIDE_TALK drop.
                    self.agent.resume_playback()
                    self._addr_reset_episode()
                if self._agent_is_speaking():
                    self.vad.set_speaking()
                return
```

4g. **`_trigger_agent_for_text`** — sau khối cancel/await task cũ (sau `self.vad.set_idle()` ~dòng 1077), TRƯỚC phần speaker-prefix:

```python
        if self._speaker_tracker is not None:
            # Enrollment hook (spec §3.2): mọi final được nhận đều qua đây,
            # SAU teardown task cũ nên không race với reset trong finally.
            if self._speaker_mode == "multi":
                self._speaker_tracker.reset()  # final này mở turn mới — người nói là asker mới
                self._speaker_tracker.enroll_from_utterance()
            elif self._speaker_tracker.centroids_empty:
                self._speaker_tracker.enroll_from_utterance()  # utterance đầu phiên (single)
```

4h. **`_run_agent` finally** (~dòng 1286-1287): thay

```python
            if self._speaker_floor is not None:
                self._speaker_floor.clear_asker()
```

bằng:

```python
            if self._speaker_tracker is not None and self._speaker_mode == "multi":
                self._speaker_tracker.reset()  # turn kết thúc tự nhiên → floor mở lại
```

- [ ] **Step 5: Chạy test mới, xác nhận pass**

Run: `pytest tests/unit/test_base_session.py -v -k "ParallelSpeaker"`
Expected: PASS

- [ ] **Step 6: Sửa/xoá test cũ trong `test_base_session.py`**

`rtk proxy grep -n "verify_speaker\|_speaker_floor\|_utterance_pcm\|interrupt_episode\|_evaluate_interrupt\|SpeakerFloor\|floor" tests/unit/test_base_session.py` — với mỗi hit:
- Test API đã xoá (`test_verify_speaker_*` ~1047/1079/1108/1306, floor tests ~1453, ~2167, các test episode/`_evaluate_interrupt_candidate`) → XOÁ test (hành vi thay thế đã cover ở class `TestParallelSpeaker*`).
- Test khác chỉ động chạm gián tiếp (mock `_speaker_floor` attr v.v.) → sửa theo API mới.
- Test `2167` (`test_multi_speaker_floor_takes_priority_over_addressee`): viết lại thành "tracker mode multi + VAD INTERRUPTED → KHÔNG mở addressee episode, chỉ set_speaking" — assert `session._addr_episode_active is False` và `c["vad"].set_speaking.assert_called()` sau khi feed đủ chunk INTERRUPTED.

Run: `pytest tests/unit/test_base_session.py -v`
Expected: PASS toàn file (so với baseline env-dependent nếu nghi ngờ).

- [ ] **Step 7: Grep site nạp settings test khác**

`rtk proxy grep -rln "speaker_adapt\|SpeakerVerifier\|SpeakerFloor\|speaker_floor" tests/ src/` — các file NGOÀI `speaker_verifier.py`/`test_speaker_verifier.py`/`test_speaker_floor.py` (Task 5 xử lý) phải sửa ngay tại đây nếu chúng gãy vì cutover (vd `tests/unit/test_speaker_gate_helpers.py`, `tests/integration/unified/*`). Sửa theo API mới hoặc xoá assertion lỗi thời.

- [ ] **Step 8: Lint + commit**

```bash
make lint && pytest tests/unit/test_base_session.py tests/unit/test_speaker_tracker.py -q
git add -A src/noble_agent/config.py src/noble_agent/server/base_session.py tests/
git commit -m "feat(speaker): cut base_session over to parallel SPV engine

Chunk verdicts drive barge-in (0.8s fast cadence → 2s after speaker match),
multi-centroid identity, per-chunk labels on finals with majority-drop.
Replaces SpeakerFloor episode + end-of-turn re-embed for both modes."
```

---

### Task 5: Xoá engine cũ

**Files:**
- Modify: `src/noble_agent/voice/speaker_verifier.py` (xoá `SpeakerVerifier`, `SpeakerFloor`; GIỮ `_normalize`/`_cosine` nếu còn ai import — kiểm tra; giữ `SpeakerEmbedder` + `_get_extractor` + `_ensure_speaker_model_present`)
- Modify: `src/noble_agent/config.py` (xoá `speaker_adapt_enabled`, `speaker_adapt_weight`)
- Delete: `tests/unit/test_speaker_verifier.py`, `tests/unit/test_speaker_floor.py`

**Interfaces:**
- Consumes: Task 4 đã gỡ mọi call-site trong `base_session.py`.
- Produces: không — task dọn dẹp.

- [ ] **Step 1: Xác nhận không còn consumer**

```bash
rtk proxy grep -rn "SpeakerVerifier\|SpeakerFloor\|speaker_adapt" src/ tests/ evals/ scripts/ | grep -v speaker_verifier.py | grep -v test_speaker_verifier | grep -v test_speaker_floor
```

Expected: 0 hit (nếu còn — quay lại sửa call-site đó trước, KHÔNG xoá bừa).

- [ ] **Step 2: Xoá code + test + config**

- `speaker_verifier.py`: xoá class `SpeakerVerifier` (dòng 35-59) và `SpeakerFloor` (164-196); cập nhật module docstring (giờ file chỉ còn embedder + model loading).
- `config.py`: xoá 2 dòng `speaker_adapt_enabled` / `speaker_adapt_weight`.
- `git rm tests/unit/test_speaker_verifier.py tests/unit/test_speaker_floor.py`

- [ ] **Step 3: Chạy suite liên quan**

Run: `pytest tests/unit/test_speaker_tracker.py tests/unit/test_speaker_embedder.py tests/unit/test_base_session.py tests/unit/test_config_gate_speaker.py tests/unit/test_speaker_prewarm.py tests/unit/test_speaker_gate_helpers.py -q && make lint`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(speaker): delete SpeakerVerifier/SpeakerFloor — superseded by SpeakerTracker"
```

---

### Task 6: Docs

**Files:**
- Modify: `src/noble_agent/SMOKE.md` (mục speaker)
- Modify: `CLAUDE.md` (bảng Change Log — thêm entry mới, XOÁ entry thứ 11; sửa dòng mô tả barge-in/speaker nếu có đoạn nói về flow cũ)
- Modify: `docs/CHANGELOG-agent.md` (entry đầy đủ lên ĐẦU bảng)

**Interfaces:** không.

- [ ] **Step 1: SMOKE.md** — cập nhật mục speaker verification: mô tả smoke 2-người-nói mới (A hỏi → agent trả lời → B chen: agent nói tiếp, log `non-speaker`; A chen: agent pause ≤ ~1s, log `chunk#N speaker`; check log `[Speaker] labels=[...]` trên mỗi final).

- [ ] **Step 2: CLAUDE.md Change Log** — thêm dòng (1-2 câu, xoá entry cũ nhất cho đủ 10):

```
| 2026-08-28 | Parallel SPV: SpeakerTracker thay SpeakerFloor/SpeakerVerifier — chunk song song STT (0.8s → SPV_CHUNK_SEC=2s sau khi chốt speaker), multi-centroid (cap SPV_MAX_CENTROIDS=10, enroll-on-match), interrupt tức thì tại chunk speaker, final kèm chuỗi nhãn + majority-drop. | Người lạ chen trước làm khách phải đợi hết turn mới ngắt được; 1 embedding/danh tính nhạy biến thiên giọng. |
```

- [ ] **Step 3: docs/CHANGELOG-agent.md** — entry đầy đủ (mô tả 2 mode lifecycle, drop rule, env mới, code đã xoá) thêm lên đầu bảng.

- [ ] **Step 4: Commit**

```bash
git add src/noble_agent/SMOKE.md CLAUDE.md docs/CHANGELOG-agent.md
git commit -m "docs: parallel SPV — smoke checklist + changelog"
```

---

### Task 7: Verify toàn cục

**Files:** không sửa gì — chỉ chạy.

- [ ] **Step 1: Full unit + lint**

```bash
make lint
pytest tests/unit -q 2>&1 | tail -20
```

Expected: pass, TRỪ nhóm env-dependent đã có ở baseline (`/tmp/base.txt` từ Global Constraints — so sánh danh sách fail, không được có fail MỚI).

- [ ] **Step 2: Unified suite**

Run: `make test-unified`
Expected: pass như baseline.

- [ ] **Step 3: Báo cáo**

Tổng hợp cho user: test kết quả, các env mới (`SPV_CHUNK_SEC`, `SPV_MAX_CENTROIDS`), và nhắc smoke thủ công 2-người-nói theo SMOKE.md (cần chạy voice thật — theo memory `voice-startup-recipe`) trước khi coi là xong. KHÔNG merge/push — user quyết.
