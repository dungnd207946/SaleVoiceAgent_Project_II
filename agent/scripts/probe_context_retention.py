"""Probe GIỮ NGỮ CẢNH đa lượt bằng LLM thật, không cần tenant config / Redis.

Một hội thoại 6 lượt cố định (tool result giả: kb_search, search_units 3 căn, get_document,
booking) rồi hỏi 3 câu "nhớ" (tên + ngân sách; 3 mã căn; ngày giờ + mã lịch + tài liệu).
Bốn biến thể cách dựng request: CŨ (history nguyên văn, không khối ngữ cảnh) / MỚI
(`build_request_messages`: digest tool cũ + `[Ngữ cảnh hiện tại]`) × trước / sau summary
(sau = chỉ còn summary + 2 lượt cuối; summary sinh bằng `build_summary_prompt` hiện hành).
Mỗi câu chạy tới 3 vòng (cấp tool result giả nếu model gọi tool) rồi chấm tỷ lệ fact xuất
hiện trong câu trả lời (so khớp có chuẩn hoá: 3,5 ~ 3.5, 30/08 ~ 30/8).

Usage: PYTHONPATH=src python scripts/probe_context_retention.py <primary_model> <out.json> [runs]
"""

import asyncio
import json
import re
import sys
from pathlib import Path

import noble_agent
from noble_agent.agent import session_facts
from noble_agent.agent.agent_config import OPTIONAL_TOOLS, parse_config
from noble_agent.agent.base import build_agent_def_from_config
from noble_agent.agent.context_compaction import build_request_messages
from noble_agent.agent.facade import build_llm_providers
from noble_agent.agent.llm.client import StreamingClient
from noble_agent.agent.prompts.builder import build_system_prompt
from noble_agent.agent.summary.summarizer import build_summary_prompt
from noble_agent.config import get_settings, primary_for, provider_model_map
from noble_agent.storage.models import Customer, State, ThreadMessage, ThreadSummary

_NORM = {
    "3,5": r"3[.,]5\s*tỷ|3 tỷ (5|rưỡi)|3,5|3\.5",
    "30/08": r"30/0?8",
    "Chính sách bán hàng": r"chính sách bán hàng|csbh",
}

primary_model, out_path = sys.argv[1], sys.argv[2]
RUNS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
SKEL = Path(noble_agent.__file__).resolve().parent / "persona" / "chat"
cfg = parse_config(
    {
        "name": "Luna",
        "brand_name": "Noble",
        "scope_does": "tư vấn dự án, đặt lịch tham quan",
        "scope_does_not": "hợp đồng, thanh toán",
        "departments": [{"ten": "CVTV", "khi_nao": "cần báo giá"}],
        "skills": list(OPTIONAL_TOOLS),
    }
)
agent = build_agent_def_from_config(SKEL, cfg, model="x", temperature=0.4, max_tokens=400)
tools = [json.loads(json.dumps(t).replace("[VOCAB]", "")) for t in agent.tool_schemas]


