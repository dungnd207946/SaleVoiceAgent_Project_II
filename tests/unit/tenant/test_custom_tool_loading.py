import importlib
import sys

import pytest

from noble_agent.agent.tools import registry as reg
from noble_agent.tenant import loader

_LOAN_MODULE = "noble_agent.tenants.demo_acme.tools.loan"


def _ensure_loan_module_reimported():
    """importlib.import_module() is a no-op once a module is cached in
    sys.modules, so ``loader._import_tenant_tools`` only re-runs the @tool
    decorator (and thus re-registers into the registry) the FIRST time this
    process imports it. Because the autouse fixture below clears the registry
    around every test, reload the module (if already cached) so the decorator
    re-runs and each test's registration is self-contained regardless of run
    order or whether this file runs alone or alongside the rest of the suite."""
    if _LOAN_MODULE in sys.modules:
        importlib.reload(sys.modules[_LOAN_MODULE])


@pytest.fixture(autouse=True)
def _clean():
    reg.clear_tenant_for_tests("demo_acme")
    yield
    reg.clear_tenant_for_tests("demo_acme")


def test_import_tenant_tools_registers_custom_tool():
    _ensure_loan_module_reimported()
    loader._import_tenant_tools("demo_acme")
    spec = reg.resolve("demo_acme", "check_loan")
    assert spec is not None
    assert spec.tenant == "demo_acme"
    assert spec.read_only is True


def test_custom_tool_isolated_from_noble():
    _ensure_loan_module_reimported()
    loader._import_tenant_tools("demo_acme")
    assert reg.resolve("noble", "check_loan") is None
    assert "check_loan" not in reg.registered_names("noble")
    assert "check_loan" in reg.registered_names("demo_acme")


async def test_custom_tool_executor_receives_tenant_and_provider():
    _ensure_loan_module_reimported()
    loader._import_tenant_tools("demo_acme")
    spec = reg.resolve("demo_acme", "check_loan")
    out = await spec.executor({"amount": 5}, provider=object(), tenant="demo_acme")
    assert out == "loan:demo_acme:5"


def test_import_tenant_tools_noop_for_tenant_without_tools():
    # noble has no tools/ package yet → must not raise.
    loader._import_tenant_tools("noble")
