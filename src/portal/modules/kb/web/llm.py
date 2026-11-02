"""Client qwen3.7-flash cho gắn nhãn và viết bài — giao thức `/chat/completions`,
thêm `enable_thinking: false` + `response_format` JSON."""

import asyncio
import json
import logging

import httpx

from portal.modules.kb import prompts, settings
from portal.modules.kb.contracts import TemporaryError
from portal.modules.kb.web.contracts import PROFILE_TAG, Tags
from portal.modules.kb.web.normalize import clean_labels, is_non_project
from portal.modules.kb.web.usage import DASHSCOPE, meter, qwen_model

log = logging.getLogger(__name__)

MAX_TAG_CHARS = 6000
MAX_TAG_LABELS = 10


class TruncatedLlmError(ValueError):
    """Trả lời bị cắt vì chạm `max_tokens` — JSON dở dang, thử lại cùng prompt cũng bị cắt y hệt."""


def parse_json(content: str) -> dict:
    # Tìm `{`…`}` ngoài cùng — fence ```json``` và chữ thừa quanh nó tự rơi ra.
    s = content.strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"không thấy JSON trong trả lời: {content[:200]!r}")
    value = json.loads(s[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("JSON trả về không phải object")
    return value


def tags_from(raw: dict) -> Tags:
    def labels(key: str) -> tuple[str, ...]:
        v = raw.get(key)
        return clean_labels(v if isinstance(v, list) else [])[:MAX_TAG_LABELS]

    rel = raw.get("relevant")
    relevant = rel is True or (isinstance(rel, str) and rel.strip().lower() == "true")
    raw_projects = raw.get("projects") if isinstance(raw.get("projects"), list) else []
    projects = tuple(p for p in clean_labels(raw_projects) if not is_non_project(p))[:MAX_TAG_LABELS]
    return Tags(relevant=relevant, projects=projects, location=labels("location"))


class WebLlm:
    def __init__(
        self, *, base_url: str, api_key: str, concurrency: int = 4, http: httpx.AsyncClient | None = None
    ) -> None:
        if not api_key:
            raise ValueError("thiếu KB_VLM_API_KEY")
        self._base = base_url.rstrip("/")
        self._key = api_key
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
            "enable_thinking": False,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": spec.prompt}, {"role": "user", "content": user_text}],
        }
        async with self._gate:
            try:
                r = await self._http.post(
                    f"{self._base}/chat/completions", headers={"Authorization": f"Bearer {self._key}"}, json=body
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise TemporaryError(f"{type(exc).__name__}: {exc}") from exc
        if r.status_code == 429 or r.status_code >= 500:
            raise TemporaryError(f"LLM {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        try:
            data = r.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(f"trả lời LLM thiếu choices/message/content: {r.text[:200]}") from exc
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        if (m := meter()) is not None:
            prompt = int(usage.get("prompt_tokens") or 0)
            m.llm(DASHSCOPE, qwen_model(spec.model, prompt), prompt, int(usage.get("completion_tokens") or 0))
        log.info(
            "LLM %s: prompt_tokens=%s completion_tokens=%s",
            profile,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
        )
        if choice.get("finish_reason") == "length":
            raise TruncatedLlmError(f"LLM profile {profile} bị cắt vì chạm max_tokens={spec.max_tokens}")
        return parse_json(str(content))

    async def tag(self, title: str, text: str) -> Tags:
        return tags_from(await self.ask(PROFILE_TAG, f"TIÊU ĐỀ: {title}\n\n{text[:MAX_TAG_CHARS]}"))
