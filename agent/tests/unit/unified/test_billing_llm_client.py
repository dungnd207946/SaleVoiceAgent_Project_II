"""StreamingClient ghi usage vào meter hiện hành mà KHÔNG đổi kiểu trả về."""

from types import SimpleNamespace

from noble_agent.agent.llm import client as llm_client
from noble_agent.agent.llm.client import StreamingClient
from noble_agent.billing import context
from noble_agent.billing.meter import UsageMeter


def _chunk(text=None, usage=None, finish=None):
    delta = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish, index=0)], usage=usage)


class FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for c in self._chunks:
                yield c

        return gen()


class FakeProvider:
    """Đủ để quack như openai.AsyncOpenAI trên đúng đường StreamingClient chạm."""

    def __init__(self, chunks, captured: dict):
        self._chunks = chunks
        self._captured = captured
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self._captured.update(kwargs)
        return FakeStream(self._chunks)


def _client(provider) -> StreamingClient:
    # _providers là LIST các tuple (name, client), không phải dict —
    # _ordered_providers trả thẳng list này và caller unpack `for name, p in ...`.
    return StreamingClient(
        providers=[("vllm", provider)],
        enable_thinking=False,
        openai_reasoning_effort="none",
    )


async def _run(client, meter, purpose="conversation"):
    async def on_token(_t):
        return None

    with context.use_meter(meter):
        return await client.stream_completion(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            model={"vllm": "qwen"},
            temperature=0.7,
            max_tokens=64,
            on_token=on_token,
            purpose=purpose,
        )


async def test_usage_from_the_stream_lands_in_the_meter():
    usage = SimpleNamespace(
        prompt_tokens=500, completion_tokens=40, prompt_tokens_details=SimpleNamespace(cached_tokens=400)
    )
    provider = FakeProvider([_chunk("xin "), _chunk("chào", usage=usage, finish="stop")], {})
    meter = UsageMeter(session_id="s1", channel="chat")

    content, tool_calls = await _run(_client(provider), meter)

    assert content == "xin chào"  # kiểu trả về KHÔNG đổi
    assert tool_calls is None
    _seq, rows = meter.drain()
    assert rows[0].input_tokens == 100  # 500 − 400 cached
    assert rows[0].cache_read_tokens == 400
    assert rows[0].output_tokens == 40
    assert rows[0].exact is True


async def test_missing_usage_is_recorded_as_inexact():
    provider = FakeProvider([_chunk("a", finish="stop")], {})
    meter = UsageMeter(session_id="s1", channel="chat")
    await _run(_client(provider), meter)
    _seq, rows = meter.drain()
    assert rows[0].exact is False
    assert rows[0].units == 1


async def test_purpose_label_reaches_the_row():
    provider = FakeProvider([_chunk("a", finish="stop")], {})
    meter = UsageMeter(session_id="s1", channel="chat")
    await _run(_client(provider), meter, purpose="addressee_gate")
    _seq, rows = meter.drain()
    assert rows[0].purpose == "addressee_gate"


async def test_llm_wall_ms_is_populated_from_the_stream_duration():
    """Contract §2.1 tài liệu hoá `llm.wall_ms` = tổng thời gian stream LLM. Để
    nó bằng 0 vĩnh viễn là bỏ hẳn cột giá vốn của mọi đường gọi LLM."""
    import asyncio

    class SlowProvider(FakeProvider):
        async def _create(self, **kwargs):
            await asyncio.sleep(0.02)
            return FakeStream(self._chunks)

    provider = SlowProvider([_chunk("a", finish="stop")], {})
    meter = UsageMeter(session_id="s1", channel="chat")
    await _run(_client(provider), meter)
    _seq, rows = meter.drain()
    assert rows[0].wall_ms >= 20.0


async def test_provider_and_model_are_stamped():
    provider = FakeProvider([_chunk("a", finish="stop")], {})
    meter = UsageMeter(session_id="s1", channel="chat")
    await _run(_client(provider), meter)
    _seq, rows = meter.drain()
    assert rows[0].provider == "vllm"
    assert rows[0].model == "qwen"


def _billing_flag(monkeypatch, enabled: bool) -> None:
    from noble_agent import config as cfg

    monkeypatch.setattr(cfg, "get_settings", lambda: SimpleNamespace(billing_metering_enabled=enabled))


async def test_stream_options_only_for_allowlisted_providers(monkeypatch):
    """Allowlist = đã gọi thật vào endpoint đó và thấy nó nhận cờ.

    Provider không hỗ trợ trả 400 — mà 400 là non-transient nên stream_completion
    nhảy provider. Bật ẩu một cờ đo lường = làm hỏng cuộc gọi. Nhưng bỏ sót cũng
    có giá: `gemini` từng nằm ngoài allowlist, và vì Gemini KHÔNG tự gửi usage
    trong stream, mọi dòng `purpose='conversation'` ra token 0 + exact=False,
    trong khi `summary` (không streaming) lại đúng — hoá đơn hụt gần hết phần
    hội thoại. Probe thật 2026-08-18: Gemini nhận cờ, trả usage, không 400.
    """
    assert "vllm" in llm_client._STREAM_USAGE_PROVIDERS
    assert "openai" in llm_client._STREAM_USAGE_PROVIDERS
    assert "gemini" in llm_client._STREAM_USAGE_PROVIDERS
    # dashscope trả usage kể cả KHÔNG gửi cờ ⇒ không cần thêm field vào body.
    assert "dashscope" not in llm_client._STREAM_USAGE_PROVIDERS
    # anthropic đi qua adapter riêng (`_adapt_stream`), không dùng cờ này.
    assert "anthropic" not in llm_client._STREAM_USAGE_PROVIDERS

    _billing_flag(monkeypatch, True)
    captured: dict = {}
    provider = FakeProvider([_chunk("a", finish="stop")], captured)
    await _run(_client(provider), UsageMeter(session_id="s1", channel="chat"))
    assert captured["stream_options"] == {"include_usage": True}


async def test_stream_options_absent_when_the_billing_flag_is_off(monkeypatch):
    """Cờ TẮT ⇒ body request không được đổi một chữ.

    Endpoint từ chối field lạ (vLLM cũ / proxy / llama.cpp-server) trả 400; 400
    là non-transient nên provider bị loại khỏi chain, và nếu nó là provider duy
    nhất thì lượt chết với RuntimeError('all LLM providers failed'). Một cờ đo
    lường đang TẮT không được phép làm rớt cuộc gọi.
    """
    _billing_flag(monkeypatch, False)
    captured: dict = {}
    provider = FakeProvider([_chunk("a", finish="stop")], captured)
    await _run(_client(provider), UsageMeter(session_id="s1", channel="chat"))
    assert "stream_options" not in captured


async def test_no_meter_means_no_crash():
    provider = FakeProvider([_chunk("a", finish="stop")], {})

    async def on_token(_t):
        return None

    content, _ = await _client(provider).stream_completion(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model={"vllm": "qwen"},
        temperature=0.7,
        max_tokens=64,
        on_token=on_token,
    )
    assert content == "a"
