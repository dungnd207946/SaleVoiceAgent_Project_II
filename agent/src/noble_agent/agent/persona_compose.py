"""Compose SOUL/RULES from the on-disk skeleton + AgentConfig: strip disabled
tool regions (pure string), then jinja-render identity/scope placeholders."""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path

import jinja2

from noble_agent.agent.agent_config import OPTIONAL_TOOLS, AgentConfig, style_prompt_context

_MARKER_LINE = re.compile(r"[ \t]*<!-- (?:TOOL:[a-z_]+|FENG_SHUI):(?:START|END) -->[ \t]*\n?")


def _remove_region(text: str, marker: str) -> str:
    pat = re.compile(
        rf"[ \t]*<!-- {re.escape(marker)}:START -->.*?<!-- {re.escape(marker)}:END -->[ \t]*\n?",
        re.DOTALL,
    )
    return pat.sub("", text)


def strip_tool_regions(text: str, enabled_optional: set[str], feng_shui: bool) -> str:
    for name in OPTIONAL_TOOLS:
        if name not in enabled_optional:
            text = _remove_region(text, f"TOOL:{name}")
    if not feng_shui:
        text = _remove_region(text, "FENG_SHUI")
    return _MARKER_LINE.sub("", text)  # drop markers of kept regions


_ENV = jinja2.Environment(loader=jinja2.BaseLoader(), autoescape=False, keep_trailing_newline=True)


def _render(text: str, ctx: dict) -> str:
    return _ENV.from_string(text).render(**ctx)


def compose_persona(skeleton_dir: Path, config: AgentConfig) -> tuple[str, str]:
    enabled_optional = {t for t in config.enabled_tools if t in OPTIONAL_TOOLS}
    ctx = {
        "identity": asdict(config.identity),
        "scope": asdict(config.scope),  # `departments` → list[dict] for jinja iteration
        "style": style_prompt_context(config.style),
    }
    soul = _render(
        strip_tool_regions((skeleton_dir / "SOUL.md").read_text("utf-8"), enabled_optional, config.feng_shui), ctx
    )
    rules = _render(
        strip_tool_regions((skeleton_dir / "RULES.md").read_text("utf-8"), enabled_optional, config.feng_shui), ctx
    )
    return soul, rules
