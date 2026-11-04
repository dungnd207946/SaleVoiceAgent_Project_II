"""Streaming LLM client with provider fallback. Provider objects must mirror the OpenAI SDK shape."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable

from noble_agent.agent.llm.sanitize import MarkdownStripper
from noble_agent.agent.llm.thinking import (
    ThinkStripper,
    disable_thinking_kwargs,
    strip_think,
)

logger = logging.getLogger("noble_agent.llm")

# Slot tương thích OpenAI đã kiểm chứng là chấp nhận `stream_options`.
# CỐ Ý bảo thủ: provider không hỗ trợ trả 400, mà `_is_transient` coi 400 là
# non-transient nên `stream_completion` sẽ nhảy sang provider kế — tức là một
# cờ ĐO LƯỜNG có thể làm hỏng cuộc gọi. Thà thiếu số liệu (exact=False) còn
# hơn rớt cuộc gọi. `anthropic` không nằm đây vì nó đi qua adapter riêng.
#
# Chỉ thêm tên vào đây sau khi gọi thật vào endpoint đó. Đã probe (2026-08-18):
#   gemini    — KHÔNG có cờ thì stream không mang usage NÀO, có cờ thì trả usage
#               bình thường (kể cả lượt có tools), không 400. ⇒ thêm vào. Thiếu
#               nó chính là bug: mọi dòng `purpose='conversation'` ra token 0 +
#               exact=False, trong khi `summary` đúng vì nó không streaming.
#   dashscope — trả usage kể cả KHÔNG gửi cờ, nên không cần cờ; giữ ngoài
#               allowlist để không thêm field vào body mà chẳng được gì.
_STREAM_USAGE_PROVIDERS = frozenset({"openai", "vllm", "gemini"})


def _billing_on() -> bool:
    """Cờ đo lường có đang bật không — quyết định có gửi `stream_options`.

    Cờ TẮT thì tuyệt đối không được đụng vào body request: một endpoint từ chối
    field lạ (vLLM cũ, proxy, llama.cpp-server) trả 400, mà 400 là non-transient
    nên provider bị loại khỏi chain — nếu nó là provider duy nhất thì cả lượt
    chết với RuntimeError. Không được để một cờ đo lường TẮT làm rớt cuộc gọi.
    Đọc settings lười (không cache) để test bật/tắt cờ trong cùng process.
    """
    try:
        from noble_agent.config import get_settings

        return bool(get_settings().billing_metering_enabled)
    except Exception:  # noqa: BLE001 — thiếu config không được làm hỏng lượt
        return False


def _resolve_model(model: str | dict[str, str], provider_name: str) -> str:
    """Resolve the per-call model name for `provider_name`.

    - `str` → that name is sent to every provider in the chain (main-agent
      path: one name flows through anthropic → openai → gemini until one
      accepts it).
    - `dict[provider_name → model]` → look up by provider name. A missing
      key or empty string means "no configured model for this provider";
      the caller skips that provider so we don't 400 with a junk model.
    """
    if isinstance(model, dict):
        return model.get(provider_name, "") or ""
    return model


def _is_real_openai(provider) -> bool:
    """True when an openai-slot provider points at the hosted OpenAI API
    (api.openai.com). vLLM / local / Azure / OpenRouter all have a different
    host and are treated as 'OpenAI-compatible' (they accept ``max_tokens`` and
    the vLLM ``chat_template_kwargs`` thinking switch). Detection is by base_url
    host only — both use the same AsyncOpenAI SDK and provider_name 'openai'.
    ``getattr(..., "")`` keeps it safe for providers lacking ``base_url`` (e.g.
    the anthropic provider)."""
    base = str(getattr(provider, "base_url", "") or "")
    return "api.openai.com" in base


def _max_tokens_kwarg(provider, provider_name: str, max_tokens: int) -> dict:
    """Real OpenAI reasoning models reject ``max_tokens`` and require
    ``max_completion_tokens``. vLLM / local / gemini accept ``max_tokens``."""
    if provider_name == "openai" and _is_real_openai(provider):
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens}


def _normalize_for_openai_compat(messages: list[dict], provider_name: str) -> list[dict]:
    """Reshape an OpenAI-canonical message list for Gemini's OpenAI-compat
    endpoint, which is stricter than real OpenAI / vLLM.

    Gated to ``provider_name == "gemini"``; every other provider gets the SAME
    list object back (passthrough) so the openai / vLLM / anthropic paths are
    provably untouched. The gemini branch returns NEW dicts — it never mutates
    the caller's ``messages`` (the runner reuses that list across the tool
    loop). Mirrors ``anthropic_provider._convert_messages``: a pure boundary
    translation, no side effects.

    For gemini it:
      1. drops the stray ``name`` key from ``role:"tool"`` messages;
      2. injects a sequential ``index`` on each assistant ``tool_calls`` entry
         and guarantees ``function.arguments`` is a valid JSON-object string
         (defaulting to ``"{}"`` when empty / missing / non-parseable);
      3. drops tool_calls entries with an empty ``id`` defensively.
    All other roles pass through shallow-copied.
    """
    if provider_name != "gemini":
        return messages

    out: list[dict] = []
    for msg in messages:
        role = msg.get("role")

        if role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", ""),
                    "content": msg.get("content", ""),
                }
            )
            continue

        if role == "assistant" and msg.get("tool_calls"):
            new_calls: list[dict] = []
            for tc in msg["tool_calls"]:
                if not tc.get("id"):
                    continue
                fn = tc.get("function") or {}
                raw_args = fn.get("arguments")
                if not isinstance(raw_args, str) or not raw_args.strip():
                    args = "{}"
                else:
                    try:
                        json.loads(raw_args)
                        args = raw_args
                    except (json.JSONDecodeError, TypeError):
                        args = "{}"
                new_call = {
                    "id": tc["id"],
                    "type": "function",
                    "index": len(new_calls),
                    "function": {"name": fn.get("name", ""), "arguments": args},
                }
                if "extra_content" in tc:
                    # Gemini 3.x requires this echoed back verbatim on a replayed
                    # tool call (thought_signature) or the request 400s.
                    # https://ai.google.dev/gemini-api/docs/thought-signatures
                    new_call["extra_content"] = tc["extra_content"]
                new_calls.append(new_call)
            out.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": new_calls})
            continue

        out.append(dict(msg))

    return out


_TRANSIENT_STATUS = {408, 409, 429}

# Providers whose OpenAI-compat endpoint accepts the OpenAI `tool_choice`
# param (verified live 2026-08-24: gemini + dashscope trả 200 với "required";
# dashscope CHỈ khi enable_thinking=false — thinking bật thì 400, non-transient
# → provider bị loại khỏi chain, nên forcing chỉ dùng cùng thinking-off).
# Anthropic nói dialect tool_choice khác ({"type": "any"}) — không forward.
_TOOL_CHOICE_PROVIDERS = {"openai", "vllm", "dashscope", "gemini"}


def _is_transient(exc: Exception) -> bool:
    """Best-effort classifier: transient errors (connection/timeout, 429, 5xx)
    fall through to the next provider quietly; non-transient 4xx client errors
    are surfaced loudly. Unknown / no status → transient, to preserve the
    voice path's fallback-as-retry resilience."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "status", None)
    if status is None:
        return True
    try:
        code = int(status)
    except (TypeError, ValueError):
        return True
    if code in _TRANSIENT_STATUS:
        return True
    return code >= 500


