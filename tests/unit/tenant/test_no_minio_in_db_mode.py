"""Guard: in db-mode (AGENT_CONFIG_SOURCE=db), no call-site ever builds the
MinIO tenant store. Regression test for the Postgres control-plane migration
(2026-08-04) — see docs/superpowers/plans/2026-08-04-retire-minio-postgres-control-plane.md."""

from noble_agent.agent import facade
from noble_agent.tenant import db_context


async def test_full_db_path_never_builds_minio(monkeypatch):
    from noble_agent import config

    monkeypatch.setattr(config.get_settings(), "agent_config_source", "db", raising=False)
    db_context.reset_db_context_for_tests()
    monkeypatch.setattr(
        "noble_agent.tenant.loader._build_store",
        lambda s: (_ for _ in ()).throw(AssertionError("MinIO built in db-mode")),
    )

    async def _pc(tid, **kw):
        from noble_agent.storage.agent_config_store import PublishedConfig

        return PublishedConfig(version=1, config={"skills": []})

    monkeypatch.setattr(facade, "read_published_config", _pc)

    async def _from_ctx(ctx, channel, version=0):
        return object()

    monkeypatch.setattr(facade, "_build_runner_from_ctx", _from_ctx)

    v = await facade._resolve_current_version("org_1_t")
    assert v == 1
    await facade._build_runner_for_version("org_1_t", v, "chat")  # no AssertionError
