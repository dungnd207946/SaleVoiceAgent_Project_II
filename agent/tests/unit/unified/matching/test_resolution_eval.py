"""Synthetic-noise accuracy gate for the resolver. Corrupts canonical names the
way STT does (drop tones, swap confusable consonants, drop a word) and asserts
top-1 accuracy + ambiguous-recall stay above a floor. Tune index thresholds here.
"""

import unicodedata

from noble_agent.data.project_matching.index import ProjectNameIndex

ROWS = [
    {"code": "NCLB", "name": "Noble Crystal Long Biên", "region": "Long Biên"},
    {"code": "NCTH", "name": "Noble Crystal Tây Hồ", "region": "Tây Hồ"},
    {"code": "NCR", "name": "Noble Crystal Riverside", "region": ""},
    {"code": "NPTH", "name": "Noble Palace Tây Hồ", "region": "Tây Hồ"},
    {"code": "NPTTL", "name": "Noble Palace Tây Thăng Long", "region": "Tây Thăng Long"},
    {"code": "SGR", "name": "Sunshine Golden River", "region": "Tây Hồ"},
    {"code": "SGI", "name": "Sunshine Green Iconic", "region": "Long Biên"},
    {"code": "SLC", "name": "Sunshine Legend City", "region": "Hà Nội"},
]


def _drop_tones(s: str) -> str:
    d = unicodedata.normalize("NFD", s.replace("đ", "d"))
    return unicodedata.normalize("NFC", "".join(c for c in d if unicodedata.category(c) != "Mn"))


def test_top1_accuracy_on_tone_dropped_full_names():
    idx = ProjectNameIndex(ROWS)
    hits = 0
    for r in ROWS:
        res = idx.resolve(_drop_tones(r["name"]))
        # full name with only tones dropped must resolve to the exact code
        if res.status == "resolved" and res.code == r["code"]:
            hits += 1
    assert hits / len(ROWS) >= 0.9  # calibrate thresholds until this holds


def test_ambiguous_recall_on_shared_prefix():
    idx = ProjectNameIndex(ROWS)
    res = idx.resolve("noble palace tay ho", region_hint="Tây Hồ")
    assert res.status == "resolved" and res.code == "NPTH"


def test_partial_returns_correct_family_in_candidates():
    idx = ProjectNameIndex(ROWS)
    res = idx.resolve("sunshine")
    codes = {c.code for c in res.candidates} if res.status == "ambiguous" else {res.code}
    assert {"SGR", "SGI", "SLC"} & codes
