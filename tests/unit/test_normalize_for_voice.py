"""Golden-case tests for normalize_for_voice — Vietnamese TTS text normalization.

Cases live in normalize_cases.json (ported from the standalone normalize module).
Each case is a full conversational sentence; `out` is the expected normalized form
sent to the TTS service. Runs entirely offline (stdlib-only module, no DB/GPU).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from noble_agent.voice.tts._normalize import normalize_for_voice

_CASES_PATH = Path(__file__).resolve().parent / "normalize_cases.json"


def _load_cases() -> list[tuple[str, str, str]]:
    data = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    cases: list[tuple[str, str, str]] = []
    for group in data["groups"]:
        gname = group["name"]
        for case in group["cases"]:
            cases.append((gname, case["in"], case["out"]))
    return cases


_CASES = _load_cases()


@pytest.mark.parametrize(
    ("group", "text_in", "expected"),
    _CASES,
    ids=[f"{i}:{c[1][:40]}" for i, c in enumerate(_CASES)],
)
def test_normalize_for_voice(group: str, text_in: str, expected: str) -> None:
    assert normalize_for_voice(text_in) == expected, f"group={group}"


def test_empty_and_none_passthrough() -> None:
    assert normalize_for_voice("") == ""
    assert normalize_for_voice(None) is None
