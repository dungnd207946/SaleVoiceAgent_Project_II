import json

from noble_agent.agent.tools import find_project
from noble_agent.data.project_matching.index import ProjectNameIndex

ROWS = [
    {"code": "NCLB", "name": "Noble Crystal Long Biên", "region": "Long Biên"},
    {"code": "NCTH", "name": "Noble Crystal Tây Hồ", "region": "Tây Hồ"},
    {"code": "NCR", "name": "Noble Crystal Riverside", "region": ""},
    {"code": "SGR", "name": "Sunshine Golden River", "region": "Tây Hồ"},
]


class _Cust:
    project_interest = None


class _State:
    def __init__(self, recent=None):
        self.scratchpad = {"recent_projects": list(recent)} if recent else {}


class _Disp:
    def __init__(self, recent=None):
        self.customer = _Cust()
        self.state = _State(recent)
        self.dirty = False

    def mark_customer_dirty(self):
        self.dirty = True


def setup_function():
    find_project.set_index(ProjectNameIndex(ROWS))


async def test_resolved_sets_project_interest():
    d = _Disp()
    out = json.loads(await find_project.run(d, {"query": "noble crystal tay ho"}))
    assert out["status"] == "resolved"
    assert out["code"] == "NCTH"
    assert d.customer.project_interest == "NCTH"
    assert d.dirty is True


async def test_ambiguous_returns_candidates_no_write():
    d = _Disp()
    out = json.loads(await find_project.run(d, {"query": "crystal"}))
    assert out["status"] == "ambiguous"
    assert len(out["candidates"]) >= 2
    assert d.customer.project_interest is None


async def test_not_found_with_best_guess_no_write():
    # STT-mangled "Golden River": not resolvable, but the payload must carry
    # a best_guess for the yes/no confirm flow — without writing the profile.
    d = _Disp()
    out = json.loads(await find_project.run(d, {"query": "gô đờn ri vờ"}))
    assert out["status"] == "not_found"
    assert out["best_guess"]["code"] == "SGR"
    assert d.customer.project_interest is None
    assert d.dirty is False


async def test_not_found_garbage_has_no_best_guess():
    d = _Disp()
    out = json.loads(await find_project.run(d, {"query": "xyzzy quux nothing"}))
    assert out["status"] == "not_found"
    assert "best_guess" not in out


async def test_no_index_is_safe():
    find_project.set_index(None)
    d = _Disp()
    out = json.loads(await find_project.run(d, {"query": "crystal"}))
    assert out["status"] == "not_found"


def test_index_is_per_tenant(monkeypatch):
    from noble_agent.config import reset_settings_for_tests
    from noble_agent.tenant.current import use_tenant

    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()

    idx_a = ProjectNameIndex([{"code": "AAA", "name": "Alpha", "region": "", "type": ""}])
    idx_b = ProjectNameIndex([{"code": "BBB", "name": "Beta", "region": "", "type": ""}])
    find_project.set_index(idx_a, tenant="t_a")
    find_project.set_index(idx_b, tenant="t_b")

    with use_tenant("t_a"):
        assert find_project.get_index() is idx_a
    with use_tenant("t_b"):
        assert find_project.get_index() is idx_b


# ── recently-listed prior ────────────────────────────────────────────────────
# The customer is usually picking from the projects Luna JUST read out. Fuzzy
# scoring cannot recover an STT-mangled English name ("Sansai" for Sunshine),
# so find_project hands the LLM that shortlist and asks it to confirm CÓ/KHÔNG.


async def test_not_found_attaches_recently_listed_for_llm_confirm():
    d = _Disp(recent=["NCLB", "SGR"])
    out = json.loads(await find_project.run(d, {"query": "Sansai"}))
    assert out["status"] == "not_found"
    assert [c["code"] for c in out["recently_listed"]] == ["NCLB", "SGR"]
    assert out["recently_listed"][1]["name"] == "Sunshine Golden River"
    assert "xác nhận" in out["message"]
    # after the customer confirms, the LLM re-calls find_project with the full
    # name so project_interest is written through the normal resolved path
    assert "find_project(query=" in out["message"]
    assert d.customer.project_interest is None
    assert d.dirty is False


async def test_recently_listed_skips_codes_unknown_to_index():
    d = _Disp(recent=["GONE", "SGR"])
    out = json.loads(await find_project.run(d, {"query": "Sansai"}))
    assert [c["code"] for c in out["recently_listed"]] == ["SGR"]


async def test_not_found_without_recent_is_unchanged():
    d = _Disp()
    out = json.loads(await find_project.run(d, {"query": "Sansai"}))
    assert out["status"] == "not_found"
    assert "recently_listed" not in out


async def test_ambiguous_narrows_to_single_recent_candidate_and_resolves():
    # "crystal" is ambiguous across the Noble Crystal family, but only NCTH was
    # just read to the customer → that is the one they mean.
    d = _Disp(recent=["SGR", "NCTH"])
    out = json.loads(await find_project.run(d, {"query": "crystal"}))
    assert out["status"] == "resolved"
    assert out["code"] == "NCTH"
    assert d.customer.project_interest == "NCTH"
    assert d.dirty is True


async def test_ambiguous_keeps_only_recent_candidates_when_several():
    d = _Disp(recent=["NCLB", "NCTH"])
    out = json.loads(await find_project.run(d, {"query": "crystal"}))
    assert out["status"] == "ambiguous"
    assert {c["code"] for c in out["candidates"]} == {"NCLB", "NCTH"}
    assert d.customer.project_interest is None


async def test_ambiguous_with_no_recent_overlap_is_unchanged():
    d = _Disp(recent=["SGR"])
    out = json.loads(await find_project.run(d, {"query": "crystal"}))
    assert out["status"] == "ambiguous"
    assert len(out["candidates"]) >= 2
