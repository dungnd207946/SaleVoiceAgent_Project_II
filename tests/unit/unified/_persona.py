"""Shared persona-dir + offered-tool list for tests (post-tenant-migration)."""

from pathlib import Path

import noble_agent

PERSONA_DIR = Path(noble_agent.__file__).resolve().parent / "tenants" / "noble" / "persona"

# Sau merge 2026-09-07: search_units nuốt recommend_units, discover_projects
# nuốt get_project_overview, analyze_projects thay check_inventory.
NOBLE_TOOLS = [
    "find_project",
    "update_customer",
    "kb_search",
    "discover_projects",
    "get_document",
    "search_units",
    "booking",
    "escalate",
    "send_media",
    "analyze_projects",
]
