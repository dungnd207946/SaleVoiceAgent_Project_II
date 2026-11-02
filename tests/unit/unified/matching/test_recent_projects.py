"""recent_projects — scratchpad memory of the project codes Luna just read to
the customer, consumed by find_project as a resolution prior."""

from types import SimpleNamespace

from noble_agent.agent.tools import recent_projects as rp


def _state(**scratch):
    return SimpleNamespace(scratchpad=dict(scratch))


def test_recall_empty_when_nothing_recorded():
    assert rp.recall(_state()) == []


def test_remember_keeps_latest_listing_first_and_dedupes():
    st = _state()
    rp.remember(st, ["A", "B", "C"])
    rp.remember(st, ["C", "D"])
    assert rp.recall(st) == ["C", "D", "A", "B"]


def test_remember_caps_history_keeping_newest():
    st = _state()
    rp.remember(st, [f"P{i}" for i in range(10)])
    got = rp.recall(st)
    assert len(got) == rp.MAX_RECENT
    assert got[0] == "P0"


def test_remember_ignores_blank_codes_and_empty_input():
    st = _state()
    rp.remember(st, ["", None, "A"])
    rp.remember(st, [])
    assert rp.recall(st) == ["A"]


def test_recall_tolerates_corrupt_scratchpad():
    # Redis state is external data: a wrong-typed value must not crash a turn.
    assert rp.recall(_state(recent_projects="not-a-list")) == []
    assert rp.recall(_state(recent_projects=[1, "A", None])) == ["A"]
