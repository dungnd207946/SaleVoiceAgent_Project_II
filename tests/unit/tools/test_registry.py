import pytest

from noble_agent.agent.tools import registry as reg

# Fake built-in names this module registers under tenant="*". They use a
# zzz_ prefix so they can never collide with a real tool registered by
# agent/tools/builtins.py — and we pop them in teardown so no "*" pollution
# leaks into another test's session (clear_tenant_for_tests never touches "*").
_TEST_BUILTINS = ("zzz_test_builtin", "zzz_shadow_builtin")


@pytest.fixture(autouse=True)
def _clean():
    reg.clear_tenant_for_tests("acme")
    yield
    reg.clear_tenant_for_tests("acme")
    for name in _TEST_BUILTINS:
        reg._REGISTRY.pop(("*", name), None)


async def _dummy(args, **_):
    return "ok"


def test_register_and_resolve_builtin():
    reg.register(reg.ToolSpec(name="zzz_test_builtin", schema={}, executor=_dummy))
    spec = reg.resolve("noble", "zzz_test_builtin")
    assert spec is not None and spec.tenant == "*" and spec.read_only is True


def test_tenant_specific_shadows_builtin():
    # Use a fake builtin name (zzz_) so this never clobbers a real tool that
    # agent/tools/builtins.py registers under "*" in the same pytest session.
    reg.register(reg.ToolSpec(name="zzz_shadow_builtin", schema={}, executor=_dummy))
    reg.register(reg.ToolSpec(name="zzz_shadow_builtin", schema={}, executor=_dummy, tenant="acme"))
    assert reg.resolve("acme", "zzz_shadow_builtin").tenant == "acme"
    assert reg.resolve("noble", "zzz_shadow_builtin").tenant == "*"  # noble unaffected


def test_resolve_unknown_returns_none():
    assert reg.resolve("noble", "does_not_exist") is None


def test_decorator_registers():
    @reg.tool(name="acme_custom", schema={"x": 1}, tenant="acme", read_only=False, dirties_customer=True)
    async def _fn(args, **_):
        return "hi"

    spec = reg.resolve("acme", "acme_custom")
    assert spec.executor is _fn and spec.read_only is False and spec.dirties_customer is True
    assert spec.schema == {"x": 1}


def test_registered_names_includes_builtins_and_own():
    reg.register(reg.ToolSpec(name="acme_only", schema={}, executor=_dummy, tenant="acme"))
    names = reg.registered_names("acme")
    assert "acme_only" in names
    assert "acme_only" not in reg.registered_names("noble")


def test_tool_spec_frozen():
    from dataclasses import FrozenInstanceError

    s = reg.ToolSpec(name="x", schema={}, executor=_dummy)
    with pytest.raises(FrozenInstanceError):
        s.name = "y"  # type: ignore[misc]
