"""Unit tests for the parallel speaker-verification engine (spec 2026-08-28).

Pure-logic tests: no model, no settings — embedder/scheduler are injected fakes.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

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
        cs.add(_vec(1.0, 0.0))  # xa query
        cs.add(_vec(0.0, 1.0))  # trùng query → max thắng
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
        cs.add(_vec(1.0, 0.0))  # sẽ bị đẩy ra
        cs.add(_vec(0.0, 1.0))
        cs.add(_vec(-1.0, 0.0))  # đẩy centroid đầu ra
        assert len(cs) == 2
        ok, _ = cs.match(_vec(1.0, 0.0))  # chỉ còn (0,1) và (-1,0) → không match
        assert ok is False

    def test_reset_empties(self) -> None:
        cs = CentroidSet(threshold=0.5, max_centroids=10)
        cs.add(_vec(1.0, 0.0))
        cs.reset()
        assert cs.empty


import asyncio

from noble_agent.voice.speaker_tracker import SpeakerRegistry, SpeakerTracker

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


class RaisingEmbedder:
    """Embedder giả lập lỗi: __call__ luôn raise (fix round 1 — Finding 2/3)."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    async def __call__(self, pcm: bytes) -> np.ndarray | None:
        self.calls.append(len(pcm))
        raise RuntimeError("embed service down")


def _spawn(coro):
    return asyncio.ensure_future(coro)


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
    utt_cap=30.0,
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
        utt_cap_sec=utt_cap,
        single_identity=single_identity,
        on_verdict=on_verdict,
        spawn_bg=_spawn,
    )


SPK = _vec(0.0, 1.0)  # giọng khách
OTHER = _vec(1.0, 0.0)  # giọng người lạ (trực giao)


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

    async def test_tail_probing_continues_past_utt_cap(self) -> None:
        """Utterance dài hơn utt_cap_sec KHÔNG được đứng hình: nếu elapsed đo
        trên `_utt_pcm` (buffer đã bị cắt ở cap) thay vì tổng byte đã feed, `now`
        ghim ở mức cap mãi mãi và mốc trượt kế tiếp không bao giờ tới — barge-in
        chết lặng lẽ đúng lúc utterance dài nhất."""
        emb = FakeEmbedder([OTHER, OTHER, OTHER])
        t = _tracker(emb, marks=(), thresholds=(0.65,), tail_window=0.5, tail_hop=0.5, utt_cap=1.0)
        reg = t._registry
        reg.set_asker(reg.observe([SPK], allow_new=True).identity)
        t.begin_utterance()
        t.feed(_pcm(0.5))  # bootstrap mốc trượt đầu tiên (elapsed=0.5s) — chưa probe
        await asyncio.sleep(0)
        t.feed(_pcm(0.5))  # elapsed=1.0s == cap → probe #1
        await asyncio.sleep(0)
        t.feed(_pcm(0.5))  # elapsed=1.5s > cap: buffer đã bị cắt còn 1.0s — vẫn phải probe #2
        await asyncio.sleep(0)
        t.feed(_pcm(0.5))  # elapsed=2.0s — probe #3 chứng minh không đứng hình sau cap
        await asyncio.sleep(0)
        assert len(emb.calls) == 3
        assert emb.calls == [int(0.5 * BPS)] * 3


class TestSpeakerTrackerInflight:
    async def test_single_inflight_backlog_folds_into_next_probe(self) -> None:
        """Đúng MỘT embed inflight — feed dồn dập trong lúc probe đang treo
        không được spawn embed thứ hai chạy song song; khi land, backlog dồn
        được cắt cho probe kế tiếp (cửa sổ trượt)."""
        emb = FakeEmbedder([OTHER, OTHER])
        emb.release.clear()  # chặn embed #1
        t = _tracker(emb, marks=(), thresholds=(0.65,), tail_window=1.0, tail_hop=0.5)
        reg = t._registry
        reg.set_asker(reg.observe([SPK], allow_new=True).identity)
        t.begin_utterance()
        t.feed(_pcm(0.5))  # bootstrap mốc trượt đầu tiên — chưa probe
        await asyncio.sleep(0)
        t.feed(_pcm(0.5))  # elapsed=1.0s ≥ next_tail_sec → probe #1, inflight treo
        await asyncio.sleep(0)  # task #1 chạy tới điểm chặn (release.wait())
        t.feed(_pcm(0.5))  # KHÔNG cắt (inflight) — dồn buffer
        t.feed(_pcm(0.5))  # vẫn dồn
        assert len(emb.calls) == 1
        emb.release.set()  # thả embed #1
        for _ in range(4):
            await asyncio.sleep(0)
        assert len(emb.calls) == 2  # sau khi land, backlog dồn đủ → probe #2 tự fire


