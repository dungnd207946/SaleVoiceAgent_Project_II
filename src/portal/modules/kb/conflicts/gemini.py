"""Gemini cho bước dò mâu thuẫn, qua cổng tương thích OpenAI `/chat/completions`.

Cùng giao diện `ask(profile, user_text) -> dict` với `WebLlm`; khác ở chỗ bật suy luận mức thấp
(tắt hẳn thì ghép bừa hai thuộc tính khác nhau thành mâu thuẫn), ép JSON theo `schema` (chế độ
`json_object` từng trả thừa dấu `}`), và ghi usage dưới provider `google`.
"""

import asyncio
import logging

import httpx

from portal.modules.kb import prompts, settings
from portal.modules.kb.contracts import TemporaryError
from portal.modules.kb.web.llm import TruncatedLlmError, parse_json
from portal.modules.kb.web.usage import GOOGLE, meter

log = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
REASONING_EFFORT = "low"


class GeminiLlm:
    def __init__(
        self, *, api_key: str, schema: dict, concurrency: int = 4, http: httpx.AsyncClient | None = None
    ) -> None:
        if not api_key:
            raise ValueError("thiếu KB_GEMINI_API_KEY")
        self._key = api_key
        self._schema = schema
        self._gate = asyncio.Semaphore(concurrency)
        self._http = http or httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SEC)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def ask(self, profile: str, user_text: str) -> dict:
        spec = prompts.get(profile)
        body = {
            "model": spec.model,
            "max_tokens": spec.max_tokens,
            "temperature": spec.temperature,
            "reasoning_effort": REASONING_EFFORT,
            "response_format": {"type": "json_schema", "json_schema": {"name": profile, "schema": self._schema}},
            "messages": [{"role": "system", "content": spec.prompt}, {"role": "user", "content": user_text}],
        }
        async with self._gate:
            try:
                r = await self._http.post(
                    f"{BASE_URL}/chat/completions", headers={"Authorization": f"Bearer {self._key}"}, json=body
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise TemporaryError(f"{type(exc).__name__}: {exc}") from exc
        if r.status_code == 429 or r.status_code >= 500:
            raise TemporaryError(f"Gemini {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        try:
            data = r.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(f"trả lời Gemini thiếu choices/message/content: {r.text[:200]}") from exc
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        if (m := meter()) is not None:
            m.llm(GOOGLE, spec.model, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))
        log.info(
            "Gemini %s: prompt_tokens=%s completion_tokens=%s",
            profile,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
        )
        if choice.get("finish_reason") == "length":
            raise TruncatedLlmError(f"Gemini profile {profile} bị cắt vì chạm max_tokens={spec.max_tokens}")
        return parse_json(str(content or ""))
