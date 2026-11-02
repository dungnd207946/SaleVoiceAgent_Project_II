"""Gọi embed service — đường ra DUY NHẤT của repo này.

Semaphore chứ không đẩy hết một lúc: service chạy trên `device: cpu` (kiểm qua
/health), nên 100 request song song chỉ làm nó xếp hàng, không nhanh hơn.

Retry ở ĐÂY, không ở tầng job: `control.jobs` không có cột `attempts` nên một job
`failed` không tự chạy lại — trước bản này cách retry duy nhất là bấm nạp lại cả
dự án. Hết lượt thì dense/sparse NỔ còn visual trả rỗng; xem `visual_image`.
"""

import asyncio
import base64
import logging
from typing import Any

import httpx

from portal.modules.kb import settings
from portal.modules.kb.clients.retry import should_retry

log = logging.getLogger(__name__)


async def _cho(giay: float) -> None:
    """Hàm module để test thay được (`monkeypatch.setattr(embed, "_cho", …)`) — cùng nếp
    `jobs._tai_anh`. Nội tuyến `asyncio.sleep` là mọi test retry chờ thật 3 giây."""
    await asyncio.sleep(giay)


def _parse_embeddings(data: Any) -> list[Any]:
    """Đo trên service thật 2026-08-12: dense trả `{"embeddings": [...]}`, sparse trả
    `{"sparse": [{indices, values}]}` — HAI khoá khác nhau, không phải một.

    Hình dạng lạ thì nổ: trả `[]` khiến tầng trên ghi "đã index" cho thứ chưa lên Qdrant.
    """
    if isinstance(data, dict):
        for khoa in ("embeddings", "sparse"):
            if khoa in data:
                return data[khoa]
    if isinstance(data, list):
        return data
    raise ValueError(f"hình dạng response /embed không nhận diện được: {data!r}")


class EmbedClient:
    def __init__(self, *, base_url: str, token: str, objects: Any = None) -> None:
        if not token:
            raise ValueError("thiếu KB_SANTA_MODELS_TOKEN — embed service từ chối request không auth")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._objects = objects
        self._http = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SEC)
        self._gate = asyncio.Semaphore(settings.WORKER_CONCURRENCY)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _goi(self, *, kind: str, texts: list[str] | None = None, images: list[str] | None = None) -> list[Any]:
        if not (texts or images):
            return []
        body: dict[str, Any] = {"side": settings.SIDE_INDEX, "kind": kind}
        if texts:
            body["texts"] = texts
        if images:
            body["images"] = images
        async with self._gate:
            data = await self._post_thu_lai(body)
        return _parse_embeddings(data)

    async def _post_thu_lai(self, body: dict[str, Any]) -> Any:
        """`RETRY_ATTEMPTS` lượt cho 429/5xx và lỗi mạng/timeout; 4xx còn lại nổ ngay.

        Chờ TRONG semaphore: 429 nghĩa là service đang nghẽn, nhả cổng lúc chờ chỉ để
        ba job khác đâm vào đúng chỗ nghẽn đó thì backpressure chỉ còn là cái tên.
        """
        url = f"{self.base_url}{settings.PATH_EMBED}"
        headers = {"Authorization": f"Bearer {self._token}"}
        for luot in range(1, settings.RETRY_ATTEMPTS + 1):
            try:
                r = await self._http.post(url, json=body, headers=headers)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                if luot >= settings.RETRY_ATTEMPTS or not should_retry(e.response.status_code):
                    raise
                ly_do = f"HTTP {e.response.status_code}"
            except httpx.TransportError as e:
                if luot >= settings.RETRY_ATTEMPTS:
                    raise
                ly_do = f"{type(e).__name__}: {e}"
            giay = min(2 ** (luot - 1), 60)  # backoff luỹ tiến 1s, 2s, 4s… chặn trần 60s
            log.warning(
                "embed %s lượt %d/%d: %s → chờ %.1fs", body.get("kind"), luot, settings.RETRY_ATTEMPTS, ly_do, giay
            )
            await _cho(giay)
        raise AssertionError("không tới được: vòng lặp hoặc return hoặc raise")

    async def dense(self, texts: list[str]) -> list[list[float]]:
        return await self._goi(kind=settings.KIND_DENSE, texts=texts)

    async def sparse(self, texts: list[str]) -> list[dict]:
        return await self._goi(kind=settings.KIND_SPARSE, texts=texts)

    async def visual_image(self, urls: list[str]) -> list[list[float]]:
        """Service nhận ẢNH BASE64, không nhận URL (đo 2026-08-12: URL trả 400
        "images không phải base64"). Tải ở đây chứ không ở caller — đây là chỗ duy
        nhất biết service muốn gì.

        HẾT LƯỢT THÌ TRẢ RỖNG, ngược hẳn với dense/sparse: `media.py` chỉ gán vector
        visual khi có, nên point vẫn lên Qdrant với vector text — mất tìm-bằng-ảnh,
        giữ tìm-bằng-caption, và badge xanh vẫn ĐÚNG vì point có thật. Dense trả rỗng
        thì không point nào lên mà sổ vẫn ghi "đã index" — chuyện khác hẳn.
        """
        try:
            anh = [await self._tai_base64(u) for u in urls]
            return await self._goi(kind=settings.KIND_VISUAL_IMAGE, images=anh)
        except Exception as e:  # noqa: BLE001
            log.warning("bỏ vector visual của %s: %s: %s", urls, type(e).__name__, e)
            return []

    async def _tai_base64(self, url: str) -> str:
        """Ảnh vượt `VISUAL_MAX_BYTES` thì thu nhỏ trước khi encode — xem hằng số đó.

        Ảnh đã nhỏ đi NGUYÊN BYTE: thêm một lượt giải mã/nén Pillow cho 870 ảnh chỉ để
        ra tệp tương đương. `to_thread` vì Pillow là CPU thuần, chạy trong event loop là
        chặn cả worker suốt lúc giải mã.

        Khoá nội bộ đọc thẳng từ kho: thumb nằm trong MinIO cùng máy, đi vòng qua HTTP
        là tải lại ảnh gốc nhiều MB lần thứ hai.
        """
        from portal.modules.kb.storage.object_store import is_internal_key

        if self._objects is not None and is_internal_key(url):
            data = await self._objects.doc(key=url)
        else:
            r = await self._http.get(url, follow_redirects=True)
            r.raise_for_status()
            data = r.content
        if len(data) > settings.VISUAL_MAX_BYTES:
            from portal.modules.kb.storage.thumbnail import to_webp

            nho = await asyncio.to_thread(to_webp, data, width=settings.VISUAL_IMAGE_WIDTH)
            log.info("thu nhỏ ảnh visual %s: %d → %d byte", url, len(data), len(nho))
            data = nho
        return base64.b64encode(data).decode()
