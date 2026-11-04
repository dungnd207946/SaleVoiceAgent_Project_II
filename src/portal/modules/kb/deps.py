"""Nối dây client thật — CHỖ DUY NHẤT. Test thay các hàm ở đây bằng fake (không mạng).

Nơi gọi PHẢI tham chiếu qua module (`deps.qdrant_store()`), không `from … import` — nếu
không monkeypatch của test không với tới và test gọi Qdrant thật.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from portal.modules.kb import settings
from portal.modules.kb.clients.media import MediaClient
from portal.modules.kb.clients.rag import RagClient
from portal.modules.kb.contracts import ObjectStore
from portal.modules.kb.index.store import QdrantStore


def object_store() -> ObjectStore:
    from portal.core.storage import kho_tep_dung_chung
    from portal.modules.kb.storage.object_store import S3Store

    return S3Store(kho_tep_dung_chung())


def qdrant_store() -> QdrantStore:
    """Xoá/đọc point KHÔNG cần embed — đừng đi qua `open_clients()` (EmbedClient ném khi
    thiếu token, và đường xoá không được hỏng vì một service nó không gọi)."""
    from portal.core.config import get_settings

    cfg = get_settings()
    return QdrantStore(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)


def embed_client(objects: ObjectStore):
    from portal.modules.kb.clients.embed import EmbedClient

    env = settings.get_env()
    return EmbedClient(base_url=env.embed_url, token=env.santa_models_token, objects=objects)


@asynccontextmanager
async def open_clients(objects: ObjectStore) -> AsyncIterator[tuple[RagClient, MediaClient]]:
    """(rag, media) dùng CHUNG một embed + một store, đóng khi xong. Dựng mới mỗi job: worker
    sống dài, client giữ kết nối qua nhiều job là chỗ lỗi khó truy khi service đổi địa chỉ."""
    embed = embed_client(objects)
    store = qdrant_store()
    rag = RagClient(embed=embed, store=store, collection=settings.collection_documents())
    media = MediaClient(embed=embed, store=store, collection=settings.collection_media())
    try:
        yield rag, media
    finally:
        await embed.aclose()
        await store.aclose()
