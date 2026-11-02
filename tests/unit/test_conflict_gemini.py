import json

import httpx
import pytest

from portal.modules.kb.conflicts.gemini import GeminiLlm
from portal.modules.kb.conflicts.llm import PROFILE, RESPONSE_SCHEMA
from portal.modules.kb.contracts import TemporaryError
from portal.modules.kb.web import usage


def _client(handler) -> GeminiLlm:
    return GeminiLlm(
        api_key="k", schema=RESPONSE_SCHEMA, http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def test_goi_cong_openai_suy_luan_thap_va_ghi_usage_google():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"conflicts": []}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 8},
            },
        )

    m = usage.UsageMeter()
    token = usage._METER.set(m)
    try:
        assert await _client(handler).ask(PROFILE, "x") == {"conflicts": []}
    finally:
        usage._METER.reset(token)
    assert seen["url"].endswith("/v1beta/openai/chat/completions")
    assert seen["body"]["reasoning_effort"] == "low"
    assert "enable_thinking" not in seen["body"]
    assert seen["body"]["response_format"]["json_schema"]["schema"] == RESPONSE_SCHEMA
    ((key, tally),) = m.tallies.items()
    assert key[:2] == ("llm", "google")
    assert (tally.input_tokens, tally.output_tokens) == (120, 8)


async def test_429_la_loi_tam_thoi():
    with pytest.raises(TemporaryError):
        await _client(lambda req: httpx.Response(429, text="quota")).ask(PROFILE, "x")
