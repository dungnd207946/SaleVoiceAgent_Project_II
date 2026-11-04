# Câu gợi ý follow-up sau mỗi lượt (quick-reply chips) — Design

- **Ngày:** 2026-07-13
- **Trạng thái:** Design (chờ implement qua noble-feature-flow)
- **Phạm vi đợt này:** Kênh **CHAT** (chat.html + chat trong app NobleX). Voice (LiveKit) hoãn.
- **Branch:** feature branch hiện tại (KHÔNG `develop`).

## 1. Mục tiêu

Sau **mỗi lượt Luna trả lời**, hiện 2–3 **chip gợi ý** để khách bấm gửi nhanh (ví dụ:
"Cho xem hình dự án", "Giá & chính sách", "Đặt lịch tham quan" như ảnh mockup). Chip phải
**bám ngữ cảnh** cặp hỏi–đáp vừa rồi, không phải một bộ tĩnh.

Ràng buộc lớn nhất: **không được làm chậm câu trả lời**. Gợi ý là thứ yếu → sinh **sau** khi
lượt đã stream xong và event `done` đã gửi.

## 2. Quyết định thiết kế (đã chốt)

| Vấn đề | Lựa chọn | Lý do |
|---|---|---|
| Nguồn sinh chip | **LLM phụ, chạy SAU lượt (async)** | Bám ngữ cảnh tốt nhất; nằm ngoài critical path; sạch kiến trúc (giống summary/warm fire-and-forget) |
| Kênh | **Chat trước**, voice sau | Khách voice ít bấm chip; chat.html đã có sẵn renderer `setChips` |
| Vị trí generation | **`TurnRunner` (orchestrator)** | Dùng lại `self._llm` / `self._model_map` / `self._repo` như summarizer; bật voice sau chỉ là thêm 1 event delivery |
| Delivery | **event mới `suggestions`, gửi sau `done`** | `done` không bị trễ; event rời khớp bản chất async |
| Chip bấm | **gửi luôn** (`text`) | Khớp hành vi tester hiện có; app mobile tự quyết UX của nó |
| Số chip | **tối đa 3** | Khớp mockup; đủ gọn cho mobile |
| Gate | `NOBLE_SUGGESTIONS_ENABLED` **default `true`** | Đây là tính năng người dùng muốn; vẫn tắt được nếu cần |

## 3. Kiến trúc & data flow (một lượt chat)

```
user_text
  → run_turn → token… → tool_done… → done          ← KHÁCH ĐÃ CÓ CÂU TRẢ LỜI (critical path xong)
                                        │
                                        ↓ ensure_future — KHÔNG chặn vòng đọc WS
                     facade.suggest_followups(sid) → TurnRunner.suggest_followups(sid)
                       ├─ repo.load(sid) → (meta, customer, state)
                       ├─ lấy last user + last assistant text từ state.history
                       ├─ build_suggestions_prompt(exchange, customer)
                       ├─ llm.simple_completion(prompt, model=self._model_map,
                       │        primary=self._suggestions_primary, max_tokens≈200, temperature≈0.4)
                       └─ parse_suggestions(text, max_n=3) → [{label,text}]  (lỗi/rỗng → [])
                                        │
                                        ↓ chỉ khi items KHÔNG rỗng
              send({"type":"suggestions","items":[{label,text}, …]})
                                        │
                                        ↓
              chat.html: case 'suggestions' → setChips(items)
```

Không có state mới trong Redis. Không đọc/ghi Mongo. Chỉ là một call LLM đọc-thoáng dựa trên
history có sẵn.

## 4. Thành phần (thay đổi tối thiểu, chat-first)

### 4.1 `src/noble_agent/agent/suggestions.py` (MỚI) — thuần, dễ test

- `build_suggestions_prompt(user_text: str, assistant_text: str, customer: Customer) -> str`
  - Prompt tiếng Việt gọn: "Dựa vào đoạn hội thoại giữa khách và trợ lý Luna, đề xuất **tối đa 3**
    câu **KHÁCH có thể nói/hỏi tiếp** với Luna. Ngắn gọn, tự nhiên, đúng vai khách. Mỗi mục có
    `label` (nhãn ngắn ≤ 24 ký tự hiện trên nút) và `text` (câu đầy đủ khách sẽ gửi). **Nếu không
    có gợi ý phù hợp (khách đã tạm biệt / đã được chuyển chuyên viên / đã chốt lịch) → trả mảng
    rỗng.** Chỉ trả JSON, không giải thích."
  - Nhúng vài trường hồ sơ nhẹ (project_interest, purpose) nếu có, để gợi ý sát hơn.
  - Yêu cầu output JSON dạng: `[{"label":"…","text":"…"}, …]`.
