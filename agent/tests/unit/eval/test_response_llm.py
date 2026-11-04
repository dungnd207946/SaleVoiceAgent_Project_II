import json

from eval.data import TurnSample
from eval.response_llm import build_prompt, judge_turn, parse_judge_json


def _sample():
    return TurnSample(
        conversation_id="c",
        turn_idx=1,
        step_idx_in_turn=0,
        is_first_assistant=False,
        is_final_assistant=False,
        user_message="giá NCTH sao em",
        prefix=[{"role": "system", "content": "s"}, {"role": "user", "content": "giá NCTH sao em"}],
        reference_response={"role": "assistant", "content": "Dạ giá khoảng 5 tỷ ạ"},
        tools=[],
    )


def test_parse_judge_json_strips_fences():
    raw = '```json\n{"scores": {"clarity": 4}, "factual_pass": true}\n```'
    out = parse_judge_json(raw)
    assert out["scores"]["clarity"] == 4
    assert out["factual_pass"] is True


def test_build_prompt_contains_sections():
    p = build_prompt(_sample(), {"role": "assistant", "content": "Dạ tầm 5 tỷ ạ"})
    assert "USER_MESSAGE" in p and "giá NCTH" in p
    assert "PREDICTED_RESPONSE" in p and "5 tỷ" in p
    assert "{criteria_list}" not in p  # template fully filled


class _FakeMessage:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeMessage(content)]


class _FakeCritic:
    def __init__(self, content):
        self._content = content
        self.chat = type("C", (), {"completions": self})()

    async def create(self, **kwargs):
        self._kwargs = kwargs
        return _FakeResp(self._content)


async def test_judge_turn_aggregates_weighted_scores():
    payload = {
        "scores": {"clarity": 4, "informativeness": 5, "relevance": 5, "coherence": 4, "empathy": 4, "engagement": 4},
        "rationale": {},
        "factual_pass": True,
        "factual_notes": "",
    }
    critic = _FakeCritic(json.dumps(payload))
    out = await judge_turn(critic, _sample(), {"role": "assistant", "content": "Dạ tầm 5 tỷ ạ"}, model="m")
    assert out["factual_pass"] is True
    assert 1.0 <= out["aggregate"] <= 5.0
    assert "tool_correctness" not in out["scores"]
