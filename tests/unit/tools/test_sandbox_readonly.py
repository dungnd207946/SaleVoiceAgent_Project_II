import noble_agent.agent.tools.builtins  # noqa: F401 — registers built-ins
from noble_agent.semcache.sandbox import _is_write_tool


def _tc(name, args="{}"):
    return {"function": {"name": name, "arguments": args}}


def test_read_only_tools_are_not_writes():
    for name in ("kb_search", "discover_projects", "get_document", "search_units", "analyze_projects"):
        assert _is_write_tool(_tc(name)) is False, name


def test_write_tools_are_writes():
    for name in ("update_customer", "send_media", "escalate", "find_project"):
        assert _is_write_tool(_tc(name)) is True, name


def test_booking_action_special_case():
    assert _is_write_tool(_tc("booking", '{"action":"check_availability"}')) is False
    assert _is_write_tool(_tc("booking", '{"action":"list"}')) is False
    assert _is_write_tool(_tc("booking", '{"action":"schedule"}')) is True


def test_unknown_tool_is_write():
    assert _is_write_tool(_tc("mystery")) is True
