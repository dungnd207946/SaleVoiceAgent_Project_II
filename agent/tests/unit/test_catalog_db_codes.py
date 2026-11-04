"""catalog.normalize returns DB ma_du_an codes; by_code is case-insensitive."""

from __future__ import annotations

import pytest

from noble_agent.agent import catalog


@pytest.mark.parametrize(
    "raw,code",
    [
        ("NCR", "NCR"),
        ("ncr", "NCR"),
        ("NCRS", "NCR"),
        ("crystal riverside", "NCR"),
        ("SLC", "SLC"),
        ("SSLC", "SLC"),
        ("legend city", "SLC"),
        ("ASM", "ASM"),
        ("alluvia sunshine marina", "ASM"),
        ("asm", "ASM"),
        ("ALM", "ALM"),
        ("ALUMI", "ALM"),
        ("alumi", "ALM"),
        ("alluvia city", "ALM"),
        ("NCLB", "NCLB"),
        ("noble crystal long biên", "NCLB"),
    ],
)
def test_normalize_returns_db_codes(raw, code):
    assert catalog.normalize(raw) == code


def test_ambiguous_tokens_still_empty():
    assert catalog.normalize("crystal") == ""
    assert catalog.normalize("sunshine") == ""
    assert catalog.normalize("") == ""


def test_by_code_case_insensitive():
    assert catalog.by_code("ALM").code == "ALM"
    assert catalog.by_code("alm").code == "ALM"
    assert catalog.by_code("Alm").code == "ALM"
    assert catalog.by_code("NCR").code == "NCR"


def test_valid_codes_have_no_stale_app_codes():
    # The pre-2026-07-06 canonicals (ALLUVIA/Alumi/NTTL) and the older app codes
    # (NCRS/SSLC/ALUMI) are all superseded by the DB set (ASM/ALM/NPTTL/NCR/SLC).
    for stale in ("ALLUVIA", "Alumi", "NTTL", "NCRS", "SSLC", "ALUMI"):
        assert stale not in catalog.VALID_CODES


def test_normalize_accepts_live_db_code_absent_from_hardcoded_registry():
    """A DB ma_du_an code the hardcoded _REGISTRY doesn't know (the DB roster can
    change without a catalog release — a brand-new project lands in project_du_an
    before the next catalog ships) is still accepted via the DB-warmed registry,
    so normalize/booking agree with the prompt table + tool enums (all built from
    the same DB source)."""
    from noble_agent.data import db_project_registry

    # A hypothetical future code, absent from _REGISTRY and the bundled fallback
    # → rejected pre-warm.
    assert catalog.normalize("NXYZ") == ""

    db_project_registry.set_cache_for_tests(
        {"NXYZ": {"code": "NXYZ", "name": "Noble Future Project", "region": "", "type": ""}}
    )
    try:
        assert catalog.normalize("NXYZ") == "NXYZ"  # exact DB code accepted
        assert catalog.normalize("nxyz") == "NXYZ"  # case-insensitive
        assert catalog.normalize("NCLB") == "NCLB"  # hardcoded codes still resolve
        assert catalog.normalize("totally-unknown") == ""  # garbage still rejected
    finally:
        db_project_registry.set_cache_for_tests(None)


def test_normalize_accepts_pg_kb_migrated_code_via_provider_cache():
    """SP1 characterization: with pg_kb as the sole data provider, project codes
    come from the migrated ``projects`` table, surfaced sync via
    ``db_project_registry.cached_codes()`` (which now delegates to
    ``PostgresKBProvider.cached_codes()``). ``catalog.normalize`` must keep
    accepting any such code even though it postdates the hardcoded alias map —
    this is the fallback the whole pg_kb migration relies on for booking /
    project-lookup tools to validate a code the LLM read off the live roster.
    Exercises exact case-insensitive match plus a whitespace-padded variant
    (``normalize`` strips before comparing)."""
    from noble_agent.data import db_project_registry

    # A brand-new pg_kb project row, absent from _REGISTRY entirely.
    db_project_registry.set_cache_for_tests(
        {"PGKB1": {"code": "PGKB1", "name": "Pg Kb Demo Project", "region": "", "type": ""}}
    )
    try:
        assert catalog.normalize("PGKB1") == "PGKB1"  # exact
        assert catalog.normalize("pgkb1") == "PGKB1"  # case-insensitive
        assert catalog.normalize("  PGKB1  ") == "PGKB1"  # whitespace-padded
        assert catalog.normalize("NCLB") == "NCLB"  # hardcoded codes unaffected
    finally:
        db_project_registry.set_cache_for_tests(None)


def test_live_db_code_wins_over_stale_hardcoded_alias():
    """A live DB ma_du_an that collides with a hardcoded ALIAS must resolve to the
    DB code, not the alias's stale canonical. Regression: the production DB uses
    ma_du_an "ASM"/"ALM"/"NPTTL", but _REGISTRY hardcodes "asm"→ALLUVIA (alias) and
    canonical "Alumi"/"NTTL". Pre-fix, normalize("ASM") returned "ALLUVIA" (the alias
    matched before the DB fallback), so get_project_overview queried a code absent
    from the DB and wrongly escalated. Live DB codes must win."""
    from noble_agent.data import db_project_registry

    db_project_registry.set_cache_for_tests(
        {
            "ASM": {"code": "ASM", "name": "Alluvia Sunshine Marina", "region": "", "type": ""},
            "ALM": {"code": "ALM", "name": "Alumi", "region": "", "type": ""},
            "NPTTL": {"code": "NPTTL", "name": "Noble Palace Tây Thăng Long", "region": "", "type": ""},
            "NCLB": {"code": "NCLB", "name": "Noble Crystal Long Biên", "region": "", "type": ""},
        }
    )
    try:
        assert catalog.normalize("ASM") == "ASM"  # NOT the stale "ALLUVIA"
        assert catalog.normalize("asm") == "ASM"  # case-insensitive
        assert catalog.normalize("ALM") == "ALM"
        assert catalog.normalize("NPTTL") == "NPTTL"
        assert catalog.normalize("NCLB") == "NCLB"  # unaffected hardcoded code
    finally:
        db_project_registry.set_cache_for_tests(None)
