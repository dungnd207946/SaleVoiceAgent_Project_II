# Prompt: một nguồn sự thật cho tool rules (bước 2 review chất lượng) — 2026-08-27

**Phạm vi:** `persona/chat/RULES.md`, `persona/voice/RULES.md`, `agent/tools/schemas.py`
(`build_schemas`). Không đụng `tenants/noble/persona/` (legacy, đóng băng) và không đổi
executor nào.

## Vấn đề

Cùng một quy tắc vận hành tool sống ở bốn nơi (Operational Protocol, bảng Tool catalog,
schema description, `instruction` trong JSON tool trả về), mỗi nơi một cách diễn đạt.
Prefix mỗi lượt ≈ 53k ký tự (chat) / 51k (voice); eval 25/08 cho thấy tool_selection phụ
thuộc mạnh vào model (0.28 → 0.94 cùng prompt) và `irrelevant_call_rate` 0.31–0.54.
Spec 2026-07-03 từng chọn "rule vận hành thuộc RULES, schema lean", nhưng rule đã trôi
ngược vào schema (booking description lặp quy tắc 8) — tức là hai nhà cho một thứ.

## Quyết định

- **Schema description = nơi DUY NHẤT** mô tả khi nào gọi, thứ tự bước, tham số, xử lý
  từng loại kết quả của một tool. Model đọc schema đúng lúc quyết định gọi.
- **RULES chỉ giữ quy tắc XUYÊN tool**: xưng hô, phân loại trong/ngoài phạm vi, tool trước
  khi trả lời / không bịa, update_customer ngay, find_project trước tool cần mã (kb_search
  đi thẳng), rỗng → nới, escalate + tín hiệu chuyển, style, guardrails; cộng persona
  (tư duy tư vấn, khi khách ngần ngại, tư vấn như người thật) đã rút gọn.
- Bỏ hẳn bảng Tool catalog. Quy tắc 6/8/12 cũ (find_project / booking / send_media) và
  mục analyze_projects / phong thủy chuyển vào description tương ứng.
- RULES giữ thêm một **bản đồ tool** 1 dòng/tool (index "nói gì → tool nào", ~1k ký tự, không
  phải protocol): probe round 2 cho thấy gemini-2.5-flash bỏ gọi booking / kb_search / escalate
  khi không có index (68 → 63/72), có index thì hồi lại — model yếu cần bảng định tuyến.
- Ngân sách khoá bằng test: rendered RULES chat ≤ 16 000 ký tự, voice ≤ 11 000.
- Gating theo tenant giữ nguyên cơ chế: marker `<!-- TOOL:x -->` trong RULES cho vài câu
  xuyên tool còn nhắc tên tool; phong thủy trong description `recommend_units` nằm giữa
  `[FENG_SHUI]…[/FENG_SHUI]`, `build_schemas` cắt khi ranker tắt (cùng cờ với
  `persona_compose`).
- `escalate.department` bỏ enum cứng của noble → free text (tenant khác có bộ phận khác;
  bỏ trống = `AgentDef.handoff_department`).

## Bản đồ chuyển nội dung

| Nội dung cũ (RULES) | Nhà mới |
|---|---|
| Quy tắc 6 — find_project resolved/ambiguous/not_found, thang xác nhận CÓ/KHÔNG, recently_listed | `find_project` description |
| Quy tắc 8 — 4 bước đặt lịch, tên/số riêng, modify chỉ field đổi | `booking` description |
| Quy tắc 12 — 3 trường hợp send_media, âm thầm, category_fallback, tour 360 | `send_media` description |
| Mục analyze_projects | `analyze_projects` description (+ voice: 1 dòng "đọc top 2–3") |
| Mục Phong thủy | `recommend_units` description `[FENG_SHUI]` |
| Tool catalog: search_units band note / recommend vs search / discover phân trang & nới | description tương ứng |
| Quy tắc 7 (kb_search sticky), 9/11 (escalate), 10 (rỗng→nới) | RULES (xuyên tool), rút gọn |

