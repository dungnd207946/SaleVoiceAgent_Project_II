"""Tests for per-tenant project index build in the orchestrator."""


def test_build_index_installs_for_current_tenant(monkeypatch):
    from noble_agent.agent import orchestrator
    from noble_agent.agent.tools import find_project
    from noble_agent.config import reset_settings_for_tests
    from noble_agent.data import db_project_registry
    from noble_agent.tenant.current import use_tenant

    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()
    db_project_registry.set_cache_for_tests(
        {"XYZ": {"code": "XYZ", "name": "Xyz", "region": "R", "type": "T"}}
    )
    try:
        with use_tenant("t_build"):
            orchestrator._build_project_index()
            assert find_project.get_index() is not None
        # a different tenant with no build has no index
        with use_tenant("t_other"):
            assert find_project.get_index() is None
    finally:
        db_project_registry.set_cache_for_tests(None)
