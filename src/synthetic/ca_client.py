"""Customer-Agent LLM client — one-shot chat completion across 3 providers.

Plays the customer side of the call. Lighter than Noble's StreamingClient
because CA doesn't stream, doesn't call tools, and doesn't need fallback —
the user picks a single provider+model in `src/synthetic/.env`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from synthetic.config import SyntheticSettings

logger = logging.getLogger("synthetic.ca_client")


class CustomerAgentClient:
    def __init__(self, settings: SyntheticSettings):
        self.settings = settings
        self._client: Any = None
        self._init_lock = asyncio.Lock()
        self._provider = settings.provider.lower().strip()
        if self._provider not in ("openai", "anthropic", "gemini"):
            raise ValueError(f"CA_PROVIDER must be openai|anthropic|gemini, got {self._provider!r}")

    async def complete(self, messages: list[dict]) -> str:
        if self._provider == "anthropic":
            return await self._complete_anthropic(messages)
        return await self._complete_openai_compat(messages)

    async def _complete_openai_compat(self, messages: list[dict]) -> str:
        import openai

        if self._client is None:
            async with self._init_lock:
                if self._client is None:
                    kwargs: dict[str, Any] = {}
                    if self._provider == "gemini":
                        if not self.settings.gemini_api_key:
                            raise RuntimeError("CA_GEMINI_API_KEY not set")
                        kwargs["api_key"] = self.settings.gemini_api_key
                        kwargs["base_url"] = self.settings.gemini_base_url
                    else:
                        if not self.settings.openai_api_key:
                            raise RuntimeError("CA_OPENAI_API_KEY not set")
                        kwargs["api_key"] = self.settings.openai_api_key
                        if self.settings.openai_base_url:
                            kwargs["base_url"] = self.settings.openai_base_url
                    self._client = openai.AsyncOpenAI(**kwargs)

        resp = await self._client.chat.completions.create(
            model=self.settings.model,
            messages=messages,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()

    async def _complete_anthropic(self, messages: list[dict]) -> str:
        import anthropic

        if self._client is None:
            async with self._init_lock:
                if self._client is None:
                    if not self.settings.anthropic_api_key:
                        raise RuntimeError("CA_ANTHROPIC_API_KEY not set")
                    kwargs: dict[str, Any] = {"api_key": self.settings.anthropic_api_key}
                    if self.settings.anthropic_base_url:
                        kwargs["base_url"] = self.settings.anthropic_base_url
                    self._client = anthropic.AsyncAnthropic(**kwargs)

        system_text = ""
        anth_messages: list[dict] = []
        for m in messages:
            if m["role"] == "system":
                system_text = (system_text + "\n\n" + m["content"]).strip()
            else:
                anth_messages.append({"role": m["role"], "content": m["content"]})

        kwargs = {
            "model": self.settings.model,
            "max_tokens": self.settings.max_tokens,
            "temperature": self.settings.temperature,
            "messages": anth_messages,
        }
        if system_text:
            kwargs["system"] = system_text

        resp = await self._client.messages.create(**kwargs)
        parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return "".join(parts).strip()
