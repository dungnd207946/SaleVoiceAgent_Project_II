"""Behavioral tests for project_catalog.normalize() — ported from voiceagentrag."""

from __future__ import annotations

from noble_agent.agent import catalog as pc

ALL_CODES = [
    "NCLB",
    "NCTH",
    "NPLB",
    "NPTTL",
    "SLC",
    "NCR",
    "NPTH",
    "SSC",
    "SGR",
    "SGI",
    "SRP",
    "SCHN",
    "SBR",
    "ASM",
    "ALM",
]


# --- codes ---
def test_canonical_code_passthrough():
    assert pc.normalize("NCLB") == "NCLB"
    assert pc.normalize("NCTH") == "NCTH"
    assert pc.normalize("NPLB") == "NPLB"
    assert pc.normalize("NPTTL") == "NPTTL"
    assert pc.normalize("SSLC") == "SLC"


def test_fifteen_codes_passthrough():
    for code in ALL_CODES:
        assert pc.normalize(code) == code
        assert pc.normalize(code.lower()) == code


def test_lowercase_code_uppercased():
    assert pc.normalize("nclb") == "NCLB"
    assert pc.normalize("  sslc  ") == "SLC"


# --- ids ---
def test_int_id_resolves_to_code():
    assert pc.normalize(1) == "NCLB"
    assert pc.normalize(2) == "NCTH"
    assert pc.normalize(3) == "NPLB"
    assert pc.normalize(4) == "NPTTL"
    assert pc.normalize(5) == "SLC"


def test_unknown_id_returns_empty():
    assert pc.normalize(0) == ""
    assert pc.normalize(99) == ""


# --- unique aliases ---
def test_full_name_vietnamese():
    assert pc.normalize("Noble Crystal Long Biên") == "NCLB"
    assert pc.normalize("noble crystal long bien") == "NCLB"
    assert pc.normalize("Crystal Tây Hồ") == "NCTH"
    assert pc.normalize("palace long biên") == "NPLB"
    assert pc.normalize("noble palace tây thăng long") == "NPTTL"
    assert pc.normalize("Sunshine Legend City") == "SLC"


def test_unique_short_aliases():
    # NTTL: "thăng long" unique
    assert pc.normalize("thăng long") == "NPTTL"
    assert pc.normalize("thang long") == "NPTTL"
    # SLC: still brand-unique on "legend"
    assert pc.normalize("legend") == "SLC"
    assert pc.normalize("legend city") == "SLC"


def test_new_project_unique_aliases():
    assert pc.normalize("crystal riverside") == "NCR"
    assert pc.normalize("palace tây hồ") == "NPTH"
    assert pc.normalize("palace tay ho") == "NPTH"
    assert pc.normalize("sky city") == "SSC"
    assert pc.normalize("sunshine sky city") == "SSC"
    assert pc.normalize("golden river") == "SGR"
    assert pc.normalize("green iconic") == "SGI"
    assert pc.normalize("river park") == "SRP"
    assert pc.normalize("sunshine city hà nội") == "SCHN"
    assert pc.normalize("sunshine city hanoi") == "SCHN"
    assert pc.normalize("bay retreat") == "SBR"
    assert pc.normalize("alluvia sunshine marina") == "ASM"
    assert pc.normalize("alumi") == "ALM"
    assert pc.normalize("alluvia city") == "ALM"


def test_sunshine_now_ambiguous():
    # "sunshine" spans 8 Sunshine* + the Alluvia-Sunshine project → no longer unique.
    assert pc.normalize("sunshine") == ""
    # "tây hồ" / "tay ho" now span NCTH (Crystal) + NPTH (Palace) → ambiguous.
    assert pc.normalize("tây hồ") == ""
    assert pc.normalize("tay ho") == ""


def test_longest_alias_wins():
    # "palace long bien" must beat any shorter substring of itself
    assert pc.normalize("palace long bien") == "NPLB"


# --- ambiguous (must return empty so agent asks) ---
def test_ambiguous_returns_empty():
    assert pc.normalize("long biên") == ""  # NCLB + NPLB
    assert pc.normalize("long bien") == ""
    assert pc.normalize("crystal") == ""  # NCLB + NCTH
    assert pc.normalize("palace") == ""  # NPLB + NTTL
    assert pc.normalize("noble") == ""  # all 4 Noble
    assert pc.normalize("noble palace") == ""  # NPLB + NTTL


# --- edges ---
def test_none_and_empty():
    assert pc.normalize(None) == ""
    assert pc.normalize("") == ""
    assert pc.normalize("   ") == ""


def test_alias_embedded_in_longer_sentence():
    # Real user turn, mixed alias + noise
    assert pc.normalize("em xem crystal long biên nhé") == "NCLB"
    # "sunshine" alone is now ambiguous → "" (the agent must clarify).
    assert pc.normalize("dự án sunshine thế nào") == ""
    assert pc.normalize("cho em hỏi sunshine sky city có gì") == "SSC"


def test_no_alias_is_ambiguous():
    """Programmatic guard: every alias must resolve to exactly its owning code.

    Catches an accidental cross-project alias collision: if any alias string
    in any project's list normalizes to a DIFFERENT code than its owner, the
    catalog is broken.
    """
    for proj in pc.all_projects():
        for alias in proj.aliases:
            assert pc.normalize(alias) == proj.code, (
                f"alias {alias!r} of {proj.code} resolved to {pc.normalize(alias)!r}"
            )


def test_no_match_returns_empty():
    assert pc.normalize("xxxxxxx") == ""
    assert pc.normalize("vinhomes") == ""


def test_substring_false_positive_rejected():
    # Word-boundary matching: the short alias "legend" must NOT fire inside a
    # longer word like "legendary"/"legends" (it used to, via substring match).
    assert pc.normalize("legendary") == ""
    assert pc.normalize("legends") == ""
    # …but the exact word, and the word embedded in a sentence, still resolve.
    assert pc.normalize("legend") == "SLC"
    assert pc.normalize("dự án legend có gì hot") == "SLC"


# --- by_code / by_id / all_projects ---
def test_by_code_roundtrip():
    p = pc.by_code("NCLB")
    assert p is not None
    assert p.code == "NCLB"
    assert p.name_vi == "Noble Crystal Long Biên"
    assert p.id == 1
    assert pc.by_code("XXXX") is None


def test_by_id_roundtrip():
    p = pc.by_id(5)
    assert p is not None
    assert p.code == "SLC"
    assert pc.by_id(99) is None


def test_valid_codes_frozenset():
    assert frozenset(ALL_CODES) == pc.VALID_CODES


def test_all_projects_stable_order():
    ids = [p.id for p in pc.all_projects()]
    assert ids == list(range(1, 16))