class StreamingClient:
    def __init__(
        self,
        providers: list[tuple[str, object]],
        enable_thinking: bool = True,
        openai_reasoning_effort: str = "none",
    ):
        """providers: ordered list of (name, openai_client_like). First success wins.

        ``enable_thinking`` is the global thinking-mode toggle. When ``False``
        every call (a) attaches the provider-specific disable kwarg and (b)
        strips any leaked ``<think>...</think>`` span from the output, so a
        model that ignores the flag still can't leak reasoning into TTS/history.
        Defaults to ``True`` (pure passthrough) so existing callers are unchanged.

        ``openai_reasoning_effort`` is sent as ``reasoning_effort`` ONLY to a
        real-OpenAI provider (api.openai.com) and only when it is not the
        ``"none"`` sentinel ("unset"). vLLM / local / gemini ignore it.
        """
        if not providers:
            raise ValueError("StreamingClient requires at least one provider")
        self._providers = providers
        self._enable_thinking = enable_thinking
        self._openai_reasoning_effort = openai_reasoning_effort

    def _ordered_providers(self, primary: str | None) -> list[tuple[str, object]]:
        """Return the provider list with `primary` moved to the front.

        Order is otherwise stable (build order from `build_llm_providers`).
        Unknown / missing primary names are silently ignored so a stale env
        var doesn't break the chain.
        """
        if not primary:
            return self._providers
        return sorted(self._providers, key=lambda np: 0 if np[0] == primary else 1)

    def _apply_provider_shaping(self, kwargs: dict, provider, provider_name: str) -> None:
        """Shape the request kwargs in-place for the target endpoint.

        - Thinking-disable kwarg: applied per provider name, EXCEPT real OpenAI
          (api.openai.com) which rejects the vLLM-only ``chat_template_kwargs``.
        - Real OpenAI reasoning models additionally require ``temperature == 1``
          and accept ``reasoning_effort`` (sent only when not the ``"none"``
          sentinel that means "unset").
        """
        real_openai = provider_name == "openai" and _is_real_openai(provider)
        if not self._enable_thinking and not real_openai:
            kwargs.update(disable_thinking_kwargs(provider_name))
        if real_openai:
            kwargs["temperature"] = 1
            if self._openai_reasoning_effort and self._openai_reasoning_effort != "none":
                kwargs["reasoning_effort"] = self._openai_reasoning_effort
        if provider_name in _STREAM_USAGE_PROVIDERS and kwargs.get("stream") and _billing_on():
            kwargs["stream_options"] = {"include_usage": True}

    async def stream_completion(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        model: str | dict[str, str],
        temperature: float,
        max_tokens: int,
        on_token: Callable[[str], Awaitable[None]],
        interrupt_check: Callable[[], bool] | None = None,
        primary: str | None = None,
        purpose: str = "conversation",
        tool_choice: str | None = None,
    ) -> tuple[str, list[dict] | None]:
        last_err: Exception | None = None
        for name, provider in self._ordered_providers(primary):
            resolved = _resolve_model(model, name)
            if not resolved:
                continue
            try:
                return await self._stream_once(
                    provider=provider,
                    provider_name=name,
                    messages=messages,
                    tools=tools,
                    model=resolved,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    on_token=on_token,
                    interrupt_check=interrupt_check,
                    purpose=purpose,
                    tool_choice=tool_choice,
                )
            except Exception as e:  # noqa: BLE001
                if _is_transient(e):
                    logger.warning("llm: provider %s failed transiently (%s), trying next", name, e)
                else:
                    logger.error("llm: provider %s failed with non-transient error (%s) — surfacing", name, e)
                last_err = e
        logger.error("llm: all providers failed; last error: %s", last_err)
        raise RuntimeError("all LLM providers failed") from last_err

    async def _stream_once(
        self,
        *,
        provider,
        provider_name="",
        messages,
        tools,
        model,
        temperature,
        max_tokens,
        on_token,
        interrupt_check=None,
        purpose="conversation",
        tool_choice=None,
    ) -> tuple[str, list[dict] | None]:
        kwargs = dict(
            model=model,
            messages=_normalize_for_openai_compat(messages, provider_name),
            temperature=temperature,
            stream=True,
        )
        kwargs.update(_max_tokens_kwarg(provider, provider_name, max_tokens))
        if tools:
            kwargs["tools"] = tools
            # DashScope từ chối tool_choice=required/object khi thinking BẬT
            # (probe 2026-08-24: 400 InvalidParameter "in thinking mode") — 400
            # là non-transient nên provider bị bỏ qua cả lượt; thà không ép còn
            # hơn mất provider.
            dashscope_thinking = provider_name == "dashscope" and self._enable_thinking
            if tool_choice and provider_name in _TOOL_CHOICE_PROVIDERS and not dashscope_thinking:
                kwargs["tool_choice"] = tool_choice
        self._apply_provider_shaping(kwargs, provider, provider_name)

        # When thinking is disabled, strip any leaked <think>...</think> span
        # from both the streamed tokens and the returned content.
        stripper = ThinkStripper() if not self._enable_thinking else None
        # Persona quy định văn nói thuần — gỡ marker markdown khỏi stream chat
        # + history (qwen3.7-flash xả bullet/bold; voice đã có tts/_normalize).
        md_stripper = MarkdownStripper()

        # Thời gian stream LLM (contract §2.1 `llm.wall_ms`) — tính từ lúc phát
        # request tới lúc stream đóng, kể cả khi bị ngắt lời giữa chừng.
        _t0 = time.perf_counter()
        stream = await provider.chat.completions.create(**kwargs)

        content_parts: list[str] = []
        # Key tool-call slots by present index (stable across arg fragments) or,
        # when index is absent (Gemini compat), by id so parallel index-less
        # calls stay separate instead of collapsing onto key 0. `order` preserves
        # first-seen order; `_auto` keys the rare no-index/no-id opening delta.
        tool_calls: dict[object, dict] = {}
        order: list[object] = []
        auto = 0
        last_usage = None

        async for chunk in stream:
            # Giữ snapshot usage mới nhất. Anthropic gắn nó vào MỌI chunk sau
            # message_start, nên khi bị ngắt giữa chừng ta vẫn còn input token.
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                last_usage = chunk_usage
            if interrupt_check is not None and interrupt_check():
                logger.info("llm: interrupted mid-stream, returning partial")
                # Best-effort close — providers expose .close() on async streams.
                close = getattr(stream, "close", None) or getattr(stream, "aclose", None)
                if close is not None:
                    try:
                        res = close()
                        if hasattr(res, "__await__"):
                            await res
                    except Exception:
                        pass
                break
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                if stripper is not None:
                    piece = stripper.feed(piece)
                if piece:
                    piece = md_stripper.feed(piece)
                if piece:
                    content_parts.append(piece)
                    await on_token(piece)
            for tc_delta in getattr(delta, "tool_calls", None) or []:
                idx = getattr(tc_delta, "index", None)
                tid = getattr(tc_delta, "id", None)
                if idx is not None:
                    key = ("i", idx)  # present index: stable across arg fragments
                elif tid:
                    key = ("d", tid)  # no index but a fresh id → new slot per id
                elif order:
                    key = order[-1]  # continuation fragment: append to last slot
                else:
                    auto += 1
                    key = ("a", auto)
                if key not in tool_calls:
                    tool_calls[key] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                    order.append(key)
                cur = tool_calls[key]
                if tid:
                    cur["id"] = tid
                fn = getattr(tc_delta, "function", None)
                if fn:
                    if getattr(fn, "name", None):
                        cur["function"]["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        cur["function"]["arguments"] += fn.arguments
                # Gemini 3.x: opaque thought_signature, delivered whole in one
                # chunk (not fragmented like arguments) — see _normalize_for_openai_compat.
                extra_content = getattr(tc_delta, "extra_content", None)
                if extra_content:
                    cur["extra_content"] = extra_content

        if stripper is not None:
            tail = stripper.flush()
            if tail:
                tail = md_stripper.feed(tail)
                if tail:
                    content_parts.append(tail)
                    await on_token(tail)
        md_tail = md_stripper.flush()
        if md_tail:
            content_parts.append(md_tail)
            await on_token(md_tail)

        from noble_agent.billing.capture import record as _record_usage

        _record_usage(
            provider_name,
            model,
            last_usage,
            purpose=purpose,
            wall_ms=(time.perf_counter() - _t0) * 1000.0,
        )

        tcs = [tool_calls[k] for k in order] if tool_calls else None
        return "".join(content_parts), tcs

    async def simple_completion(
        self,
        prompt: str,
        *,
        model: str | dict[str, str],
        max_tokens: int = 400,
        temperature: float = 0.3,
        primary: str | None = None,
        purpose: str = "conversation",
    ) -> str:
        """Single-turn non-streaming completion. Used by the summary helper."""
        messages = [{"role": "user", "content": prompt}]
        return await self.complete_once(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            primary=primary,
            purpose=purpose,
        )

    async def complete_once(
        self,
        *,
        messages,
        model: str | dict[str, str],
        temperature,
        max_tokens,
        primary: str | None = None,
        request_timeout: float | None = None,
        purpose: str = "conversation",
    ) -> str:
        """Non-streaming completion with the SAME provider fallback chain as the
        streaming path. ``request_timeout`` (seconds) bounds EACH provider
        attempt so a slow/hung provider fails fast and the loop falls through to
        the next one — a per-provider bound, not an overall cap, so fallback is
        never cut short. OpenAI-compatible providers honour it; the Anthropic
        shim ignores the extra kwarg (uses its own client default)."""
        last_err: Exception | None = None
        for name, provider in self._ordered_providers(primary):
            resolved = _resolve_model(model, name)
            if not resolved:
                continue
            try:
                kwargs = dict(
                    model=resolved,
                    messages=_normalize_for_openai_compat(messages, name),
                    temperature=temperature,
                    stream=False,
                )
                if request_timeout is not None:
                    kwargs["timeout"] = request_timeout
                kwargs.update(_max_tokens_kwarg(provider, name, max_tokens))
                self._apply_provider_shaping(kwargs, provider, name)
                _t0 = time.perf_counter()
                resp = await provider.chat.completions.create(**kwargs)

                from noble_agent.billing.capture import record as _record_usage

                _record_usage(
                    name,
                    resolved,
                    getattr(resp, "usage", None),
                    purpose=purpose,
                    wall_ms=(time.perf_counter() - _t0) * 1000.0,
                )

                content = resp.choices[0].message.content or ""
                return content if self._enable_thinking else strip_think(content)
            except Exception as e:  # noqa: BLE001
                if _is_transient(e):
                    logger.warning("llm.complete_once: provider %s failed transiently (%s), trying next", name, e)
                else:
                    logger.error(
                        "llm.complete_once: provider %s failed with non-transient error (%s) — surfacing", name, e
                    )
                last_err = e
        logger.error("llm.complete_once: all providers failed; last error: %s", last_err)
        raise RuntimeError("all LLM providers failed") from last_err
