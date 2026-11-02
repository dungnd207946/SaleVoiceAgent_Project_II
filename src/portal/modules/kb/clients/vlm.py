"""DashScope qwen-vl-max: caption ảnh và OCR một trang PDF scan.

Giao thức OpenAI-compatible (`/chat/completions`) — cùng bề mặt agent đang dùng.
Ảnh đi bằng URL khi nguồn công khai (CloudFront), bằng data URI khi nó nằm trong kho
của ta hoặc là trang PDF vừa render.
"""

import base64
from typing import Any

import httpx

from portal.modules.kb import prompts, settings
from portal.modules.kb.clients.rate_gate import VlmRateGate
from portal.modules.kb.clients.retry import should_retry
from portal.modules.kb.contracts import LANE_CAPTION, TemporaryError


def _parse_content(data: Any) -> str:
    """`choices` vắng hoặc content rỗng phải nổ rõ ràng: một caption rỗng lặng lẽ ghi
    vào cột `media.caption` trông y hệt "chưa chạy job", và không ai phân biệt được.
    """
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"response VLM thiếu choices/message/content: {data!r}") from exc
    text = str(content).strip()
    if not text:
        raise ValueError(f"response VLM trả content rỗng: {data!r}")
    return text


def _bo_fence(text: str) -> str:
    """Bỏ code fence model tự bọc quanh markdown (```markdown … ```).

    Đo trên dữ liệu thật 2026-08-25: qwen-vl-max bọc mỗi trang OCR trong một fence, nên
    một tài liệu 2 trang mang 4 dòng rác vào chữ được embed. Chunker không đọc fence nên
    heading vẫn nhận ra — đây là dọn rác, không phải vá lỗi cấu trúc.
    """
    dong = text.strip().split("\n")
    if dong and dong[0].lstrip().startswith("```"):
        dong = dong[1:]
    if dong and dong[-1].strip().startswith("```"):
        dong = dong[:-1]
    return "\n".join(dong).strip()


# Cùng trần với làn caption của worker: hai con số lệch nhau thì một cái thành vô nghĩa.
_GATE = VlmRateGate(ceiling=LANE_CAPTION)


class VlmClient:
    def __init__(self, *, base_url: str, api_key: str) -> None:
        if not api_key:
            raise ValueError("thiếu KB_VLM_API_KEY — không gửi request không auth")
        self.base_url = base_url.rstrip("/")
        self._key = api_key
        self._http = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SEC)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _chat(self, *, spec: prompts.PromptSpec, image_part: dict) -> str:
        async with _GATE:
            try:
                r = await self._http.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._key}"},
                    json={
                        "model": spec.model,
                        "max_tokens": spec.max_tokens,
                        "temperature": spec.temperature,
                        "messages": [{"role": "user", "content": [image_part, {"type": "text", "text": spec.prompt}]}],
                    },
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise TemporaryError(f"{type(exc).__name__}: {exc}") from exc
            if should_retry(r.status_code):
                _GATE.penalize()
                raise TemporaryError(f"VLM {r.status_code}: {r.text[:200]}")
            r.raise_for_status()
            _GATE.reward()
            return _parse_content(r.json())

    async def caption(self, image_url: str, *, profile: str) -> str:
        spec = prompts.get(profile)
        return await self._chat(spec=spec, image_part={"type": "image_url", "image_url": {"url": image_url}})

    @staticmethod
    async def _uri_anh(data: bytes, *, mime: str) -> str:
        """Thu nhỏ RỒI mới base64. Không có bước này thì ảnh 98 MB đi thẳng sang model.

        Đo được trên dev 2026-08-12 ở đường nhúng thị giác — cùng loại lỗi, cùng loại ảnh:
        `EmbedClient` tự tải ảnh rồi gửi base64, nên 98.7 MB thành ~131 MB trong body và
        model trả 500 hoặc hết thời gian chờ. Đường VLM này TRƯỚC ĐÂY KHÔNG CÓ MỘT PHÉP
        RESIZE NÀO — không guard kích thước, không thu nhỏ.

        Cả `to_webp` lẫn `b64encode` đều qua thread: một lượt encode 20 trang PDF ở
        `scale=2` là 20 lần cấp phát chuỗi nhiều MB trên event loop.
        """
        import asyncio

        from portal.modules.kb.storage.thumbnail import to_webp

        def _lam() -> str:
            nho = data
            if len(nho) > settings.VLM_MAX_BYTES:
                nho = to_webp(nho, width=settings.VLM_IMAGE_WIDTH)
                return f"data:image/webp;base64,{base64.b64encode(nho).decode()}"
            return f"data:{mime};base64,{base64.b64encode(nho).decode()}"

        return await asyncio.to_thread(_lam)

    async def caption_bytes(self, data: bytes, *, mime: str, profile: str) -> str:
        """Ảnh nằm trong kho ta: gửi byte, không gửi URL.

        Presigned URL trỏ endpoint của kho — `localhost:9002` ở dev, mạng nội bộ ở prod —
        và DashScope ở ngoài mở không được: nó trả 400 `InvalidParameter` (đo 2026-08-12).
        """
        spec = prompts.get(profile)
        uri = await self._uri_anh(data, mime=mime)
        return await self._chat(spec=spec, image_part={"type": "image_url", "image_url": {"url": uri}})

    async def ocr_page(self, image_bytes: bytes, *, profile: str = "ocr_markdown") -> str:
        spec = prompts.get(profile)
        uri = await self._uri_anh(image_bytes, mime="image/png")
        return _bo_fence(await self._chat(spec=spec, image_part={"type": "image_url", "image_url": {"url": uri}}))
