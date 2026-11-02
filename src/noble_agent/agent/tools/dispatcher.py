"""Tool dispatcher — registry-backed dispatch + customer_dirty signal.

``_exec`` resolves a ``ToolSpec`` from the registry (built-ins registered by
importing ``builtins``, tenant custom tools registered separately) and calls
its executor. The outer ``dispatch()`` wrapper (start/done callbacks, crash
handling, auto-escalate, display-items stripping) is unchanged from the
pre-registry dispatcher.

There is no ``switch_agent`` in the unified single-agent — handoff is
expressed via the ``escalate`` tool (transfer to a human department).
"""

from __future__ import annotations

import json
import logging

from noble_agent.agent import session_facts
from noble_agent.agent.tools import builtins as _builtins  # noqa: F401 — registers built-ins
from noble_agent.agent.tools import registry, support_ops
from noble_agent.config import get_settings
from noble_agent.data.providers import ESCALATE_SIGNAL, get_provider

logger = logging.getLogger("noble_agent.agent.tools.dispatcher")

# `booking` is handled per-action — only action=schedule actually writes back
# to Customer (via schedule_viewing). Other tools' dirty flag comes from the
# resolved ToolSpec (`spec.dirties_customer`).
_BOOKING_DIRTYING_ACTIONS = {"schedule"}


# Tools whose ``items[]`` is a DISPLAY-ONLY media payload (rendered by the
# client/app, never needed by the model to reply). Their ``items`` is stripped
# from the copy appended to the LLM context. This is an explicit allowlist —
# NOT a blanket strip of every ``items`` key — so a tool that returns ``items``
# as content the model actually needs is never touched. Add a new media tool here.
_DISPLAY_ITEMS_TOOLS = {"send_media", "service_customer", "kb_search"}


def _strip_display_items(name: str, result: str) -> str:
    """For a display-only media tool (``_DISPLAY_ITEMS_TOOLS``), drop the
    ``items[]`` payload from the result before it enters the LLM context
    (``state.history``).

    ``items[]`` (e.g. ``send_media``'s image/video list) is rendered by the
    client/app; the model never needs it to reply, and it can be large (URLs +
    captions), so keeping it in history just bloats every subsequent turn. The
    full result (incl. ``items``) still reaches the client via ``on_tool_done``;
    this only strips the copy the runner appends to history. Every other field
    (``ok``/``project_name``/``caption``/``count``/``message``…) is preserved, so
    the model still knows what was sent (``count`` conveys how many). Non-media
    tools are returned verbatim — their ``items`` (if any) is left intact."""
    if name not in _DISPLAY_ITEMS_TOOLS:
        return result
    try:
        data = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return result
    if isinstance(data, dict) and "items" in data:
        return json.dumps({k: v for k, v in data.items() if k != "items"}, ensure_ascii=False)
    return result


