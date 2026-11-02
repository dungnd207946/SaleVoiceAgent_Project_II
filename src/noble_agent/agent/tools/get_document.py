"""get_document — fetch a project's document (title/body/file_url) so Luna can
hand the customer a real file (CSBH/legal PDF). Reads tenant_data.documents via
the provider (scope = project_code + the '__ALL__' tenant-wide sentinel).
Empty result → ESCALATE_SIGNAL (hand off)."""

from __future__ import annotations

import json

from noble_agent.config import get_settings
from noble_agent.data import providers
from noble_agent.data.providers.base import ESCALATE_SIGNAL


async def run(args: dict) -> str:
    provider = providers.get_provider(get_settings())
    docs = await provider.get_document(args.get("project_code", "") or "", args.get("query", "") or "")
    if not docs:
        return ESCALATE_SIGNAL
    return json.dumps(
        {
            "count": len(docs),
            "documents": [{"title": d.title, "body": d.body[:800], "file_url": d.file_url} for d in docs],
        },
        ensure_ascii=False,
    )
