# tests/unit/test_speaker_prewarm.py
import noble_agent.voice.prewarm as pw


def test_speaker_prewarm_skipped_in_remote_mode(monkeypatch):
    monkeypatch.setattr(pw.settings, "speaker_verification_enabled", True, raising=False)
    monkeypatch.setattr(pw.settings, "speaker_remote_url", "http://svc", raising=False)
    called = {"n": 0}
    # If prewarm tries to load the local extractor in remote mode, this would bump.
    import noble_agent.voice.speaker_verifier as sv

    monkeypatch.setattr(sv, "_get_extractor", lambda: called.__setitem__("n", called["n"] + 1))
    import noble_agent.voice.vad.silero as silero_mod  # prewarm also warms Silero — keep hermetic

    monkeypatch.setattr(silero_mod, "_load_shared_model", lambda: None)
    pw.prewarm_voice_models()
    assert called["n"] == 0
