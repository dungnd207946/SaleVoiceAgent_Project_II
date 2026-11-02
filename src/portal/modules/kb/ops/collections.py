"""Vòng đời 2 collection Qdrant của một workspace. Gọi lúc provision (§8) và teardown.

Còn mở: provision không có atomicity xuyên kho (Postgres + 2 collection + prefix S3).
Nên cho nó đi qua control.jobs để có dấu vết và retry idempotent.
"""

from portal.modules.kb.contracts import IndexClient


async def create(*, rag: IndexClient, media: IndexClient, workspace_slug: str) -> None:
    """Dựng collection VÀ chỉ mục payload. Cả hai idempotent.

    Chỉ mục payload phải gọi RIÊNG vì `ensure_collection` thoát sớm khi collection đã tồn
    tại — nếu để chỉ mục ở trong đó thì 8 collection đang sống không bao giờ có chỉ mục
    mới, và `status` (mệnh đề duy nhất ngăn nội dung nháp tới khách) sẽ phải quét.
    """
    for client in (rag, media):
        await client.create_collection(workspace_slug=workspace_slug)
        await client.ensure_payload_indexes(workspace_slug=workspace_slug)


async def drop(*, rag: IndexClient, media: IndexClient, workspace_slug: str) -> None:
    """Gọi SAU khi DELETE FROM control.tenants thành công."""
    await rag.drop_collection(workspace_slug=workspace_slug)
    await media.drop_collection(workspace_slug=workspace_slug)


async def xoa_kho_cua_workspace(tenant_id: str) -> list[str]:
    """Xoá HAI collection Qdrant của một workspace. Trả tên đã xoá.

    Khác `drop()` ngay trên ở chỗ nó TỰ dựng client: `drop()` nhận `IndexClient` đã
    có (worker luôn có sẵn qua `open_dependencies`), còn đường xoá workspace chạy
    trong một request HTTP và không có bộ dependency nào trong tay.

    KHÔNG dùng `jobs.open_dependencies()`: bộ đó còn dựng `EmbedClient` (cần
    `embed_url` + token của santa-models) và một `ObjectStore`. Xoá một collection
    không cần nhúng gì cả — kéo theo hai client nữa là để đường XOÁ hỏng vì một
    service KHÔNG LIÊN QUAN chưa cấu hình.

    KHÔNG đi qua `control.jobs` như `KIND_PROVISION` của chiều dựng: hàng `jobs` mang
    `tenant_id` với FK `ON DELETE CASCADE`, nên một việc xếp cho tenant vừa bị xoá
    cứng sẽ TỰ BIẾN MẤT trước khi worker nhặt. Chiều xoá vì thế phải chạy đồng bộ.

    Tên collection lấy từ `clients/{rag,media}.py` — chỗ ĐANG ghi vào chúng. Ghép
    `f"{tenant_id}_documents"` ở đây là bản thứ hai của quy tắc đặt tên, và lệch một
    ký tự nghĩa là xoá trượt: kho của khách cũ ở lại chờ khách sau trùng id.
    """
    from portal.core.config import get_settings
    from portal.core.ten_tai_nguyen import ten_kho_web
    from portal.modules.kb.clients.media import collection_name as _ten_media
    from portal.modules.kb.clients.rag import collection_name as _ten_rag
    from portal.modules.kb.index.store import QdrantStore

    cfg = get_settings()
    store = QdrantStore(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)
    ten = [_ten_rag(tenant_id), _ten_media(tenant_id), ten_kho_web(tenant_id)]
    try:
        for t in ten:
            await store.drop_collection(t)
    finally:
        aclose = getattr(store, "aclose", None)
        if aclose is not None:
            await aclose()
    return ten
