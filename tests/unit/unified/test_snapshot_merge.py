"""Snapshot merge: prompt construction + LLM-guarded merge_snapshot."""

from __future__ import annotations

from noble_agent.agent.memory import snapshot


def _history():
    return [
        {"role": "user", "content": "Tôi muốn đổi sang NCTH 3 phòng ngủ"},
        {"role": "assistant", "content": "Dạ NCTH có căn 3PN ạ"},
    ]


def test_build_merge_prompt_includes_old_and_history_and_rules():
    p = snapshot.build_merge_prompt("Anh Dự quan tâm NCLB 2PN.", _history())
    assert "Anh Dự quan tâm NCLB 2PN." in p       # old snapshot embedded
    assert "NCTH 3 phòng ngủ" in p                 # history embedded
    assert "GIỮ NGUYÊN" in p                        # preserve-old-facts rule present
    assert "SNAPSHOT MỚI" in p                      # output anchor present


def test_build_merge_prompt_handles_empty_old():
    p = snapshot.build_merge_prompt("", _history())
    assert "NCTH 3 phòng ngủ" in p


async def test_merge_snapshot_returns_llm_text(monkeypatch):
    async def _fake_llm(prompt: str) -> str:
        return "  Anh Dự nay quan tâm NCTH 3PN (đổi từ NCLB).  "

    monkeypatch.setattr(snapshot, "_call_merge_llm", _fake_llm)
    out = await snapshot.merge_snapshot("Anh Dự quan tâm NCLB 2PN.", _history())
    assert out == "Anh Dự nay quan tâm NCTH 3PN (đổi từ NCLB)."


async def test_merge_snapshot_empty_on_llm_failure(monkeypatch):
    async def _fake_llm(prompt: str) -> str:
        return ""

    monkeypatch.setattr(snapshot, "_call_merge_llm", _fake_llm)
    assert await snapshot.merge_snapshot("old", _history()) == ""


async def test_merge_snapshot_empty_when_no_history():
    assert await snapshot.merge_snapshot("old", []) == ""
