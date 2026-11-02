"""Parallel speaker-verification engine (spec 2026-08-28).

CentroidSet + SpeakerTracker are pure chunk/vector logic — no model, no
settings import. The session injects an async ``embed`` callable and a
``spawn_bg`` scheduler, so unit tests run entirely on fakes.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

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

    def kth_sim(self, emb: np.ndarray, k: int) -> float:
        """Cosine hạng k (k tự kẹp theo cỡ tập — k=1 ≡ max, tập 1 mẫu giữ hành vi cũ).
        Trúng đúng 1 mẫu có thể chỉ là trùng hợp/echo; đòi k mẫu là đòi bằng chứng
        lặp lại — mẫu vào tập theo cụm ≥2 cửa sổ tương quan nên match thật luôn có cặp."""
        if not self._centroids:
            return 0.0
        sims = sorted((_cosine(c, emb) for c in self._centroids), reverse=True)
        return sims[min(max(1, k), len(sims)) - 1]

    def match_k(self, emb: np.ndarray, threshold: float, k: int) -> tuple[bool, float]:
        """So cosine hạng k với ngưỡng. sim trả về = giá trị thực sự bị so,
        để log đọc đúng lý do quyết định."""
        if not self._centroids:
            return True, 1.0
        decisive = self.kth_sim(emb, k)
        return decisive >= threshold, decisive


@dataclass
class ObserveResult:
    """Kết quả nhận diện một utterance. KHÔNG chứa quyết định trao lượt —
    'ai giữ lượt' là việc của session (xem base_session drop rule)."""

    identity: int | None
    is_new: bool
    best_sim: float


@dataclass
class UtteranceVerdict:
    """Kết quả `finalize()` một utterance: danh tính chốt + bằng chứng cụm nhất
    quán dùng để enroll (hoặc không) vào `SpeakerRegistry`."""

    identity: int | None
    is_new: bool
    cluster_size: int
    best_sim: float
    probe_labels: list[str]


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
        self,
        *,
        match_threshold: float,
        adapt_margin: float,
        max_identities: int,
        max_centroids: int,
        min_match_probe: int = 2,
        min_match_identify: int = 1,
    ) -> None:
        self._match_threshold = match_threshold
        self._write_threshold = match_threshold + adapt_margin
        self._max_identities = max(1, max_identities)
        self._max_centroids = max_centroids
        self._min_match_probe = max(1, min_match_probe)
        # Đường nguội mặc định 1 (= max, hành vi cũ): identify sai tạo danh tính
        # TRÙNG cho cùng một người → nhánh 4/5 drop final của chính khách. Chỉ
        # nâng lên 2 sau khi log thật cho thấy mẫu nhiễu bắt nhầm cụm.
        self._min_match_identify = max(1, min_match_identify)
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
            sim = cset.kth_sim(emb, self._min_match_identify)
            if sim > best_sim:
                best_id, best_sim = ident, sim
        if best_id is None or best_sim < self._match_threshold:
            return None, best_sim
        return best_id, best_sim

    def match_asker(self, emb: np.ndarray, threshold: float) -> tuple[bool, float]:
        """Fail-open: chưa có asker ⇒ floor mở, mọi người ngắt được (auto-greeting).
        Đường ngắt đòi khớp ≥ min_match_probe centroid (xem CentroidSet.match_k);
        identify()/observe() ở đường nguội vẫn dùng max — enroll đã có van riêng
        (consensus + adapt_margin)."""
        if self._asker is None or self._asker not in self._identities:
            return True, 1.0
        return self._identities[self._asker].match_k(emb, threshold, self._min_match_probe)

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
            # Ưu tiên evict danh tính CŨ NHẤT mà KHÔNG phải asker và KHÔNG phải
            # danh tính vừa tạo — FIFO trần (popleft vô điều kiện) hay xoá đúng
            # người đang giữ lượt, vì asker thường chính là mục cũ nhất trong
            # `_order`. Không có ứng viên an toàn nào (vd max_identities=1) →
            # rơi về hành vi cũ: evict oldest, clear `_asker` nếu trúng nó.
            evicted = next((i for i in self._order if i != self._asker and i != ident), self._order[0])
            self._order.remove(evicted)
            self._identities.pop(evicted, None)
            if self._asker == evicted:
                self._asker = None
                logger.info("[Speaker] asker identity evicted by FIFO cap — floor reopened")
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


class SpeakerTracker:
    """Máy probe cửa sổ tích luỹ + gắn nhãn speaker song song với STT (spec 2026-09-03).

    Nhận PCM đã qua input gate. Ở chuỗi mốc `probe_marks_sec`, mỗi mốc embed
    đoạn TÍCH LUỸ từ đầu utterance (mốc sau chứa audio mốc trước — độ tin cậy
    tăng theo thời gian) so với ngưỡng riêng `probe_thresholds[i]` qua
    `SpeakerRegistry.match_asker` (fail-open khi chưa có asker); quyết được
    (match) thì dừng chuỗi mốc. Hết mốc mà chưa quyết → chuyển cửa sổ TRƯỢT
    (`probe_tail_window_sec`/`probe_tail_hop_sec`) — tích luỹ tiếp ở giai đoạn
    này sẽ trộn giọng người nói trước với người chen sau thành một embedding
    lai. Đúng MỘT embed inflight — probe kế đợi cái đang chạy xong.
    """

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

        self._utt_pcm = bytearray()  # toàn bộ utterance hiện tại (bị cắt ở _utt_cap)
        self._fed_bytes = 0  # TỔNG byte đã feed — KHÔNG bị cắt, elapsed dựa vào đây
        self._labels: list[str] = []
        self._sims: list[float] = []
        self._mark_idx = 0  # mốc kế tiếp trong self._marks
        self._decided = False  # đã quyết trong chuỗi mốc chưa
        self._next_tail_sec = 0.0  # mốc trượt kế tiếp (giai đoạn đuôi)
        self._gen = 0  # epoch utterance — guard verdict land muộn
        self._inflight: asyncio.Task | None = None

    def begin_utterance(self) -> None:
        """Utterance mới: reset lịch probe. Embed inflight của utterance trước
        tự discard qua gen-guard khi land."""
        self._gen += 1
        self._utt_pcm = bytearray()
        self._fed_bytes = 0
        self._labels = []
        self._sims = []
        self._mark_idx = 0
        self._decided = False
        self._next_tail_sec = 0.0

    def feed(self, pcm: bytes) -> None:
        self._utt_pcm.extend(pcm)
        self._fed_bytes += len(pcm)
        if len(self._utt_pcm) > self._utt_cap:
            del self._utt_pcm[: len(self._utt_pcm) - self._utt_cap]
        self._maybe_probe()

    def _elapsed_sec(self) -> float:
        """Thời gian đã trôi qua của utterance — tính trên TỔNG byte đã feed,
        KHÔNG phải độ dài `_utt_pcm` (buffer đó bị cắt ở `_utt_cap` để giới hạn
        bộ nhớ). Utterance dài hơn utt_cap_sec vẫn phải tiếp tục probe: nếu đo
        trên buffer đã cắt, `now` sẽ ghim ở mức cap mãi mãi và mốc trượt kế
        tiếp không bao giờ tới — probe đứng hình đúng lúc utterance dài nhất."""
        return self._fed_bytes / self._bps

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
