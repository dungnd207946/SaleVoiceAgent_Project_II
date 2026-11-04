from noble_agent.data.project_matching.index import ProjectNameIndex

ROWS = [
    {"code": "NCLB", "name": "Noble Crystal Long Biên", "region": "Long Biên"},
    {"code": "NCTH", "name": "Noble Crystal Tây Hồ", "region": "Tây Hồ"},
    {"code": "NCR", "name": "Noble Crystal Riverside", "region": ""},
    {"code": "NPTH", "name": "Noble Palace Tây Hồ", "region": "Tây Hồ"},
    {"code": "SGR", "name": "Sunshine Golden River", "region": "Tây Hồ"},
]

VOP_ROWS = [
    {"code": "VOP2", "name": "Vinhomes Ocean Park 2", "region": "Hưng Yên"},
    {"code": "VOP3", "name": "Vinhomes Ocean Park 3", "region": "Hưng Yên"},
    {"code": "NCLB", "name": "Noble Crystal Long Biên", "region": "Long Biên"},
    {"code": "NCTH", "name": "Noble Crystal Tây Hồ", "region": "Tây Hồ"},
]


def _idx():
    return ProjectNameIndex(ROWS)


def _vop_idx():
    return ProjectNameIndex(VOP_ROWS)


def test_resolved_on_tone_stripped_full_name():
    r = _idx().resolve("noble crystal tay ho")
    assert r.status == "resolved"
    assert r.code == "NCTH"


def test_ambiguous_on_partial_name():
    r = _idx().resolve("crystal")
    assert r.status == "ambiguous"
    codes = {c.code for c in r.candidates}
    assert {"NCLB", "NCTH", "NCR"} <= codes


def test_region_hint_disambiguates():
    r = _idx().resolve("crystal", region_hint="Long Biên")
    assert r.status == "resolved"
    assert r.code == "NCLB"


def test_not_found_on_garbage():
    r = _idx().resolve("xyzzy quux nothing")
    assert r.status == "not_found"
    assert r.candidates == []


def test_not_found_carries_best_guess_on_clear_top1():
    # Heavy STT mangle of "Sunshine Golden River": under the ambiguous floor,
    # but top-1 clearly separated from top-2 → not_found still carries the
    # guess so the agent can confirm yes/no instead of re-asking open-ended.
    r = _idx().resolve("gô đờn ri vờ")
    assert r.status == "not_found"
    assert [c.code for c in r.candidates] == ["SGR"]


def test_not_found_no_guess_without_margin():
    # Non-name speech: top-1 and top-2 nearly tied → a guess would be noise.
    r = _idx().resolve("alo alo nghe rõ không")
    assert r.status == "not_found"
    assert r.candidates == []


def test_candidates_capped_at_four():
    r = _idx().resolve("noble")
    assert len(r.candidates) <= 4


def test_exact_query_resolves_despite_near_identical_distractor():
    # "Vinhomes Ocean Park 2" is an EXACT norm-name match; VOP3 sits at 0.934,
    # under the standard 0.09 margin — the exact short-circuit must still resolve.
    r = _vop_idx().resolve("Vinhomes Ocean Park 2")
    assert r.status == "resolved"
    assert r.code == "VOP2"


def test_typo_with_number_resolves_via_strong_tier():
    r = _vop_idx().resolve("vinhome ocean park 2")
    assert r.status == "resolved"
    assert r.code == "VOP2"


def test_no_number_query_stays_ambiguous_true_tie():
    r = _vop_idx().resolve("Vinhomes Ocean Park")
    assert r.status == "ambiguous"
    codes = {c.code for c in r.candidates}
    assert {"VOP2", "VOP3"} <= codes


def test_clear_margin_case_resolves_unchanged():
    r = _vop_idx().resolve("Ocean Park 3")
    assert r.status == "resolved"
    assert r.code == "VOP3"