- `parse_suggestions(raw: str, max_n: int = 3) -> list[dict]`
  - Bóc JSON (chịu được rào ```json … ``` hoặc text thừa quanh JSON — tìm mảng `[…]` đầu tiên).
  - Validate từng item: có `label` **và** `text` (str, non-empty). Cắt `label` về ≤ 24 ký tự.
  - Trả tối đa `max_n`. Mọi lỗi parse → `[]` (không raise).

### 4.2 `src/noble_agent/agent/orchestrator.py` — `TurnRunner.suggest_followups`

```python
async def suggest_followups(self, sid: str) -> list[dict]:
    if not self._settings.suggestions_enabled:
        return []
    try:
        _meta, customer, state = await self._repo.load(sid)
        user_text, assistant_text = _last_exchange(state.history)   # helper cục bộ
        if not user_text or not assistant_text:
            return []
        prompt = build_suggestions_prompt(user_text, assistant_text, customer)
        raw = await self._llm.simple_completion(
            prompt, model=self._model_map,
            primary=self._suggestions_primary, max_tokens=200, temperature=0.4,
        )
        return parse_suggestions(raw, max_n=3)
    except Exception as exc:      # tool/side-path boundary: không bao giờ raise
        logger.warning("suggest_followups failed: %s", exc)
        return []
```

- `_last_exchange(history)`: câu `role=user` cuối cùng + text `role=assistant` cuối cùng theo sau nó.
  Bỏ qua tool messages. Nếu assistant cuối trống (chỉ tool_calls) → `[]`.
- `self._suggestions_primary`: tính trong `__init__` bằng `config.primary_for(settings,
  settings.suggestions_model)` — **mirror y hệt `self._summary_primary`**. Rỗng/unknown → `None`
  (dùng chain mặc định).

### 4.3 `src/noble_agent/agent/facade.py` — expose

```python
async def suggest_followups(self, session_id: str) -> list[dict]:
    return await self._runner.suggest_followups(session_id)
```

### 4.4 `src/noble_agent/server/text_chat.py` — delivery (chat)

Sau khi `send({"type":"done", …})` (trong `finally`, sau khi drain xong), thêm:

```python
if get_settings().suggestions_enabled:
    async def _emit_suggestions() -> None:
        items = await llm.suggest_followups(session_id)
        if items:
            await send({"type": "suggestions", "items": items})
    asyncio.ensure_future(_emit_suggestions())
```

- `ensure_future` → **không chặn** vòng đọc WS / lượt kế tiếp (giống pattern `_send_json` bên voice).
- Chỉ gửi khi `items` không rỗng.
- `session_id` đã có trong scope handler.

### 4.5 `static/chat.html` — render (renderer đã có sẵn)

- WS handler: thêm `case 'suggestions': setChips(ev.items); break;`
- Khi khách gửi tin mới (`sendText`) → `dropChips()` ngay (chip cũ biến mất khi bắt đầu lượt;
  chip mới hiện khi có event `suggestions`). `START_CHIPS` giữ nguyên cho lời chào.

### 4.6 `src/noble_agent/config.py` — 2 field mới

| Env | Default | Ý nghĩa |
|---|---|---|
| `NOBLE_SUGGESTIONS_ENABLED` | `true` | Bật/tắt sinh chip gợi ý sau mỗi lượt |
| `NOBLE_SUGGESTIONS_MODEL` | `""` | Pin primary provider cho call gợi ý (mirror `NOBLE_SUMMARY_MODEL`). Phải khớp một `<P>_MODEL`; rỗng/unknown → chain mặc định |

### 4.7 `docs/api/noblex-app-dev-guide.md` §2 — contract

- Thêm row vào bảng "Server gửi":
  `{"type":"suggestions","items":[{"label","text"}]}` | gợi ý follow-up, **gửi SAU `done`** →
  render chip; app bấm chip = gửi `text` như một `user_text`.
