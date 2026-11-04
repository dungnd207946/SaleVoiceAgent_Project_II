"""judge_client — cache/budget/call thuần, network mock hết."""
import json

import pytest
from evals import judge_client as jc


def test_cache_roundtrip(tmp_path):
    jc.set_cache_path(tmp_path / "c.db")
    key = jc.cache_key("case-1", "output", "model", "rubric-v1")
    assert jc.cache_get(key) is None
    jc.cache_put(key, {"x": 1})
    assert jc.cache_get(key) == {"x": 1}
    jc.set_cache_path(None)  # tắt → get trả None
    assert jc.cache_get(key) is None


def test_cache_key_differs_by_rubric():
    assert jc.cache_key("a", "b", "m", "v1") != jc.cache_key("a", "b", "m", "v2")


async def test_budget_exceeded_raises(monkeypatch):
    jc.reset_cost()
    jc.set_budget(0.0)
    monkeypatch.setattr(jc, "_COST_USD", 1.0)
    with pytest.raises(jc.BudgetExceeded):
        await jc.call_llm("gpt-4o", "s", "u")
    jc.set_budget(None)
    jc.reset_cost()


async def test_call_llm_json_retries_then_none(monkeypatch):
    calls = []

    async def fake_call(model, system, user, *, json_mode=True, max_tokens=800):
        calls.append(1)
        return "not json"

    monkeypatch.setattr(jc, "call_llm", fake_call)
    monkeypatch.setattr(jc.asyncio, "sleep", _no_sleep)
    raw, parsed = await jc.call_llm_json("m", "s", "u")
    assert parsed is None
    assert len(calls) == jc.JUDGE_RETRY + 1


async def test_call_llm_json_parses(monkeypatch):
    async def fake_call(model, system, user, *, json_mode=True, max_tokens=800):
        return json.dumps({"ok": 1})

    monkeypatch.setattr(jc, "call_llm", fake_call)
    raw, parsed = await jc.call_llm_json("m", "s", "u")
    assert parsed == {"ok": 1}


async def _no_sleep(_s):
    return None
