from eval.data import TurnSample
from eval.predict import predict_turn


class _FakeClient:
    def __init__(self, content, tool_calls):
        self._content = content
        self._tool_calls = tool_calls
        self.calls = []

    async def stream_completion(self, *, messages, tools, model, temperature, max_tokens, on_token, primary=None):
        self.calls.append({"messages": messages, "tools": tools, "primary": primary})
        await on_token("ignored")
        return self._content, self._tool_calls


def _sample():
    return TurnSample(
        conversation_id="c",
        turn_idx=0,
        step_idx_in_turn=0,
        is_first_assistant=True,
        is_final_assistant=False,
        user_message="alo",
        prefix=[{"role": "system", "content": "s"}, {"role": "user", "content": "alo"}],
        reference_response={},
        tools=[{"type": "function", "function": {"name": "x"}}],
    )


async def test_predict_turn_shapes_response():
    tool_call = {"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}
    client = _FakeClient("Dạ chào anh", [tool_call])
    out = await predict_turn(client, _sample(), model="m", primary="anthropic", temperature=0.2, max_tokens=1024)
    assert out["role"] == "assistant"
    assert out["content"] == "Dạ chào anh"
    assert out["tool_calls"][0]["function"]["name"] == "x"
    assert client.calls[0]["primary"] == "anthropic"
    assert client.calls[0]["tools"] == _sample().tools


async def test_predict_turn_handles_none_tool_calls():
    client = _FakeClient("Dạ vâng ạ", None)
    out = await predict_turn(client, _sample(), model="m", primary=None, temperature=0.2, max_tokens=1024)
    assert out["tool_calls"] == []
    assert out["content"] == "Dạ vâng ạ"


async def test_predict_turn_strips_thinking_from_content():
    client = _FakeClient("Dạ<think>reasoning here</think> chào anh", None)
    out = await predict_turn(client, _sample(), model="m", primary=None, temperature=0.2, max_tokens=1024)
    assert out["content"] == "Dạ chào anh"
