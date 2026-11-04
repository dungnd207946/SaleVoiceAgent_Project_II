"""Bộ đếm tiêu thụ in-memory — lớp DUY NHẤT của billing chạm đường nóng.

Hai loại phép đo sống ở đây:

* **Sự kiện** (lời gọi LLM) — rời rạc, append khi xảy ra.
* **Đồng hồ đo** (thành phần audio) — liên tục, nên meter giữ số tích luỹ và
  ``drain()`` chỉ phát ra phần tăng thêm kể từ lần drain đã commit. VAD và
  thời lượng cuộc gọi chạy bất kể có lượt nào đang diễn ra hay không; ghi số
  tích luỹ thay vì delta sẽ tính tiền hai lần cùng một quãng âm thanh.

Mọi thứ ở đây là số học O(1): không await, không khoá, không serialize.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

MAX_PENDING = 2000

# Khuôn 0 của đồng hồ đo audio — thêm trường mới thì thêm ở ĐÂY và trong drain().
_ZERO_TOTALS = {"audio_sec": 0.0, "wall_ms": 0.0, "units": 0.0, "text_units": 0.0}

# Các phép đo chạy ngoài phạm vi một lượt hội thoại → turn_idx NULL.
# Khoá theo (component, purpose), KHÔNG theo component đơn thuần: cùng một
# component có thể mang cả phép đo per-turn lẫn phép đo cả-phiên — stt vừa có
# giây-khách-nói của lượt (conversation) vừa có thời-gian-stream-mở của cả
# cuộc gọi (stream); khoá theo component sẽ kéo cả hai về một phía.
_SESSION_SCOPED = frozenset(
    {
        ("vad", "conversation"),
        ("call", "session"),
        ("stt", "stream"),
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class UsageRow:
    component: str
    purpose: str = "conversation"
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    audio_sec: float = 0.0
    wall_ms: float = 0.0
    # units = SỐ LẦN GỌI/sự kiện gộp trong dòng (lời gọi LLM, clause synth,
    # lần mở stream...). text_units = LƯỢNG TEXT theo ký tự (transcript STT ra,
    # ký tự vào TTS, ký tự đem embed) — cơ sở tính tiền của các vendor đếm chữ.
    units: int = 0
    text_units: int = 0
    exact: bool = True
    turn_idx: int | None = None
    # Thời điểm PHÁT SINH, đóng dấu lúc dòng được tạo — KHÔNG phải lúc INSERT.
    # Contract §8: "Dòng đến muộn, occurred_at vẫn đúng thời điểm phát sinh".
    # Để DB default now() thì một lô bị PG chết chặn qua nửa đêm cuối tháng sẽ
    # rơi vào kỳ hoá đơn sau (Portal rollup gộp theo occurred_at). Chỉ là một
    # phép lấy giờ trong RAM, không phải I/O.
    occurred_at: datetime = field(default_factory=_now)


class UsageMeter:
    """Một instance mỗi phiên. Không async, không I/O."""

    def __init__(
        self,
        *,
        session_id: str,
        channel: str,
        max_pending: int = MAX_PENDING,
        start_seq: int = 0,
    ) -> None:
        """``start_seq`` = seq đầu tiên lô của meter này được dùng.

        Khác 0 chỉ ở một tình huống: phiên được RESUME (hoặc bị LRU-evict rồi
        dựng lại) nên meter mới phải tiếp tục sau seq cao nhất chặng trước đã
        dùng — dùng lại seq cũ là mọi dòng trùng khoá và bị DO NOTHING bỏ đi.
        Xem ``billing/context.py`` (bản đồ high-water).
        """
        self.session_id = session_id
        self.channel = channel
        self.turn_idx = 0
        self.dropped = 0
        self._max_pending = max_pending
        self._seq = start_seq
        self._events: list[UsageRow] = []
        # (component, purpose) -> {"audio_sec", "wall_ms", "units"}
        self._totals: dict[tuple[str, str], dict[str, float]] = {}
        self._written: dict[tuple[str, str], dict[str, float]] = {}
        # Lô đã drain nhưng chưa xác nhận ghi thành công.
        self._inflight: tuple[int, list[UsageRow], dict[tuple[str, str], dict[str, float]]] | None = None

    @property
    def pending_count(self) -> int:
        return len(self._events)

    @property
    def next_seq(self) -> int:
        """Seq nhỏ nhất mà một meter MỚI của cùng phiên được phép dùng.

        Lô inflight chưa commit vẫn tính là **đã dùng**: nó có thể thực sự đã
        landed (lỗi xảy ra lúc trả lời), nên dùng lại seq đó cho dữ liệu mới sẽ
        khiến dữ liệu mới trùng khoá và biến mất im lặng.
        """
        return self._seq + 1 if self._inflight is not None else self._seq

    def add_llm(
        self,
        *,
        purpose: str,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
        wall_ms: float = 0.0,
        exact: bool = True,
    ) -> None:
        """``wall_ms`` = thời gian của CHÍNH lời gọi này (contract §2.1: llm.wall_ms
        là tổng thời gian stream LLM; các lời gọi gộp trong một dòng thì cộng lại).
        Đây là số giá vốn nội bộ, KHÔNG tính cho khách."""
        self._append(
            UsageRow(
                component="llm",
                purpose=purpose,
                provider=provider or "",
                model=model or "",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_write_tokens=cache_write_tokens,
                cache_read_tokens=cache_read_tokens,
                wall_ms=wall_ms,
                units=1,
                exact=exact,
                turn_idx=self.turn_idx,
            )
        )

    def add_embed(
        self,
        *,
        provider: str,
        model: str,
        chars: int,
        wall_ms: float = 0.0,
        input_tokens: int = 0,
    ) -> None:
        """Một lời gọi embed (contract §2.1 ``component='embed'``).

        Đi qua đường **sự kiện**, không phải đồng hồ đo: mỗi lời gọi là một biến
        cố rời rạc có giá riêng, không phải một quãng liên tục như VAD. Nhờ đó nó
        dùng luôn khoá gộp ``(component, purpose, provider, model)`` của
        ``_aggregate_events``, nên nhánh dense TRẢ PHÍ (``gemini`` /
        ``service``) không bị trộn vào nhánh sparse chạy LOCAL trên CPU của ta
        (``fastembed``) — hai thang giá khác nhau, gộp một dòng là Portal không
        còn tách được. Nếu dùng ``add_audio`` thì cả hai rơi vào cùng khoá
        ``("embed", "embed")`` và mất phân biệt đó.

        ``chars`` = **tổng ký tự của text đem embed** → cột ``text_units``, và là
        **cơ sở tính tiền của dòng embed** (2026-08-20, trước đó là số đoạn text
        trong ``units``): provider embed bill tỷ lệ theo lượng text vào — câu
        500 ký tự tốn hơn câu 10 ký tự, "số đoạn" không phản ánh được. ``units``
        = số lời gọi, thống nhất với mọi component khác.

        Không provider embed nào trả token count (Gemini ``batchEmbedContents``
        chỉ trả vector), nên ``input_tokens`` gần như luôn 0. ``exact`` vì thế để
        ``True``: nó nói về độ tin của cột token, mà cột token không phải cơ sở
        tính tiền ở đây — đặt ``False`` sẽ làm nhiễu vĩnh viễn thước đo
        "doanh thu đang rơi" mà Portal dựng trên tỷ lệ ``exact=false``.

        Lời gọi THẤT BẠI gọi vào đây với ``chars=0``: ``wall_ms`` vẫn là giá vốn
        thật đã tiêu, nhưng khách không phải trả cho lỗi của ta. Dấu hiệu lỗi
        trong bảng: ``wall_ms > 0`` mà ``text_units = 0``.
        """
        self._append(
            UsageRow(
                component="embed",
                purpose="embed",
                provider=provider or "",
                model=model or "",
                input_tokens=input_tokens,
                wall_ms=wall_ms,
                units=1,
                text_units=chars,
                turn_idx=self.turn_idx,
            )
        )

    def add_audio(
        self,
        component: str,
        *,
        purpose: str = "conversation",
        audio_sec: float = 0.0,
        wall_ms: float = 0.0,
        units: int = 0,
        text_units: int = 0,
    ) -> None:
        t = self._totals.setdefault((component, purpose), dict(_ZERO_TOTALS))
        t["audio_sec"] += audio_sec
        t["wall_ms"] += wall_ms
        t["units"] += units
        t["text_units"] += text_units

    def drain(self, *, turn_idx: int | None = None) -> tuple[int, list[UsageRow]] | None:
        """Lô cần ghi, hoặc None khi không có gì.

        ``turn_idx`` — dấu lượt cho các dòng audio **không** session-scoped.
        Bỏ trống thì dùng ``self.turn_idx`` hiện tại. Caller PHẢI truyền tường
        minh khi flush chạy bất đồng bộ: ``add_llm`` đóng dấu lúc append (trong
        lượt, = N) còn dòng audio đóng dấu tại đây, nên nếu ``self.turn_idx`` đã
        bị tăng trước khi task flush thực sự chạy thì cùng một lô ra hai
        ``turn_idx`` khác nhau. Xem ``orchestrator.handle_turn``.

        Lô chưa commit được trả lại **nguyên vẹn** (cùng seq, cùng nội dung):
        nếu lần ghi trước thực ra đã landed thì ``ON CONFLICT DO NOTHING`` giữ
        bản đầu, nên gộp thêm dữ liệu mới vào cùng seq sẽ làm dữ liệu mới biến
        mất im lặng. Dữ liệu mới chờ seq kế tiếp. Vì vậy nhánh replay **bỏ qua**
        ``turn_idx``: dòng đã đóng dấu rồi, đóng lại là đổi nội dung của một seq
        có thể đã landed.

        Returns copies of the rows, never live references to _inflight state.
        Callers cannot corrupt the replay by mutating returned objects.
        """
        if self._inflight is not None:
            seq, rows, _snapshot = self._inflight
            # Return fresh copies so callers cannot mutate the canonical batch
            return seq, [UsageRow(**vars(row)) for row in rows]

        stamp = self.turn_idx if turn_idx is None else turn_idx
        rows = self._aggregate_events()
        snapshot: dict[tuple[str, str], dict[str, float]] = {}
        for key, total in self._totals.items():
            written = self._written.get(key, _ZERO_TOTALS)
            d_audio = total["audio_sec"] - written["audio_sec"]
            d_wall = total["wall_ms"] - written["wall_ms"]
            d_units = total["units"] - written["units"]
            d_text = total["text_units"] - written["text_units"]
            if d_audio <= 0 and d_wall <= 0 and d_units <= 0 and d_text <= 0:
                continue
            component, purpose = key
            rows.append(
                UsageRow(
                    component=component,
                    purpose=purpose,
                    audio_sec=round(d_audio, 3),
                    wall_ms=round(d_wall, 1),
                    units=int(d_units),
                    text_units=int(d_text),
                    turn_idx=None if (component, purpose) in _SESSION_SCOPED else stamp,
                )
            )
            snapshot[key] = dict(total)

        if not rows:
            return None

        seq = self._seq
        self._inflight = (seq, rows, snapshot)
        self._events = []
        # Return fresh copies so callers cannot mutate the canonical batch
        return seq, [UsageRow(**vars(row)) for row in rows]

    def commit(self, seq: int) -> None:
        """Xác nhận lô ``seq`` đã ghi thành công; mở đường cho seq kế tiếp."""
        if self._inflight is None or self._inflight[0] != seq:
            return
        _seq, _rows, snapshot = self._inflight
        for key, total in snapshot.items():
            self._written[key] = total
        self._seq = seq + 1
        self._inflight = None

    # ── nội bộ ──────────────────────────────────────────────────────────
    def _append(self, row: UsageRow) -> None:
        self._events.append(row)
        while len(self._events) > self._max_pending:
            self._events.pop(0)
            self.dropped += 1

    def _aggregate_events(self) -> list[UsageRow]:
        """Gộp theo ĐÚNG 4 cột khoá của contract: (component, purpose, provider, model).

        Khoá gộp phải trùng khít khoá UNIQUE của bảng
        ``(tenant_id, session_id, seq, component, purpose, provider, model)``.
        ``exact`` CỐ Ý không nằm trong khoá: nếu có, một lô có thể chứa hai dòng
        giống nhau ở cả 7 cột khoá và chỉ khác ``exact`` — dòng thứ hai đụng
        ràng buộc và bị ``ON CONFLICT DO NOTHING`` **bỏ đi không log**. Bẫy thật:
        lượt bị ngắt lời ghi ``exact=False`` token 0, ``save_all`` của lượt đó
        hỏng nên lô ở lại; lượt sau ghi ``exact=True`` với hàng nghìn token thật
        — cùng seq, và dòng bị nuốt là dòng mang token thật.

        Vì vậy token của mọi lời gọi được **cộng hết** (phần đo được vẫn là thật
        và vẫn phải tính tiền) và dòng gộp mang ``exact=False`` khi có bất kỳ
        lời gọi nào không đo được: cờ vẫn nói cho Portal biết dòng này đo thiếu
        một phần, chỉ không còn tách được phần nào thiếu.
        """
        merged: dict[tuple, UsageRow] = {}
        for e in self._events:
            key = (e.component, e.purpose, e.provider, e.model)
            cur = merged.get(key)
            if cur is None:
                merged[key] = UsageRow(**vars(e))
                continue
            cur.input_tokens += e.input_tokens
            cur.output_tokens += e.output_tokens
            cur.cache_write_tokens += e.cache_write_tokens
            cur.cache_read_tokens += e.cache_read_tokens
            cur.audio_sec += e.audio_sec
            cur.wall_ms += e.wall_ms
            cur.units += e.units
            cur.text_units += e.text_units
            cur.exact = cur.exact and e.exact
        return list(merged.values())
