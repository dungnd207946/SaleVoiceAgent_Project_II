from noble_agent.tenant.validation import (
    parse_manifest,
    tool_names_declared,
    validate_bundle,
)

_GOOD_MANIFEST = """\
tenant_id = "acme"
data_source = "nbx"
persona_dir = "persona"
[tools]
enabled = ["kb_search", "check_loan"]
"""

_PERSONA = {
    "persona/config.json": '{"name":"Ava","model":"m","temperature":0.3,"max_tokens":800}',
    "persona/SOUL.md": "soul",
    "persona/RULES.md": "rules",
    "persona/PROMPT_TEMPLATE.md": "tmpl",
    "persona/CUSTOMER_PROFILE.md": "cust",
}

_LOAN_TOOL = '''\
from noble_agent.agent.tools.registry import tool
@tool(name="check_loan", schema={}, tenant="acme")
async def check_loan(args, *, provider, tenant, **_):
    return "ok"
'''


def test_parse_manifest_ok():
    d = parse_manifest(_GOOD_MANIFEST)
    assert d["data_source"] == "nbx"
    assert d["tools"]["enabled"] == ["kb_search", "check_loan"]


def test_parse_manifest_bad_toml_raises():
    import pytest
    with pytest.raises(ValueError):
        parse_manifest("this is = = not toml")


def test_parse_manifest_missing_key_raises():
    import pytest
    with pytest.raises(ValueError):
        parse_manifest('data_source = "nbx"\npersona_dir = "persona"\n')


def test_tool_names_declared_extracts_without_executing():
    assert tool_names_declared(_LOAN_TOOL) == {"check_loan"}


def test_tool_names_declared_syntax_error_returns_empty():
    assert tool_names_declared("def broken(:\n") == set()


def test_validate_good_bundle_passes():
    files = {**_PERSONA, "tools/loan.py": _LOAN_TOOL}
    r = validate_bundle("acme", _GOOD_MANIFEST, files)
    assert r.ok, r.errors


def test_validate_rejects_bad_slug():
    r = validate_bundle("Bad Slug!", _GOOD_MANIFEST, {**_PERSONA, "tools/loan.py": _LOAN_TOOL})
    assert not r.ok
    assert any("slug" in e.lower() for e in r.errors)


def test_validate_rejects_duplicate_id():
    files = {**_PERSONA, "tools/loan.py": _LOAN_TOOL}
    r = validate_bundle("acme", _GOOD_MANIFEST, files, existing_ids=("acme",))
    assert not r.ok
    assert any("exist" in e.lower() for e in r.errors)


def test_validate_rejects_unresolvable_enabled_tool():
    m = _GOOD_MANIFEST.replace('"check_loan"', '"nonexistent_tool"')
    r = validate_bundle("acme", m, dict(_PERSONA))  # no tools/ providing it
    assert not r.ok
    assert any("nonexistent_tool" in e for e in r.errors)


def test_validate_rejects_missing_persona_file():
    files = {k: v for k, v in _PERSONA.items() if k != "persona/SOUL.md"}
    files["tools/loan.py"] = _LOAN_TOOL
    r = validate_bundle("acme", _GOOD_MANIFEST, files)
    assert not r.ok
    assert any("SOUL.md" in e for e in r.errors)


def test_validate_rejects_tool_syntax_error():
    files = {**_PERSONA, "tools/loan.py": "def broken(:\n"}
    m = _GOOD_MANIFEST.replace('"check_loan"', '"kb_search"')  # keep enabled resolvable
    r = validate_bundle("acme", m, files)
    assert not r.ok
    assert any("syntax" in e.lower() or "compile" in e.lower() for e in r.errors)


def test_validate_warns_on_non_allowlisted_import():
    tool_src = _LOAN_TOOL + "\nimport os\n"
    files = {**_PERSONA, "tools/loan.py": tool_src}
    r = validate_bundle("acme", _GOOD_MANIFEST, files)
    assert r.ok  # a warning, not an error
    assert any("os" in w for w in r.warnings)


def test_validate_rejects_invalid_config_json():
    files = {**_PERSONA, "tools/loan.py": _LOAN_TOOL}
    files["persona/config.json"] = "{not valid json"
    r = validate_bundle("acme", _GOOD_MANIFEST, files)
    assert not r.ok
    assert any("config.json" in e and "JSON" in e for e in r.errors)


def test_tool_names_declared_extracts_dotted_decorator_form():
    src = (
        "from noble_agent.agent.tools import registry\n"
        '@registry.tool(name="foo", schema={}, tenant="acme")\n'
        "async def foo(args, *, provider, tenant, **_):\n"
        "    return 'ok'\n"
    )
    assert "foo" in tool_names_declared(src)


def test_parse_manifest_non_table_tools_raises_valueerror():
    import pytest
    m = 'data_source = "nbx"\npersona_dir = "persona"\ntools = "kb_search"\n'
    with pytest.raises(ValueError):
        parse_manifest(m)


def test_validate_non_table_tools_returns_report_not_raises():
    m = 'data_source = "nbx"\npersona_dir = "persona"\ntools = "kb_search"\n'
    r = validate_bundle("acme", m, {**_PERSONA, "tools/loan.py": _LOAN_TOOL})
    assert r.ok is False
    assert any("tools.enabled" in e for e in r.errors)


def test_validate_non_list_enabled_reports_must_be_a_list():
    m = """\
tenant_id = "acme"
data_source = "nbx"
persona_dir = "persona"
[tools]
enabled = "kb_search"
"""
    r = validate_bundle("acme", m, {**_PERSONA, "tools/loan.py": _LOAN_TOOL})
    assert not r.ok
    assert any("must be a list" in e for e in r.errors)
