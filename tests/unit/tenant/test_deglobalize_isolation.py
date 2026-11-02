# tests/unit/tenant/test_deglobalize_isolation.py
"""§9 de-globalize gate: two tenants interleaved in ONE process each get their
own TenantContext / provider instance / find_project index — no bleed."""
from noble_agent.agent.tools import find_project
from noble_agent.config import reset_settings_for_tests
from noble_agent.data import providers
from noble_agent.data.project_matching.index import ProjectNameIndex
from noble_agent.tenant.current import use_tenant
from noble_agent.tenant.loader import get_tenant_context, reset_tenant_context_for_tests


def test_two_tenants_do_not_bleed(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()
    reset_tenant_context_for_tests()
    providers.reset_for_tests()

    idx_noble = ProjectNameIndex([{"code": "NBL", "name": "N", "region": "", "type": ""}])
    idx_acme = ProjectNameIndex([{"code": "ACM", "name": "A", "region": "", "type": ""}])
    find_project.set_index(idx_noble, tenant="noble")
    find_project.set_index(idx_acme, tenant="demo_acme")

    # Interleave: noble → acme → noble → acme
    for _ in range(2):
        with use_tenant("noble"):
            assert get_tenant_context().tenant_id == "noble"
            assert find_project.get_index() is idx_noble
        with use_tenant("demo_acme"):
            assert get_tenant_context().tenant_id == "demo_acme"
            assert find_project.get_index() is idx_acme
