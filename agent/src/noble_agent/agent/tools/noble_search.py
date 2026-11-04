"""Tool: noble_search with V7 auto-set of customer.project_interest."""

from __future__ import annotations

import json
import logging
from typing import Protocol

logger = logging.getLogger("noble_agent.agent.tools.noble_search")

# Kết quả rỗng KHÔNG trả "" trần: model nhận con số không sẽ tự ứng biến — đường
# ngắn nhất tới bịa số liệu ("Anh có muốn em gửi hình ảnh không ạ?" là phiên bản
# nhẹ; đoán giá là phiên bản nặng). Vẫn là CHUỖI TRẦN nên contract hình-dạng-có-
# cổng của kb_search giữ nguyên; mọi backend degrade im lặng về rỗng đều rơi vào
# đây nên "pipeline hỏng" và "không có hit" cùng ra một chỉ đạo trung thực.
# Plain text không qua _strip_tool_directives (chỉ gỡ JSON dict) — chỉ đạo nằm
# lại history tới khi digest, chấp nhận vì ngắn và đọc lại vẫn đúng.
_EMPTY_RESULT_INSTRUCTION = (
    "Kho kiến thức KHÔNG có thông tin cho câu này. Nói trung thực với khách là em chưa có thông tin, "
    "TUYỆT ĐỐI không bịa hay tự đoán số liệu; rồi CHỦ ĐỘNG dẫn tiếp mạch tư vấn (gợi ý khía cạnh hoặc "
    "dự án khác đang có thông tin, hoặc khai thác thêm nhu cầu khách). KHÔNG hỏi xin phép kiểu "
    "'có muốn... không'."
)


class _DispatcherCtx(Protocol):
    customer: object
    state: object

    def mark_customer_dirty(self) -> None: ...


