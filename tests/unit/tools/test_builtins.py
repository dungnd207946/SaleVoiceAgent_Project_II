from noble_agent.agent.tools import builtins as _b  # noqa: F401 — import registers
from noble_agent.agent.tools import registry as reg

# The exact behaviour-identity contract after the 2026-09-07 tool merge
# (6 → 3 structured-data tools: search_units nuốt recommend_units,
# discover_projects nuốt get_project_overview, analyze_projects nuốt
# check_inventory).
READ_ONLY = {
    "kb_search", "discover_projects", "get_document", "search_units",
    "analyze_projects", "no_lookup_needed",
}
DIRTIES = {"update_customer"}
# Every built-in the registry must carry. Flag parity is asserted EXHAUSTIVELY
# over this set so a future flag flip on any one tool is caught (flags feed
# semcache's read/write classification — behaviour-identity is the whole point).
ALL_11 = {
    "find_project", "update_customer", "kb_search", "discover_projects",
    "get_document", "search_units", "booking", "escalate", "send_media",
    "analyze_projects", "no_lookup_needed",
}
# Merged away 2026-09-07 — must NOT resolve anymore (a stale registration would
# put a dead tool back into the catalog silently).
MERGED_AWAY = {"recommend_units", "get_project_overview", "check_inventory"}


def test_all_standard_tools_registered_as_builtins():
    for name in ALL_11:
        spec = reg.resolve("noble", name)
        assert spec is not None and spec.tenant == "*", name


def test_merged_away_tools_are_not_registered():
    for name in MERGED_AWAY:
        assert reg.resolve("noble", name) is None, name


def test_read_only_flags_match_legacy_set():
    # Exhaustive: every one of the 11 tools is True iff it's in READ_ONLY.
    for name in ALL_11:
        assert reg.resolve("noble", name).read_only is (name in READ_ONLY), name


def test_dirties_customer_flags_match_legacy_set():
    # Exhaustive: every one of the 11 tools is True iff it's in DIRTIES.
    for name in ALL_11:
        assert reg.resolve("noble", name).dirties_customer is (name in DIRTIES), name


def test_builtin_schema_is_the_canonical_schema():
    from noble_agent.agent.tools.schemas import SCHEMAS
    assert reg.resolve("noble", "booking").schema is SCHEMAS["booking"]
