"""Adapter Anthropic phải chuyển usage ra ngoài — hiện nó bỏ hẳn hai event mang
số token (message_start và message_delta)."""

from types import SimpleNamespace

from noble_agent.agent.llm.anthropic_provider import _adapt_stream


class FakeStream:
    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        async def gen():
            for e in self._events:
                yield e

        return gen()


def _start(**usage):
    return SimpleNamespace(type="message_start", message=SimpleNamespace(usage=SimpleNamespace(**usage)))


def _text(t):
    return SimpleNamespace(type="content_block_delta", index=0, delta=SimpleNamespace(type="text_delta", text=t))


async def _collect(events):
    return [c async for c in _adapt_stream(FakeStream(events))]


async def test_usage_appears_on_the_final_chunk():
    chunks = await _collect(
        [
            _start(input_tokens=2140, cache_creation_input_tokens=0, cache_read_input_tokens=11800),
            _text("xin chào"),
            SimpleNamespace(
                type="message_delta",
                delta=SimpleNamespace(stop_reason="end_turn"),
                usage=SimpleNamespace(output_tokens=214),
            ),
            SimpleNamespace(type="message_stop"),
        ]
    )
    last = chunks[-1]
    assert last.usage.input_tokens == 2140
    assert last.usage.cache_read_input_tokens == 11800
    assert last.usage.output_tokens == 214


async def test_text_still_streams_unchanged():
    chunks = await _collect(
        [
            _start(input_tokens=10, cache_creation_input_tokens=0, cache_read_input_tokens=0),
            _text("a"),
            _text("b"),
            SimpleNamespace(type="message_stop"),
        ]
    )
    text = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert text == "ab"


async def test_input_tokens_are_available_before_the_stream_finishes():
    """Khi khách ngắt lời, ta đóng stream giữa chừng nên message_delta không
    bao giờ về. Input token phải đã có sẵn từ message_start, còn output để
    None để tầng trên đánh dấu exact=False."""
    chunks = await _collect(
        [
            _start(input_tokens=1460, cache_creation_input_tokens=0, cache_read_input_tokens=14100),
            _text("đang nói dở"),
        ]
    )
    mid = chunks[-1]
    assert mid.usage.input_tokens == 1460
    assert mid.usage.output_tokens is None


async def test_no_message_start_means_no_usage_attribute_value():
    chunks = await _collect([_text("a"), SimpleNamespace(type="message_stop")])
    assert getattr(chunks[-1], "usage", None) is None
