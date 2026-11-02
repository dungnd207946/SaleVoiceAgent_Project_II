"""Bản giả của santa-models và S3 — cơ chế ② của spec tổng.

Nhờ nó, service/source/directive/state/ops test được dù `/index` chưa tồn tại. Fake nhớ
mọi lời gọi để test khẳng định được "đã gọi đúng một lần với đúng chỉ thị này".
"""

import hashlib

from portal.modules.kb.contracts import IndexResult, MediaDirective, TextDirective
from portal.modules.kb.storage.object_store import build_key


class FakeIndexClient:
    def __init__(self, *, generated_caption: str | None = None, extracted_text: str | None = None) -> None:
        self.generated_caption = generated_caption
        self.extracted_text = extracted_text
        self.indexed: list[TextDirective | MediaDirective] = []
        self.deleted: list[tuple[str, int, str]] = []
        self.deleted_entities: list[str] = []
        self.created_collections: list[str] = []
        self.indexed_payload_keys: list[str] = []
        self.set_payloads: list[tuple] = []
        self.dropped_collections: list[str] = []
        self.index_calls = 0
        self.hash_calls = 0

    @staticmethod
    def _hash_cua(directive: TextDirective | MediaDirective) -> str:
        is_media = isinstance(directive, MediaDirective)
        payload = f"{directive.caption}|{directive.media_url}" if is_media else directive.text
        return hashlib.sha1(payload.encode(), usedforsecurity=False).hexdigest()

    def content_hash_of(self, directive: TextDirective | MediaDirective) -> str:
        self.hash_calls += 1
        return self._hash_cua(directive)

    async def index(self, directive: TextDirective | MediaDirective) -> IndexResult:
        self.indexed.append(directive)
        self.index_calls += 1
        is_media = isinstance(directive, MediaDirective)
        return IndexResult(
            points_upserted=1,
            content_hash=self._hash_cua(directive),
            caption=self.generated_caption if is_media and directive.caption is None else None,
            extracted_text=self.extracted_text if not is_media else None,
        )

    async def delete(self, *, workspace_slug: str, record_id: int, doc_type: str = "", entity: str = "") -> IndexResult:
        self.deleted.append((workspace_slug, record_id, doc_type))
        self.deleted_entities.append(entity)
        return IndexResult(points_deleted=1)

    async def create_collection(self, *, workspace_slug: str) -> None:
        self.created_collections.append(workspace_slug)

    async def set_payload(self, *, workspace_slug, anchor_code, gia_tri, chi_record_ids=None) -> int:
        """Ghi lại để test khẳng định ĐÃ cập nhật payload thay vì nhúng lại."""
        self.set_payloads.append((workspace_slug, anchor_code, dict(gia_tri), chi_record_ids))
        return len(self.set_payloads)

    async def ensure_payload_indexes(self, *, workspace_slug: str) -> list[str]:
        """Ghi lại để test khẳng định chỉ mục ĐƯỢC gọi — nó tách khỏi `create_collection`
        đúng vì `ensure_collection` thật thoát sớm khi collection đã tồn tại."""
        self.indexed_payload_keys.append(workspace_slug)
        return []

    async def drop_collection(self, *, workspace_slug: str) -> None:
        self.dropped_collections.append(workspace_slug)


class FakeObjectStore:
    """Dùng đúng `build_key` thật — fake tự ghép key thì test cách ly đang kiểm fake."""

    def __init__(self) -> None:
        self.stored: dict[str, bytes] = {}
        self.presigned: list[str] = []

    def key(self, *, tenant_id: str, path: str) -> str:
        return build_key(tenant_id=tenant_id, path=path)

    async def presign_get(self, *, key: str, ttl_sec: int = 300) -> str:
        self.presigned.append(key)
        return f"https://fake-s3.local/{key}?X-Amz-Expires={ttl_sec}"

    async def put(self, *, key: str, data: bytes, content_type: str) -> str:
        self.stored[key] = data
        return f"https://fake-s3.local/{key}"

    async def delete(self, *, key: str) -> None:
        self.stored.pop(key, None)

    async def doc(self, *, key: str) -> bytes:
        return self.stored.get(key, b"")
