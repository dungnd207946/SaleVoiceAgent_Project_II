"""ensure_sql_ro_roles: validate tên role TRƯỚC khi chạm DB (không cần asyncpg/PG)."""

import pytest

from noble_agent.tenant import pg_provisioning as pg


async def test_ensure_sql_ro_rejects_bad_role_names():
    with pytest.raises(ValueError):
        await pg.ensure_sql_ro_roles("postgresql://x", sql_ro_role='bad"name', app_role="odyssey_agent")
    with pytest.raises(ValueError):
        await pg.ensure_sql_ro_roles("postgresql://x", sql_ro_role="agent_sql_ro", app_role="BAD ROLE")


def test_view_constants():
    assert pg.VIEW_OWNER_ROLE == "agent_kb_view_owner"
    assert pg.AGENT_VIEWS == ("agent_projects_v", "agent_units_v")
