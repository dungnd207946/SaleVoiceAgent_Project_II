"""AgentDef — frozen single-agent definition loaded from `definitions/`."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import jinja2

# Delivery channels a persona can be specialized for. The shared skeleton
# (src/noble_agent/persona/) ships one subfolder per channel; legacy tenant
# bundles stay flat and serve both channels from the same files.
PERSONA_CHANNELS = ("chat", "voice")


def resolve_persona_dir(base: Path | str, channel: str) -> Path:
    """Persona dir for `channel`: `base/<channel>` when that subdir exists
    (channel-split skeleton), else `base` itself (flat legacy bundle)."""
    if channel not in PERSONA_CHANNELS:
        raise ValueError(f"unknown persona channel {channel!r}, expected one of {PERSONA_CHANNELS}")
    sub = Path(base) / channel
    return sub if (sub / "SOUL.md").is_file() else Path(base)


@dataclass(frozen=True)
class AgentDef:
    name: str
    model: str
    temperature: float
    max_tokens: int
    prompt_template: jinja2.Template
    sections: dict[str, str]  # keys: soul, rules, customer_format
    tool_names: list[str]
    tool_schemas: list[dict]
    # Transport-level identity (voice opening line): spoken brand + the
    # tenant-configured greeting ("" = transport falls back to its default).
    brand: str = ""
    greeting: str = ""
    # Bộ phận tiếp nhận mặc định khi chuyển người thật (config.scope.handoff_department
    # ở DB path). Dispatcher dùng cho auto-escalate và khi LLM bỏ trống `department`.
    # "CVTV" = giá trị lịch sử của tenant noble, giữ cho bundle legacy.
    handoff_department: str = "CVTV"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_agent_def(
    persona_dir: Path | str,
    *,
    tool_names: list[str],
    agent_name: str | None = None,
    brand: dict | None = None,
) -> AgentDef:
    from noble_agent.agent.tools.schemas import build_schemas

    d = Path(persona_dir)
    config = json.loads(_read(d / "config.json"))
    name = agent_name or config["name"]

    env = jinja2.Environment(
        loader=jinja2.BaseLoader(),
        autoescape=False,
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    template_src = _read(d / "PROMPT_TEMPLATE.md")
    tmpl = env.from_string(template_src)

    # SOUL.md / RULES.md carry the agent's display name as `{{ agent_name }}`.
    # Render them once here (name is fixed per process) so builder.py needs no
    # further substitution.
    _brand = brand or {"company": "Noble", "app_name": "NobleX"}
    soul = env.from_string(_read(d / "SOUL.md")).render(agent_name=name, brand=_brand)
    rules = env.from_string(_read(d / "RULES.md")).render(agent_name=name, brand=_brand)
    sections = {
        "soul": soul,
        "rules": rules,
        "customer_format": _read(d / "CUSTOMER_PROFILE.md"),
    }

    tool_names = list(tool_names)
    tool_schemas = build_schemas(tool_names)

    return AgentDef(
        name=name,
        model=config["model"],
        temperature=float(config["temperature"]),
        max_tokens=int(config["max_tokens"]),
        prompt_template=tmpl,
        sections=sections,
        tool_names=tool_names,
        tool_schemas=tool_schemas,
        # Legacy bundles speak the app brand (the old fixed greeting said
        # "bên NobleX"); no per-tenant greeting column on this path.
        brand=_brand.get("app_name") or _brand.get("company") or "",
    )


def build_agent_def_from_config(
    skeleton_dir: Path | str,
    config,  # noble_agent.agent.agent_config.AgentConfig
    *,
    model: str,
    temperature: float,
    max_tokens: int,
) -> AgentDef:
    """Build an AgentDef from the shared on-disk skeleton + a parsed AgentConfig
    (DB path). Marker-strips + renders SOUL/RULES, offers config.enabled_tools,
    renders brand from config.identity.brand, gates feng-shui by config.feng_shui."""
    from noble_agent.agent.persona_compose import compose_persona
    from noble_agent.agent.tools.schemas import build_schemas

    d = Path(skeleton_dir)
    env = jinja2.Environment(loader=jinja2.BaseLoader(), autoescape=False, keep_trailing_newline=True)
    tmpl = env.from_string(_read(d / "PROMPT_TEMPLATE.md"))
    soul, rules = compose_persona(d, config)
    sections = {"soul": soul, "rules": rules, "customer_format": _read(d / "CUSTOMER_PROFILE.md")}

    brand = {"company": config.identity.brand, "app_name": config.identity.brand}
    rankers = frozenset({"feng_shui"}) if config.feng_shui else frozenset()
    tool_names = list(config.enabled_tools)
    tool_schemas = build_schemas(tool_names, brand=brand, rankers=rankers)

    return AgentDef(
        name=config.identity.agent_name,
        model=model,
        temperature=float(temperature),
        max_tokens=int(max_tokens),
        prompt_template=tmpl,
        sections=sections,
        tool_names=tool_names,
        tool_schemas=tool_schemas,
        brand=config.identity.brand,
        greeting=config.identity.greeting,
        handoff_department=config.scope.handoff_department,
    )
