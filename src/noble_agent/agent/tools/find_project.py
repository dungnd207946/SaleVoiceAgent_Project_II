"""find_project tool — resolve a spoken project name to a canonical code.

Returns resolved / ambiguous / not_found. On resolved, sticks the code into
customer.project_interest so downstream data tools default to it. The
ProjectNameIndex singleton is populated by the orchestrator at bootstrap.

Recently-listed prior: the customer usually answers a project list with ONE
word, and STT mangles English names ("Sansai" for Sunshine) beyond what fuzzy
scoring recovers — and in-shortlist fuzzy scores are not separable from plain
speech either (measured 2026-08-25). So the code only narrows: an ambiguous
family with exactly one member in the just-listed set resolves to it; a
not_found result carries the just-listed projects (`recently_listed`) and asks
the LLM — which does know that "san sai" sounds like Sunshine — to confirm
CÓ/KHÔNG instead of asking the customer to repeat.
"""

from __future__ import annotations

import json

from noble_agent.agent.tools import recent_projects
from noble_agent.data.project_matching.index import Candidate, ProjectNameIndex, ResolveResult

_INDEX_BY_TENANT: dict[str, ProjectNameIndex] = {}


def _resolve_tenant(tenant: str | None) -> str:
    if tenant:
        return tenant
    from noble_agent.tenant.current import current_tenant

    return current_tenant()


def set_index(idx: ProjectNameIndex | None, *, tenant: str | None = None) -> None:
    tid = _resolve_tenant(tenant)
    if idx is None:
        _INDEX_BY_TENANT.pop(tid, None)
    else:
        _INDEX_BY_TENANT[tid] = idx


def get_index(*, tenant: str | None = None) -> ProjectNameIndex | None:
    return _INDEX_BY_TENANT.get(_resolve_tenant(tenant))


_RECENT_MESSAGE = (
    "Không tìm thấy dự án khớp. Khách nhiều khả năng đang chọn từ recently_listed (các dự án "
    "vừa giới thiệu) mà STT ghi méo tên — nhất là tên tiếng Anh đọc kiểu Việt (vd 'san sai' ≈ "
    "Sunshine, 'vin hôm' ≈ Vinhomes, 'lu mi e' ≈ Lumière). Nếu tên khách nói NGHE GẦN GIỐNG một "
    "dự án trong đó → hỏi khách xác nhận CÓ/KHÔNG dự án đó (đọc tên đầy đủ), đừng xin nhắc lại. "
    "Không giống dự án nào mà có best_guess → hỏi xác nhận best_guess. Khách xác nhận → gọi "
    "find_project(query=<tên đầy đủ dự án đó>) để hệ thống ghi nhớ dự án đang quan tâm."
)


def _apply_recent_prior(r: ResolveResult, recent: list[str]) -> ResolveResult:
    """Narrow an ambiguous family to the members the customer just heard."""
    if r.status != "ambiguous" or not recent:
        return r
    hits = [c for c in r.candidates if c.code in recent]
    if len(hits) == 1:
        c = hits[0]
        return ResolveResult(status="resolved", code=c.code, name=c.name, region=c.region)
    if len(hits) > 1:
        return ResolveResult(status="ambiguous", candidates=hits)
    return r


def _cand_json(c: Candidate) -> dict:
    return {"code": c.code, "name": c.name, "region": c.region}


def _to_json(r: ResolveResult, listed: list[Candidate] = ()) -> str:
    if r.status == "resolved":
        payload = {"status": "resolved", "code": r.code, "name": r.name, "region": r.region}
    elif r.status == "ambiguous":
        payload = {"status": "ambiguous", "candidates": [_cand_json(c) for c in r.candidates]}
    else:
        payload = {"status": "not_found", "message": r.message or "Không tìm thấy dự án."}
        if r.candidates:
            payload["best_guess"] = _cand_json(r.candidates[0])
            payload["message"] = (
                "Không tìm thấy dự án khớp, nhưng tên khách nói NGHE GẦN GIỐNG best_guess — "
                "hỏi khách xác nhận CÓ/KHÔNG dự án đó thay vì xin nhắc lại lần nữa."
            )
        if listed:
            payload["recently_listed"] = [_cand_json(c) for c in listed]
            payload["message"] = _RECENT_MESSAGE
    return json.dumps(payload, ensure_ascii=False)


async def run(dispatcher, args: dict) -> str:
    idx = get_index()
    if idx is None:
        return json.dumps({"status": "not_found", "message": "Danh mục dự án chưa sẵn sàng."}, ensure_ascii=False)
    query = args.get("query", "") or ""
    region_hint = args.get("region_hint", "") or ""
    investor_hint = args.get("investor_hint", "") or ""
    # Fallback context from session state when the LLM omits a hint.
    if not region_hint:
        region_hint = getattr(dispatcher.customer, "preferred_area", "") or ""
    recent = recent_projects.recall(dispatcher.state)
    result = _apply_recent_prior(idx.resolve(query, region_hint=region_hint, investor_hint=investor_hint), recent)
    if result.status == "resolved" and getattr(dispatcher.customer, "project_interest", None) != result.code:
        dispatcher.customer.project_interest = result.code
        dispatcher.mark_customer_dirty()
    listed = [c for c in map(idx.lookup, recent) if c is not None] if result.status == "not_found" else []
    return _to_json(result, listed)
