"""Tests for HippoRAG OpenIE triple parsing (pure) and the extract wrapper."""

from __future__ import annotations

from noble_agent.agent.rag.hipporag import openie


def test_parse_plain_json_array():
    txt = '[["Noble Crystal","ở","Tây Hồ"],["Noble Crystal","có","bể bơi"]]'
    triples = openie.parse_triples(txt)
    assert triples == [("Noble Crystal", "ở", "Tây Hồ"), ("Noble Crystal", "có", "bể bơi")]


def test_parse_fenced_json():
    txt = "Đây là kết quả:\n```json\n[[\"A\",\"r\",\"B\"]]\n```\nHết."
    assert openie.parse_triples(txt) == [("A", "r", "B")]


def test_parse_object_with_triples_key():
    txt = '{"triples": [["A","liên quan","B"], ["B","thuộc","C"]]}'
    assert openie.parse_triples(txt) == [("A", "liên quan", "B"), ("B", "thuộc", "C")]


def test_parse_garbage_returns_empty():
    assert openie.parse_triples("xin chào không có gì") == []
    assert openie.parse_triples("") == []
    assert openie.parse_triples(None) == []


def test_parse_drops_malformed_rows():
    txt = '[["A","r","B"], ["only","two"], "notalist", ["","r",""], ["X","r","Y"]]'
    # rows with <3 items, non-lists, or empty subject/object are dropped
    assert openie.parse_triples(txt) == [("A", "r", "B"), ("X", "r", "Y")]


async def test_extract_uses_injected_complete_fn():
    calls = {}

    async def fake_complete(prompt: str) -> str:
        calls["prompt"] = prompt
        return '[["Noble Crystal","ở","Tây Hồ"]]'

    triples = await openie.extract("Noble Crystal nằm ở Tây Hồ.", fake_complete)
    assert triples == [("Noble Crystal", "ở", "Tây Hồ")]
    assert "Noble Crystal nằm ở Tây Hồ." in calls["prompt"]


async def test_extract_swallows_llm_error():
    async def boom(prompt: str) -> str:
        raise RuntimeError("provider down")

    assert await openie.extract("bất kỳ", boom) == []
