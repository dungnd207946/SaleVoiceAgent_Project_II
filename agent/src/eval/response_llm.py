"""LLM-as-judge for one turn. Critic reuses the .env Anthropic provider by default."""

from __future__ import annotations

import json
import re
from pathlib import Path

from eval.data import TurnSample

_PROMPT_PATH = Path(__file__).parent / "prompts" / "critic_multiturn_luna.txt"

# (id, description, weight). tool_correctness intentionally excluded — covered by rule-based metrics.
CRITERIA = [
    {"id": "clarity", "desc": "Câu trả lời rõ ràng, dễ hiểu", "weight": 1.0},
    {"id": "informativeness", "desc": "Cung cấp đủ thông tin user cần", "weight": 1.5},
    {"id": "relevance", "desc": "Đúng trọng tâm câu hỏi", "weight": 1.5},
    {"id": "coherence", "desc": "Mạch lạc với lịch sử hội thoại", "weight": 1.0},
    {"id": "empathy", "desc": "Thái độ lịch sự, đồng cảm", "weight": 1.0},
    {"id": "engagement", "desc": "Dẫn dắt cuộc gọi tự nhiên", "weight": 1.0},
]
_FACTUAL = {"id": "factual_pass", "desc": "Không bịa fact, không mâu thuẫn kết quả tool trong history"}


def _format_response(msg: dict) -> str:
    content = msg.get("content") or ""
    calls = msg.get("tool_calls") or []
    if not calls:
        return content or "(không có nội dung)"
    names = ", ".join((c.get("function") or {}).get("name", "") for c in calls)
    return f"{content}\n[tool_calls: {names}]"


def _format_history(prefix: list[dict]) -> str:
    lines = []
    for m in prefix:
        role = m.get("role")
        if role == "system":
            continue
        lines.append(f"[{role}] {_format_response(m) if role == 'assistant' else (m.get('content') or '')}")
    return "\n".join(lines) if lines else "(trống)"


def build_prompt(sample: TurnSample, predicted_msg: dict) -> str:
    criteria_list = "\n".join(f"- `{c['id']}`: {c['desc']} (1-5)" for c in CRITERIA)
    factual_axis = f"- `{_FACTUAL['id']}`: {_FACTUAL['desc']}"
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(
        criteria_list=criteria_list,
        factual_axis=factual_axis,
        history_block=_format_history(sample.prefix),
        user_message=sample.user_message,
        reference_response=_format_response(sample.reference_response),
        predicted_response=_format_response(predicted_msg),
    )


def parse_judge_json(raw: str) -> dict:
    """Defensive parse: strip ``` fences, then take the first {...} block."""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


async def judge_turn(critic, sample: TurnSample, predicted_msg: dict, *, model: str) -> dict:
    prompt = build_prompt(sample, predicted_msg)
    resp = await critic.chat.completions.create(
        model=model,
        temperature=0.2,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    payload = parse_judge_json(resp.choices[0].message.content)
    scores = {k: int(v) for k, v in (payload.get("scores") or {}).items() if k != "tool_correctness"}
    weights = {c["id"]: c["weight"] for c in CRITERIA}
    total = sum(scores.get(cid, 0) * w for cid, w in weights.items())
    wsum = sum(w for cid, w in weights.items() if cid in scores)
    return {
        "scores": scores,
        "rationale": payload.get("rationale", {}),
        "factual_pass": bool(payload.get("factual_pass", False)),
        "factual_notes": payload.get("factual_notes", ""),
        "aggregate": (total / wsum) if wsum else 0.0,
    }


def build_critic():
    """Resolve (critic_client, model). EVAL_CRITIC_* wins; else the .env Anthropic provider."""
    from eval.config import EvalSettings
    from noble_agent.agent.facade import build_llm_providers
    from noble_agent.config import get_settings, provider_model_map

    cfg = EvalSettings()
    if cfg.critic_model:
        import openai

        kwargs = {"api_key": cfg.critic_api_key or "EMPTY"}
        if cfg.critic_base_url:
            kwargs["base_url"] = cfg.critic_base_url
        return openai.AsyncOpenAI(**kwargs), cfg.critic_model

    settings = get_settings()
    providers = build_llm_providers()
    for name, prov in providers:
        if name == "anthropic":
            return prov, settings.anthropic_model
    name, prov = providers[0]
    return prov, provider_model_map(settings)[name]
