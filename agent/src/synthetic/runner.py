"""Drive one CA↔Noble conversation and dump it in eval_sft.json format.

End-to-end shape per conversation:

    {
      "conversation_id": "synth-...",
      "prompt_variant": "general",
      "messages": [
        {"role": "system", "content": <Noble's rendered system prompt>},
        {"role": "user", "content": <CA turn 1>},
        {"role": "assistant", "content": "...", "tool_calls": [...]},   # opt
        {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."},
        {"role": "assistant", "content": <Noble final reply>},
        ...
      ],
      "tools": [<Noble's tool schemas>]
    }

CA only sees Noble's final-text replies — the tool-call internals stay in
Noble's Redis state and only land in the dumped record at the end.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from noble_agent.agent.facade import NobleAgent, _get_runner
from noble_agent.agent.prompts.builder import build_system_prompt
from noble_agent.tenant.current import current_tenant
from synthetic.ca_client import CustomerAgentClient
from synthetic.personas import Persona

logger = logging.getLogger("synthetic.runner")

END_TOKEN = "[END_CALL]"
_END_PAT = re.compile(re.escape(END_TOKEN), re.IGNORECASE)

CA_SYSTEM_PROMPT_TEMPLATE = """Bạn đang đóng vai KHÁCH HÀNG gọi vào hotline Noble. Không phải nhân viên, không phải AI.

# Hồ sơ
- {profile}
- Mục tiêu cuộc gọi: {intent}
- Cách nói: {style}
- Kiểu kết thúc: {ending_hint}

# Bối cảnh
- Vừa bấm gọi hotline Noble Real Estate, nhân viên (Luna) ở đầu dây bên kia.
- Noble có 15 dự án (đa số ở Hà Nội, có cả Hưng Yên và TP.HCM); bạn chỉ biết tên — hỏi nhân viên tra:
  • Long Biên (Hà Nội): Noble Crystal Long Biên, Noble Palace Long Biên, Sunshine Green Iconic
  • Tây Hồ (Hà Nội): Noble Crystal Tây Hồ, Noble Palace Tây Hồ, Sunshine Golden River
  • Bắc Từ Liêm (Hà Nội): Sunshine City Hà Nội
  • Tây Thăng Long / Đan Phượng (Hà Nội): Noble Palace Tây Thăng Long
  • Văn Giang (Hưng Yên): Sunshine Legend City, Alumi (Alluvia City)
  • Quận 7 (TP.HCM): Sunshine Sky City
  • Khác (chưa rõ khu): Noble Crystal Riverside, Sunshine River Park, Sunshine Bay Retreat, Alluvia Sunshine Marina
- KHÔNG dùng mã nội bộ (NCLB/NCTH/SSC...). Gọi tên thường: "Crystal Long Biên", "bên Tây Hồ", "Sky City Quận 7"...

# VĂN PHONG (QUAN TRỌNG NHẤT)
Đây là CUỘC GỌI ĐIỆN THOẠI, không phải email. Khách thật nói RẤT NGẮN.

- Mỗi lượt: 1 câu, thường 4-15 từ. Tối đa 2 câu khi thực sự cần đưa nhiều info.
- Dùng từ đệm tự nhiên: "ờ", "à", "thế", "nhỉ", "ạ", "ấy", "vậy". Câu cụt, không cần đủ chủ-vị.
- TUYỆT ĐỐI tránh giọng văn viết kiểu "Xin chào, tôi muốn được tư vấn về..." — đó là email. Khách thật chỉ buột mồm "alo", "chào em", "ê em ơi", hoặc hỏi thẳng "cho anh hỏi...".
- KHÔNG xã giao thừa ("rất cảm ơn em đã nhiệt tình hỗ trợ", "em vui lòng cho tôi biết thêm...").
- KHÔNG lặp lại / xác nhận lại nguyên văn câu nhân viên vừa nói.
- KHÔNG markdown, bullet, xuống dòng nhiều lần.

# Lượt mở đầu (turn 1)
Chọn 1 trong các kiểu, theo persona — RẤT NGẮN:
- Chỉ chào: "alo em", "chào em", "alo Noble à em?"
- Chào + hỏi thẳng: "chào em, cho anh hỏi bên em còn căn 3PN nào tầm 5 tỷ không"
- Vào thẳng: "alo em ơi cho anh hỏi xíu"
- Ngắt ngứ (driving/elderly...): "alo... ờ, alo em hả"
KHÔNG mở "Xin chào, tôi tên là... tôi muốn được tư vấn...". Sai văn phong.

# Khi nhân viên hỏi info
Trả NGẮN, không cần câu hoàn chỉnh:
- "0912345678 nhé", "Anh Minh", "tầm 3 tỷ thôi", "ở luôn em", "sáng thứ Bảy đi"
- SĐT 10 chữ số / CCCD 12 chữ số: bịa số hợp lý, dùng nhất quán trong cuộc gọi.

