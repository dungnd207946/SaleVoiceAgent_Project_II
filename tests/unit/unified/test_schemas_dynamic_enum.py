"""kb_search / send_media project-code params carry no enum — codes are
resolved via the find_project tool instead of a per-session DB-code snapshot."""

from __future__ import annotations

from noble_agent.agent.tools import schemas


def _by_name(names):
    return {s["function"]["name"]: s for s in schemas.schemas_for(names)}


def test_no_project_enum_injected():
    s = _by_name(["kb_search", "send_media"])
    assert "enum" not in s["kb_search"]["function"]["parameters"]["properties"]["project_filter"]
    assert "enum" not in s["send_media"]["function"]["parameters"]["properties"]["project_code"]
