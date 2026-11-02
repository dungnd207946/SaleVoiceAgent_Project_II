"""Vòng đời collection."""

from portal.modules.kb.ops import collections
from tests.modules.kb.fake import FakeIndexClient


async def test_provision_tao_ca_hai_collection():
    rag, media = FakeIndexClient(), FakeIndexClient()
    await collections.create(rag=rag, media=media, workspace_slug="kb_acme")
    assert rag.created_collections == ["kb_acme"]
    assert media.created_collections == ["kb_acme"]

    await collections.drop(rag=rag, media=media, workspace_slug="kb_acme")
    assert rag.dropped_collections == media.dropped_collections == ["kb_acme"]
