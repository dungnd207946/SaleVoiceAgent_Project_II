"""Load the reference JSONL and enumerate per-assistant-turn samples for teacher forcing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TurnSample:
    conversation_id: str
    turn_idx: int
    step_idx_in_turn: int
    is_first_assistant: bool
    is_final_assistant: bool
    user_message: str
    prefix: list[dict]
    reference_response: dict
    tools: list[dict]

    def dedup_key(self) -> tuple[str, int, int]:
        return (self.conversation_id, self.turn_idx, self.step_idx_in_turn)


def load_eval_file(path: str | Path) -> list[dict]:
    """Read a JSONL file into a list of conversation records."""
    records: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def enumerate_turns(record: dict) -> list[TurnSample]:
    """Yield one TurnSample per assistant message in the conversation record.

    - One TurnSample is emitted per assistant message; ``prefix = messages[:i]``.
    - INVARIANT: ``prefix`` and ``tools`` are READ-ONLY views that share dict/list
      references with the input ``record`` — callers MUST NOT mutate them (mutating a
      prefix message would corrupt the source record and sibling samples).
    - ``turn_idx`` increments on each user message; ``step_idx_in_turn`` resets to 0 on
      each user message and increments per assistant message within that turn.
    - ASSUMPTION: the conversation starts with a system/user message (Luna never
      self-initiates). If an assistant message appears before the first user message it
      is clamped to ``turn_idx=0``, which can collide with the first real turn's
      ``dedup_key``; the synthetic SFT data never does this.
    """
    messages: list[dict] = record.get("messages") or []
    tools: list[dict] = record.get("tools") or []
    cid: str = record.get("conversation_id", "")

    asst_indices = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    if not asst_indices:
        return []
    first_i, last_i = asst_indices[0], asst_indices[-1]

    samples: list[TurnSample] = []
    turn_idx = -1
    step = 0
    last_user = ""
    for i, m in enumerate(messages):
        role = m.get("role")
        if role == "user":
            turn_idx += 1
            step = 0
            last_user = m.get("content") or ""
        elif role == "assistant":
            samples.append(
                TurnSample(
                    conversation_id=cid,
                    turn_idx=max(turn_idx, 0),
                    step_idx_in_turn=step,
                    is_first_assistant=(i == first_i),
                    is_final_assistant=(i == last_i),
                    user_message=last_user,
                    prefix=messages[:i],
                    reference_response=m,
                    tools=tools,
                )
            )
            step += 1
    return samples
