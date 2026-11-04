"""Custom tool (tenant=noble): trả lời chính sách bán hàng/khuyến mãi/vay vốn
(CSBH) của một dự án từ Qdrant collection `media_v3` (category=csbh).

Đưa `caption` vào context LLM (trường `context`) + gửi media (ảnh/video) cho app
qua `items[]` (được dispatcher strip khỏi history → caption không lặp). Không có
csbh / thiếu mã / lỗi Qdrant → payload chứa ESCALATE_SIGNAL để dispatcher
auto-escalate sang CVTV/sale. Không bao giờ raise.
"""

from __future__ import annotations

import json
import logging
import os

from noble_agent.agent.rag import qdrant_store
from noble_agent.agent.tools.registry import tool
from noble_agent.data import media_data
from noble_agent.data.providers.base import ESCALATE_SIGNAL

logger = logging.getLogger("noble_agent.tenants.noble.tools.service_customer")

_COLLECTION = os.environ.get("CSBH_MEDIA_COLLECTION", "media_v3")
_SCROLL_LIMIT = 16
_HANDOFF_MSG = "Thông tin câu hỏi của anh chị đã được gửi cho bên sale ạ"

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "service_customer",
        "description": (
            "Trả lời câu hỏi về CHÍNH SÁCH của một dự án: chính sách bán hàng, "
            "khuyến mãi/ưu đãi, hoặc vay vốn/hỗ trợ lãi suất. Ví dụ: khách hỏi "
            "'dự án X có chính sách vay vốn thế nào', 'ưu đãi thanh toán sớm ra sao'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_code": {
                    "type": "string",
                    "description": "Mã dự án khách hỏi chính sách. Để trống nếu đã biết dự án khách quan tâm.",
                }
            },
            "required": [],
        },
    },
}


def _handoff() -> str:
    return json.dumps(
        {"ok": False, "note": "no_csbh", "message": _HANDOFF_MSG, "signal": ESCALATE_SIGNAL},
        ensure_ascii=False,
    )


def _scroll_filter(code: str):
    from qdrant_client import models

    return models.Filter(
        must=[
            models.FieldCondition(key="project_id", match=models.MatchValue(value=code)),
            models.FieldCondition(key="category", match=models.MatchValue(value="csbh")),
        ]
    )


@tool(name="service_customer", schema=_SCHEMA, tenant="noble", read_only=True, dirties_customer=False)
async def service_customer(args, *, customer, session_id, **_) -> str:
    code = (args.get("project_code") or "").strip().upper()
    if not code:
        code = (getattr(customer, "project_interest", "") or "").strip().upper()
    if not code:
        logger.info("[service_customer] sid=%s no project code/interest", session_id)
        return _handoff()

    try:
        client = qdrant_store._get_client()
        points, _next = await client.scroll(
            collection_name=_COLLECTION,
            scroll_filter=_scroll_filter(code),
            with_payload=True,
            with_vectors=False,
            limit=_SCROLL_LIMIT,
        )
    except Exception as exc:  # never raise out of a tool
        logger.warning("[service_customer] sid=%s code=%s scroll failed: %s", session_id, code, exc)
        return _handoff()

    payloads = [p.payload or {} for p in points]
    captions = [(pl.get("caption") or "").strip() for pl in payloads]
    captions = [c for c in captions if c]
    if not captions:
        logger.info("[service_customer] sid=%s code=%s no csbh", session_id, code)
        return _handoff()

    try:
        items = media_data._map_items(payloads)
        # The (long CSBH) caption lives in `context` — the sole source the LLM
        # answers from. Media items only need their renderable fields, so drop
        # the caption that _map_items copies into label/title to keep items lean.
        for it in items:
            it.pop("label", None)
            it.pop("title", None)
    except Exception as exc:  # never raise out of a tool
        logger.warning("[service_customer] sid=%s code=%s map_items failed: %s", session_id, code, exc)
        items = []

    from noble_agent.data import db_project_registry

    try:
        project_name = db_project_registry.code_to_name().get(code) or code
    except Exception as exc:  # never raise out of a tool
        logger.warning("[service_customer] sid=%s code=%s code_to_name failed: %s", session_id, code, exc)
        project_name = code

    context = "\n\n---\n\n".join(captions)
    message = (
        "Dạ em gửi thông tin chính sách qua app cho anh/chị rồi ạ."
        if items
        else "Dạ em gửi thông tin chính sách cho anh/chị ạ."
    )
    logger.info("[service_customer] sid=%s code=%s captions=%d items=%d", session_id, code, len(captions), len(items))
    return json.dumps(
        {
            "ok": True,
            "project_name": project_name,
            "context": context,
            "items": items,
            "count": len(items),
            "message": message,
        },
        ensure_ascii=False,
    )
