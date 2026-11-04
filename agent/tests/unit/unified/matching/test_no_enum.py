from noble_agent.agent.tools.schemas import schemas_for


def test_project_code_params_have_no_enum():
    schemas = schemas_for(["search_units", "booking", "kb_search", "find_project"])
    by_name = {s["function"]["name"]: s for s in schemas}
    su = by_name["search_units"]["function"]["parameters"]["properties"]["project_code"]
    assert "enum" not in su
    nf = by_name["kb_search"]["function"]["parameters"]["properties"]["project_filter"]
    assert "enum" not in nf
    assert "find_project" in by_name
