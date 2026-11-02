"""Khai báo lĩnh vực phải khớp những chỗ khác đang tin nó."""

from portal.modules.kb.clients import media, rag


def test_ten_collection_sinh_tu_slug():
    assert rag.collection_name("acme") == "acme_documents"
    assert media.collection_name("acme") == "acme_media"
