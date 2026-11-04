from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from noble_agent.tenant.context import TenantContext


def test_tenant_context_fields_and_frozen():
    ctx = TenantContext(
        tenant_id="noble",
        data_source="nbx",
        persona_dir=Path("/x/persona"),
        enabled_tools=("find_project", "booking"),
        rankers=frozenset({"feng_shui"}),
        media_channel="noblex_app",
        brand={"company": "Noble", "app_name": "NobleX"},
    )
    assert ctx.tenant_id == "noble"
    assert ctx.enabled_tools == ("find_project", "booking")
    assert "feng_shui" in ctx.rankers
    assert ctx.brand["app_name"] == "NobleX"
    with pytest.raises(FrozenInstanceError):
        ctx.tenant_id = "other"  # type: ignore[misc]


def test_tenant_id_setting_default():
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings(_env_file=None)
    assert s.tenant_id == "noble"
