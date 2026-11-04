import pytest

from noble_agent.agent.tools import builtins as _b  # noqa: F401 — registers
from noble_agent.agent.tools import schemas
from noble_agent.tenant import loader


def test_brand_tokens_rendered_in_descriptions():
    out = {s["function"]["name"]: s for s in schemas.build_schemas(["send_media", "update_customer"])}
    send_desc = out["send_media"]["function"]["description"]
    # Noble renders the app-name literal; NO raw token survives.
    assert "{{ brand.app_name }}" not in send_desc
    assert "NobleX" in send_desc
    upd_desc = out["update_customer"]["function"]["parameters"]["properties"]["is_noble_customer"]["description"]
    assert "{{ brand.company }}" not in upd_desc
    assert "Noble" in upd_desc


def test_project_name_examples_not_templated():
    # "Noble Crystal" is a project name, must survive verbatim (not turned into a token).
    out = {s["function"]["name"]: s for s in schemas.build_schemas(["find_project"])}
    assert "Noble Crystal" in out["find_project"]["function"]["description"]


@pytest.fixture
def _rankers(monkeypatch):
    # Patch thẳng get_tenant_context: bản cũ patch dict cache `_ctx_by_tenant`
    # nhưng path AGENT_CONFIG_SOURCE=db không đọc cache đó → fixture trượt im
    # lặng và test fail theo .env (bẫy env-dependent đã ghi trong memory).
    def _set(rankers):
        from dataclasses import replace

        try:
            ctx = replace(loader.get_tenant_context(), rankers=frozenset(rankers))
        except Exception:
            from types import SimpleNamespace

            ctx = SimpleNamespace(rankers=frozenset(rankers), tenant_id="noble", brand={})
        monkeypatch.setattr(loader, "get_tenant_context", lambda: ctx)

    return _set


def test_feng_shui_params_present_when_ranker_enabled(_rankers):
    _rankers({"feng_shui"})
    out = {s["function"]["name"]: s for s in schemas.build_schemas(["search_units"])}
    props = out["search_units"]["function"]["parameters"]["properties"]
    for p in ("birth_year", "gender", "menh", "zodiac"):
        assert p in props, p


def test_feng_shui_params_stripped_when_ranker_disabled(_rankers):
    _rankers(set())
    out = {s["function"]["name"]: s for s in schemas.build_schemas(["search_units"])}
    props = out["search_units"]["function"]["parameters"]["properties"]
    for p in ("birth_year", "gender", "menh", "zodiac"):
        assert p not in props, p
    # non-feng-shui params survive
    assert "max_price" in props and "region" in props and "scope" in props
