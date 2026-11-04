"""Kho tệp của module kb — uỷ quyền cho `portal.core.storage.KhoTep` (cùng kho `S3_*` của core)."""

from portal.core.storage import KhoTep
from portal.modules.kb import settings


def build_key(path: str) -> str:
    """Khoá dưới `kb/`. Mọi khoá module ghi phải đi qua đây.

    IDEMPOTENT: `path` đã bắt đầu bằng `kb/` thì giữ nguyên — nơi gọi hay truyền lại khoá
    đã dựng (thumb của ảnh vừa kéo về), cộng tiền tố lần hai là khoá không tồn tại.
    Chặn `..`: khoá thoát ra ngoài `kb/` sẽ lọt qua phép kiểm tiền tố của route phát tệp.
    """
    clean = path.strip().lstrip("/")
    if not clean or ".." in clean.split("/"):
        raise ValueError(f"đường dẫn không hợp lệ: {path!r}")
    return clean if clean.startswith(settings.KB_PREFIX) else f"{settings.KB_PREFIX}{clean}"


def is_internal_key(url_or_key: str) -> bool:
    """False = URL ngoài (CDN hãng, YouTube…) — không đọc từ kho được."""
    return not url_or_key.startswith(("http://", "https://"))


class S3Store:
    """Cài `contracts.ObjectStore`."""

    def __init__(self, kho: KhoTep) -> None:
        self._kho = kho

    def key(self, *, path: str) -> str:
        return build_key(path)

    async def put(self, *, key: str, data: bytes, content_type: str) -> None:
        await self._kho.ghi(key, data, content_type=content_type)

    async def delete(self, *, key: str) -> None:
        await self._kho.xoa(key)

    async def doc(self, *, key: str) -> bytes:
        """`KhoTep.doc` ném `KhongTimThay` cho khoá lạ — KHÔNG nuốt thành b"": byte rỗng đi
        vào bộ bóc chữ thành "tài liệu không có chữ", người dùng thấy sai lý do."""
        return await self._kho.doc(key)
