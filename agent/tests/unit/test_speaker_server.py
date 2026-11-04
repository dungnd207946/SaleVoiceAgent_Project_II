import base64

import numpy as np

import noble_agent.voice.service.speaker_server as srv


def test_embed_payload_roundtrip(monkeypatch):
    class _FakeEmbedder:
        def embed(self, pcm16):
            assert pcm16 == b"\x01\x00"
            return np.array([0.5, 0.5], dtype=np.float32)

    monkeypatch.setattr(srv, "_embedder", _FakeEmbedder())
    out = srv._handle_embed({"audio_b64": base64.b64encode(b"\x01\x00").decode("ascii")})
    assert out == {"embedding": [0.5, 0.5]}
