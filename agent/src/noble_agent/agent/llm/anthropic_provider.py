"""Anthropic provider adapter — exposes Claude's Messages API behind the
OpenAI ``chat.completions.create`` shape that ``StreamingClient`` expects.

The refactor's ``StreamingClient`` ([llm/client.py]) is duck-typed: it calls
``provider.chat.completions.create(**openai_kwargs)`` and iterates the result
as if it were an OpenAI ``AsyncStream``. We mirror that surface here and do
all the format translation inside — so the rest of the package (orchestrator,
tool dispatcher, transport) keeps speaking OpenAI shape end-to-end.

Translation, in both directions:

  outgoing kwargs (OpenAI → Anthropic)
    - ``messages`` ─ system message extracted to top-level ``system`` param;
      ``role:"tool"`` rewrapped as ``role:"user"`` with a ``tool_result``
      content block; assistant messages carrying ``tool_calls`` become a
      content list of ``text`` + ``tool_use`` blocks (arguments JSON parsed).
    - ``tools`` ─ ``{type:"function", function:{name, description, parameters}}``
      → ``{name, description, input_schema}``.
    - ``model`` ─ ignored; we always use the model passed to ``__init__`` so
      provider fallback (Anthropic primary → OpenAI/Gemini secondary) can keep
      different model names per provider without the agent registry caring.
    - ``stream`` ─ honored; non-streaming path used by ``StreamingClient.complete_once``.

  incoming stream (Anthropic → OpenAI)
    - ``content_block_delta`` / ``text_delta`` → chunk with ``delta.content``.
    - ``content_block_start`` / ``tool_use`` → chunk that opens a new tool call
      (``delta.tool_calls[*].id`` + ``.function.name``).
    - ``content_block_delta`` / ``input_json_delta`` → chunk with
      ``delta.tool_calls[*].function.arguments`` (partial JSON; receiver
      concatenates into the full argument string).
    - ``message_delta`` / ``stop_reason`` → final chunk with ``finish_reason``
      (``end_turn``→``stop``, ``tool_use``→``tool_calls``, ``max_tokens``→``length``).

Prompt caching: when ``cache_system=True`` (default) the system prompt is
sent with ``cache_control:{type:"ephemeral"}`` so Anthropic's 5-minute cache
absorbs the SOUL+SKILL+FAQ prefix — typical workload sees ~50% input-token
discount on repeat turns.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger("noble_agent.llm.anthropic")


# ── Format converters ────────────────────────────────────────────────────────


def _convert_tools(openai_tools: list[dict] | None) -> list[dict] | None:
    """OpenAI tool schema → Anthropic tool schema.

    OpenAI: ``{type:"function", function:{name, description, parameters}}``
    Anthropic: ``{name, description, input_schema}``
    """
    if not openai_tools:
        return None
    converted: list[dict] = []
    for tool in openai_tools:
        fn = tool.get("function") or tool
        name = fn.get("name")
        if not name:
            continue
        entry: dict[str, Any] = {"name": name}
        if "description" in fn:
            entry["description"] = fn["description"]
        entry["input_schema"] = fn.get("parameters") or {"type": "object", "properties": {}}
        converted.append(entry)
    return converted


def _convert_messages(openai_messages: list[dict]) -> tuple[str | None, list[dict]]:
    """OpenAI message list → (system_text, anthropic_messages).

    Rules:
      - ``role:"system"`` is concatenated and pulled out into the top-level
        ``system`` param. Anthropic rejects ``role:"system"`` inside messages.
      - ``role:"tool"`` is rewrapped as ``role:"user"`` with one
        ``tool_result`` content block tied back to ``tool_use_id``.
      - ``role:"assistant"`` carrying ``tool_calls`` is split into a content
        list of optional text + one ``tool_use`` block per call.
      - Consecutive same-role messages are merged so Anthropic's
        strict-alternation validator doesn't reject the conversation.
    """
    system_parts: list[str] = []
    out: list[dict] = []

    for msg in openai_messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            if content:
                system_parts.append(content if isinstance(content, str) else str(content))
            continue

        if role == "tool":
            # Anthropic encodes tool results as a user message containing a
            # ``tool_result`` content block. ``tool_call_id`` from the OpenAI
            # side is the id we emitted when we surfaced the tool_use block.
            block = {
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": content if isinstance(content, str) else json.dumps(content),
            }
            _append_or_merge(out, {"role": "user", "content": [block]})
            continue

        if role == "assistant":
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                # Plain text assistant message — keep ``content`` as a string
                # (Anthropic accepts either string or block list for assistant).
                if content:
                    _append_or_merge(out, {"role": "assistant", "content": content})
                continue

            blocks: list[dict] = []
            if content:
                blocks.append({"type": "text", "text": content})
            for tc in tool_calls:
                fn = tc.get("function") or {}
                raw_args = fn.get("arguments") or "{}"
                try:
                    parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except (json.JSONDecodeError, TypeError):
                    # Anthropic requires ``input`` to be a JSON object; fall back
                    # to wrapping the raw string so the call surfaces rather
                    # than disappearing on a malformed-args edge case.
                    parsed_args = {"_raw": raw_args}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": parsed_args,
                    }
                )
            _append_or_merge(out, {"role": "assistant", "content": blocks})
            continue

        if role == "user" and content:
            _append_or_merge(out, {"role": "user", "content": content})

    system_text = "\n\n".join(p for p in system_parts if p) or None
    return system_text, out


def _append_or_merge(messages: list[dict], new_msg: dict) -> None:
    """Append ``new_msg`` to ``messages``, merging content blocks when the
    last message has the same role (Anthropic requires strict user/assistant
    alternation)."""
    if messages and messages[-1]["role"] == new_msg["role"]:
        prev = messages[-1]
        prev_content = prev["content"]
        new_content = new_msg["content"]

        # Normalize to block lists on merge so mixed string/list content
        # doesn't blow up downstream.
        if isinstance(prev_content, str):
            prev_content = [{"type": "text", "text": prev_content}]
        if isinstance(new_content, str):
            new_content = [{"type": "text", "text": new_content}]
        prev["content"] = prev_content + new_content
    else:
        messages.append(new_msg)


def _build_system_param(system_text: str | None, cache: bool) -> Any:
    """Return the Anthropic ``system`` param. When caching is on we send a
    block list so we can attach ``cache_control:{type:"ephemeral"}`` to the
    prefix; otherwise a plain string is fine and slightly cheaper to parse.
    """
    if not system_text:
        return None
    if cache:
        return [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]
    return system_text


# ── Stream adapter ───────────────────────────────────────────────────────────


_STOP_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
}


def _openai_chunk(
    *,
    content: str | None = None,
    tool_call: dict | None = None,
    finish_reason: str | None = None,
    usage: Any = None,
) -> SimpleNamespace:
    """Build a chunk that quacks like ``openai.types.chat.ChatCompletionChunk``
    — only the attribute paths ``StreamingClient`` actually touches matter:
    ``chunk.choices[0].delta.content`` and ``...delta.tool_calls[*]``.

    ``usage`` piggybacks on the same shape the OpenAI SDK uses when
    ``stream_options.include_usage`` is on, so ``StreamingClient`` reads one
    attribute path for both provider families.
    """
    delta_kwargs: dict[str, Any] = {"content": content, "tool_calls": None}
    if tool_call is not None:
        delta_kwargs["tool_calls"] = [tool_call]
    delta = SimpleNamespace(**delta_kwargs)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason, index=0)
    return SimpleNamespace(choices=[choice], usage=usage)


def _tool_call_open(index: int, tool_id: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        id=tool_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=""),
    )


def _tool_call_delta(index: int, arguments_chunk: str) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        id=None,
        type="function",
        function=SimpleNamespace(name=None, arguments=arguments_chunk),
    )


async def _adapt_stream(anth_stream):
    """Iterate Anthropic stream events and yield OpenAI-shaped chunks.

    Tool-call index tracking: Anthropic gives each content block an integer
    index starting at 0. We reuse that as the OpenAI ``tool_calls[*].index``
    so the consumer's accumulator keys line up.

    Usage: ``message_start`` carries input + cache counts, ``message_delta``
    carries output. We attach the running snapshot to EVERY chunk, not just the
    last one, because an interrupted turn closes the stream before
    ``message_delta`` arrives — the consumer still needs the input counts that
    were already billed, with ``output_tokens`` left None so it can mark the
    row inexact instead of guessing.
    """
    tool_block_indices: dict[int, int] = {}  # anthropic block idx → openai tc idx
    next_tc_idx = 0
    finish_reason: str | None = None
    usage: SimpleNamespace | None = None

    async for event in anth_stream:
        etype = getattr(event, "type", None)

        if etype == "message_start":
            src = getattr(getattr(event, "message", None), "usage", None)
            if src is not None:
                usage = SimpleNamespace(
                    input_tokens=getattr(src, "input_tokens", 0) or 0,
                    output_tokens=None,
                    cache_creation_input_tokens=getattr(src, "cache_creation_input_tokens", 0) or 0,
                    cache_read_input_tokens=getattr(src, "cache_read_input_tokens", 0) or 0,
                )
            continue

        if etype == "content_block_start":
            block = getattr(event, "content_block", None)
            block_idx = getattr(event, "index", 0)
            if block is not None and getattr(block, "type", None) == "tool_use":
                tool_id = getattr(block, "id", "") or ""
                tool_name = getattr(block, "name", "") or ""
                tc_idx = next_tc_idx
                next_tc_idx += 1
                tool_block_indices[block_idx] = tc_idx
                yield _openai_chunk(tool_call=_tool_call_open(tc_idx, tool_id, tool_name), usage=usage)
            continue

        if etype == "content_block_delta":
            block_idx = getattr(event, "index", 0)
            delta = getattr(event, "delta", None)
            if delta is None:
                continue
            dtype = getattr(delta, "type", None)
            if dtype == "text_delta":
                text = getattr(delta, "text", "") or ""
                if text:
                    yield _openai_chunk(content=text, usage=usage)
            elif dtype == "input_json_delta":
                partial = getattr(delta, "partial_json", "") or ""
                if partial and block_idx in tool_block_indices:
                    yield _openai_chunk(
                        tool_call=_tool_call_delta(tool_block_indices[block_idx], partial),
                        usage=usage,
                    )
            continue

        if etype == "message_delta":
            delta = getattr(event, "delta", None)
            stop = getattr(delta, "stop_reason", None) if delta else None
            if stop:
                finish_reason = _STOP_REASON_MAP.get(stop, "stop")
            u = getattr(event, "usage", None)
            if u is not None and usage is not None:
                usage.output_tokens = getattr(u, "output_tokens", 0) or 0
            continue

        if etype == "message_stop":
            yield _openai_chunk(finish_reason=finish_reason or "stop", usage=usage)
            return


# ── Provider class ───────────────────────────────────────────────────────────


class _Completions:
    def __init__(self, parent: AnthropicProvider) -> None:
        self._parent = parent

    async def create(self, **kwargs: Any) -> Any:
        """Mirror ``openai.AsyncOpenAI().chat.completions.create``. The
        ``StreamingClient`` will ``await`` this and then iterate the result
        for streaming, or read ``.choices[0].message.content`` for non-stream.
        """
        messages_in = kwargs.get("messages") or []
        tools_in = kwargs.get("tools")
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens") or kwargs.get("max_completion_tokens") or 4096
        stream = bool(kwargs.get("stream"))

        system_text, anth_messages = _convert_messages(messages_in)
        anth_tools = _convert_tools(tools_in)

        request_kwargs: dict[str, Any] = {
            "model": self._parent._model,
            "messages": anth_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        system_param = _build_system_param(system_text, self._parent._cache_system)
        if system_param is not None:
            request_kwargs["system"] = system_param
        if anth_tools:
            request_kwargs["tools"] = anth_tools

        if stream:
            anth_stream = await self._parent._client.messages.create(stream=True, **request_kwargs)
            return _adapt_stream(anth_stream)

        resp = await self._parent._client.messages.create(stream=False, **request_kwargs)
        return _wrap_nonstream_response(resp)


class _Chat:
    def __init__(self, parent: AnthropicProvider) -> None:
        self.completions = _Completions(parent)


class AnthropicProvider:
    """OpenAI-compat shim around ``anthropic.AsyncAnthropic``.

    Plug into ``StreamingClient.providers`` exactly like an ``AsyncOpenAI``
    instance:

        providers.append(("anthropic", AnthropicProvider(
            api_key=..., model="claude-sonnet-4-6"
        )))

    The ``model`` arg the caller passes to ``chat.completions.create`` is
    ignored — we always use the model fixed at construction. Reason: provider
    fallback walks the list with a single shared model name (agent.model),
    but Anthropic's catalog doesn't overlap with OpenAI/Qwen names. Pinning
    here keeps fallback semantics clean.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        cache_system: bool = True,
        client: Any | None = None,
    ) -> None:
        if client is not None:
            # Test seam: inject a pre-built mock so unit tests don't need
            # the real SDK to be importable.
            self._client = client
        else:
            import anthropic  # local import: optional dep, only loaded when used

            ctor_kwargs: dict[str, Any] = {"api_key": api_key}
            if base_url:
                ctor_kwargs["base_url"] = base_url
            self._client = anthropic.AsyncAnthropic(**ctor_kwargs)

        self._model = model
        self._cache_system = cache_system
        self.chat = _Chat(self)


def _wrap_nonstream_response(anth_resp: Any) -> SimpleNamespace:
    """Wrap a non-streaming Anthropic Message into the OpenAI shape that
    ``StreamingClient.complete_once`` reads (``resp.choices[0].message.content``).
    """
    blocks = getattr(anth_resp, "content", None) or []
    text_parts: list[str] = []
    for block in blocks:
        if getattr(block, "type", None) == "text":
            text_parts.append(getattr(block, "text", "") or "")
    message = SimpleNamespace(content="".join(text_parts), role="assistant")
    choice = SimpleNamespace(message=message, finish_reason="stop", index=0)
    return SimpleNamespace(choices=[choice])
