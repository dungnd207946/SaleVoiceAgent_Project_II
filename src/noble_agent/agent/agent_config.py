"""Structured agent config (identity / scope / style / tools) parsed from the
flat Portal table `tenant_data.agent_config` (one row per tenant, one column per
field). Pure — no I/O. See docs/handoff/agent-config-bang-phang.md."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("noble_agent.agent.agent_config")

CORE_TOOLS: tuple[str, ...] = (
    "update_customer",
    "kb_search",
    "find_project",
    "escalate",
)

# Van xả cho LLM_FORCE_TOOL_FIRST_ROUND (vòng đầu bị ép gọi tool): lượt xã giao
# gọi nó rồi trả lời tự nhiên. CHỈ chào khi cờ bật — cờ tắt (mặc định) thì nó là
# một tool chết chiếm chỗ trong prompt mỗi lượt. Facade truyền cờ vào
# parse_config (path db) và tự append vào tool_names (path legacy).
NO_LOOKUP_TOOL = "no_lookup_needed"

OPTIONAL_TOOLS: tuple[str, ...] = (
    "discover_projects",
    "get_document",
    "search_units",
    "booking",
    "send_media",
    "analyze_projects",
)

# Merge 2026-09-07 (6 → 3 tool dữ liệu cấu trúc): config Portal đã publish /
# manifest bundle cũ còn chở tên trước-merge — map về tool hợp nhất để deploy
# agent không phụ thuộc Portal migrate config cùng lúc. Portal dọn xong config
# thì gỡ bảng này. Lưu ý check_inventory → analyze_projects là một lần NỚI
# capability (tenant chỉ bật inventory nay được cả SQL) — chấp nhận vì an toàn
# nằm ở 3 khoá DB (READ ONLY + role 2-view + RLS), không ở tên tool.
TOOL_ALIASES: dict[str, str] = {
    "recommend_units": "search_units",
    "get_project_overview": "discover_projects",
    "check_inventory": "analyze_projects",
}


def resolve_tool_aliases(names) -> tuple[str, ...]:
    """Map tên tool trước-merge về tool hợp nhất, dedupe giữ thứ tự xuất hiện.
    Log warning mỗi tên cũ để Portal/chủ bundle còn biết mà dọn."""
    out: list[str] = []
    for n in names:
        canon = TOOL_ALIASES.get(n, n)
        if canon != n:
            logger.warning("tool %r đã gộp vào %r (merge 2026-09-07) — dọn config để hết cảnh báo", n, canon)
        if canon not in out:
            out.append(canon)
    return tuple(out)

# Closed vocab → human-readable prompt line (soft guidance).
_TONE_DESC: dict[str, str] = {
    "lich_su": "Lịch sự, giữ khoảng cách.",
    "than_thien": "Thân thiện, gần gũi.",
    "ngan_gon": "Ngắn gọn, đi thẳng vào việc.",
}
_REPLY_LEN_DESC: dict[str, str] = {
    "ngan": "Ưu tiên trả lời ngắn gọn (1–2 câu) khi đã đủ ý.",
    "trung_binh": "Trả lời vừa phải, khoảng 3–4 câu.",
    "chi_tiet": "Trả lời đầy đủ, chi tiết khi cần.",
}
_DEFAULT_TONE = "than_thien"
_DEFAULT_REPLY_LENGTH = "trung_binh"


@dataclass(frozen=True)
class Identity:
    agent_name: str = "Trợ lý"
    brand: str = ""
    honorific_self: str = "em"
    honorific_customer: str = "anh/chị"
    greeting: str = ""


@dataclass(frozen=True)
class Department:
    ten: str
    khi_nao: str = ""


@dataclass(frozen=True)
class Scope:
    does: str = ""
    does_not: str = ""
    refusal: str = ""
    handoff_department: str = "CSKH"
    departments: tuple[Department, ...] = ()


@dataclass(frozen=True)
class Style:
    tone: str = _DEFAULT_TONE
    reply_length: str = _DEFAULT_REPLY_LENGTH


@dataclass(frozen=True)
class AgentConfig:
    identity: Identity
    scope: Scope
    style: Style
    enabled_tools: tuple[str, ...]
    feng_shui: bool
    media_channel: str
    data_source: str
    # Tenant reading dictionary, layered over the platform baseline in
    # data/tts_normalize_vi.json. Tenant wins on a shared key.
    tts_normalization: dict[str, str] = field(default_factory=dict)


def _str(d: dict, key: str, default: str) -> str:
    v = d.get(key)
    return v if isinstance(v, str) and v != "" else default


def _departments(raw_list) -> tuple[Department, ...]:
    out: list[Department] = []
    for d in raw_list or []:
        if not isinstance(d, dict):
            continue
        ten = d.get("ten")
        if isinstance(ten, str) and ten.strip():
            khi = d.get("khi_nao")
            out.append(Department(ten=ten.strip(), khi_nao=khi.strip() if isinstance(khi, str) else ""))
    return tuple(out)


def style_prompt_context(style: Style) -> dict:
    """Jinja context for the persona `style` block — codes + human descriptions."""
    return {
        "tone": style.tone,
        "reply_length": style.reply_length,
        "tone_desc": _TONE_DESC.get(style.tone, ""),
        "reply_length_desc": _REPLY_LEN_DESC.get(style.reply_length, ""),
    }


def _tts_normalization(value) -> dict[str, str]:
    """Object -> {term: read_as}. Any other shape becomes empty.

    The DB column is an OBJECT (CHECK jsonb_typeof = 'object'), unlike departments/skills.
    A list arriving here means the decode path is broken, and dropping it silently beats an
    AttributeError mid-utterance.
    """
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str) and k and v}


def parse_config(raw: dict, *, force_tool_first_round: bool = False) -> AgentConfig:
    """Parse one flat `tenant_data.agent_config` row (column name → value) into an
    AgentConfig. Missing/blank columns fall back to sensible defaults.
    ``force_tool_first_round`` (= settings.llm_force_tool_first_round, truyền từ
    facade để hàm này giữ pure) quyết định có chào van xả no_lookup_needed."""
    raw = raw or {}
    identity = Identity(
        agent_name=_str(raw, "name", "Trợ lý"),
        brand=_str(raw, "brand_name", ""),
        honorific_self=_str(raw, "self_pronoun", "em"),
        honorific_customer=_str(raw, "customer_pronoun", "anh/chị"),
        greeting=raw.get("greeting") if isinstance(raw.get("greeting"), str) else "",
    )
    departments = _departments(raw.get("departments"))
    scope = Scope(
        does=raw.get("scope_does") if isinstance(raw.get("scope_does"), str) else "",
        does_not=raw.get("scope_does_not") if isinstance(raw.get("scope_does_not"), str) else "",
        refusal=raw.get("refusal_line") if isinstance(raw.get("refusal_line"), str) else "",
        handoff_department=departments[0].ten if departments else "CSKH",
        departments=departments,
    )
    style = Style(
        tone=raw["tone"] if raw.get("tone") in _TONE_DESC else _DEFAULT_TONE,
        reply_length=raw["reply_length"] if raw.get("reply_length") in _REPLY_LEN_DESC else _DEFAULT_REPLY_LENGTH,
    )
    requested = set(resolve_tool_aliases(t for t in (raw.get("skills") or []) if isinstance(t, str)))
    optional = tuple(t for t in OPTIONAL_TOOLS if t in requested)  # canonical order, valid only
    # Core always on (escalate never disable-able); van xả cuối nhóm core, trước optional.
    core = CORE_TOOLS + ((NO_LOOKUP_TOOL,) if force_tool_first_round else ())
    enabled_tools = core + optional
    # No feng_shui column yet (deferred): derive it from search_units being enabled.
    feng_shui = "search_units" in enabled_tools
    media_channel = _str(raw, "media_channel", "noblex_app")
    data_source = _str(raw, "data_source", "pg_kb")
    return AgentConfig(
        identity=identity,
        scope=scope,
        style=style,
        enabled_tools=enabled_tools,
        feng_shui=feng_shui,
        media_channel=media_channel,
        data_source=data_source,
        tts_normalization=_tts_normalization(raw.get("tts_normalization")),
    )
