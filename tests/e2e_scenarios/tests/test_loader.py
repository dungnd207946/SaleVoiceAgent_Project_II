"""Unit tests for the YAML scenario loader (strict validation)."""

from __future__ import annotations

import pytest

from tests.e2e_scenarios.loader import Scenario, parse_scenario


def _valid():
    return {
        "name": "s1",
        "description": "d",
        "turns": [
            {"user": "alo em", "expect": {"tool_called": "kb_search"}},
            {"user": "giá bao nhiêu", "expect": {}},
        ],
    }


class TestParse:
    def test_valid(self):
        s = parse_scenario(_valid())
        assert isinstance(s, Scenario)
        assert s.name == "s1"
        assert len(s.turns) == 2
        assert s.turns[0].expect["tool_called"] == "kb_search"

    def test_turn_without_expect_defaults_empty(self):
        s = parse_scenario(_valid())
        assert s.turns[1].expect == {}

    def test_optional_customer(self):
        data = _valid()
        data["customer"] = {"name": "Anh Minh"}
        assert parse_scenario(data).customer == {"name": "Anh Minh"}


class TestValidation:
    def test_missing_name(self):
        data = _valid()
        del data["name"]
        with pytest.raises(ValueError, match="name"):
            parse_scenario(data)

    def test_empty_turns(self):
        data = _valid()
        data["turns"] = []
        with pytest.raises(ValueError, match="turns"):
            parse_scenario(data)

    def test_turn_missing_user(self):
        data = _valid()
        data["turns"][0] = {"expect": {}}
        with pytest.raises(ValueError, match="user"):
            parse_scenario(data)

    def test_unknown_expect_key(self):
        data = _valid()
        data["turns"][0]["expect"] = {"reply_has": "x"}  # typo, not a known key
        with pytest.raises(ValueError, match="unknown expect keys"):
            parse_scenario(data)

    def test_not_a_mapping(self):
        with pytest.raises(ValueError, match="mapping"):
            parse_scenario(["not", "a", "dict"])
