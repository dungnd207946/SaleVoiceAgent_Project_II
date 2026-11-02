from pathlib import Path

from noble_agent.agent.agent_config import parse_config
from noble_agent.tenant.db_context import (
    context_from_config,
    default_db_context,
    get_db_context,
    reset_db_context_for_tests,
    set_db_context,
)

SK = Path("/tmp/skeleton")


def test_context_from_config_maps_fields():
    cfg = parse_config(
        {
            "skills": ["search_units", "booking"],
            "brand_name": "An Phú",
        }
    )
    ctx = context_from_config("org_1_t", cfg, skeleton_dir=SK)
    assert ctx.tenant_id == "org_1_t"
    assert ctx.data_source == "pg_kb"
    assert "search_units" in ctx.enabled_tools and "escalate" in ctx.enabled_tools
    assert ctx.rankers == frozenset({"feng_shui"})
    assert ctx.media_channel == "noblex_app"
    assert ctx.brand == {"company": "An Phú", "app_name": "An Phú"}
    assert ctx.persona_dir == SK


def test_feng_shui_off_no_ranker():
    cfg = parse_config({"skills": ["booking"]})
    ctx = context_from_config("t", cfg, skeleton_dir=SK)
    assert ctx.rankers == frozenset()  # search_units off → feng_shui not derived by parse_config


def test_db_context_cache_roundtrip():
    reset_db_context_for_tests()
    ctx = default_db_context("t9", skeleton_dir=SK)
    assert ctx.data_source == "pg_kb" and ctx.enabled_tools == ()
    set_db_context("t9", ctx)
    assert get_db_context("t9") is ctx
