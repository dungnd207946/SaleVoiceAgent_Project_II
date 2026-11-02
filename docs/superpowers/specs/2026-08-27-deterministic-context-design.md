# Context xác định: session facts + compaction kết quả tool + summary có khung (bước 3) — 2026-08-27

**Phạm vi:** `agent/session_facts.py` (mới), `agent/context_compaction.py` (mới),
`agent/tools/dispatcher.py`, `agent/runner.py`, `agent/orchestrator.py::_warm`,
`agent/summary/summarizer.py`, `persona/{chat,voice}/RULES.md` (một đoạn). Không đổi
schema Redis (chỉ thêm khoá `scratchpad["session_facts"]`), không đổi transport.

## Vấn đề (từ review 27/08, mục 2.1 / 2.2 / 4)

1. Hồ sơ khách trong system prompt **đóng băng cả phiên** (để giữ prefix cache) —
   tên / ngân sách / dự án khách vừa cho chỉ tồn tại trong history dạng tool-call; sau
   summary, nếu bản tóm tắt bỏ sót thì quy tắc "chưa có hồ sơ → hỏi tên" kích hoạt lại.
2. Kết quả tool nằm **nguyên văn** trong history 4–9 user-turn: 20–50k ký tự JSON cũ
   mỗi lượt — tốn prefill, pha loãng attention (model lấy nhầm giá căn cũ).
3. Summary là một đoạn văn < 200 từ không cấu trúc — mã căn, tài liệu, lịch hẹn rơi.

## Quyết định

- **`session_facts`** — bộ nhớ XÁC ĐỊNH do code ghi từ kết quả tool (dispatcher, sau exec
  thành công, không sandbox): căn đã giới thiệu (mã, PN, giá, dự án; 8 gần nhất), tài liệu
  đã gửi (4), media đã gửi (6), lịch đã chốt, đã chuyển chuyên viên. `render(state,
  customer)` dựng khối `[Ngữ cảnh hiện tại — hệ thống tự cập nhật, không phải lời khách]`
  gồm **hồ sơ mới nhất** (tên + xưng hô, dự án quan tâm kèm tên, ngân sách, khu vực, PN,
  mục đích, ghi chú) + các fact trên; rỗng khi chưa có gì.
- **Chèn ở ĐUÔI context, không phải system prompt**: runner ghép khối vào đầu user message
  cuối của REQUEST (`build_request_messages(..., ephemeral=...)`). System prompt và history
  persist không đổi → prefix cache của provider không bị ảnh hưởng (phần đuôi vốn thay đổi
  mỗi lượt). Chọn "prepend vào user message" thay vì message `system` giữa hội thoại vì
  cả 5 provider đều chắc chắn chấp nhận; persona có một câu giải thích khối này là của hệ
  thống, có tên trong đó thì không hỏi tên nữa.
- **Compaction**: khi dựng request, tool message của các lượt cũ hơn 2 user-turn cuối
  được thay bằng digest theo tool (`kb_search` → query + tiêu đề mục; `search_units` /
  `recommend_units` → mã căn (PN, giá, dự án); `discover_projects` → tên dự án; `get_document`
  → tiêu đề; `send_media` → số + caption; còn lại → 250 ký tự đầu). Kết quả ≤ 300 ký tự giữ
  nguyên. Bản đầy đủ vẫn trong `state.history` (transcript / eval / summary không đổi).
  Giá phải trả: message vừa rơi khỏi cửa sổ đổi nội dung một lần → prefix cache vỡ tại
  điểm đó (~2 lượt cuối); system + history xa hơn vẫn hit. Warm cache dựng qua
  `build_warm_messages` (cửa sổ trượt 1) để khớp lượt live kế tiếp.
- **Summary có khung**: 4 mục cố định `KHÁCH: / ĐÃ TRA: / ĐÃ CHỐT: / CÒN MỞ:`, yêu cầu giữ
  nguyên mã căn / tên dự án / con số / tên tài liệu; `max_tokens` 400 → 500.

## Không làm (cố ý)

- Không đổi cơ chế đóng băng customer block — lý do cache vẫn đúng.
- Không đưa session facts vào persist ngoài scratchpad (Redis đã có, TTL theo phiên).
- Không dùng LLM để tóm tắt tool result: digest là cắt xác định, rẻ, lặp được.

## Kiểm chứng

- Unit: `test_context_compaction.py`, `test_session_facts.py`, wiring ở `test_dispatcher.py`,
  `test_runner.py`, `test_cache_warm.py`, khung summary ở `test_summarizer.py`, persona ở
  `test_persona_skeleton.py`.
- Probe giữ ngữ cảnh đa lượt (LLM thật): hội thoại 6 lượt có tool result giả (kb_search,
  search_units 3 căn, get_document, booking), hỏi 3 câu "nhớ" (tên + ngân sách; 3 mã căn;
  ngày giờ + mã lịch + tài liệu), điểm = tỷ lệ fact xuất hiện trong câu trả lời, 3 lần/câu.
  Bốn biến thể: request cũ / mới × trước summary / sau summary (chỉ còn summary + 2 lượt cuối).

Kết quả (`scripts/probe_context_retention.py`, temperature 0.4, 3 lần/câu; điểm = tỷ lệ fact
trong câu trả lời, so khớp có chuẩn hoá):

| Biến thể | gemini-3.7-flash (tên+NS / 3 căn / lịch+tài liệu) | qwen3.7-flash |
|---|---|---|
| cũ, trước summary | 0.67 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |
| mới, trước summary | 0.67 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |
| cũ, sau summary | 1.00 / 1.00 / 0.89 | 1.00 / 1.00 / 1.00 |
| mới, sau summary | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |

Đọc kết quả:
- Không regression; kịch bản này cả hai model đều nhớ tốt kể cả bản cũ, nên probe chủ yếu
  chứng minh compaction + khối ngữ cảnh **không làm mất** gì (0.67 ở gemini là "3 tỷ rưỡi"
  chưa khớp regex, cả cũ lẫn mới). Summary có khung giữ đủ mã căn / lịch / tài liệu (cả biến
  thể "cũ, sau summary" cũng dùng khung mới — probe không dựng lại prompt summary cũ).
- Cái đo được chắc chắn là **kích thước request**: phần history của request trên hội thoại
  này cũ 7 132 → mới 3 944 ký tự (−45 %); khối ngữ cảnh 373 ký tự.
- Gemini gọi `no_lookup_needed` ở hầu hết lượt "nhớ" (cả cũ lẫn mới) — trên prod đã ép tool
  vòng đầu nên không tốn thêm; ngoài prod là một round-trip thừa, đã ghi nhận ở review 2.3.
- Chưa đo được `context_retention` / `hallucination` bằng judge trên 100 case — cần
  `EVAL_TENANT_API_KEY` (`make eval-quality --judge`).
