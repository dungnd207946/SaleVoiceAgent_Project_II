"""Job `kb_conflict_check`. Import ở `worker/__main__.py::load_handlers()`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

from portal.core.config import get_settings
from portal.core.jobs import JobResult, register
from portal.modules.kb import prompts
from portal.modules.kb.clients.rag import collection_name
from portal.modules.kb.conflicts import service
from portal.modules.kb.conflicts.gemini import GeminiLlm
from portal.modules.kb.conflicts.llm import PROFILE, RESPONSE_SCHEMA
from portal.modules.kb.conflicts.repo import KIND_CONFLICT_CHECK
from portal.modules.kb.contracts import RETRY_VIEC_KB
from portal.modules.kb.index.store import QdrantStore
from portal.modules.kb.settings import get_env
from portal.modules.kb.web.llm import WebLlm
from portal.modules.kb.web.usage import metered

PURPOSE = "conflict_check"
CHANNEL = "kb_conflict"
SESSION_PREFIX = "kbconflict:"


@asynccontextmanager
async def open_deps() -> AsyncIterator[tuple[QdrantStore, service.Asker]]:
    cfg, env = get_settings(), get_env()
    store = QdrantStore(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)
    llm: GeminiLlm | WebLlm
    if prompts.get(PROFILE).model.startswith("gemini"):
        llm = GeminiLlm(api_key=env.gemini_api_key, schema=RESPONSE_SCHEMA, concurrency=2)
    else:
        llm = WebLlm(base_url=env.vlm_base_url, api_key=env.vlm_api_key, concurrency=2)
    try:
        yield store, llm
    finally:
        await llm.aclose()
        await store.aclose()


async def handle_conflict_check(conn: asyncpg.Connection, payload: dict) -> JobResult:
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    project_code = str(payload["project_code"])
    coll = collection_name(tenant_id)
    async with open_deps() as (store, llm):
        if payload.get("entity"):
            res = await service.check_record(
                conn,
                store=store,
                llm=llm,
                collection=coll,
                project_code=project_code,
                entity=str(payload["entity"]),
                record_id=int(payload["record_id"]),
            )
        else:
            res = await service.check_project(conn, store=store, llm=llm, collection=coll, project_code=project_code)
    return JobResult(
        count=res.opened,
        message=f"{project_code}: {res.calls} lượt LLM · {res.opened} mâu thuẫn mới · {res.resolved} đã đóng",
    )


register(
    KIND_CONFLICT_CHECK,
    metered(handle_conflict_check, purpose=PURPOSE, channel=CHANNEL, session_prefix=SESSION_PREFIX),
    retries=RETRY_VIEC_KB,
    max_concurrency=2,
)
