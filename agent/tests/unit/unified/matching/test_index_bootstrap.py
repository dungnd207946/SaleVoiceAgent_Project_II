from noble_agent.agent.tools import find_project
from noble_agent.data import db_project_registry


def teardown_function():
    db_project_registry.set_cache_for_tests(None)
    find_project.set_index(None)


def test_rebuild_installs_index_from_registry():
    db_project_registry.set_cache_for_tests(
        {
            "NCTH": {"code": "NCTH", "name": "Noble Crystal Tây Hồ", "region": "Tây Hồ", "type": ""},
            "SGR": {"code": "SGR", "name": "Sunshine Golden River", "region": "Tây Hồ", "type": ""},
        }
    )
    from noble_agent.agent.orchestrator import _build_project_index

    _build_project_index()
    idx = find_project.get_index()
    assert idx is not None
    assert idx.resolve("noble crystal tay ho").code == "NCTH"
