"""Probe chọn tool VÒNG ĐẦU của LLM thật trên bộ kịch bản cố định — dùng để so hai bản
prompt (persona + schema) mà KHÔNG cần tenant config / Redis / Qdrant: chỉ cần LLM key.

Vì sao có nó: `make eval-quality` cần EVAL_TENANT_API_KEY + data thật; khi sửa prompt
người ta cần một phép đo rẻ, lặp được, chạy trong vài phút. Cái này chỉ đo "gọi tool gì
ở lượt đầu" (không chạy tool, không đo câu trả lời) — đủ để bắt regression chọn tool,
KHÔNG thay thế eval đầy đủ.

Cách dùng (so HEAD với working tree):
    git archive HEAD src | tar -x -C /tmp/head
    PYTHONPATH=/tmp/head/src python scripts/probe_tool_selection.py old gemini-3.7-flash /tmp/old.json 3
    PYTHONPATH=src            python scripts/probe_tool_selection.py new gemini-3.7-flash /tmp/new.json 3
Tham số: <label> <tên model primary, khớp một <P>_MODEL trong .env> <out.json> [số lần/kịch bản].
Đổi model Gemini: GEMINI_MODEL=gemini-2.5-flash ... Kịch bản + tập tool kỳ vọng ở `SCEN`;
`ok` = gọi ít nhất một tool kỳ vọng và không gọi tool ngoài tập (update_customer miễn trừ).
"""

import asyncio
import json
import sys
from pathlib import Path

import noble_agent
from noble_agent.agent.agent_config import OPTIONAL_TOOLS, parse_config
from noble_agent.agent.base import build_agent_def_from_config
from noble_agent.agent.facade import build_llm_providers
from noble_agent.agent.llm.client import StreamingClient
from noble_agent.agent.prompts.builder import build_system_prompt
from noble_agent.config import get_settings, primary_for, provider_model_map
from noble_agent.storage.models import Customer

label, primary_model, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
RUNS = int(sys.argv[4]) if len(sys.argv) > 4 else 1
SKEL = Path(noble_agent.__file__).resolve().parent / "persona" / "chat"
cfg = parse_config(
    {
        "name": "Luna",
        "brand_name": "Noble",
        "scope_does": "tư vấn dự án, đặt lịch tham quan",
        "scope_does_not": "hợp đồng, thanh toán, sổ hồng, bảo hành",
        "departments": [{"ten": "CVTV", "khi_nao": "cần báo giá / gặp người thật"}],
        "skills": list(OPTIONAL_TOOLS),
    }
)
agent = build_agent_def_from_config(SKEL, cfg, model="x", temperature=0.4, max_tokens=400)
tools = [json.loads(json.dumps(t).replace("[VOCAB]", "")) for t in agent.tool_schemas]