- Ghi rõ: `label` = chữ trên nút; `text` = nội dung gửi đi. Có thể **không có** event này nếu
  không có gợi ý phù hợp. Voice: **TBD** (đợt sau).

## 5. Event contract mới

```json
{"type":"suggestions","items":[
  {"label":"Cho xem hình dự án","text":"Cho mình xem vài hình ảnh dự án với em"},
  {"label":"Giá & chính sách","text":"Giá và chính sách hiện tại thế nào em?"},
  {"label":"Đặt lịch tham quan","text":"Mình muốn đặt lịch đi xem nhà mẫu"}
]}
```

Trùng khít contract `setChips([{label,text}])` đang có trong `chat.html`.

## 6. Edge cases

| Tình huống | Hành vi |
|---|---|
| Lượt kết thúc bằng escalate / chào tạm biệt / đã chốt lịch | Prompt hướng dẫn → LLM trả `[]` → không gửi event, không hiện chip |
| Call phụ lỗi / timeout | `[]`, im lặng; lượt vẫn hoàn tất bình thường (event `done` đã gửi trước đó) |
| Assistant cuối chỉ có tool_calls (chưa có text) | `_last_exchange` → `[]` (không có gì để gợi ý theo) |
| `NOBLE_SUGGESTIONS_ENABLED=false` | `suggest_followups` trả `[]` ngay, không call LLM |
| LLM trả JSON rác / có văn bản thừa | `parse_suggestions` bóc mảng `[…]` đầu tiên; không parse được → `[]` |
| Item thiếu `label`/`text` hoặc rỗng | Bỏ item đó; giữ các item hợp lệ (≤ 3) |

## 7. Chi phí & độ trễ

- **+1 call LLM nhỏ mỗi lượt** (`max_tokens≈200`), model = chain agent hiện tại (gemini-2.5-flash)
  hoặc pin riêng qua `NOBLE_SUGGESTIONS_MODEL`.
- **Ngoài critical path**: TTFA, token stream, event `done` không bị ảnh hưởng. Chip xuất hiện
  trễ hơn câu trả lời khoảng vài trăm ms — chấp nhận được (follow-up).
- Tắt hoàn toàn được bằng env.

## 8. Testing

`tests/unit/unified/test_suggestions.py` (mới):

- `parse_suggestions`: JSON hợp lệ → đúng list; cắt còn 3 khi LLM trả > 3; cap `label` ≤ 24 ký tự;
  JSON bọc ```json fence → vẫn bóc được; rác/rỗng/không phải mảng → `[]`; item thiếu field → bị loại.
- `build_suggestions_prompt`: chứa cả `user_text` lẫn `assistant_text`; có chỉ dẫn "mảng rỗng khi
  không phù hợp".
- `TurnRunner.suggest_followups` (fake `_repo` + fake `_llm`): disabled → `[]` (không gọi llm);
  history thiếu exchange → `[]`; `_llm.simple_completion` raise → `[]`; happy path → list parse đúng.
- (Tùy chọn, nếu chi phí thấp) forwarding test cho `text_chat`: một lượt có `suggestions_enabled`
  → sau `done` phát đúng event `{"type":"suggestions","items":[…]}`; `items` rỗng → không phát event.

Gate chất lượng: `make test-unit` xanh, `ruff check` sạch.

## 9. Out of scope

- Kênh **voice** (LiveKit data channel) — generation đã nằm ở `TurnRunner` nên bật sau chỉ là thêm
  1 event `suggestions` qua data channel + 1 nhánh render ở `livekit.html`.
- Render chip trong app mobile — app-team tự làm theo contract §4.7.
- Số chip / độ dài / hành vi bấm tùy biến qua env.
- Cache/dedup gợi ý giữa các lượt.

## 10. Transition

Sau khi user duyệt spec này → implement qua harness **noble-feature-flow** (planner đọc spec →
tdd-implementer → code-reviewer + qa-verifier song song). Cập nhật `CLAUDE.md` Change Log +
memory `santa-media-send-via-app.md`-style entry cho tính năng khi hoàn tất. KHÔNG commit/push/PR
khi chưa được yêu cầu.
