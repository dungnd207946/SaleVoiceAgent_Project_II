"""get_document tool — fetches a project's document (title/body/file_url) via
the active provider. Empty result → ESCALATE_SIGNAL (hand off)."""

from __future__ import annotations

import json

import pytest

from noble_agent.agent.tools import get_document
from noble_agent.data.providers import base


class _P:
    async def get_document(self, code, query=""):
        return [base.Document(project_code="NPLB", title="CSBH Q3", body="Tiến độ...", file_url="acme/csbh.pdf")]


class _EmptyP:
    async def get_document(self, code, query=""):
        return []


@pytest.mark.asyncio
async def test_get_document_returns_file(monkeypatch):
    monkeypatch.setattr("noble_agent.data.providers.get_provider", lambda s: _P())
    out = json.loads(await get_document.run({"project_code": "NPLB", "query": "CSBH"}))
    assert out["documents"][0]["file_url"] == "acme/csbh.pdf"
    assert out["count"] == 1


@pytest.mark.asyncio
async def test_get_document_empty_escalates(monkeypatch):
    monkeypatch.setattr("noble_agent.data.providers.get_provider", lambda s: _EmptyP())
    out = await get_document.run({"project_code": "NPLB", "query": "unknown"})
    assert out == base.ESCALATE_SIGNAL
