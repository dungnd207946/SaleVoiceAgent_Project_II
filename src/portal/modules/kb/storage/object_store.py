"""Client S3. `build_key` cài thật; phần mạng uỷ quyền cho `portal.core.storage.KhoTep`
— cùng client đã dùng thật ở `modules/config`, không dựng session `aioboto3` thứ hai."""

import re

from portal.core.storage import KhoTep
from portal.modules.kb import settings
from portal.modules.kb.contracts import ObjectStore

_TENANT = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")


def build_key(*, tenant_id: str, path: str) -> str:
    """Ghép key dưới `tenants/<tenant_id>/`. Mọi key phải đi qua đây.

    IDEMPOTENT: `path` đã bắt đầu bằng `tenants/<tenant_id>/` thì trả nguyên văn.
    `POST /realestate/uploads` trả khoá ĐẦY ĐỦ và frontend lưu nguyên văn nó vào
    `media.media_url` / `documents.file_url`, nên hàm này nhận cả hai dạng. Cộng tiền
    tố lần hai cho ra `tenants/x/tenants/x/…` — khoá không tồn tại, mà không chỗ nào
    báo: `presign_get` vẫn ký được (404 lúc tải), `doc()` thì ném `KhongTimThay` và
    mọi job enrich nhánh documents failed.

    Chỉ tiền tố của CHÍNH `tenant_id` mới được giữ nguyên: `tenants/<tenant khác>/…`
    vẫn bị lồng xuống dưới tiền tố của mình.

    Chặn `..`: một path thoát ra khỏi prefix sẽ được IAM policy theo tiền tố cho qua.
    """
    if not _TENANT.match(tenant_id):
        raise ValueError(f"tenant_id không hợp lệ cho key S3: {tenant_id!r}")
    clean = path.strip().lstrip("/")
    if not clean or ".." in clean.split("/"):
        raise ValueError(f"đường dẫn không hợp lệ: {path!r}")
    tien_to = f"{settings.ROOT_PREFIX}/{tenant_id}/"
    return clean if clean.startswith(tien_to) else f"{tien_to}{clean}"


def is_internal_key(url_or_key: str) -> bool:
    """False = URL ngoài (YouTube/kuula/Drive) → không presign được, gửi file_url=None (§4.2d)."""
    return not url_or_key.startswith(("http://", "https://"))


async def presigned_if_internal(
    store: ObjectStore,
    *,
    tenant_id: str,
    url_or_key: str,
    ttl_sec: int = settings.PRESIGN_TTL_SEC,
) -> str | None:
    """Khoá nội bộ → URL tải được; URL ngoài → None (caller dùng nguyên văn).

    Một chỗ duy nhất cho ba dòng `is_internal_key → key() → presign_get()`: chép chúng
    lần thứ hai là cách chặng enrich gửi khoá S3 thô cho DashScope, và DashScope không
    tải được thứ đó.
    """
    if not is_internal_key(url_or_key):
        return None
    return await store.presign_get(key=store.key(tenant_id=tenant_id, path=url_or_key), ttl_sec=ttl_sec)


class S3Store:
    """Cài contracts.ObjectStore bằng cách uỷ quyền cho `KhoTep` — không tự cài lại
    client S3. Cùng kho `S3_*` của core (`kho_tep_tu_cai_dat()`)."""

    def __init__(self, kho: KhoTep) -> None:
        self._kho = kho

    def key(self, *, tenant_id: str, path: str) -> str:
        return build_key(tenant_id=tenant_id, path=path)

    async def presign_get(self, *, key: str, ttl_sec: int = settings.PRESIGN_TTL_SEC) -> str:
        return await self._kho.presign_get(key, ttl_sec=ttl_sec)

    async def put(self, *, key: str, data: bytes, content_type: str) -> str:
        await self._kho.ghi(key, data, content_type=content_type)
        return await self._kho.presign_get(key, ttl_sec=settings.PRESIGN_TTL_SEC)

    async def delete(self, *, key: str) -> None:
        await self._kho.xoa(key)

    async def doc(self, *, key: str) -> bytes:
        """Đọc byte cho Docling. `KhoTep.doc` ném `KhongTimThay` cho khoá lạ — KHÔNG
        nuốt thành b"": byte rỗng đi vào Docling thành "tài liệu không có chữ", và
        người dùng thấy ô trống thay vì một lỗi rõ ràng."""
        return await self._kho.doc(key)
