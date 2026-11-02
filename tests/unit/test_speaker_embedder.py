import base64

import numpy as np

import noble_agent.voice.speaker_verifier as sv


class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"embedding": [0.1, 0.2, 0.3]}


class _FakeClient:
    def __init__(self, *a, **k):
        self.posted = None

    def post(self, url, json=None):
        self.posted = (url, json)
        return _FakeResp()


def test_remote_embed_posts_base64_and_parses(monkeypatch):
    emb = sv.SpeakerEmbedder.__new__(sv.SpeakerEmbedder)  # bypass __init__/_load
    emb._extractor = None
    emb._remote_url = "http://svc:9000"
    emb._remote_client = _FakeClient()
    out = emb.embed(b"\x01\x00\x02\x00")
    assert isinstance(out, np.ndarray)
    np.testing.assert_allclose(out, np.array([0.1, 0.2, 0.3], dtype=np.float32), rtol=1e-6)
    url, payload = emb._remote_client.posted
    assert url == "http://svc:9000/embed"
    assert base64.b64decode(payload["audio_b64"]) == b"\x01\x00\x02\x00"


def test_embed_empty_returns_none():
    emb = sv.SpeakerEmbedder.__new__(sv.SpeakerEmbedder)
    emb._extractor = None
    emb._remote_client = None
    assert emb.embed(b"") is None