# Luật xưng hô và meta
- KHÔNG tự xưng "em" với nhân viên — bạn là khách (xưng anh/chị/tôi/chú/cô theo hồ sơ).
- KHÔNG nhắc "AI", "đóng vai", "đang test", "chatbot" (trừ persona anti-chatbot — họ HỎI nhân viên có phải AI không, không tự nhận).
- KHÔNG bịa data nội bộ Noble (giá cụ thể, mã căn, mã hợp đồng).

# Ngân sách thời lượng
- Tối đa {max_turns} lượt khách. Đây là TRẦN.
- Đạt mục tiêu sớm thì kết thúc NGAY — không kéo dài cho đủ.
- Khoảng lượt thứ {max_turns}-1 → {max_turns}: bắt đầu chốt/chào.
- KHÔNG hỏi trùng, KHÔNG thêm câu xã giao để lấp turn.

# Kết thúc
- Khi đủ thông tin / chốt được lịch / được hứa escalate / chán không muốn tiếp / cáu quá: nói câu chào NGẮN ("ok cảm ơn em", "thế nhé em", "thôi anh cúp đây", "thôi để chị suy nghĩ", "ờ ok"), rồi thêm chuỗi {end_token} ở CUỐI message.
- KHÔNG dùng {end_token} ở lượt 1.
- KHÔNG giải thích {end_token}, không thêm gì sau nó.

Trả lời thẳng câu thoại tiếp theo. Không prefix, không xuống dòng kiểu kịch bản.
"""


def _build_ca_system(persona: Persona, max_turns: int) -> str:
    return CA_SYSTEM_PROMPT_TEMPLATE.format(
        profile=persona.profile,
        intent=persona.intent,
        style=persona.style,
        ending_hint=persona.ending_hint,
        end_token=END_TOKEN,
        max_turns=max_turns,
    )


def _strip_end_token(text: str) -> tuple[str, bool]:
    """Return (cleaned_text, ended) — strips END_CALL marker if present."""
    if _END_PAT.search(text):
        cleaned = _END_PAT.sub("", text).strip()
        return cleaned, True
    return text.strip(), False


async def run_conversation(
    *,
    persona: Persona,
    ca: CustomerAgentClient,
    max_turns: int,
) -> dict[str, Any]:
    """Run one CA↔Noble conversation. Returns the eval_sft.json-shaped dict."""
    session_id = f"synth-{uuid.uuid4().hex[:10]}"
    runner = await _get_runner(current_tenant(), "chat")
    agent = NobleAgent(session_id=session_id, runner=runner, channel="chat")
    await agent.reset()  # guarantee clean Redis state

    ca_messages: list[dict] = [
        {"role": "system", "content": _build_ca_system(persona, max_turns)},
        {
            "role": "user",
            "content": (
                "(Vừa kết nối — nhân viên Noble nhấc máy nhưng chưa nói. "
                "Bạn nói câu mở đầu, kiểu điện thoại đời thực: NGẮN (4-15 từ), "
                "hoặc chỉ chào, hoặc chào + hỏi thẳng. Không dùng END_CALL.)"
            ),
        },
    ]

    ended_naturally = False
    turns_done = 0

    for turn_idx in range(max_turns):
        try:
            ca_raw = await ca.complete(ca_messages)
        except Exception:
            logger.exception("CA completion failed at turn %d", turn_idx)
            break

        if not ca_raw.strip():
            logger.warning("CA returned empty at turn %d — stopping", turn_idx)
            break

        user_text, is_end = _strip_end_token(ca_raw)
        # Forbid END on the very first turn — re-ask if model jumped the gun.
        if is_end and turn_idx == 0:
            is_end = False  # ignore the marker; keep the text portion

        # Save CA's own line into CA history (raw, including END marker so the
        # next CA turn understands it already committed to ending).
        ca_messages.append({"role": "assistant", "content": ca_raw})

        if not user_text:
            # CA emitted nothing but the END token → close immediately.
            ended_naturally = True
            break

        try:
            noble_reply = await agent.stream_response(user_text=user_text)
        except Exception:
            logger.exception("Noble Agent failed at turn %d", turn_idx)
            break

        turns_done += 1

        # Feed Noble's spoken reply back to CA as the "other party" message.
        # CA never sees the tool internals — only the final text.
        noble_reply = (noble_reply or "").strip()
        if not noble_reply:
            noble_reply = "(im lặng)"
        ca_messages.append({"role": "user", "content": noble_reply})

        if is_end:
            ended_naturally = True
            break

    # Pull the full Noble-side thread (system + history with tool calls + results).
    meta, customer, state = await runner._repo.load(session_id)
    system_prompt = build_system_prompt(runner._agent, customer, state.summary)

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for m in state.history:
        messages.append(m.to_openai())

    return {
        "conversation_id": session_id,
        "prompt_variant": "general",
        "messages": messages,
        "tools": runner._agent.tool_schemas,
        "persona": persona.label,
        "ended_naturally": ended_naturally,
        "turns": turns_done,
    }
