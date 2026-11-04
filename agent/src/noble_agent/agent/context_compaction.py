"""Dựng danh sách message gửi LLM từ history — history persist KHÔNG đổi.

Hai việc:
1. Kết quả tool của các lượt CŨ (ngoài `keep_user_turns` lượt khách gần nhất) được thay
   bằng DIGEST ngắn (mục đã tra, mã căn + giá đã liệt kê…). Một cuộc gọi bình thường
   mang 20–50k ký tự JSON tool cũ trong context — tốn prefill và pha loãng attention
   (model lấy nhầm giá căn cũ). Digest giữ đúng những định danh cần để tham chiếu lại;
   bản đầy đủ vẫn nằm trong `state.history` cho transcript / eval / summary.
   Giá phải trả: message vừa rơi khỏi cửa sổ đổi nội dung một lần → prefix cache của
   provider vỡ tại điểm đó (≈ 2 lượt cuối), phần system + history xa hơn vẫn hit.
2. Khối ngữ cảnh ephemeral (`session_facts.render`) chèn vào ĐẦU user message cuối —
   hồ sơ mới nhất + fact phiên, không persist, không đụng prefix.

Warm cache (orchestrator) phải dựng qua cùng hàm này với `keep_user_turns` ít hơn 1 —
lượt live kế tiếp có thêm một user message nên cửa sổ verbatim đã trượt một nấc.
"""

from __future__ import annotations

import json
import re

from noble_agent.agent.session_facts import format_unit
from noble_agent.storage.models import ThreadMessage

KEEP_VERBATIM_USER_TURNS = 2
VERBATIM_MAX_CHARS = 300
DIGEST_MAX_CHARS = 380
_KB_HEADER = re.compile(r"^\[([^\]\n]{1,120})\]", re.MULTILINE)
_SUFFIX = " [đã rút gọn]"


def _clip(s: str) -> str:
    return s if len(s) <= DIGEST_MAX_CHARS else s[: DIGEST_MAX_CHARS - len(_SUFFIX) - 1] + "…" + _SUFFIX


def digest_tool_result(name: str, args: dict, content: str) -> str:
    """Bản rút gọn của một kết quả tool đã cũ; kết quả ngắn giữ nguyên văn."""
    content = content or ""
    if len(content) <= VERBATIM_MAX_CHARS:
        return content
    args = args or {}
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        data = None

    if name == "kb_search":
        heads: list[str] = []
        for h in _KB_HEADER.findall(content):
            if h not in heads:
                heads.append(h)
        q = args.get("query", "")
        body = "; ".join(heads[:3]) if heads else content[:150].replace("\n", " ")
        return _clip(f"(đã tra kb_search: '{q}' → {body}){_SUFFIX}")
    if isinstance(data, dict):
        if name == "search_units" and isinstance(data.get("units"), list):
            units = "; ".join(format_unit(u) for u in data["units"][:6] if isinstance(u, dict))
            note = f"; note={data['note']}" if data.get("note") else ""
            return _clip(f"(đã liệt kê căn: {units or 'không có'}{note}){_SUFFIX}")
        if name == "discover_projects":
            if isinstance(data.get("projects"), list):
                names = ", ".join(str(p.get("name") or p.get("code")) for p in data["projects"] if isinstance(p, dict))
                return _clip(f"(đã liệt kê dự án: {names or 'không có'}; tổng {data.get('total', '?')}){_SUFFIX}")
            # Mode chi tiết (nuốt get_project_overview 2026-09-07): dict overview phẳng.
            return _clip(f"(đã đọc tổng quan {data.get('name', '?')} — {data.get('region', '')}){_SUFFIX}")
        if name == "get_document" and isinstance(data.get("documents"), list):
            titles = "; ".join(str(d.get("title")) for d in data["documents"] if isinstance(d, dict))
            return _clip(f"(đã gửi tài liệu: {titles}){_SUFFIX}")
        if name == "send_media":
            return _clip(f"(đã gửi {data.get('count', '?')} media: {data.get('caption', '')}){_SUFFIX}")
    return _clip(content[:250] + " …" + _SUFFIX)


def build_request_messages(
    history: list[ThreadMessage],
    *,
    start: int = 0,
    keep_user_turns: int = KEEP_VERBATIM_USER_TURNS,
    ephemeral: str | None = None,
) -> list[dict]:
    """`history[start:]` → OpenAI message dicts (bản MỚI, không đụng history)."""
    tail = history[start:]
    user_idx = [i for i, m in enumerate(tail) if m.role == "user"]
    boundary = user_idx[-keep_user_turns] if 0 < keep_user_turns <= len(user_idx) else 0
    args_by_id: dict[str, dict] = {}
    out: list[dict] = []
    for i, m in enumerate(tail):
        d = m.to_openai()
        if m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                fn = tc.get("function") or {}
                try:
                    args_by_id[tc.get("id", "")] = json.loads(fn.get("arguments") or "{}")
                except (TypeError, ValueError):
                    args_by_id[tc.get("id", "")] = {}
        elif m.role == "tool" and i < boundary:
            d["content"] = digest_tool_result(m.name or "", args_by_id.get(m.tool_call_id or "", {}), m.content)
        out.append(d)
    if ephemeral and user_idx:
        last = user_idx[-1]
        out[last]["content"] = f"{ephemeral}\n\n{out[last]['content']}"
    return out


def build_warm_messages(history: list[ThreadMessage], *, start: int = 0) -> list[dict]:
    """Bản cho warm cache: khớp prefix của lượt live KẾ TIẾP (cửa sổ verbatim trượt 1)."""
    return build_request_messages(history, start=start, keep_user_turns=max(KEEP_VERBATIM_USER_TURNS - 1, 0))
