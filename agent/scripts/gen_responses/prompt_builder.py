"""
Prompt builder for NobleX voice agent response generation.

Reads SOUL.md, IDENTITY.md, SKILL.md, RULES.md from the agent definitions
and assembles a complete prompt for the AI API.
"""
from __future__ import annotations

import os
from pathlib import Path

from scenarios import Scenario

# Base path to agent definitions
_BASE = Path(__file__).resolve().parent.parent.parent / "src" / "noble_agent" / "agent" / "definitions"
_AGENTS_DIR = _BASE / "agents"
_SHARED_DIR = _BASE / "shared"

# Skill name → agent mapping for directory lookup
_SKILL_TO_AGENT = {
    "noble-router": "router",
    "consultant-info": "consultant",
    "consultant-pricing": "consultant",
    "consultant-advisor": "consultant",
    "consultant-booking": "consultant",
    "support-crm": "support",
    "support-escalation": "support",
}


def _read_file(path: Path) -> str:
    """Read file content, return empty string if not found."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _load_shared_files() -> str:
    """Load RULES.md and PROJECTS.md from shared/."""
    rules = _read_file(_SHARED_DIR / "RULES.md")
    projects = _read_file(_SHARED_DIR / "PROJECTS.md")
    parts = []
    if rules:
        parts.append(f"═══ RULES.md ═══\n{rules}")
    if projects:
        parts.append(f"═══ PROJECTS.md ═══\n{projects}")
    return "\n\n".join(parts)


def _load_agent_files(agent: str) -> str:
    """Load SOUL.md and IDENTITY.md for the given agent."""
    agent_dir = _AGENTS_DIR / agent
    soul = _read_file(agent_dir / "SOUL.md")
    identity = _read_file(agent_dir / "IDENTITY.md")
    parts = []
    if identity:
        parts.append(f"═══ IDENTITY.md ═══\n{identity}")
    if soul:
        parts.append(f"═══ SOUL.md ═══\n{soul}")
    return "\n\n".join(parts)


def _load_skill_file(skill: str) -> str:
    """Load SKILL.md for the given skill name."""
    agent = _SKILL_TO_AGENT.get(skill, "")
    if not agent:
        return ""
    skill_path = _AGENTS_DIR / agent / "skills" / skill / "SKILL.md"
    content = _read_file(skill_path)
    if content:
        return f"═══ SKILL.md ({skill}) ═══\n{content}"
    return ""


def _format_customer_context(ctx: dict) -> str:
    """Format customer context for the prompt."""
    if not ctx:
        return "Chưa có thông tin khách hàng."
    lines = []
    mapping = {
        "name": "Tên",
        "full_name": "Họ tên đầy đủ",
        "gender": "Giới tính",
        "phone": "SĐT",
        "project_interest": "Dự án quan tâm",
        "purpose": "Mục đích",
        "budget": "Ngân sách",
        "preferred_area": "Khu vực",
        "bedroom_count": "Số phòng ngủ",
    }
    for key, label in mapping.items():
        if key in ctx and ctx[key]:
            val = ctx[key]
            if key == "gender":
                val = "Nam" if val == "M" else "Nữ"
            lines.append(f"- {label}: {val}")
    return "\n".join(lines) if lines else "Chưa có thông tin khách hàng."


def _format_tool_results(tool_calls: list[dict]) -> str:
    """Format tool call results for the prompt."""
    if not tool_calls:
        return "(Không có tool nào được gọi cho scenario này)"
    parts = []
    for i, tc in enumerate(tool_calls, 1):
        name = tc["name"]
        args = tc.get("args", {})
        output = tc.get("output", "{}")
        parts.append(
            f"[Tool {i}] {name}({args})\n"
            f"→ Kết quả:\n{output}"
        )
    return "\n\n".join(parts)


def build_prompt(scenario: Scenario, variation_idx: int = 0) -> tuple[str, str]:
    """
    Build a (system_prompt, user_message) tuple for the given scenario.

    Returns:
        (system_prompt, user_message) — ready to send to AI API.
    """
    # 1. System prompt = shared files + agent identity + skill
    shared = _load_shared_files()
    agent_files = _load_agent_files(scenario.agent)
    skill_file = _load_skill_file(scenario.skill)

    system_parts = [
        "Bạn đang gen câu trả lời MẪU cho hệ thống voice agent NobleX.",
        "Hãy trả lời ĐÚNG NHƯ CÁCH bạn sẽ nói khi trực tiếp tư vấn khách hàng qua điện thoại.",
        "",
        "═══ QUY TẮC TUYỆT ĐỐI ═══",
        "1. Trả lời bằng VĂN NÓI tiếng Việt tự nhiên — KHÔNG markdown, KHÔNG bullet, KHÔNG numbering, KHÔNG emoji",
        "2. Viết SỐ BẰNG CHỮ: 8 tỷ → tám tỷ, 70m² → bảy mươi mét vuông, 30% → ba mươi phần trăm",
        "3. Mọi câu bắt đầu bằng 'Dạ' và kết thúc bằng 'ạ'",
        "4. Xưng 'em', gọi khách theo thông tin bên dưới",
        "5. KHÔNG bịa đặt — chỉ dùng dữ liệu từ tool results bên dưới",
        "6. Kết thúc bằng Bridge Response (câu gợi mở tiếp theo)",
        "7. CHỈ output text thuần — KHÔNG output tool calls hay JSON",
        "",
        shared,
        "",
        agent_files,
        "",
        skill_file,
    ]

    system_prompt = "\n".join(system_parts)

    # 2. User message = context + tool results + customer query
    ctx_text = _format_customer_context(scenario.customer_context)
    tool_text = _format_tool_results(scenario.tool_calls)

    variation_note = ""
    if variation_idx > 0:
        variation_note = (
            f"\n[BIẾN THỂ #{variation_idx + 1}]: Hãy diễn đạt KHÁC với lần trước, "
            "giữ nguyên thông tin chính nhưng đổi cách nói, cấu trúc câu."
        )

    extra_notes = ""
    if scenario.notes:
        extra_notes = f"\n[GHI CHÚ]: {scenario.notes}"

    user_message = (
        f"═══ THÔNG TIN KHÁCH HÀNG ═══\n{ctx_text}\n\n"
        f"═══ KẾT QUẢ TOOLS (đã gọi xong) ═══\n{tool_text}\n\n"
        f"═══ CÂU HỎI KHÁCH HÀNG ═══\n{scenario.customer_query}\n"
        f"{extra_notes}"
        f"{variation_note}\n\n"
        f"Hãy trả lời khách hàng bằng văn nói tự nhiên (2-4 câu, tối đa 6 câu cho nội dung phức tạp). "
        f"CHỈ output text trả lời, không có gì khác."
    )

    return system_prompt, user_message


def build_prompt_text(scenario: Scenario, variation_idx: int = 0) -> str:
    """Build a single combined prompt (for debugging/preview)."""
    system, user = build_prompt(scenario, variation_idx)
    return f"=== SYSTEM ===\n{system}\n\n=== USER ===\n{user}"
