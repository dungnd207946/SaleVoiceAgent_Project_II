"""Thinking-mode control for the LLM path.

Two layers, used by :class:`StreamingClient` when thinking is disabled:

1. :func:`disable_thinking_kwargs` — provider-specific request kwarg that asks
   the backend not to generate reasoning at all (saves tokens / latency).
2. :class:`ThinkStripper` — a stateful, chunk-tolerant filter that removes any
   ``<think>...</think>`` span a model leaks into its content anyway. This is
   the universal guarantee: a base model (e.g. Qwen3-0.6B) may ignore the flag
   above and still emit ``<think>`` tags, which must never reach TTS or history.
"""

from __future__ import annotations

import re

_OPEN = "<think>"
_CLOSE = "</think>"
_STRIP_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def disable_thinking_kwargs(provider_name: str) -> dict:
    """Return the request kwargs that disable thinking for ``provider_name``.

    - ``openai`` / ``vllm`` slot (vLLM / Qwen self-host): the Qwen chat
      template reads ``chat_template_kwargs.enable_thinking``.
    - ``dashscope`` (Alibaba DashScope OpenAI-compat): Qwen3 there reads a
      top-level ``extra_body.enable_thinking`` flag (NOT the chat-template one).
    - ``gemini`` (OpenAI-compat): ``reasoning_effort="none"``.
    - everything else (``anthropic`` …): nothing — Claude does not emit
      ``<think>`` into content and extended thinking is off by default.
    """
    if provider_name in ("openai", "vllm"):
        return {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
    if provider_name == "dashscope":
        return {"extra_body": {"enable_thinking": False}}
    if provider_name == "gemini":
        return {"reasoning_effort": "none"}
    return {}


def strip_think(text: str) -> str:
    """Remove complete ``<think>...</think>`` spans from a whole string.

    Used on the non-streaming path (``complete_once`` / summary)."""
    return _STRIP_RE.sub("", text)


def _suffix_prefix_len(buf: str, tag: str) -> int:
    """Length of the longest suffix of ``buf`` that is a *partial* prefix of
    ``tag`` (1 ≤ k < len(tag)). Held back so a tag split across chunks isn't
    emitted or missed. A full match would already have been found by ``find``.
    """
    max_k = min(len(buf), len(tag) - 1)
    for k in range(max_k, 0, -1):
        if buf[-k:] == tag[:k]:
            return k
    return 0


class ThinkStripper:
    """Streaming remover of ``<think>...</think>`` spans.

    Feed it content pieces as they arrive; ``feed`` returns the text that is
    safe to emit now (text outside any think span). Tags split across chunk
    boundaries are buffered until resolved. Call ``flush`` at end of stream to
    drain the buffer — an unterminated ``<think>`` is discarded; a dangling
    partial-tag prefix that never completed is real text and is returned.
    """

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False

    def feed(self, piece: str) -> str:
        if not piece:
            return ""
        self._buf += piece
        out: list[str] = []
        while self._buf:
            if not self._inside:
                idx = self._buf.find(_OPEN)
                if idx != -1:
                    out.append(self._buf[:idx])
                    self._buf = self._buf[idx + len(_OPEN) :]
                    self._inside = True
                    continue
                hold = _suffix_prefix_len(self._buf, _OPEN)
                if hold:
                    out.append(self._buf[:-hold])
                    self._buf = self._buf[-hold:]
                else:
                    out.append(self._buf)
                    self._buf = ""
                break
            # inside a think span: suppress everything up to the close tag
            idx = self._buf.find(_CLOSE)
            if idx != -1:
                self._buf = self._buf[idx + len(_CLOSE) :]
                self._inside = False
                continue
            hold = _suffix_prefix_len(self._buf, _CLOSE)
            self._buf = self._buf[-hold:] if hold else ""
            break
        return "".join(out)

    def flush(self) -> str:
        if self._inside:
            self._buf = ""
            return ""
        out = self._buf
        self._buf = ""
        return out