class ToolDispatcher:
    def __init__(
        self,
        state,
        customer,
        rag,
        callbacks,
        session_id: str,
        tenant: str = "noble",
        sandbox: bool = False,
        handoff_department: str = "CVTV",
    ):
        self.state = state
        self.customer = customer
        self.rag = rag
        self.callbacks = callbacks
        self.session_id = session_id
        self.tenant = tenant
        self.sandbox = sandbox
        # Bộ phận tiếp nhận của TENANT (AgentDef.handoff_department) — trước đây
        # auto-escalate ghi cứng "CVTV" nên tenant khác chuyển vào bộ phận không tồn tại.
        self.handoff_department = handoff_department or "CVTV"
        self._customer_dirty = False
        self._provider = None
        # Trạng thái media của LƯỢT này (dispatcher dựng mới mỗi lượt ở
        # `orchestrator._run_live`). Xem `finish_turn`.
        self._media_da_gui = False
        self._media_cho_chon: dict | None = None
        self._y_dinh_hinh_anh = ""

    @property
    def provider(self):
        if self._provider is None:
            self._provider = get_provider(get_settings())
        return self._provider

    def mark_customer_dirty(self) -> None:
        self._customer_dirty = True

    def consume_customer_dirty(self) -> bool:
        v, self._customer_dirty = self._customer_dirty, False
        return v

    def default_project_code(self, args: dict) -> None:
        """Default an empty `project_code` arg to the customer's sticky
        project of interest (set earlier via find_project / noble_search)."""
        if not args.get("project_code"):
            args["project_code"] = getattr(self.customer, "project_interest", "") or ""

    async def dispatch(self, tool_call: dict) -> str:
        name = tool_call["function"]["name"]
        raw_args = tool_call["function"]["arguments"] or "{}"
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError as e:
            logger.warning("dispatcher: bad args for %s: %s", name, e)
            # Emit trace events even on bad-args so UI/metrics see the call.
            await self.callbacks.on_tool_start(name, {"_raw": raw_args, "_parse_error": str(e)})
            result = json.dumps({"ok": False, "error": f"bad args: {e}"})
            await self.callbacks.on_tool_done(name, result)
            return result

        await self.callbacks.on_tool_start(name, args)
        crashed = False
        try:
            result = await self._exec(name, args)
        except Exception as e:
            logger.exception("dispatcher: tool %s crashed", name)
            result = json.dumps({"error": f"tool {name} crashed: {e}"})
            crashed = True

        # Only signal the runner to rebuild the system prompt when the tool
        # actually ran. A crashed update_customer/booking did not mutate state,
        # so a rebuild would be pure waste AND mask the failure with a
        # misleading cache-invalidation signal.
        spec = registry.resolve(self.tenant, name)
        if not crashed and (
            (spec is not None and spec.dirties_customer)
            or (name == "booking" and args.get("action") in _BOOKING_DIRTYING_ACTIONS)
        ):
            self._customer_dirty = True

        if not crashed:
            self._ghi_nhan_media(name, args, result)
            # Bộ nhớ xác định của phiên (căn / tài liệu / ảnh đã đưa, lịch, chuyển) —
            # sandbox là lượt ghost của semcache, không được ghi.
            if not self.sandbox:
                session_facts.record(self.state, name, args, result)

        # Client/app gets the FULL result (incl. items[] media) for display.
        await self.callbacks.on_tool_done(name, result)

        # Code-driven handoff: a data tool returned ESCALATE_SIGNAL (no data).
        # The prompt asks Luna to call escalate herself, but she does so
        # intermittently — record the transfer here so the promised callback
        # always exists. The sentinel result returned to the LLM is unchanged.
        # `sandbox` = lượt ghost của semcache, chạy trên state clone nhưng DÙNG
        # CHUNG session_id thật — escalate ở đó ghi ca chuyển sale ngoài đời.
        if not crashed and not self.sandbox and name != "escalate" and ESCALATE_SIGNAL in result:
            await self._auto_escalate(name, args)

        # The LLM context (state.history) gets the result WITHOUT items[] for
        # display-only media tools (already sent to the client above). All other
        # tools are returned verbatim.
        return _strip_display_items(name, result)

    # Ý định hình ảnh suy từ câu hỏi — CỐ Ý chỉ hai danh mục không mơ hồ.
    #
    # `tien_do` đứng ngoài: "tiến độ thanh toán" rất phổ biến ở tenant bán hàng và nó
    # sẽ kéo ảnh công trường vào một câu hỏi về tiền. `noi_that`/`ngoai_that`/`tien_ich`
    # cũng đứng ngoài — chúng hay xuất hiện trong văn mô tả chứ không phải yêu cầu xem.
    _Y_DINH = (
        ("vi_tri", ("vị trí", "bản đồ", "ở đâu", "nằm ở")),
        ("mat_bang", ("mặt bằng",)),
    )
    # Cụm chứa từ khoá nhưng KHÔNG phải yêu cầu xem ảnh. "mặt bằng giá" là mức giá,
    # không phải bản vẽ.
    _KHONG_PHAI_Y_DINH = ("mặt bằng giá", "mặt bằng chung", "vị trí thanh toán")

    def _suy_y_dinh_hinh_anh(self, query: str) -> str:
        q = (query or "").lower()
        if not q or any(x in q for x in self._KHONG_PHAI_Y_DINH):
            return ""
        for cat, tu in self._Y_DINH:
            if any(t in q for t in tu):
                return cat
        return ""

    def _ghi_nhan_media(self, name: str, args: dict, result: str) -> None:
        """Ghi lại những gì lượt này CÒN NỢ về media. Xem `finish_turn`."""
        if name == "kb_search":
            self._y_dinh_hinh_anh = self._y_dinh_hinh_anh or self._suy_y_dinh_hinh_anh(args.get("query", ""))
            return
        if name != "send_media":
            return
        try:
            data = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(data, dict):
            return
        if data.get("items"):
            self._media_da_gui = True
            self._media_cho_chon = None
        elif data.get("note") == "category_fallback":
            self._media_cho_chon = dict(args)

    async def finish_turn(self) -> None:
        """Trả nợ media cuối lượt. KHÔNG ghi vào history — lượt đã xong, và một
        tool message không có assistant(tool_calls) đi kèm sẽ phá bất biến mà
        `run_turn` đang canh. Client vẫn nhận ảnh qua `on_tool_done`.

        Tồn tại vì hai đường đều phụ thuộc việc mô hình chịu gọi tool, mà repo này
        đã ghi lại năm lần rằng nó làm không đều — cùng lý lẽ `_auto_escalate`:
        "prompt nhờ Luna tự gọi, nhưng nó làm không đều".
        """
        if self.sandbox or self._media_da_gui:
            return

        # ① Lượt trả `candidates` mà mô hình không chốt → gửi cả rổ. Không có vế này
        # thì mọi yêu cầu ảnh rơi vào fallback kết thúc bằng MÀN HÌNH TRỐNG.
        if self._media_cho_chon is not None:
            args = {**self._media_cho_chon, "_gui_het": True}
            logger.info("dispatcher: lượt kết thúc mà candidates chưa được chốt → gửi cả rổ")
            await self._gui_media_bu(args)
            return

        # ② Câu hỏi có ý định xem ảnh mà mô hình không gọi send_media.
        code = getattr(self.customer, "project_interest", "") or ""
        if self._y_dinh_hinh_anh and code:
            logger.info(
                "dispatcher: ý định %s nhưng send_media không được gọi → tự gửi (project=%s)",
                self._y_dinh_hinh_anh,
                code,
            )
            await self._gui_media_bu({"query": "", "project_code": code, "category": self._y_dinh_hinh_anh})

    async def _gui_media_bu(self, args: dict) -> None:
        """Gọi send_media rồi phát cho client. Nuốt mọi lỗi: đây là lưới đỡ, nó
        không được phép làm vỡ một lượt đã trả lời xong."""
        try:
            result = await self._exec("send_media", args)
            await self.callbacks.on_tool_done("send_media", result)
        except Exception:
            logger.warning("dispatcher: gửi media bù thất bại", exc_info=True)

    async def _auto_escalate(self, source_tool: str, args: dict) -> None:
        esc_args = {
            "action": "transfer",
            "department": self.handoff_department,
            "reason": (
                f"Hệ thống không có dữ liệu trả lời khách ({source_tool}: {json.dumps(args, ensure_ascii=False)[:120]})"
            ),
        }
        try:
            await self.callbacks.on_tool_start("escalate", esc_args)
            result = await support_ops.escalate(
                self.state,
                self.customer,
                esc_args,
                session_id=self.session_id,
                missing_data_tool=source_tool,
            )
            await self.callbacks.on_tool_done("escalate", result)
        except Exception:
            logger.exception("dispatcher: auto-escalate after %s failed", source_tool)

    async def _exec(self, name: str, args: dict) -> str:
        spec = registry.resolve(self.tenant, name)
        if spec is None:
            return json.dumps({"error": f"unknown tool {name}"})
        return await spec.executor(
            args,
            state=self.state,
            customer=self.customer,
            callbacks=self.callbacks,
            session_id=self.session_id,
            provider=self.provider,
            tenant=self.tenant,
            rag=self.rag,
            dispatcher=self,
        )
