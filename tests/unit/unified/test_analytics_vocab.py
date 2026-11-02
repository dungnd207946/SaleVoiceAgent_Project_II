"""Vocab cache per-tenant + inject per-turn vào description (AgentDef frozen
nên KHÔNG chèn lúc build_schemas — chèn ở runner mỗi lượt)."""

import copy

import pytest

from noble_agent.agent.tools import analytics_vocab as av


@pytest.fixture(autouse=True)
def _reset():
    av.reset_for_tests()


def _schemas(with_analyze=True):
    out = [
        {"type": "function", "function": {"name": "kb_search", "description": "Tra cứu tài liệu.",
                                          "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "search_units", "description": "Tìm căn.",
                                          "parameters": {"type": "object", "properties": {}}}},
    ]
    if with_analyze:
        out.append({"type": "function", "function": {
            "name": "analyze_projects", "description": f"Thống kê.\n{av.VOCAB_TOKEN}",
            "parameters": {"type": "object", "properties": {}}}})
    return out


def test_inject_noop_without_analyze_tool():
    schemas = _schemas(with_analyze=False)
    assert av.inject(schemas) is schemas  # fast-path: cùng object


def test_inject_strips_token_when_no_vocab():
    out = av.inject(_schemas())
    desc = next(s for s in out if s["function"]["name"] == "analyze_projects")["function"]["description"]
    assert av.VOCAB_TOKEN not in desc


def test_inject_puts_cached_vocab_and_xref(monkeypatch):
    monkeypatch.setattr(av, "_current_tenant", lambda: "t1")
    av._store("t1", "GIÁ TRỊ THỰC TẾ:\n- product_type: căn hộ, shophouse")
    src = _schemas()
    before = copy.deepcopy(src)
    out = av.inject(src)
    assert src == before  # không mutate input (schemas cache trong AgentDef frozen)
    by_name = {s["function"]["name"]: s["function"]["description"] for s in out}
    assert "căn hộ, shophouse" in by_name["analyze_projects"]
    assert "analyze_projects" in by_name["kb_search"]      # xref ranh giới 2 chiều
    assert "analyze_projects" in by_name["search_units"]


async def test_warm_if_stale_never_raises(monkeypatch):
    async def boom(sql):
        raise RuntimeError("no pg")

    monkeypatch.setattr(av, "_fetch_distinct", boom)
    monkeypatch.setattr(av, "_current_tenant", lambda: "t1")
    await av.warm_if_stale(600)  # không raise
    assert av.vocab_block("t1") == ""


async def test_warm_builds_block_and_ttl_debounces(monkeypatch):
    calls = []

    async def fake_fetch(sql):
        calls.append(sql)
        return ["căn hộ", "shophouse"]

    monkeypatch.setattr(av, "_fetch_distinct", fake_fetch)
    monkeypatch.setattr(av, "_current_tenant", lambda: "t1")
    await av.warm_if_stale(600)
    n = len(calls)
    assert n == len(av._VOCAB_SQLS)
    assert "căn hộ" in av.vocab_block("t1")
    await av.warm_if_stale(600)  # trong TTL → không query lại
    assert len(calls) == n