class TestSpeakerTrackerVerdictAndGuard:
    async def test_on_verdict_called_with_label_sim_idx(self) -> None:
        seen: list[tuple[str, int]] = []

        async def on_verdict(label: str, sim: float, idx: int) -> None:
            seen.append((label, idx))

        emb = FakeEmbedder([OTHER])
        t = _tracker(emb, marks=(0.25,), thresholds=(0.65,), on_verdict=on_verdict)
        reg = t._registry
        reg.set_asker(reg.observe([SPK], allow_new=True).identity)
        t.begin_utterance()
        t.feed(_pcm(0.25))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert seen == [("non-speaker", 0)]

    async def test_stale_embed_discarded_after_new_utterance(self) -> None:
        emb = FakeEmbedder([SPK])
        emb.release.clear()
        t = _tracker(emb, marks=(0.25,), thresholds=(0.65,))
        reg = t._registry
        reg.set_asker(reg.observe([SPK], allow_new=True).identity)
        t.begin_utterance()
        t.feed(_pcm(0.25))  # inflight treo
        t.begin_utterance()  # utterance mới TRƯỚC khi embed land
        emb.release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert t._labels == []  # verdict cũ bị discard

    async def test_embed_failure_labels_unknown(self) -> None:
        emb = FakeEmbedder([None])
        t = _tracker(emb, marks=(0.25,), thresholds=(0.65,))
        t.begin_utterance()
        t.feed(_pcm(0.25))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert t._labels == ["unknown"]


class TestSpeakerTrackerEmbedRaises:
    """Fix round 1 — Finding 2/3: embed raise phải xử lý như emb=None (spec §5)."""

    async def test_embed_raise_labels_unknown_and_fires_verdict(self) -> None:
        seen: list[tuple[str, float, int]] = []

        async def on_verdict(label: str, sim: float, idx: int) -> None:
            seen.append((label, sim, idx))

        emb = RaisingEmbedder()
        t = _tracker(emb, marks=(0.25,), thresholds=(0.65,), on_verdict=on_verdict)
        reg = t._registry
        reg.set_asker(reg.observe([SPK], allow_new=True).identity)
        t.begin_utterance()
        t.feed(_pcm(0.25))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert t._labels == ["unknown"]
        assert math.isnan(t._sims[0])
        assert len(seen) == 1
        label, sim, idx = seen[0]
        assert label == "unknown"
        assert math.isnan(sim)
        assert idx == 0

    async def test_finalize_survives_embed_raise_returns_empty_verdict(self) -> None:
        """Cold path: mọi cửa sổ enroll đều raise → finalize không được để lộ
        exception ra ngoài, trả verdict rỗng (fail-open) thay vì crash turn loop."""
        emb = RaisingEmbedder()
        t = _tracker(emb)
        t.begin_utterance()
        t.feed(_pcm(3.0))
        v = await t.finalize()  # không được để lộ RuntimeError ra ngoài
        assert v.identity is None
        assert len(emb.calls) >= 1


class TestConsensusEnroll:
    async def test_consistent_windows_enroll_all(self) -> None:
        # marks=(): utterance dài liền một hơi (feed một lần) sẽ bị chuỗi mốc mặc
        # định của _tracker tự bắn probe (hot path) trước khi finalize() kịp cắt
        # cửa sổ enroll (cold path) — hai đường CÙNG DÙNG self._embed, nên probe ăn
        # trước sẽ làm cạn kịch bản FakeEmbedder dành cho enroll. Tắt hẳn mốc probe
        # để cách ly rành mạch hành vi cold-path đang kiểm ở đây.
        emb = FakeEmbedder([SPK, SPK, SPK])
        t = _tracker(emb, marks=())
        t.begin_utterance()
        t.feed(_pcm(3.0))
        v = await t.finalize()
        assert v.cluster_size >= 2 and v.is_new and v.identity is not None

    async def test_outlier_window_is_excluded_from_the_cluster(self) -> None:
        """W2 lạc loài (trực giao) không được thành centroid — đây là chốt chống
        'audio tồi biến thành chuẩn danh tính' của bản 2026-08-28."""
        emb = FakeEmbedder([SPK, OTHER, SPK])
        t = _tracker(emb, marks=())  # cách ly hot-path probe khỏi kịch bản enroll
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
        t = _tracker(emb, marks=())  # cách ly hot-path probe khỏi kịch bản enroll
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
        t = _tracker(emb, single_identity=True, marks=())  # cách ly hot-path probe
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
        được kéo nhãn/PCM của utterance kế vào verdict đang chốt.

        Fix round 1 — Finding 1: kiểm bằng NỘI DUNG thay vì `probe_labels is not
        None` (vacuous — luôn đúng bất kể finalize trả gì). `emb.release.clear()`
        chặn embed cửa sổ đầu để finalize() THẬT SỰ còn đang await khi utterance
        0.1s chen vào; cả 3 cửa sổ enroll (1.5s/cửa sổ, hop 0.75s) phải bám đúng
        3.0s GỐC — không lệch cỡ vì utterance kế, và verdict vẫn chốt danh tính
        từ 3 cửa sổ SPK gốc (mirror của test đã xoá ở base_session, style
        `calls[-2:] == [int(3.0*bps), ...]`, thích nghi với API cửa sổ trượt)."""
        emb = FakeEmbedder([SPK, SPK, SPK])
        t = _tracker(emb, marks=())  # cách ly hot-path probe khỏi kịch bản enroll
        t.begin_utterance()
        t.feed(_pcm(3.0))
        emb.release.clear()  # chặn embed cửa sổ đầu: finalize() kẹt trong _embed_windows
        task = asyncio.ensure_future(t.finalize())
        await asyncio.sleep(0)  # finalize() chạy synchronously tới điểm chặn (release.wait())
        t.begin_utterance()  # utterance mới chen vào GIỮA lúc finalize() đang await
        t.feed(_pcm(0.1))
        emb.release.set()
        v = await task
        # Cả 3 cửa sổ enroll đều bám 3.0s GỐC — utterance 0.1s không lọt vào.
        assert emb.calls == [int(1.5 * BPS)] * 3
        assert v.identity is not None
        assert v.cluster_size >= 2
