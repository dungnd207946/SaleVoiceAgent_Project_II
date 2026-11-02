"""Tests for the thinking-mode helpers: provider disable-kwargs and the
streaming `<think>...</think>` stripper that guarantees clean output even when
a base model ignores the disable flag."""

from __future__ import annotations

import pytest

from noble_agent.agent.llm.thinking import (
    ThinkStripper,
    disable_thinking_kwargs,
    strip_think,
)


def _run(pieces: list[str]) -> str:
    """Feed pieces through a fresh stripper and append the flush remainder."""
    s = ThinkStripper()
    out = "".join(s.feed(p) for p in pieces)
    return out + s.flush()


# ── disable_thinking_kwargs ──────────────────────────────────────────────────


def test_disable_kwargs_openai_uses_chat_template_kwargs():
    assert disable_thinking_kwargs("openai") == {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}


def test_disable_kwargs_vllm_uses_chat_template_kwargs():
    # The named vLLM slot uses the same Qwen chat-template switch as the openai slot.
    assert disable_thinking_kwargs("vllm") == {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}


def test_disable_kwargs_dashscope_uses_top_level_enable_thinking():
    # Alibaba DashScope's Qwen3 reads a top-level extra_body.enable_thinking,
    # NOT the vLLM/openai chat-template flag.
    assert disable_thinking_kwargs("dashscope") == {"extra_body": {"enable_thinking": False}}


def test_disable_kwargs_gemini_uses_reasoning_effort():
    assert disable_thinking_kwargs("gemini") == {"reasoning_effort": "none"}


def test_disable_kwargs_anthropic_is_empty():
    # Claude never emits <think> into content; extended thinking is off by default.
    assert disable_thinking_kwargs("anthropic") == {}


def test_disable_kwargs_unknown_provider_is_empty():
    assert disable_thinking_kwargs("groq") == {}


# ── strip_think (non-streaming) ──────────────────────────────────────────────


def test_strip_think_removes_block_across_newlines():
    assert strip_think("a<think>line1\nline2</think>b") == "ab"


def test_strip_think_no_tags_passthrough():
    assert strip_think("just an answer") == "just an answer"


# ── ThinkStripper (streaming) ────────────────────────────────────────────────


def test_stripper_passthrough_when_no_tags():
    assert _run(["hello ", "world"]) == "hello world"


def test_stripper_removes_whole_block_in_one_piece():
    assert _run(["a<think>xyz</think>b"]) == "ab"


def test_stripper_preserves_content_around_block():
    assert _run(["before <think>reasoning</think> after"]) == "before  after"


def test_stripper_handles_open_tag_split_across_chunks():
    assert _run(["a<thi", "nk>xyz</thi", "nk>b"]) == "ab"


def test_stripper_handles_close_tag_split_across_chunks():
    assert _run(["<think>aaa</thi", "nk>tail"]) == "tail"


def test_stripper_removes_multiple_blocks():
    assert _run(["x<think>1</think>y<think>2</think>z"]) == "xyz"


def test_stripper_suppresses_unterminated_think_on_flush():
    assert _run(["ok<think>still thinking with no close"]) == "ok"


def test_stripper_emits_partial_open_prefix_that_never_completes():
    # "<thi" at the end is real text, not a tag — flush must emit it.
    assert _run(["done<thi"]) == "done<thi"


def test_stripper_emits_chunk_by_chunk_not_only_at_flush():
    s = ThinkStripper()
    # Plain text outside a tag should be released as it arrives, so TTS isn't
    # stalled waiting for end-of-stream.
    assert s.feed("hi ") == "hi "
    assert s.feed("there") == "there"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
