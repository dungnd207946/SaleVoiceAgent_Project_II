"""Built-in (standard) tool registrations — thin adapters over the existing
tool modules, preserving every arg-massage. Imported for its registration
side effect. Behaviour-identical to the pre-registry dispatcher `_exec`."""

from __future__ import annotations

from noble_agent.agent.tools import (
    analytics,
    booking,
    find_project,
    get_document,
    noble_search,
    projects_info,
    support_ops,
    update_customer,
)
from noble_agent.agent.tools.registry import ToolSpec, register
from noble_agent.agent.tools.schemas import SCHEMAS

_BOOKING_NEEDS_PROJECT_ACTIONS = {"check_availability", "schedule"}


async def _update_customer(args, *, customer, **_):
    return await update_customer.run(customer, args)


async def _kb_search(args, *, dispatcher, rag, **_):
    return await noble_search.run(rag, dispatcher, args)


async def _find_project(args, *, dispatcher, **_):
    return await find_project.run(dispatcher, args)


async def _discover_projects(args, *, state, **_):
    # KHÔNG default project_code: rỗng = chế độ khám phá danh sách; auto-fill từ
    # hồ sơ sẽ giết chết chế độ đó ngay khi khách có "dự án quan tâm".
    return await projects_info.discover_projects(args, state=state)


async def _get_document(args, *, dispatcher, **_):
    dispatcher.default_project_code(args)
    return await get_document.run(args)


async def _search_units(args, *, state, customer, dispatcher, **_):
    # scope='in_project' → điền dự án đang quan tâm khi model bỏ trống; scope
    # 'all_projects' / thiếu scope KHÔNG điền (nghĩa xuyên-dự-án của recommend cũ).
    if args.get("scope") == "in_project":
        dispatcher.default_project_code(args)
    return await projects_info.search_units(args, state=state, customer=customer)


async def _analyze_projects(args, **_):
    return await analytics.run(args)


async def _booking(args, *, state, customer, session_id, dispatcher, **_):
    if args.get("action") in _BOOKING_NEEDS_PROJECT_ACTIONS:
        dispatcher.default_project_code(args)
    return await booking.run(state, customer, args, session_id=session_id)


async def _no_lookup_needed(args, **_):
    # Van xả cho LLM_FORCE_TOOL_FIRST_ROUND: lượt xã giao không có gì để tra.
    return "OK — không cần tra cứu, trả lời khách tự nhiên."


async def _escalate(args, *, state, customer, session_id, dispatcher, **_):
    # LLM hay bỏ trống `department` — điền bộ phận tiếp nhận của tenant thay vì
    # để support_ops rơi về "CVTV" (chỉ đúng với noble).
    if not args.get("department"):
        args = {**args, "department": dispatcher.handoff_department}
    return await support_ops.escalate(state, customer, args, session_id=session_id)


async def _send_media(args, *, customer, session_id, dispatcher, **_):
    dispatcher.default_project_code(args)
    return await support_ops.send_media(customer, args, session_id=session_id)


# (name, executor, dirties_customer, read_only)
# Merge 2026-09-07: search_units nuốt recommend_units, discover_projects nuốt
# get_project_overview, analyze_projects nuốt check_inventory — 14 → 11 built-in.
_BUILTINS = [
    ("update_customer", _update_customer, True, False),
    ("kb_search", _kb_search, False, True),
    ("find_project", _find_project, False, False),
    ("discover_projects", _discover_projects, False, True),
    ("get_document", _get_document, False, True),
    ("search_units", _search_units, False, True),
    ("analyze_projects", _analyze_projects, False, True),
    ("booking", _booking, False, False),
    ("escalate", _escalate, False, False),
    ("no_lookup_needed", _no_lookup_needed, False, True),
    ("send_media", _send_media, False, False),
]

for _name, _fn, _dirty, _ro in _BUILTINS:
    register(ToolSpec(name=_name, schema=SCHEMAS.get(_name, {}), executor=_fn, dirties_customer=_dirty, read_only=_ro))