def tc(cid, name, args):
    return {
        "id": cid,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


KB = (
    "[Noble Crystal › Giá bán]\nGiá từ 90 triệu/m², căn 2PN từ 3,2 tỷ, 3PN từ 4,5 tỷ. "
    + "Chi tiết bảng giá theo tầng. " * 40
    + "\n---\n[Noble Crystal › Chính sách bán hàng]\nVay tối đa 70%, ân hạn nợ gốc 24 tháng, lãi ưu đãi 0% 18 tháng. "
    + "Điều kiện áp dụng. " * 40
)
UNITS = json.dumps(
    {
        "units": [
            {
                "unit_code": "A-1203",
                "product_type": "chung_cu",
                "bedrooms": 2,
                "area_built_m2": 72.5,
                "direction": "dong_nam",
                "price_vnd": 3200000000,
                "price_per_m2_vnd": 44000000,
                "project_code": "NCR",
                "project_name": "Noble Crystal",
            },
            {
                "unit_code": "B-0805",
                "product_type": "chung_cu",
                "bedrooms": 2,
                "area_built_m2": 75.0,
                "direction": "tay",
                "price_vnd": 3450000000,
                "price_per_m2_vnd": 46000000,
                "project_code": "NCR",
                "project_name": "Noble Crystal",
            },
            {
                "unit_code": "C-1501",
                "product_type": "chung_cu",
                "bedrooms": 2,
                "area_built_m2": 70.2,
                "direction": "dong",
                "price_vnd": 3100000000,
                "price_per_m2_vnd": 44100000,
                "project_code": "NCR",
                "project_name": "Noble Crystal",
            },
        ],
        "counts": {"total": 3},
        "criteria": {"bedrooms": 2},
        "instruction": "Giới thiệu 2-3 căn nổi bật (dự án + hướng + giá), dẫn dắt khách.",
    },
    ensure_ascii=False,
)
DOC = json.dumps(
    {
        "count": 1,
        "documents": [
            {
                "title": "Chính sách bán hàng Noble Crystal T8/2026",
                "body": "Nội dung CSBH " * 60,
                "file_url": "https://files.example/csbh-ncr.pdf",
            }
        ],
    },
    ensure_ascii=False,
)
BOOK = json.dumps(
    {
        "ok": True,
        "success": True,
        "appointment_id": "APT48213",
        "project": "NCR",
        "preferred_date": "30/08/2026",
        "preferred_time": "09:00 - 10:00",
        "notes": "",
        "message": "Đặt lịch thành công.",
    },
    ensure_ascii=False,
)


def make_history():
    return [
        ThreadMessage(
            role="user", content="Chào em, anh tên Hùng, anh muốn tìm căn 2 ngủ tầm 3 tỷ rưỡi ở Noble Crystal"
        ),
        ThreadMessage(
            role="assistant",
            content="",
            tool_calls=[
                tc(
                    "c1",
                    "update_customer",
                    {"name": "Hùng", "budget": "3,5 tỷ", "bedroom_count": "2PN", "project_interest": "NCR"},
                ),
                tc("c2", "kb_search", {"query": "giá bán căn 2 phòng ngủ Noble Crystal", "project_filter": "NCR"}),
            ],
        ),
        ThreadMessage(
            role="tool",
            tool_call_id="c1",
            name="update_customer",
            content=json.dumps({"ok": True, "updated_fields": ["name", "budget", "bedroom_count", "project_interest"]}),
        ),
        ThreadMessage(role="tool", tool_call_id="c2", name="kb_search", content=KB),
        ThreadMessage(
            role="assistant",
            content=(
                "Chào anh Hùng. Noble Crystal căn 2 ngủ giá từ 3,2 tỷ, vay được 70% với ân hạn "
                "gốc 24 tháng. Anh muốn em tìm luôn vài căn cụ thể không?"
            ),
        ),
        ThreadMessage(role="user", content="Ừ tìm đi em"),
        ThreadMessage(
            role="assistant",
            content="",
            tool_calls=[tc("c3", "search_units", {"project_code": "NCR", "bedrooms": 2, "max_price": 3500000000})],
        ),
        ThreadMessage(role="tool", tool_call_id="c3", name="search_units", content=UNITS),
        ThreadMessage(
            role="assistant",
            content=(
                "Có ba căn hợp tầm anh: A-1203 hướng Đông Nam 3,2 tỷ, C-1501 hướng Đông 3,1 tỷ và "
                "B-0805 hướng Tây 3,45 tỷ. Căn A-1203 hợp anh nhất vì hướng mát mà giá vừa. Anh "
                "muốn em nói kỹ căn này không?"
            ),
        ),
        ThreadMessage(role="user", content="Gửi anh chính sách bán hàng trước đã"),
        ThreadMessage(
            role="assistant",
            content="",
            tool_calls=[tc("c4", "get_document", {"project_code": "NCR", "query": "CSBH"})],
        ),
        ThreadMessage(role="tool", tool_call_id="c4", name="get_document", content=DOC),
        ThreadMessage(
            role="assistant",
            content=(
                "Em gửi anh Chính sách bán hàng Noble Crystal tháng 8 rồi. Anh xem xong mình đặt "
                "lịch đi xem căn A-1203 nhé?"
            ),
        ),
        ThreadMessage(role="user", content="Ok đặt lịch sáng thứ bảy này đi, dùng tên với số này luôn"),
        ThreadMessage(
            role="assistant",
            content="",
            tool_calls=[
                tc(
                    "c5",
                    "booking",
                    {
                        "action": "schedule",
                        "project_code": "NCR",
                        "preferred_date": "30/08/2026",
                        "preferred_time": "09:00 - 10:00",
                        "use_profile_name": True,
                        "use_calling_phone": True,
                        "confirmed": True,
                    },
                )
            ],
        ),
        ThreadMessage(role="tool", tool_call_id="c5", name="booking", content=BOOK),
        ThreadMessage(
            role="assistant",
            content=(
                "Xong rồi anh Hùng, lịch xem căn sáng thứ bảy 30/08 lúc 9 giờ, mã APT48213. Có gì thay đổi anh nhắn em."
            ),
        ),
        ThreadMessage(role="user", content="Ok cảm ơn em"),
        ThreadMessage(role="assistant", content="Dạ, hẹn gặp anh thứ bảy."),
        ThreadMessage(role="user", content="À mà tiện ích của dự án có gì?"),
        ThreadMessage(
            role="assistant",
            content="",
            tool_calls=[tc("c6", "kb_search", {"query": "tiện ích nội khu Noble Crystal", "project_filter": "NCR"})],
        ),
        ThreadMessage(
            role="tool",
            tool_call_id="c6",
            name="kb_search",
            content="[Noble Crystal › Tiện ích]\nBể bơi vô cực tầng 5, gym, trường mầm non nội khu, công viên 2ha. "
            + "Chi tiết tiện ích. " * 40,
        ),
        ThreadMessage(
            role="assistant",
            content=(
                "Dự án có bể bơi vô cực, gym, trường mầm non nội khu và công viên 2 hecta. Anh có "
                "con nhỏ không, để em xem thêm phần trường?"
            ),
        ),
    ]


QUESTIONS = [
    (
        "name_budget",
        "Ơ anh quên mất, anh nói với em ngân sách bao nhiêu nhỉ? Với lại em nhớ tên anh không?",
        ["Hùng", "3,5"],
    ),
    ("units", "Ba căn lúc nãy em kể là những căn nào ấy nhỉ, đọc lại mã căn cho anh?", ["A-1203", "B-0805", "C-1501"]),
    (
        "booking_doc",
        "Anh đặt lịch ngày nào giờ nào rồi ấy nhỉ, mã lịch là gì? Em gửi anh tài liệu gì rồi?",
        ["30/08", "APT48213", "Chính sách bán hàng"],
    ),
]


def customer_after():
    return Customer(
        name="Hùng", gender="M", phone="0912345678", project_interest="NCR", budget="3,5 tỷ", bedroom_count="2PN"
    )


def facts_state(history):
    st = State(history=list(history))
    for m in history:
        if m.role == "tool":
            args = {}
            for a in history:
                for t in a.tool_calls or []:
                    if t["id"] == m.tool_call_id:
                        args = json.loads(t["function"]["arguments"])
            session_facts.record(st, m.name, args, m.content)
    return st


def messages_old(history, customer, summary, q):
    system = build_system_prompt(
        agent, Customer(phone=customer.phone), summary, customer_block=None
    )  # block đóng băng lúc chưa biết tên
    start = summary.covers_turns if summary else 0
    return (
        [{"role": "system", "content": system}]
        + [m.to_openai() for m in history[start:]]
        + [{"role": "user", "content": q}]
    )


def messages_new(history, customer, summary, q, st):
    system = build_system_prompt(agent, Customer(phone=customer.phone), summary, customer_block=None)
    start = summary.covers_turns if summary else 0
    hist = history[start:] + [ThreadMessage(role="user", content=q)]
    return [{"role": "system", "content": system}] + build_request_messages(
        hist, ephemeral=session_facts.render(st, customer) or None
    )


async def main():
    settings = get_settings()
    client = StreamingClient(providers=build_llm_providers(), enable_thinking=False)
    model_map = provider_model_map(settings)
    primary = primary_for(settings, primary_model)

    async def noop(_):
        pass

    history = make_history()
    customer = customer_after()
    st = facts_state(history)
    # summary (prompt mới hiện hành) trên 4 user-turn đầu (covers 18 message), giữ 2 lượt cuối
    cut = 18
    sum_prompt = build_summary_prompt(None, history[:cut])
    sum_text = await client.simple_completion(
        sum_prompt, model=model_map, primary=primary, max_tokens=500, temperature=0.2
    )
    summary = ThreadSummary(
        text=sum_text, covers_turns=cut, updated_at=__import__("datetime").datetime.now(__import__("datetime").UTC)
    )
    results = {"summary_text": sum_text, "cases": {}}
    for variant in ("old_full", "new_full", "old_after_summary", "new_after_summary"):
        for key, q, expect in QUESTIONS:
            hits = []
            for _ in range(RUNS):
                summ = summary if variant.endswith("after_summary") else None
                msgs = (
                    messages_old(history, customer, summ, q)
                    if variant.startswith("old")
                    else messages_new(history, customer, summ, q, st)
                )
                calls = []
                content = ""
                try:
                    for _round in range(3):
                        content, tcs = await client.stream_completion(
                            messages=msgs,
                            tools=tools,
                            model=model_map,
                            temperature=0.4,
                            max_tokens=400,
                            on_token=noop,
                            primary=primary,
                        )
                        if not tcs:
                            break
                        calls += [t["function"]["name"] for t in tcs]
                        msgs = msgs + [{"role": "assistant", "content": content or "", "tool_calls": tcs}]
                        for t in tcs:
                            n = t["function"]["name"]
                            fake = {
                                "no_lookup_needed": "OK — không cần tra cứu, trả lời khách tự nhiên.",
                                "search_units": UNITS,
                                "recommend_units": UNITS,
                                "kb_search": KB,
                                "get_document": DOC,
                                "booking": json.dumps({"bookings": [json.loads(BOOK)], "count": 1}, ensure_ascii=False),
                            }.get(n, "{}")
                            msgs = msgs + [{"role": "tool", "tool_call_id": t["id"], "name": n, "content": fake}]
                except Exception as e:
                    content = f"ERROR {e}"[:200]
                found = [e for e in expect if re.search(_NORM.get(e, re.escape(e)), content or "", re.I)]
                hits.append(
                    {
                        "content": (content or "")[:220],
                        "calls": calls,
                        "found": found,
                        "score": len(found) / len(expect),
                    }
                )
            avg = sum(h["score"] for h in hits) / len(hits)
            results["cases"][f"{variant}:{key}"] = {"avg": avg, "runs": hits}
            print(
                f"{variant:18s} {key:12s} {avg:.2f}  "
                + " | ".join(f"{h['score']:.2f}{'+' + ','.join(h['calls']) if h['calls'] else ''}" for h in hits),
                flush=True,
            )
    Path(out_path).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


asyncio.run(main())
