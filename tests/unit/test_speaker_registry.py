import numpy as np
import pytest

from noble_agent.voice.speaker_tracker import SpeakerRegistry


def _vec(*xs: float) -> np.ndarray:
    return np.array(xs, dtype=np.float32)


A = _vec(0.0, 1.0)  # giọng A
B = _vec(1.0, 0.0)  # giọng B (trực giao với A)


def _reg(*, margin=0.1, max_identities=4, max_centroids=10, min_match=2, min_identify=1) -> SpeakerRegistry:
    return SpeakerRegistry(
        match_threshold=0.5,
        adapt_margin=margin,
        max_identities=max_identities,
        max_centroids=max_centroids,
        min_match_probe=min_match,
        min_match_identify=min_identify,
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

    def test_fifo_eviction_never_evicts_the_asker(self) -> None:
        """I1: FIFO trần (popleft vô điều kiện) đẩy đúng người đang giữ lượt vì
        asker thường là mục cũ nhất trong _order. A giữ lượt phải sống sót; B
        (cũ nhất KHÔNG phải asker) mới là mục bị đẩy ra."""
        r = _reg(max_identities=2)
        a = r.observe([_vec(1.0, 0.0, 0.0)], allow_new=True).identity
        r.set_asker(a)
        r.observe([_vec(0.0, 1.0, 0.0)], allow_new=True)  # B — oldest non-asker
        r.observe([_vec(0.0, 0.0, 1.0)], allow_new=True)  # C — trigger eviction
        assert r.asker == a
        assert r.identify(_vec(1.0, 0.0, 0.0))[0] == a  # A vẫn nhận diện được
        assert r.identify(_vec(0.0, 1.0, 0.0))[0] is None  # B (oldest non-asker) bị đẩy

    def test_centroid_cap_per_identity(self) -> None:
        r = _reg(max_centroids=3)
        ident = r.observe([A], allow_new=True).identity
        for _ in range(5):
            r.observe([A], allow_new=True)
        assert len(r._identities[ident]) == 3


class TestMinMatchProbe:
    """Probe chỉ được tính là speaker khi khớp ≥ min_match_probe centroid —
    trúng đúng 1 mẫu trong tập có thể chỉ là trùng hợp/echo."""

    A1 = _vec(1.0, 0.0)
    A2 = _vec(0.8, 0.6)  # đơn vị sẵn; cos(A1, A2) = 0.8

    def _asker_with_two_centroids(self, *, min_match=2) -> SpeakerRegistry:
        r = _reg(min_match=min_match)
        ident = r.observe([self.A1, self.A2], allow_new=True).identity
        r.set_asker(ident)
        return r

    def test_probe_matching_only_one_centroid_is_rejected(self) -> None:
        """cos với A1 = 1.0 (đạt), với A2 = 0.8 (trượt ngưỡng 0.9) → chỉ 1/2 → non-speaker.
        sim trả về là cosine hạng k (giá trị quyết định), không phải max."""
        r = self._asker_with_two_centroids()
        ok, sim = r.match_asker(self.A1, 0.9)
        assert ok is False
        assert sim == pytest.approx(0.8, abs=1e-3)

    def test_probe_matching_k_centroids_passes(self) -> None:
        r = self._asker_with_two_centroids()
        ok, sim = r.match_asker(self.A1, 0.7)  # 1.0 và 0.8 đều ≥ 0.7
        assert ok is True
        assert sim == pytest.approx(0.8, abs=1e-3)

    def test_k_is_clamped_to_set_size(self) -> None:
        """Tập mới chỉ có 1 centroid → yêu cầu 2 sẽ tự kẹp về 1, không khoá cứng."""
        r = _reg(min_match=2)
        ident = r.observe([A], allow_new=True).identity
        r.set_asker(ident)
        ok, sim = r.match_asker(A, 0.9)
        assert ok is True and sim > 0.99

    def test_no_asker_stays_fail_open(self) -> None:
        r = _reg(min_match=2)
        ok, sim = r.match_asker(B, 0.9)
        assert ok is True and sim == 1.0


class TestMinMatchIdentify:
    """identify() theo cosine hạng k: một centroid nhiễu đơn lẻ không được
    quyền 'bắt cóc' cụm của người khác về danh tính chứa nó."""

    A1 = _vec(0.0, 1.0, 0.0)  # giọng A thật
    NOISY = _vec(1.0, 0.0, 0.0)  # mẫu nhiễu lọt vào tập của A, tình cờ ≈ giọng B
    B = _vec(1.0, 0.0, 0.0)

    def test_one_noisy_centroid_cannot_capture_a_cluster(self) -> None:
        r = _reg(min_identify=2)
        r.observe([self.A1, self.NOISY], allow_new=True)
        ident, sim = r.identify(self.B)
        assert ident is None  # hạng-2 của B so với tập A = cos(B, A1) = 0 < 0.5
        assert sim < 0.5

    def test_default_k1_still_captures_via_max(self) -> None:
        """Đối chứng: k=1 (mặc định, hành vi cũ) thì mẫu nhiễu bắt được cụm."""
        r = _reg(min_identify=1)
        ident0 = r.observe([self.A1, self.NOISY], allow_new=True).identity
        ident, sim = r.identify(self.B)
        assert ident == ident0 and sim > 0.99

    def test_pair_written_by_one_cluster_still_matches_with_k2(self) -> None:
        """Mẫu luôn vào tập theo cụm ≥2 cửa sổ tương quan → match thật vẫn qua hạng-2."""
        w1 = _vec(1.0, 0.0, 0.0)
        w2 = _vec(0.95, 0.312, 0.0)  # cos(w1, w2) ≈ 0.95 — cặp cửa sổ cùng câu nói
        r = _reg(min_identify=2)
        ident0 = r.observe([w1, w2], allow_new=True).identity
        ident, sim = r.identify(w1)
        assert ident == ident0
        assert sim == pytest.approx(0.95, abs=0.01)  # sim là hạng-2, không phải max

    def test_k_clamped_for_single_centroid_set(self) -> None:
        r = _reg(min_identify=2)
        ident0 = r.observe([self.A1], allow_new=True).identity
        ident, sim = r.identify(self.A1)
        assert ident == ident0 and sim > 0.99


class TestRegistryDropAsker:
    def test_drop_asker_reopens_the_floor(self) -> None:
        r = _reg()
        ident = r.observe([A], allow_new=True).identity
        r.set_asker(ident)
        r.drop_asker()
        assert r.asker is None
        assert r.identify(A)[0] is None  # danh tính đã bị xoá hẳn
        assert r.match_asker(B, 0.5)[0] is True  # floor mở lại