NCR = Customer(name="Hùng", gender="M", phone="0912345678", project_interest="NCR")
ANON = Customer(phone="0912345678")
PRIOR = "Dạ, Noble Crystal ở Tây Hồ, chung cư cao cấp, giá từ 90 triệu một mét. Anh muốn em nói kỹ hơn phần nào?"
SCEN = [
    ("chao", ANON, None, "Chào em", {"none", "no_lookup_needed"}),
    ("discover", ANON, None, "Bên em đang có dự án nào ở Hà Nội?", {"discover_projects"}),
    ("budget_only", ANON, None, "Anh có 5 tỷ thì mua căn nào được?", {"recommend_units"}),
    (
        "overview_named",
        ANON,
        None,
        "Dự án Noble Crystal thế nào em?",
        {"find_project", "get_project_overview", "kb_search"},
    ),
    ("price_named", ANON, None, "Giá Noble Crystal bao nhiêu một mét vậy?", {"kb_search"}),
    ("units_named", ANON, None, "Sunshine Legend còn căn 3 ngủ dưới 6 tỷ không?", {"find_project", "search_units"}),
    ("media_matbang", NCR, PRIOR, "Cho anh xem mặt bằng dự án đó", {"send_media"}),
    ("media_video", NCR, PRIOR, "Có video dự án không em?", {"send_media"}),
    ("booking_start", NCR, PRIOR, "Anh muốn đặt lịch xem nhà cuối tuần này", {"booking"}),
    ("post_sale", NCR, None, "Anh mua căn ở Noble Crystal rồi, giờ hỏi tiến độ thanh toán theo hợp đồng", {"escalate"}),
    (
        "intro_multi",
        ANON,
        None,
        "Anh tên Hùng, làm ở Long Biên, đang tìm căn 2 ngủ tầm 3 tỷ",
        {"update_customer", "recommend_units"},
    ),
    ("aggregate", ANON, None, "Dự án nào bên em có nhiều loại hình nhất?", {"analyze_projects"}),
    ("document", NCR, PRIOR, "Gửi anh file chính sách bán hàng của dự án này", {"get_document"}),
    ("fengshui", ANON, None, "Anh sinh năm 1990, hợp căn hướng nào?", {"recommend_units"}),
    ("inventory", ANON, None, "Noble Crystal còn nhiều căn không em?", {"find_project", "check_inventory"}),
    (
        "objection_price",
        NCR,
        PRIOR,
        "Đắt quá em ơi, tầm đó anh không với được",
        {"update_customer", "kb_search", "recommend_units"},
    ),
    ("tour360", NCR, PRIOR, "Cho anh link tour 360 của dự án", {"send_media"}),
    ("think", NCR, PRIOR, "Thôi để anh suy nghĩ thêm đã", {"none", "no_lookup_needed", "update_customer"}),
    ("compare", ANON, None, "So sánh Noble Crystal với Sunshine Legend giúp anh", {"kb_search"}),
    ("human", ANON, None, "Anh muốn gặp nhân viên tư vấn trực tiếp", {"escalate"}),
    ("ambig", ANON, None, "Ocean Park thì sao em?", {"find_project", "kb_search"}),
    ("bye", NCR, PRIOR, "Cảm ơn em nhé, chào em", {"none", "no_lookup_needed"}),
    ("region_budget", ANON, None, "Ở Tây Hồ có dự án nào tầm 4 tỷ không?", {"discover_projects", "recommend_units"}),
    ("area_band", NCR, PRIOR, "Căn nào tầm 120 mét ở dự án này?", {"search_units"}),
]


async def main():
    settings = get_settings()
    client = StreamingClient(providers=build_llm_providers(), enable_thinking=False)
    model_map = provider_model_map(settings)
    primary = primary_for(settings, primary_model)

    async def noop(_):
        pass

    results = {}
    for key, cust, prior, user, expect in SCEN:
        system = build_system_prompt(agent, cust, None)
        msgs = [{"role": "system", "content": system}]
        if prior:
            msgs += [
                {"role": "user", "content": "Giới thiệu dự án Noble Crystal đi em"},
                {"role": "assistant", "content": prior},
            ]
        msgs.append({"role": "user", "content": user})
        runs = []
        for _ in range(RUNS):
            try:
                content, tcs = await client.stream_completion(
                    messages=msgs,
                    tools=tools,
                    model=model_map,
                    temperature=0.4,
                    max_tokens=400,
                    on_token=noop,
                    primary=primary,
                )
                calls = [(tc["function"]["name"], tc["function"].get("arguments", "")) for tc in (tcs or [])]
            except Exception as e:
                calls = [("ERROR", str(e)[:120])]
                content = ""
            names = {n for n, _ in calls} or {"none"}
            ok = bool(names & expect) and not (names - expect - {"update_customer"})
            runs.append({"calls": calls, "ok": ok, "content": (content or "")[:160]})
        passed = sum(r["ok"] for r in runs)
        results[key] = {"expect": sorted(expect), "passed": passed, "runs": runs}
        print(
            f"[{label}] {key:16s} {passed}/{RUNS}  "
            + " | ".join(str(sorted({n for n, _ in r["calls"]} or {"none"})) for r in runs),
            flush=True,
        )
    total = sum(r["passed"] for r in results.values())
    denom = RUNS * len(results)
    Path(out_path).write_text(
        json.dumps(
            {
                "label": label,
                "runs": RUNS,
                "total": total,
                "denom": denom,
                "system_chars": len(build_system_prompt(agent, ANON, None)),
                "schema_chars": len(json.dumps(tools, ensure_ascii=False)),
                "results": results,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"[{label}] TOTAL {total}/{denom}")


asyncio.run(main())
