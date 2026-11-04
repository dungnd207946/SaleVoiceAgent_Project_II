import importlib

from noble_agent.tenant.loader import get_tenant_context, reset_tenant_context_for_tests


def test_manifest_offers_service_customer_not_financial():
    reset_tenant_context_for_tests()
    # đảm bảo tool module đã import (decorator self-register)
    importlib.import_module("noble_agent.tenants.noble.tools.service_customer")
    ctx = get_tenant_context()
    assert "service_customer" in ctx.enabled_tools
    assert "get_project_financial" not in ctx.enabled_tools


def test_agent_def_offers_service_customer_schema():
    reset_tenant_context_for_tests()
    importlib.import_module("noble_agent.tenants.noble.tools.service_customer")
    ctx = get_tenant_context()
    from noble_agent.agent.base import load_agent_def

    agent = load_agent_def(ctx.persona_dir, tool_names=list(ctx.enabled_tools), brand=dict(ctx.brand))
    names = {s["function"]["name"] for s in agent.tool_schemas}
    assert "service_customer" in names
    assert "get_project_financial" not in names
