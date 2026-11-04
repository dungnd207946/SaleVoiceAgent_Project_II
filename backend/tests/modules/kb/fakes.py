"""Thay embed service, Qdrant và S3 trong test — không mạng, không container ngoài Postgres."""

from portal.core.storage import KhongTimThay
from portal.modules.kb.storage.object_store import build_key


class FakeEmbed:
    def __init__(self) -> None:
        self.calls = 0

    async def dense(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def sparse(self, texts: list[str]) -> list[dict]:
        return [{"indices": [1], "values": [1.0]} for _ in texts]

    async def visual_image(self, urls: list[str]) -> list[list[float]]:
        return []

    async def aclose(self) -> None:
        pass


class FakeStore:
    """Cùng bề mặt `QdrantStore` mà module dùng; point giữ trong dict theo collection."""

    def __init__(self) -> None:
        self.cols: dict[str, dict[str, tuple[dict, dict]]] = {}

    async def ensure_collection(self, name: str, *, media: bool) -> None:
        self.cols.setdefault(name, {})

    async def ensure_payload_indexes(self, name: str) -> list[str]:
        return []

    async def drop_collection(self, name: str) -> None:
        self.cols.pop(name, None)

    async def upsert(self, name: str, points) -> int:
        col = self.cols.setdefault(name, {})
        for p in points:
            col[p.point_id] = (p.vectors, p.payload)
        return len(points)

    async def delete_by_record(self, name: str, *, record_id: int, doc_type: str) -> None:
        assert doc_type, "xoá thiếu doc_type"
        col = self.cols.get(name, {})
        for pid in [k for k, (_, pl) in col.items() if pl["record_id"] == record_id and pl["doc_type"] == doc_type]:
            del col[pid]

    async def payload_many(self, name: str, point_ids: list[str]) -> dict[str, dict]:
        col = self.cols.get(name, {})
        return {pid: col[pid][1] for pid in point_ids if pid in col}

    async def aclose(self) -> None:
        pass

    def payloads(self, name: str, *, doc_type: str | None = None, record_id: int | None = None) -> list[dict]:
        ra = [pl for _, pl in self.cols.get(name, {}).values()]
        if doc_type is not None:
            ra = [p for p in ra if p["doc_type"] == doc_type]
        if record_id is not None:
            ra = [p for p in ra if p["record_id"] == record_id]
        return sorted(ra, key=lambda p: p.get("chunk_idx", 0))


class FakeObjects:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def key(self, *, path: str) -> str:
        return build_key(path)

    async def put(self, *, key: str, data: bytes, content_type: str) -> None:
        self.data[key] = data

    async def doc(self, *, key: str) -> bytes:
        if key not in self.data:
            raise KhongTimThay(key)
        return self.data[key]

    async def delete(self, *, key: str) -> None:
        self.data.pop(key, None)
