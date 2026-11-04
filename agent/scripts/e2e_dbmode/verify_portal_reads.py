"""Verify agent-side db-mode readers against the Portal-sim (no servers needed).
Run from repo root with venv:  AGENT_CONFIG_SOURCE=db POSTGRES_DSN=...local python verify_portal_reads.py

Note (2026-08-10): gateway auth no longer reads control.tenants/control.agent_keys
directly — those two agent_control_store readers were removed along with the old
subdomain + Postgres/MinIO registry path; gateway auth now calls the Portal
runtime-credentials API instead (see gateway/credentials.py).

Note (2026-08-19, Portal `0941`): the deployment-id lookup is gone too —
`control.deployments` was dropped and heartbeats are keyed by `tenant_id` alone. The
script therefore checks the one reader `agent_control_store`/`agent_config_store` still
own: the published-config reader. It also asserts the dropped table stays dropped —
a stray `SELECT control.deployments` would be swallowed by `beat()`'s except clause and
fail silently, which is exactly how the heartbeat stayed dead from `0919` to `0941`.
"""
import asyncio

from noble_agent.storage.agent_config_store import read_published_config


async def main() -> None:
    from noble_agent.storage import agent_control_store as acs

    assert not hasattr(acs, "read_deployment_id"), "read_deployment_id đã bỏ ở 0941"

    pc = await read_published_config("acme")
    print("published version(acme)         =", pc.version)
    print("published brand(acme)           =", pc.config["identity"]["brand"])
    print("published tools(acme)           =", pc.config["tools"]["enabled"])


asyncio.run(main())
