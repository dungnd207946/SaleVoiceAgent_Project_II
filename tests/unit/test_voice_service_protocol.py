"""Pure framing/auth helpers for the voice service WS protocol (Task 2)."""

from __future__ import annotations

from noble_agent.voice.service import protocol as p


def test_transcript_msg_roundtrip():
    raw = p.transcript_msg(p.FINAL, "xin chào")
    assert p.parse(raw) == {"type": "final", "text": "xin chào"}


def test_synthesize_msg_with_voice():
    assert p.parse(p.synthesize_msg("a", voice="luna")) == {
        "type": "synthesize",
        "text": "a",
        "voice": "luna",
    }


def test_synthesize_msg_without_voice_omits_key():
    assert p.parse(p.synthesize_msg("a")) == {"type": "synthesize", "text": "a"}


def test_control_msg():
    assert p.parse(p.control_msg(p.END)) == {"type": "end"}


def test_auth_headers_empty_token_is_empty_dict():
    assert p.auth_headers("") == {}


def test_auth_headers_sets_bearer():
    assert p.auth_headers("tok") == {"Authorization": "Bearer tok"}


def test_token_from_headers():
    assert p.token_from_headers({"Authorization": "Bearer tok"}) == "tok"
    assert p.token_from_headers({}) == ""
    assert p.token_from_headers({"Authorization": "Basic xyz"}) == ""


def test_check_token_disabled_when_expected_empty():
    assert p.check_token({}, "") is True


def test_check_token_match_and_mismatch():
    assert p.check_token({"Authorization": "Bearer tok"}, "tok") is True
    assert p.check_token({"Authorization": "Bearer nope"}, "tok") is False
    assert p.check_token({}, "tok") is False
