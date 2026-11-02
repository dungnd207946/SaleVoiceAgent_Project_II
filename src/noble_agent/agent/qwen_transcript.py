"""Render conversation threads in Qwen3-Instruct-2507 ChatML format and dump to disk.

The output mirrors what `tokenizer.apply_chat_template(..., tools=...)` produces
for Qwen/Qwen3-4B-Instruct-2507, so the files are directly usable as SFT
training samples. The unified agent has a single flat history thread per
session, emitted as one Qwen block.

Public API:
    render_qwen_transcript(system_prompt, tools, messages) -> str
    TranscriptWriter(base_dir, agent).write_session(...)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from noble_agent.agent.base import AgentDef
from noble_agent.agent.prompts.builder import build_system_prompt
from noble_agent.agent.tools import analytics_vocab
from noble_agent.storage.models import Customer, State, ThreadMessage

logger = logging.getLogger("noble_agent.qwen_transcript")

_TOOLS_HEADER = (
    "# Tools\n"
    "\n"
    "You may call one or more functions to assist with the user query.\n"
    "\n"
    "You are provided with function signatures within <tools></tools> XML tags:\n"
    "<tools>"
)
_TOOLS_FOOTER = (
    "</tools>\n"
    "\n"
    "For each function call, return a json object with function name and arguments "
    "within <tool_call></tool_call> XML tags:\n"
    "<tool_call>\n"
    '{"name": <function-name>, "arguments": <args-json-object>}\n'
    "</tool_call>"
)


def _render_tools_block(tools: list[dict]) -> str:
    body = "\n".join(json.dumps(t, ensure_ascii=False) for t in tools)
    return f"{_TOOLS_HEADER}\n{body}\n{_TOOLS_FOOTER}"


def _render_tool_call(tc: dict[str, Any]) -> str:
    func = tc.get("function") if isinstance(tc.get("function"), dict) else tc
    name = func.get("name", "")
    args = func.get("arguments", "")
    args_str = (args if args.strip() else "{}") if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
    return f'<tool_call>\n{{"name": "{name}", "arguments": {args_str}}}\n</tool_call>'


def _render_assistant(msg: ThreadMessage) -> str:
    content = msg.content or ""
    body = f"<|im_start|>assistant\n{content}"
    if msg.tool_calls:
        for idx, tc in enumerate(msg.tool_calls):
            need_sep = (idx == 0 and content) or idx > 0
            body += ("\n" if need_sep else "") + _render_tool_call(tc)
    body += "<|im_end|>"
    return body


def _render_tool_run(messages: list[ThreadMessage], start: int) -> tuple[str, int]:
    """Bundle consecutive tool messages into a single user/tool_response block."""
    body = "<|im_start|>user"
    i = start
    while i < len(messages) and messages[i].role == "tool":
        body += f"\n<tool_response>\n{messages[i].content}\n</tool_response>"
        i += 1
    body += "<|im_end|>"
    return body, i


def render_qwen_transcript(
    *,
    system_prompt: str,
    tools: list[dict],
    messages: list[ThreadMessage],
) -> str:
    """Serialize the single-agent thread to a Qwen3-Instruct-2507 ChatML string."""
    parts: list[str] = []

    sys_body = f"{system_prompt}\n\n{_render_tools_block(tools)}" if tools else system_prompt
    parts.append(f"<|im_start|>system\n{sys_body}<|im_end|>")

    i = 0
    while i < len(messages):
        m = messages[i]
        if m.role == "user":
            parts.append(f"<|im_start|>user\n{m.content}<|im_end|>")
            i += 1
        elif m.role == "assistant":
            parts.append(_render_assistant(m))
            i += 1
        elif m.role == "tool":
            block, i = _render_tool_run(messages, i)
            parts.append(block)
        else:
            i += 1

    return "\n".join(parts) + "\n"


class TranscriptWriter:
    """Write per-session Qwen-format transcripts after each user turn.

    Each session yields a single file: <base_dir>/<session_id>.txt containing
    one Qwen ChatML block for the unified agent's flat history.
    """

    def __init__(self, base_dir: str | Path, agent: AgentDef):
        self._base = Path(base_dir)
        self._agent = agent
        self._paths: dict[str, Path] = {}

    def _resolve_path(self, session_id: str) -> Path:
        cached = self._paths.get(session_id)
        if cached is not None:
            return cached
        if self._base.exists():
            existing = sorted(self._base.glob(f"*_{session_id}.txt"))
            if existing:
                self._paths[session_id] = existing[0]
                return existing[0]
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = self._base / f"{ts}_{session_id}.txt"
        self._paths[session_id] = out
        return out

    def write_session(
        self,
        *,
        session_id: str,
        customer: Customer,
        state: State,
    ) -> Path | None:
        try:
            if not state.history:
                return None
            self._base.mkdir(parents=True, exist_ok=True)
            system_prompt = build_system_prompt(self._agent, customer, state.summary)
            qwen_text = render_qwen_transcript(
                system_prompt=system_prompt,
                tools=analytics_vocab.inject(self._agent.tool_schemas),
                messages=state.history,
            )
            out = self._resolve_path(session_id)
            out.write_text(qwen_text, encoding="utf-8")
            return out
        except Exception:
            logger.exception("qwen_transcript: write failed for session=%s", session_id)
            return None

    async def write_session_async(
        self,
        *,
        session_id: str,
        customer: Customer,
        state: State,
    ) -> Path | None:
        return await asyncio.to_thread(
            self.write_session,
            session_id=session_id,
            customer=customer,
            state=state,
        )
