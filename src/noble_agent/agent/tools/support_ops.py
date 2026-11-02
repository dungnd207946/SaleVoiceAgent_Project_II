"""Support-side tools: escalate, send_media.

Escalation state (transfer flag) lives in SessionState.scratchpad; the escalation
row itself goes to Postgres via ``storage/pg_data_plane.py::record_escalation``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from noble_agent.agent.summary.escalation_summary import spawn_escalation_summary
from noble_agent.config import get_settings
from noble_agent.data import media_data
from noble_agent.storage.pg_data_plane import record_escalation

logger = logging.getLogger("noble_agent.agent.tools.support_ops")
_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Degraded reply when no renderable media exists / a read fails (§9). Luna then
# describes the project verbally — it does NOT escalate.
_NO_MEDIA_MSG = "Hình ảnh phần này bên em chưa có sẵn, để em mô tả cho anh/chị nhé"


def _retry_payload(error: str, message: str) -> str:
    """Actionable error for the LLM: the call was rejected before hitting the
    service (bad args) → the model should FIX the args and call send_media again.
    Distinct from `_no_media_payload` (valid args, but no media exists)."""
    return json.dumps({"ok": False, "error": error, "retry": True, "message": message}, ensure_ascii=False)


def _first_str(v) -> str:
    """Arg từ LLM có thể là list (đã gặp thật với project_code) — lấy phần tử đầu."""
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v or "").strip()


def _no_media_payload() -> str:
    return json.dumps(
        {"ok": False, "items": [], "count": 0, "note": "no_media", "message": _NO_MEDIA_MSG},
        ensure_ascii=False,
    )


def _bo_khoa_noi_bo(item: dict) -> dict:
    """Item không còn khoá `_*` — DỰNG DICT MỚI, không `del` tại chỗ.

    `media_data._cache` copy NÔNG (nó copy mảng, không copy từng dict), nên xoá
    khoá tại chỗ là ghi thẳng vào bản đang nằm trong cache: lượt gọi sau trong cửa
    sổ TTL nhận item đã mất `_ref` và phép lọc theo `ids` im lặng không khớp gì.
    """
    return {k: v for k, v in item.items() if not k.startswith("_")}


def _payload_candidates(project_name: str, category: str, items: list[dict]) -> str:
    """Ứng viên cho LLM chọn — CỐ Ý không có `items[]`.

    Thiếu `items[]` là cách chặn việc gửi mà không phải sửa dispatcher hay client:
    cả ba đường render đều bỏ qua khi mảng rỗng hoặc vắng (`voice_agent.py`
    on_tool_done, `chatGateway.ts` phần đọc media, `ThuAgentScreen.tsx` phần dựng
    thẻ). Nhờ vậy màn hình khách trống cho tới khi LLM chốt.

    KHÔNG có `message`: đường này tồn tại chính vì câu mớm sẵn là thứ nói sai. Câu
    nói do LLM viết sau khi đọc `candidates`.
    """
    return json.dumps(
        {
            "ok": False,
            "note": "category_fallback",
            "project_name": project_name,
            "category_yeu_cau": category,
            "candidates": [
                {
                    "ref": it.get(media_data.KHOA_REF, ""),
                    "kind": it.get("kind", ""),
                    "caption": it.get("label") or it.get("title") or "",
                }
                for it in items
            ],
            "huong_dan": (
                f"Workspace không có ảnh nào thuộc danh mục '{category}' cho dự án này. "
                "Danh sách trên là ảnh gần nhất tìm được, KHÔNG phải ảnh đúng danh mục. "
                "Đọc caption rồi gọi lại send_media với ids là những ref phù hợp — "
                "và nói rõ với khách rằng đây không phải ảnh họ xin. Không có cái nào "
                "phù hợp thì đừng gọi lại, hãy nói thẳng là chưa có."
            ),
        },
        ensure_ascii=False,
    )


def _is_working_hours() -> bool:
    now = datetime.now(tz=_VN_TZ)
    return 8 <= now.hour < 21


def _to_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


async def escalate(state, customer, args: dict, *, session_id: str = "", missing_data_tool: str = "") -> str:
    action = args.get("action", "check_state")

    if action == "check_state":
        has_name = bool(customer.name or customer.full_name)
        has_phone = bool(customer.phone)
        return json.dumps(
            {
                "has_name": has_name,
                "has_phone": has_phone,
                "transfer_ready": has_name and has_phone,
                "working_hours": _is_working_hours(),
            },
            ensure_ascii=False,
        )

    if action == "transfer":
        reason = args.get("reason", "") or ""
        department = args.get("department", "CVTV") or "CVTV"
        priority = args.get("priority", "normal") or "normal"

        name = customer.full_name or customer.name or "Chưa cung cấp"
        phone = customer.phone or "Chưa cung cấp"
        project = customer.project_interest or "Chưa xác định"

        summary = f"Khách: {name}, SĐT: {phone}, Dự án: {project}. Lý do chuyển: {reason}."
        # Mark transfer in scratchpad so downstream agents can see this happened.
        state.scratchpad["escalation_transferred"] = "1"
        state.scratchpad["escalation_summary"] = summary

        logger.info("[ESCALATE] → %s (%s) reason=%s", department, priority, reason[:80])

        # Awaited, not fire-and-forget: the row must exist before the summary task
        # can update it, and a caller who hangs up now must not lose the case.
        try:
            esc_id = await record_escalation(
                session_id=session_id,
                phone=customer.phone or "",
                customer_name=customer.full_name or customer.name or "",
                project=customer.project_interest or "",
                missing_data_tool=missing_data_tool,
                summary=summary,
                message_seq=len(state.history),
            )
            if esc_id:
                spawn_escalation_summary(
                    esc_id,
                    history_snapshot=[{"role": m.role, "content": m.content} for m in state.history],
                    customer=customer.model_dump(exclude_none=True),
                    reason=reason,
                )
        except Exception:
            logger.warning("[ESCALATE] persist failed session=%s", session_id, exc_info=True)

        working = _is_working_hours()
        message = (
            "Em chuyển thông tin cho chuyên viên ngay, anh chị chờ một chút nhé."
            if working
            else "Giờ này bên em đã hết giờ làm việc, chuyên viên sẽ liên hệ lại anh chị vào ngày làm việc tiếp theo ạ."
        )
        return json.dumps(
            {
                "status": "transfer_completed",
                "department": department,
                "priority": priority,
                "summary": summary,
                "working_hours": working,
                "message": message,
            },
            ensure_ascii=False,
        )

    return json.dumps({"error": f"Unknown escalate action: {action}"}, ensure_ascii=False)


_DANH_TU_TRUY_VAN = {"video": "video", "tour_360": "tour tham quan thực tế ảo 360 độ"}


async def send_media(customer, args: dict, session_id: str) -> str:
    """Send real project media (images + video YouTube/Drive… + tour 360) to the NobleX app.

    Runs a Qdrant hybrid text+visual search (``media_data.search_media``) over the
    current tenant's media collection for the given project code (else
    ``customer.project_interest``), lọc theo ``category`` và/hoặc ``content_type``
    (cả hai optional nhưng không được rỗng cả hai), và trả về ``items[]`` payload
    mà chat/voice forward nguyên văn cho client. On any failure — no project code,
    unconfigured infra, no renderable media, or a Qdrant/embed error — returns the
    degraded ``no_media`` payload and never raises.
    """
    from noble_agent.agent.tools.schemas import SEND_MEDIA_CATEGORIES, SEND_MEDIA_CONTENT_TYPES

    query = _first_str(args.get("query"))
    category = _first_str(args.get("category")).lower()
    content_type = _first_str(args.get("content_type")).lower()
    code = _first_str(args.get("project_code")).upper()
    # `ids` = lượt GỬI của luồng hai bước: LLM đã đọc `candidates` và chốt. Lọc
    # bằng `_ref` chứ không bằng vị trí — vị trí buộc lượt này tin rằng thứ tự
    # không đổi giữa hai lời gọi, mà giữa chúng có cả một lượt LLM.
    ids = [s for s in (_first_str(x) for x in (args.get("ids") or [])) if s]
    if not code and customer.project_interest:
        code = customer.project_interest.strip().upper()

    # ── arg validation → actionable retry messages (LLM re-calls with fixes) ──
    # Cả category và content_type đều optional, nhưng rỗng CẢ HAI thì không rõ
    # khách muốn gì: nhánh chủ động giới thiệu cần tong_quan (ảnh phối cảnh, nhẹ),
    # bỏ trống sẽ lôi cả bản vẽ mặt bằng nhiều MB.
    cats = ", ".join(SEND_MEDIA_CATEGORIES)
    ctypes = ", ".join(SEND_MEDIA_CONTENT_TYPES)
    if not category and not content_type:
        logger.info("[send_media] sid=%s missing category and content_type", session_id)
        return _retry_payload(
            "missing_filter",
            f"Cần ít nhất một trong category ({cats}) hoặc content_type ({ctypes}). "
            "Giới thiệu tổng quan dự án → category=tong_quan; khách xin video → content_type=video.",
        )
    if category and category not in SEND_MEDIA_CATEGORIES:
        logger.info("[send_media] sid=%s invalid category=%s", session_id, category)
        return _retry_payload(
            "invalid_category",
            f"category '{category}' không hợp lệ. Hãy gọi lại send_media với category là một trong: {cats}.",
        )
    if content_type and content_type not in SEND_MEDIA_CONTENT_TYPES:
        logger.info("[send_media] sid=%s invalid content_type=%s", session_id, content_type)
        return _retry_payload(
            "invalid_content_type",
            f"content_type '{content_type}' không hợp lệ. "
            f"Hãy gọi lại send_media với content_type là một trong: {ctypes}.",
        )
    if not code:
        logger.info("[send_media] sid=%s no project code/interest", session_id)
        return _retry_payload(
            "missing_project_code",
            "Chưa xác định dự án. Hãy gọi lại send_media kèm project_code là mã dự án khách muốn xem hình.",
        )

    from noble_agent.tenant.current import current_tenant

    settings = get_settings()
    if not settings.qdrant_url:
        logger.warning("[send_media] sid=%s code=%s qdrant_url not configured", session_id, code)
        return _no_media_payload()

    # category có thể rỗng → ghép từ các phần non-rỗng để không ra hai khoảng trắng.
    # Danh từ đi VÀO câu truy vấn nhúng, nên `tour_360` mà hỏi "hình ảnh dự án" là tìm sai
    # thứ — caption của point tour là "Tour tham quan thực tế ảo 360 độ — <tên dự án>".
    noun = _DANH_TU_TRUY_VAN.get(content_type, "hình ảnh")
    search_query = query or " ".join(p for p in (noun, category, "dự án") if p)
    try:
        kq = await media_data.search_media_detailed(
            search_query,
            code,
            category,
            tenant_id=current_tenant(),
            qdrant_url=settings.qdrant_url,
            qdrant_api_key=settings.qdrant_api_key,
            content_type=content_type,
            top_k=settings.media_search_top_k,
            threshold=settings.media_search_threshold,
            qdrant_timeout=settings.qdrant_timeout,
            cache_ttl=settings.media_search_cache_ttl,
            with_visual=bool(settings.embed_service_url),
            include_thumb=settings.media_send_thumb,
        )
    except Exception as exc:  # never raise out of the tool
        logger.warning("[send_media] sid=%s code=%s search failed: %s", session_id, code, exc)
        kq = media_data.MediaResult([], False)
    items = kq.items

    if not items:
        logger.info("[send_media] sid=%s code=%s no renderable media", session_id, code)
        return _no_media_payload()

    from noble_agent.data import db_project_registry

    project_name = db_project_registry.code_to_name().get(code) or code

    # ── Luồng hai bước, CHỈ trên nhánh đã bị gỡ lọc category ─────────────────
    #
    # Không có nhánh này, ảnh tới màn hình khách trước khi LLM sinh token nào
    # (`dispatch` gọi `on_tool_done` rồi mới `return`), và LLM không thấy `items[]`
    # nên nó nói "đã gửi ảnh nội thất" cho một rổ ảnh phối cảnh.
    #
    # Đường khớp category KHÔNG đi qua đây: ở đó ảnh đúng thứ khách xin, thêm một
    # lượt LLM là trả độ trễ cho việc không cần làm.
    # `_gui_het` là cửa NỘI BỘ của lưới đỡ cuối lượt (`dispatcher.finish_turn`), cố ý
    # KHÔNG khai trong schema nên LLM không dùng được: nó nghĩa là "lượt đã xong, mô
    # hình không chốt, gửi cả rổ còn hơn để màn hình trống".
    if kq.category_fallback and not ids and not args.get("_gui_het"):
        logger.info(
            "[send_media] sid=%s code=%s category=%s bị gỡ lọc → trả %d ứng viên cho LLM chọn",
            session_id,
            code,
            category,
            len(items),
        )
        return _payload_candidates(project_name, category, items)

    if ids:
        chon = {i for i in ids}
        loc = [it for it in items if it.get(media_data.KHOA_REF) in chon]
        # Không khớp ref nào: ref bịa, hoặc cache đã hết hạn giữa hai lượt nên
        # point id đổi. Gửi nguyên rổ còn hơn gửi rỗng — khách đang chờ ảnh, và
        # `no_media` ở đây là nói dối (media CÓ tồn tại).
        if loc:
            items = loc
        else:
            logger.warning(
                "[send_media] sid=%s code=%s ids=%s không khớp ref nào → gửi cả rổ",
                session_id,
                code,
                ids,
            )
    logger.info("[send_media] sid=%s code=%s items=%d", session_id, code, len(items))
    # Danh từ suy từ items THỰC SỰ gửi, không từ content_type (content_type rỗng
    # vẫn có thể ra toàn video) — tránh khách xin video mà thấy chữ "Hình ảnh".
    kinds = {i.get("kind") for i in items}
    # `tour` đứng trước `image` vì `_map_items` đặt tour LÊN ĐẦU danh sách: gọi cả rổ là
    # "hình ảnh" trong khi thứ khách thấy đầu tiên là một tour 360 khiến LLM tưởng gửi
    # trượt rồi gọi lại send_media — đúng lỗi mà nhánh "video" đã được thêm để tránh.
    if kinds == {"video"}:
        noun = "Video"
    elif "tour" in kinds:
        noun = "Tour 360"
    else:
        noun = "Hình ảnh"
    return json.dumps(
        {
            "ok": True,
            "project_name": project_name,
            "caption": f"{noun} dự án {project_name}",
            # Gỡ khoá nội bộ Ở ĐÂY, chỗ duy nhất payload rời tool. Client không bao
            # giờ thấy `_ref`; xem `_bo_khoa_noi_bo` về việc vì sao phải dựng dict mới.
            "items": [_bo_khoa_noi_bo(it) for it in items],
            "count": len(items),
            "message": f"Đã gửi {noun.lower()} dự án qua app cho khách.",
        },
        ensure_ascii=False,
    )
