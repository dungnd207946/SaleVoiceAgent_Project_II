from noble_agent.agent import facade
from noble_agent.tenant.db_context import get_db_context, reset_db_context_for_tests


async def test_build_for_version_db_sets_context_no_minio(monkeypatch):
    from noble_agent import config

    reset_db_context_for_tests()
    monkeypatch.setattr(config.get_settings(), "agent_config_source", "db", raising=False)

    async def _pc(tid, **kw):
        from noble_agent.storage.agent_config_store import PublishedConfig

        return PublishedConfig(version=3, config={"skills": ["booking"]})

    monkeypatch.setattr(facade, "read_published_config", _pc)
    monkeypatch.setattr(
        "noble_agent.tenant.loader._build_store",
        lambda s: (_ for _ in ()).throw(AssertionError("MinIO touched")),
    )
    sentinel = object()

    async def _from_ctx(ctx, channel, version=0):
        assert ctx.tenant_id == "org_1_t" and ctx.data_source == "pg_kb"
        assert channel == "chat"
        assert version == 3  # stamped onto the live `conversations` row
        return sentinel

    monkeypatch.setattr(facade, "_build_runner_from_ctx", _from_ctx)
    runner = await facade._build_runner_for_version("org_1_t", 3, "chat")
    assert runner is sentinel
    assert get_db_context("org_1_t") is not None  # cached for provider-source