async def run(rag, dispatcher: _DispatcherCtx, args: dict) -> str:
    query = args.get("query", "")
    raw_filter = args.get("project_filter") or None

    # Scope ONLY when the LLM passes project_filter explicitly. An omitted filter
    # searches ALL projects — do NOT auto-scope to customer.project_interest, or a
    # comparison / multi-project query gets silently narrowed to the sticky project
    # (e.g. "so sánh VRI và VOP2" would return only VRI). The LLM controls scope.
    project_for_search: str | None = None
    if raw_filter:
        from noble_agent.agent import catalog

        canonical = catalog.normalize(raw_filter)
        if canonical and canonical != getattr(dispatcher.customer, "project_interest", None):
            dispatcher.customer.project_interest = canonical
            dispatcher.mark_customer_dirty()
        project_for_search = canonical or raw_filter

    from noble_agent.config import get_settings

    backend = get_settings().search_backend
    if backend == "empty":
        return _EMPTY_RESULT_INSTRUCTION
    if backend == "grep":
        from noble_agent.agent.rag import grep_search

        grepped = grep_search.search(query=query, project_filter=project_for_search)
        return grepped if grepped.strip() else _EMPTY_RESULT_INSTRUCTION

    if rag is None:
        logger.warning("noble_search: backend=rag but RAG is disabled; returning empty context")
        return _EMPTY_RESULT_INSTRUCTION

    # Bồn chứa tệp/ảnh nguồn. Chỉ backend `kb_service` đổ vào; `getattr` vì test và bản
    # RAG cũ có `search` không nhận tham số này.
    dinh_kem: list[dict] = []
    du_an: list[str] = []
    # Sổ số ảnh sống theo PHIÊN, không theo lượt — `state.scratchpad` đã là chỗ cho thứ
    # như vậy (`recent_projects` dùng cùng kiểu) và nó được lưu Redis cùng state.
    #
    # ⚠️ KHÔNG viết `getattr(...) and ... or {}`: một scratchpad rỗng là falsy, nên `or`
    # sẽ trả về một dict MỚI và sổ mất liên kết với state — số lại đánh theo lượt, đúng
    # cái bản vá này tồn tại để chấm dứt, mà không lỗi nào phát ra.
    state = getattr(dispatcher, "state", None)
    image_numbers: dict[str, int] = state.scratchpad.setdefault("image_numbers", {}) if state is not None else {}

    # THANG BẬC, không phải một nhánh tất-cả-hoặc-không. Một `except TypeError` bao trọn
    # nghĩa là một RAG biết `dinh_kem` mà chưa biết `du_an`/`numbers` sẽ mất LUÔN
    # `dinh_kem` — tệp nguồn im lặng không tới client. Mỗi bậc giữ đúng cái nó biết.
    try:
        result = await rag.search(
            query=query, project_filter=project_for_search, dinh_kem=dinh_kem, du_an=du_an, numbers=image_numbers
        )
    except TypeError:
        try:
            result = await rag.search(query=query, project_filter=project_for_search, dinh_kem=dinh_kem, du_an=du_an)
        except TypeError:
            try:
                result = await rag.search(query=query, project_filter=project_for_search, dinh_kem=dinh_kem)
            except TypeError:
                result = await rag.search(query=query, project_filter=project_for_search)
    context = result if isinstance(result, str) else str(result)

    # STICKY TỪ KẾT QUẢ khi LLM không truyền filter.
    #
    # Trước `e21c2d9`, `find_project` luôn chạy trước nên `project_interest` luôn có và
    # `send_media` luôn dùng được. Commit đó cho `kb_search` đi thẳng để tiết kiệm ~1.3s
    # và vô tình cắt đường lấy `project_code`: nhánh trên chỉ đặt sticky khi CÓ
    # `project_filter`, nên "vị trí ocean park 3" trả lời đúng mà `project_interest` rỗng
    # — rồi `send_media` trả `missing_project_code` và mô hình đi HỎI khách thay vì gửi.
    # Đo với CẢ Gemini 2.5 Flash và qwen3.7-flash: lỗi cấu trúc, không phải mô hình.
    #
    # Khác nhánh trên ở chỗ nó đặt sticky SAU khi tìm xong nên không thu hẹp phép tìm —
    # đúng điều comment `project_for_search` ở trên lo. Câu so sánh nhiều dự án ra hits
    # không đồng nhất ⇒ `du_an` rỗng ⇒ không đặt gì.
    if not raw_filter and du_an and du_an[0] != getattr(dispatcher.customer, "project_interest", None):
        dispatcher.customer.project_interest = du_an[0]
        dispatcher.mark_customer_dirty()
        logger.info("noble_search: sticky project từ kết quả = %s", du_an[0])

    if not dinh_kem:
        # KHÔNG có tệp kèm ⇒ trả CHUỖI TRẦN, đúng như trước.
        #
        # Đây là một hình dạng CÓ CỔNG, cố ý. `kb_search` là tool dùng nhiều nhất và mọi
        # luật prompt về nó đều viết cho một chuỗi ngữ cảnh; bọc JSON vô điều kiện là đặt
        # 100% câu trả lời vào rủi ro để phục vụ thiểu số lượt có tệp. Hình dạng JSON chỉ
        # xuất hiện đúng khi câu trả lời LẤY TỪ MỘT TỆP — nên nó là một tín hiệu có nghĩa,
        # không phải một sự bất nhất tuỳ hứng.
        return context if context.strip() else _EMPTY_RESULT_INSTRUCTION

    # `items` bị lược khỏi ngữ cảnh LLM bởi `dispatcher._strip_display_items` (kb_search
    # nằm trong danh sách cho phép) nhưng VẪN tới client qua `on_tool_done`. Nhờ vậy LLM
    # không bao giờ phải CHÉP LẠI một URL dài — chép sai là chuyện sẽ xảy ra.
    return json.dumps({"context": context, "items": dinh_kem}, ensure_ascii=False)