## Kết quả đo (compose đủ 14 tool, tenant mẫu)

| | HEAD | Mới | Δ |
|---|---|---|---|
| chat: system + schemas | 32 991 + 20 012 = 53 003 | 16 564 + 24 386 = 40 950 | −23 % |
| voice: system + schemas | 31 022 + 20 012 = 51 034 | 11 558 + 24 386 = 35 944 | −30 % |

Kiểm chứng hành vi: xem mục "Probe" bên dưới (cập nhật sau khi chạy) và, khi có
`EVAL_TENANT_API_KEY`, `make eval-quality` trên cùng bộ case trước/sau — gate loại 2 đã
chốt ở `thresholds.toml`.

## Probe chọn tool vòng đầu (LLM thật, tool result không cần)

Script: `scripts/probe_tool_selection.py` — 24 kịch bản, cùng persona config, system prompt
HEAD vs mới, so tập tool gọi ở vòng đầu với tập kỳ vọng (không cần tenant config / Redis).

Điều kiện: temperature 0.4, `max_tokens` 400, không ép tool (`LLM_FORCE_TOOL_FIRST_ROUND` tắt),
không chạy tool thật; `ok` = gọi ≥1 tool kỳ vọng và không gọi tool ngoài tập (update_customer
miễn trừ). Mỗi ô = số lượt đúng / 72 (24 kịch bản × 3 lần). "Cũ" = HEAD `2137d20`.

| Model | Cũ | Mới (không bản đồ tool) | Mới (bản cuối, có bản đồ tool) |
|---|---|---|---|
| gemini-3.7-flash | 69 | 72 | 69 |
| gemini-2.5-flash | 68 | 63 | 62–66 (2 lần chạy) |
| qwen3.7-flash | 48 | 55 | 54–55 |

Đọc kết quả:
- **gemini-3.7**: ngang cũ (69–72/72); chỉ trượt `region_budget` ("Ở Tây Hồ có dự án nào tầm
  4 tỷ") — kịch bản mơ hồ, bản cũ cũng 2/3.
- **qwen3.7**: +6–7 (48 → 54–55). Còn lại là thói quen gọi lại `find_project` khi khách nói
  "dự án này" dù hồ sơ đã có dự án quan tâm (cả cũ lẫn mới, 5 kịch bản) và không tra tool khi
  khách chê đắt — hai điểm đã có câu chặn trong description, qwen vẫn bỏ qua.
- **gemini-2.5**: tụt 2–6/72, dao động mạnh giữa các lần chạy (cùng kịch bản `intro_multi`
  0/3 → 3/3 → 0/3 với khác biệt prompt vài chục ký tự): model này nhạy với prompt và hay
  "nói đã làm" (đã ghi nhận / sẽ chuyển chuyên viên) mà không gọi tool. Bản đồ tool kéo
  `booking` / `escalate` về; `objection_price` (hỏi ngân sách thay vì tra vay) chưa về.
  Trên prod, `LLM_FORCE_TOOL_FIRST_ROUND=true` ép vòng đầu phải gọi tool nên các ca "none"
  ở đây không xảy ra y hệt — probe cố ý không ép để thấy xu hướng tự nhiên.
- Giới hạn: n = 3/kịch bản, chỉ đo vòng đầu, không đo câu trả lời / tham số / đa lượt. Kết
  luận chắc hơn cần `make eval-quality` (100 case, judge) trước/sau — chờ `EVAL_TENANT_API_KEY`.

Quyết định: giữ bản mới. Lợi ích cấu trúc (một nguồn sự thật, −23…30 % prefix) và cải thiện
trên qwen (model primary trong `.env`) + parity trên gemini-3.7 đủ bù cho tụt nhỏ, không ổn
định trên gemini-2.5 (model đang không phải primary). Nếu 2.5 quay lại làm primary, chạy
lại probe ×5 và cân nhắc thêm ví dụ cho `escalate`/`update_customer` vào bản đồ tool.
