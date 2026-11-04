# Review cấu trúc agent Luna — điểm có thể cải thiện chất lượng (2026-08-27)

Phạm vi: `src/noble_agent/agent/*` (turn loop, prompt/persona, tools, RAG, summary/memory) +
`evals/`. Đọc code + đo prompt đã compose + số liệu `evals/registry.jsonl`. Không sửa code.

## 0. Bức tranh hiện trạng (số đo, không phải cảm nhận)

**Kích thước prefix cố định mỗi lượt** (compose từ skeleton `persona/chat`, bật đủ 14 tool):

| Thành phần | Ký tự | Token (ước lượng, tiếng Việt ≈ 2.5–3.5 ký tự/token) |
|---|---|---|
| System prompt (SOUL + RULES + hồ sơ) | 32 851 | ~10–13k |
| 14 tool schema | 19 927 | ~6–8k |
| **Tổng prefix / lượt** | **~53k ký tự** | **~17–21k token** |

RULES.md chat = 42.9 KB nguồn, voice = 40.3 KB — diff giữa hai bản chỉ 262 dòng và gần như
toàn bộ là thay chữ ("tin nhắn" → "lượt nói"). Tách kênh **không** làm voice ngắn hơn.

**Eval quality gần nhất** (100 case, `kb_service`, tenant noble, 2026-08-25):

| Metric | gemini-3.7-flash | gemini-2.5-flash | qwen3.7-flash |
|---|---|---|---|
| tool_selection_accuracy | 0.94 | 0.28 | 0.40 |
| irrelevant_call_rate | 0.54 | 0.31 | 0.43 |
| banned_call_rate | — | 0.33 | — |
| policy_pass_rate | 0.99 | 0.86 | 0.71 |
| answer_correctness_mean | — | 0.47 | — |
| hallucination_rate | — | 0.33 | — |
| grounded_rate | — | 0.81 | — |
| context_retention | — | 0.79 | — |
| TTFT p50 / p95 | — | 2.3 s / 4.2 s | — |

Đọc chung: chất lượng **phụ thuộc mạnh vào model** (0.28 → 0.94 cùng prompt), tức là
prompt đang ở mức chỉ model mạnh nhất mới theo nổi. `irrelevant_call_rate` cao ở cả ba —
model gọi thừa tool. Đó là hai triệu chứng của cùng một nguyên nhân gốc (mục 1).

## 1. Bề mặt chỉ dẫn quá lớn và trùng lặp 3–4 nơi (tác động lớn nhất)

Cùng một quy tắc đang sống ở **bốn** chỗ, mỗi chỗ một cách diễn đạt hơi khác:

1. `RULES.md › Operational Protocol` (10.8k ký tự — riêng quy tắc 6 find_project ≈ 2.2k,
   quy tắc 8 booking ≈ 2.5k, quy tắc 12 send_media ≈ 2.3k);
2. `RULES.md › Tool catalog` (bảng 5k ký tự lặp lại "khi nào gọi tool gì");
3. `schemas.py` description (booking 2.6k, search_units 2.1k, update_customer 2.1k…);
4. `instruction`/`note`/`huong_dan` nhúng trong JSON tool trả về (`projects_info.py`,
   `support_ops.py`, `find_project.py`).

Hệ quả đo được: model nhỏ (2.5-flash, qwen) chọn tool sai/thừa; prefill ~20k token mỗi
lượt là phần lớn của TTFT 2.3 s; mỗi lần vá một hành vi lại thêm một đoạn (lịch sử
changelog cho thấy RULES chỉ tăng). Ngoài ra có mâu thuẫn nội tại: Style nói "tối đa 2–3
câu mỗi lượt" trong khi `style.reply_length_desc` (config tenant) có thể chèn "3–4 câu";
chat RULES vẫn ghi "đọc qua TTS" (thừa cho kênh chat).

**Đề xuất:**
- Chọn **một** nguồn sự thật cho "khi nào gọi tool": để ở schema description (model đọc
  schema đúng lúc quyết định gọi), bỏ bảng Tool catalog, rút Operational Protocol về các
  quy tắc *xuyên tool* (không bịa, xưng hô, escalate, rỗng thì nới). Mục tiêu RULES ≤ 15k ký tự.
- Với voice: viết bản **thật sự ngắn** (≤ 8–10k ký tự) — kênh này TTFT quan trọng nhất và
  câu trả lời ngắn nhất, không cần 3.3k ký tự "khi khách ngần ngại" bản đầy đủ.
- Đưa các hành vi có thể quyết định bằng code ra khỏi prompt (mục 3): booking step machine,
  find_project → mã, media, escalate — repo đã làm việc này nhiều lần (auto-escalate, lưới
  media cuối lượt, cap tool) và mỗi lần đều hiệu quả hơn thêm chữ vào RULES.
- Sau khi rút, chạy `make eval-quality` trên cả 3 model để xác nhận tool_selection không giảm;
  kỳ vọng irrelevant_call giảm và TTFT giảm rõ.

## 2. Turn loop / runner

### 2.1 Hồ sơ khách bị đóng băng — model chỉ "nhớ" qua history
`customer_block` render **một lần** đầu phiên (`orchestrator.handle_turn`), `run_turn` luôn
dùng bản đóng băng; `consume_customer_dirty()` hiện chỉ còn được gọi trong
`semcache/sandbox.py` — runner live **không** rebuild system prompt sau `update_customer`
(CLAUDE.md đang mô tả sai chỗ này). Việc đóng băng có lý do (giữ prefix ổn định cho prompt
cache theo phiên), nhưng hệ quả là tên/ngân sách/dự án khách vừa cho chỉ tồn tại trong
history dạng tool-call; sau summary (K=8, keep_tail=4) nếu bản tóm tắt bỏ sót tên → quy
tắc 1 "chưa có hồ sơ → hỏi tên" kích hoạt lại. `context_retention 0.79` khớp triệu chứng.

**Đề xuất:** chèn một khối **ephemeral** "Hồ sơ hiện tại" (5–6 dòng, render từ `Customer`
mỗi lượt) vào **cuối** context — ngay trước user message cuối, chỉ ở lúc dựng `messages`
trong `run_turn`, không persist vào history. Prefix cache không bị ảnh hưởng (phần đuôi
vốn thay đổi mỗi lượt), model luôn thấy hồ sơ mới nhất một cách xác định.

### 2.2 Kết quả tool tồn nguyên văn trong history
Cửa sổ verbatim = 4–9 user-turn; mỗi `kb_search` ≈ 5 × ≤1200 ký tự, `recommend_units` 6
căn × 12 trường, `get_project_overview` ~1–2k. Một cuộc gọi bình thường dễ mang 20–50k ký
tự JSON cũ trong context — vừa tốn prefill vừa pha loãng attention (model lấy nhầm giá của
căn cũ).

**Đề xuất:** *tool-result compaction*: khi dựng `messages`, tool message của các lượt cũ
hơn N=2 user-turn được thay bằng digest ngắn (vd `kb_search` → 1 dòng "đã tra: <query> →
<3 tiêu đề mục>"; `recommend_units` → danh sách `mã căn (PN, giá)`). Chỉ thay lúc build
request, history persist giữ nguyên để transcript/eval không đổi.

### 2.3 `LLM_FORCE_TOOL_FIRST_ROUND` nhân đôi round-trip ở lượt xã giao
Với `tool_choice=required`, mọi lượt chào hỏi phải đi `no_lookup_needed` rồi mới gọi LLM
lần hai → TTFT × 2 cho đúng loại lượt cần nhanh nhất; và `no_lookup_needed` có thể bị
scorer đếm vào irrelevant_call (0.54 trên 3.7-flash cần kiểm tra run đó bật cờ hay không).
Đây là nạng cho qwen bỏ tool 44% lượt — nếu qwen còn là primary thì giữ, nhưng nên đo riêng
"TTFT lượt không tool" và tắt cờ khi chạy gemini-3.7.

### 2.4 Barge-in: history ghi cả phần khách chưa nghe
`_stream_once` cắt ở **thời điểm LLM** bị ngắt, còn TTS phát chậm hơn nhiều (synth-ahead).
`VoiceAgent.spoken_text_this_turn` đã theo dõi đúng phần đã phát, nhưng không có đường nào
cắt `assistant.content` trong `state.history` về phần đó. Model lượt sau tin rằng mình đã
nói những câu khách không hề nghe (đã giới thiệu căn X, đã hỏi Y…).

**Đề xuất:** khi interrupt, orchestrator/transport cắt content của assistant message cuối
về `spoken_text_this_turn` + hậu tố "(bị ngắt)". Thay đổi nhỏ, chỉ voice.

### 2.5 Nhiệt độ 0.7 cho agent gọi tool
`agent_temperature=0.7` (DB path). Với agent mà 60–70% giá trị nằm ở chọn đúng tool + tham
số đúng đơn vị (VNĐ), 0.7 là cao; hallucination 0.33 và arg_accuracy 0.86 là chỗ đáng thử
0.3–0.4 rồi so bằng eval (rẻ, một env var).

### 2.6 Doc drift
CLAUDE.md: `MAX_TOOL_ITERATIONS=5` (code: 7) và "if consume_customer_dirty → rebuild
system prompt" (không còn đúng ở runner live). Cần sửa cùng commit kế tiếp.

## 3. Tools & dispatcher

- **`update_customer` "mỗi field một call"** (quy tắc 4 + `_TOOL_CAP_EXEMPT`): tool vốn nhận
  nhiều field; quy tắc này sinh 3–4 tool message cho một câu khách tự giới thiệu, bơm
  history và `irrelevant_call_rate`, kèm 3–4 lần `fire_and_forget(save_customer_persistent)`.
  Đổi thành "gộp mọi field vào MỘT call" — chỉ sửa prompt + schema, không sửa executor.
- **`_auto_escalate` hardcode `department="CVTV"`** (`dispatcher.py:244`, `support_ops.py:125`)
  trong khi tenant config có `scope.handoff_department`. Tenant khác sẽ bị chuyển vào bộ
  phận không tồn tại. Lỗi multi-tenant thật, sửa nhanh.
- **Chỉ dẫn nằm trong JSON tool trả về** (`instruction`, `huong_dan`, `note`): hữu ích cho
  model nhỏ nhưng là nơi thứ tư chứa rule; nên ngắn, và đừng lặp lại điều RULES đã nói.
- **Heuristic intent tiếng Việt trong dispatcher** (`_suy_y_dinh_hinh_anh` — khớp "vị trí",
  "mặt bằng" rồi phải trừ "mặt bằng giá", "vị trí thanh toán"): lưới đỡ hợp lý nhưng dễ
  mục; cần giữ danh sách ngoại lệ có test, hoặc chuyển thành "media debt" do chính
  `send_media` khai báo thay vì đoán từ query của `kb_search`.
- Skeleton dùng chung vẫn mang tên Noble: `Customer.is_noble_customer`/`noble_info`,
  CUSTOMER_PROFILE "Đã là khách Noble", `_NO_MEDIA_MSG` cứng "anh/chị" — rò rỉ vào tenant
  khác qua DB path.

## 4. Summary & memory

- Summary trong phiên là **một đoạn văn < 200 từ, không cấu trúc**; mã căn / giá / tài liệu
  đã gửi / lịch đã chốt thường rơi. `recent_projects` (scratchpad) là bước đúng nhưng mới
  chỉ có mã dự án.
- **Đề xuất:** (a) *session facts* xác định bằng code — dispatcher ghi vào scratchpad từ
  kết quả tool: căn đã giới thiệu (mã, PN, giá), tài liệu/ảnh đã gửi, trạng thái booking,
  băn khoăn khách đã nêu — và render thành khối ngắn cùng chỗ với "Hồ sơ hiện tại" (2.1);
  (b) summary prompt theo khung cố định (Khách / Đã tra & kết quả chính / Đã chốt / Còn mở)
  thay vì "một đoạn duy nhất". Cả hai nâng `context_retention` mà không phụ thuộc model.
- Snapshot xuyên cuộc gọi theo SĐT (`memory/snapshot.py`) thiết kế tốt (lock, merge, không
  ghi nhận định hệ thống). Giữ.

## 5. RAG

- `kb_search` → `kb_service`: hybrid + RRF server-side, header `[dự án › mục]`, sticky dự án
  từ kết quả — hợp lý. `grounded_rate 0.81` cho thấy retrieval không phải điểm yếu nhất.
- Điểm nhỏ: `rag_top_k=3` vs `kb_search_top_k=5` (hai knob cùng nghĩa, hai default); không
  dedupe nhiều chunk cùng một tài liệu; không rerank. Chỉ đụng sau khi mục 1–2 xong.
- Lưu ý dev: `.env` local đang `NOBLE_RAG_BACKEND=empty` → mọi probe grounding chạy local
  là vô nghĩa (kb_search luôn rỗng). Nên ghi rõ ở `chat_repl` banner.

## 6. Evals — đã có harness tốt, chưa dùng hết

- `thresholds.toml` mới có gate loại 1; gate loại 2 (correctness / hallucination / latency)
  "cố ý chưa có, chốt sau baseline" — đã có ≥ 3 run 100 case → chốt được rồi. Không có gate
  thì mọi thay đổi prompt ở mục 1 không có lưới.
- Thiếu scorer **văn phong** dù đây là thứ vừa sửa bằng tay và đo bằng tay (29/32 tin mở
  "Dạ", "ạ" 50→21%): một linter xác định (đếm "ạ"/tin, mở đầu "Dạ", ký tự markdown, > 1 dấu
  hỏi/tin, tên khách lặp) là vài chục dòng, chạy không cần judge, bắt regression Style ngay.
- Case: `cases/noble` rỗng, 100 case synthetic `noblex_sales` + `aina_prod`; objection chỉ
  có 7 case ở `du_test`. Bổ sung 20–30 case multi-turn "ngần ngại / đổi tiêu chí / quay lại
  sau summary" — đúng các đường vừa được viết rule.
- Luôn chạy eval trên **cùng** model primary với prod (`.env` đang qwen3.7-flash, run gần
  nhất là gemini-2.5-flash).

## 7. Điểm mạnh nên giữ

- Bất biến history (tool_calls ↔ tool messages, truncate về anchor khi crash, placeholder khi
  interrupt, `on_done` luôn bắn) — vững, có test.
- Cap tool/lượt + vòng chốt `tools=[]` khi chạm trần — chống loop thực dụng, đo thật.
- Lưới đỡ bằng code cho hành vi model làm không đều (auto-escalate, media cuối lượt,
  sticky project từ kết quả kb_search) — đúng hướng "code làm việc xác định".
- Fallback chain LLM + per-provider shaping, billing usage capture, tenant isolation theo
  collection/RLS, snapshot memory có lock.

## 8. Thứ tự làm (theo tác động / công sức)

1. **Sửa nhanh (≤ 1 ngày):** `_auto_escalate` dùng `handoff_department`; gộp field
   `update_customer`; thử `agent_temperature` 0.3–0.4; chốt gate loại 2 + style linter;
   sửa CLAUDE.md (2.6). Verify: `make eval-quality` trước/sau trên model prod.
2. **Rút prompt (2–3 ngày):** một nguồn sự thật cho tool rules, RULES chat ≤ 15k ký tự,
   voice ≤ 10k. Verify: tool_selection không giảm trên 2.5-flash + qwen, TTFT p50 giảm.
3. **Context xác định (2–3 ngày):** khối "Hồ sơ hiện tại + session facts" ephemeral cuối
   context; tool-result compaction cho lượt cũ; summary có khung. Verify: context_retention,
   hallucination, TTFT ở case ≥ 10 lượt.
4. **Voice:** cắt history về `spoken_text_this_turn` khi barge-in. Verify: SMOKE voice + một
   case eval "ngắt lời rồi hỏi 'em vừa nói căn nào'".

## 9. Trạng thái bước 1 (cập nhật 2026-08-27)

| Việc | Trạng thái | Ở đâu |
|---|---|---|
| `_auto_escalate` / `escalate` thiếu `department` → `AgentDef.handoff_department` | Xong, có test | `agent/base.py`, `agent/tools/dispatcher.py`, `agent/tools/builtins.py`, `agent/orchestrator.py` |
| `update_customer` gộp field vào MỘT lời gọi | Xong, có test | RULES chat/voice/legacy + `agent/tools/schemas.py` (cap runner vẫn miễn trừ) |
| Style linter + gate loại 2 | Xong, có test | `evals/quality/scorers/style.py`, `evals/quality/scorecard.py` (`judge = true` → `skipped`), `thresholds.toml` |
| CLAUDE.md drift + changelog | Xong | `CLAUDE.md`, `docs/CHANGELOG-agent.md`, `evals/README.md` |
| A/B `agent_temperature` 0.7 vs 0.4 | **Đã đo 27/08 — chênh trong nhiễu, giữ 0.7** | gemini-2.5-flash (model prod dev), 46 case `tool` của `aina_prod` chạy trên bản sao dữ liệu `aina_test` (`python -m evals run --tenant aina_prod --as-tenant aina_test --tag tool`, key `EVAL_TENANT_API_KEY` của `aina_test` qua tunnel dev), 1 lượt/mức — run `temp07-g25-tool` / `temp04-g25-tool` (registry): tool_selection 0.829 → 0.842 (+1 case), irrelevant_call 0.171 → 0.145, arg_accuracy 0.978 → 0.979, steps_overhead 1.039 → 1.026, policy_violations 5 → 3 (không cùng case: bịa ngày `30/08`, `7%`/`0%` — ngẫu nhiên), p50 3.70 → 3.67 s, p95 5.57 → 5.70 s; style_violation_rate 0.70 → 0.75 (xấu hơn). Chênh ≤ 1–2 case/46 = nhiễu một lượt; muốn kết luận cần ≥ 3 lượt/mức. Lỗi tool_selection lặp Y HỆT ở cả hai mức (SYN-TOOL-105/120/210/215: gọi `kb_search` thay `find_project`+`search_units`/`get_document`) ⇒ nguồn lỗi là prompt/schema (mô tả `kb_search` "đi thẳng" hút cả câu hỏi căn/tài liệu), không phải temperature. |

Chưa chạy `SMOKE.md` thủ công vì cùng lý do (không có tenant published config local).

## 10. Trạng thái bước 2 (2026-08-27)

| Việc | Trạng thái | Ở đâu |
|---|---|---|
| Schema description = một nguồn sự thật cho protocol từng tool | Xong, có test | `agent/tools/schemas.py` (find_project / booking / send_media / search_units / recommend_units `[FENG_SHUI]` / discover / analyze / escalate / kb_search) |
| RULES chat/voice chỉ còn quy tắc xuyên tool + bản đồ tool 1 dòng/tool + persona + style + guardrails | Xong, budget khoá bằng test (chat ≤ 16k, voice ≤ 11k rendered) | `persona/chat/RULES.md`, `persona/voice/RULES.md` |
| Prefix mỗi lượt | chat 53.0k → 41.0k ký tự (−23 %), voice 51.0k → 35.9k (−30 %) | spec |
| Kiểm chứng hành vi | Probe chọn tool vòng đầu (/72): gemini-3.7 69 → 69, qwen 48 → 54, gemini-2.5 68 → 62–66 | `scripts/probe_tool_selection.py`, spec `2026-08-27-prompt-single-source-of-truth-design.md` |
| Eval đầy đủ trước/sau | **Chưa** — cần `EVAL_TENANT_API_KEY` | `make eval-quality` |

## 11. Trạng thái bước 3 (2026-08-27)

| Việc | Trạng thái | Ở đâu |
|---|---|---|
| Khối "[Ngữ cảnh hiện tại]" ephemeral (hồ sơ mới nhất + session facts) ở đuôi context | Xong, có test | `agent/session_facts.py`, `agent/context_compaction.py`, `agent/runner.py` |
| Session facts do code ghi từ kết quả tool (căn / tài liệu / media / lịch / chuyển) | Xong, có test | `agent/session_facts.py`, `agent/tools/dispatcher.py` |
| Tool-result compaction cho lượt cũ (warm dùng cửa sổ trượt 1) | Xong, có test | `agent/context_compaction.py`, `agent/orchestrator.py` |
| Summary có khung 4 mục | Xong, có test | `agent/summary/summarizer.py` |
| Kiểm chứng | Probe giữ ngữ cảnh: không regression (gemini-3.7 / qwen); request −45 % ký tự phần history trên hội thoại mẫu | `scripts/probe_context_retention.py`, spec `2026-08-27-deterministic-context-design.md` |
| Eval judge (context_retention / hallucination) | **Chưa** — cần `EVAL_TENANT_API_KEY` | `make eval-quality ARGS="--judge"` |

## 12. Trạng thái bước 4 (2026-08-27)

| Việc | Trạng thái | Ở đâu |
|---|---|---|
| Cắt assistant cuối về `spoken_text_this_turn` khi barge-in | Xong, có test (14) | `agent/interrupt_trim.py`, `agent/facade.py::note_interrupted`, `voice/voice_agent.py::_trim_if_interrupted` |
| SMOKE voice thật (nói dài → ngắt → hỏi "em vừa nói tới đâu") | **Chưa** — không có tenant config local | `SMOKE.md` |

## 13. Eval đầy đủ sau 4 bước + fix routing (2026-08-27, chiều) — bảng CÙNG JUDGE

**Cách đo.** Key `EVAL_TENANT_API_KEY` thuộc `aina_test` (bản sao dữ liệu `aina_prod` trên odyssey-dev;
xác minh 4 case khớp golden) → 100 case `aina_prod` chạy bằng `--as-tenant aina_test` qua SSH tunnel
(Portal 8100 / PG 5442 / Qdrant 6343 / embed 8013), judge `qwen3.7-plus` (DashScope), temperature 0.7,
**1 lượt/ô** (chênh ≤ 2–3 case là nhiễu). Cột **before** = code `d3afdb9` (develop trước review, chính
là code của baseline 25/08) chạy lại hôm nay qua `PYTHONPATH` → cùng hạ tầng, cùng golden, cùng judge.

**Baseline 25/08 trong registry KHÔNG dùng được để so:** cùng code `d3afdb9`/`5e815a2` chạy lại hôm nay
cho gemini-2.5 tool_selection **0.832** (registry 25/08: 0.277) và gemini-3.7 policy **18** (25/08: 1),
correctness 0.60 (25/08: 0.80). Khớp với ghi chú handoff 25/08 "lần chạy đầu 26/26 kb_search rỗng vì
token stale": KB rỗng ⇒ không có con số để nêu ⇒ policy ≈ 0, và judge khác (gpt-5.4-nano). Mọi kết
luận dưới đây chỉ dựa trên các cột đo hôm nay.

### gemini-2.5-flash (model prod dev)

| metric | before `d3afdb9` | 4 bước `b458c69` | + fix giá `4053cdf` | + fix CSBH (fix2) |
|---|---|---|---|---|
| tool_selection_accuracy | 0.832 | 0.840 | **0.872** | **0.904** |
| arg_accuracy | 0.978 | 0.968 | 0.984 | 0.990 |
| banned_call_rate | 0.000 | 0.167 | 0.167 | 0.333 |
| irrelevant_call_rate | 0.272 | 0.208 | **0.192** | **0.176** |
| steps_overhead | 1.16 | 1.10 | 1.12 | 1.14 |
| policy_violations | 15 | 22 | 18 | 21 |
| TTFT p50 / turn p50 / p95 (s) | 2.6 / 3.0 / 4.7 | 3.1 / 3.5 / 5.4 | 3.3 / 3.8 / 5.8 | 3.3 / 3.8 / 6.0 |
| answer_correctness_mean (judge) | 0.604 | 0.551 | 0.588 | 0.584 |
| hallucination_rate (judge) | 0.309 | 0.412 | 0.375 | 0.397 |
| grounded_rate (judge) | 0.854 | 0.808 | 0.780 | 0.767 |
| context_retention_score (judge) | 0.845 | **0.920** | 0.895 | 0.915 |
| style_violation_rate / "Dạ" mở đầu | 0.897 / 0.750 | 0.632 / 0.404 | 0.807 / 0.556 | 0.706 / — |

### gemini-3.7-flash

| metric | before `d3afdb9` | 4 bước + fix giá `4053cdf` | + fix CSBH (fix2) |
|---|---|---|---|
| tool_selection_accuracy | 0.880 | **0.912** | 0.896 |
| arg_accuracy | 0.990 | 0.995 | 0.995 |
| banned_call_rate | 0.000 | 0.000 | 0.000 |
| irrelevant_call_rate | 0.384 | **0.312** | **0.264** |
| steps_overhead | 1.49 | 1.40 | 1.41 |
| policy_violations | 18 | 26 | 24 |
| TTFT p50 / turn p50 / p95 (s) | 7.6 / 7.7 / 24.5 | **6.1 / 6.2 / 15.3** | 6.7 / 6.9 / 19.7 |
| answer_correctness_mean (judge) | 0.600 | 0.609 | 0.579 |
| hallucination_rate (judge) | 0.390 | 0.397 | 0.404 |
| grounded_rate (judge) | 0.654 | **0.728** | 0.676 |
| context_retention_score (judge) | 0.860 | **0.950** | **0.950** |
| style_violation_rate / "Dạ" mở đầu | 0.551 / 0.419 | **0.066 / 0.059** | 0.081 / — |

qwen3.7-flash chỉ có cột after (`after-qwen-fix`: tool_selection 0.864, arg 0.979, irrelevant 0.264,
policy 26, p50 5.1 s, correctness 0.573, hallucination 0.426, retention 0.910, style 0.375) — chưa chạy
before cùng judge.

### Đọc số

- **Tool / context / style: đúng hướng ở cả hai model.** tool_selection +0.03–0.04, irrelevant −0.07–0.08,
  retention +0.05–0.09 (bước 3), style −0.09…−0.49 (mục Style "ăn" mạnh trên 3.7: 0.55 → 0.07; trên 2.5
  chỉ 0.90 → 0.63–0.81 — gemini-2.5 vẫn mở đầu "Dạ" ~50 %). Trên 3.7 latency giảm rõ (p50 −1.4 s,
  p95 −9 s: bớt tool call 2.31 → 2.15/lượt + prefix −30 %); trên 2.5 TTFT p50 **+0.5–0.7 s** dù tool
  call/lượt giảm 1.46 → 1.40 — chưa tách được code vs giờ chạy → A/B xen kẽ old/new (mục dưới).
- **Fix routing giá (4053cdf):** SYN-TOOL-105/120 từ "chưa có thông tin giá" (kb_search với mã đoán
  `SRL`/`NP`) → `find_project` → `search_units` → "4.3–5.2 tỷ, 67–81 m²" / "68–193 tỷ" đúng golden.
  Cột before cũng sai y hệt (105/120/210/215 → kb_search) — đoạn "giá → kb_search, GỌI THẲNG" đến từ
  commit perf `e21c2d9` (develop 25/08), bước 2 giữ nguyên; fix hôm nay sửa phần giá, fix2 sửa CSBH.
- **Regression thật cần xử lý: escalate + con số.** Escalate miss (khách đã mua / hợp đồng bất lợi /
  chuyển nhượng chưa sổ / cam kết lợi nhuận): 2.5: 0 → 2–3; 3.7: 2 → 4. Nêu %/chiết khấu trong reply
  (golden cấm): 2.5: 7 → 9; 3.7: 11 → 15. Nghi vấn: persona 26/08 "Tư vấn như người thật" + "Khi khách
  ngần ngại → KHÔNG escalate" (`b08b252`/`057737a`, SAU d3afdb9, TRƯỚC 4 bước) làm model trả lời từ KB
  thay vì chuyển; mốc `mid-g25-118931e` (code 26/08, chưa có bước nào) sẽ tách phần này khỏi 4 bước.
  Con số có thật trong CSBH (vay 70 %, chiết khấu 10–13 %, cam kết thuê 7 %/năm — KB có) mà golden
  cấm mọi con số → reviewer quyết qua labeller; con số KHÔNG có trong tool (cọc 50–100 triệu, phí bảo
  trì 2 % "theo Luật Nhà ở", lãi thả nổi 7,5 %) là bịa thật — judge groundedness đã gắn cờ.
- **Golden bug:** SYN-POL-507 `reply_not_contains "AI"` = substring lower-case → bắt brand **AINA** và
  chữ "ai" tiếng Việt, fail ở MỌI lượt (kể cả before) → đổi sang `reply_not_matches "\\bAI\\b"` sau khi
  ma trận xong (task J). banned_call 0.167 trên 2.5 = 1 case (SYN-QA-214 gọi escalate khi bị cấm).
- **Fix CSBH (fix2) trên 2.5:** SYN-TOOL-210/215 nay `find_project` → `get_document`, trả "3 CSBH, mới nhất
  02/07/2026" / "hiệu lực 09/05/2026" đúng golden; tool_selection 0.872 → **0.904** (before 0.832 ⇒ +0.07 tổng),
  irrelevant 0.192 → 0.176; policy 21 (±nhiễu; banned_call 2 case QA-214/…). 
- **Fix CSBH (fix2) trên 3.7:** 210/215 pass, irrelevant 0.312 → 0.264; tool_selection 0.912 → 0.896 (−2 case,
  nhiễu một lượt), p50 6.2 → 6.9 s (before 7.7). Tổng before → fix2 trên 3.7: tool_selection +0.02, irrelevant −0.12,
  retention +0.09, style 0.55 → 0.08, p95 −4.9 s; policy 18 → 24 (escalate miss 2 → 3, nêu % 11 → 15).
- **Mốc `mid` = code `118931e` (persona 26/08 "Tư vấn như người thật" + "Khi khách ngần ngại", CHƯA có bước
  nào của 27/08), gemini-2.5, cùng judge — tách nguồn regression:

  | metric | before `d3afdb9` | mid `118931e` | 4 bước `b458c69` | fix2 HEAD |
  |---|---|---|---|---|
  | tool_selection / irrelevant | 0.832 / 0.272 | 0.816 / 0.272 | 0.840 / 0.208 | **0.904 / 0.176** |
  | policy (escalate miss · nêu %) | 15 (0 · 7) | 21 (1 · 11) | 22 (3 · 9) | 21 (3 · 9) |
  | hallucination / grounded (judge) | 0.309 / 0.854 | 0.390 / 0.785 | 0.412 / 0.808 | 0.397 / 0.767 |
  | context_retention (judge) | 0.845 | 0.845 | **0.920** | 0.915 |
  | style_violation / "Dạ" mở đầu | 0.897 / 0.750 | 0.831 / 0.640 | **0.632 / 0.404** | 0.706 / 0.434 |
  | TTFT p50 / turn p95 (s) | 2.6 / 4.7 | 3.5 / 6.5 | 3.1 / 5.4 | 3.3 / 6.0 |
  | reply p50 (ký tự) · tool call/lượt | 220 · 1.46 | 253 · 1.48 | 271 · 1.38 | 245 · 1.43 |

  **before → mid (persona 26/08):** hallucination +0.08, grounded −0.07, nêu % 7 → 11, banned 0 → 2, TTFT +0.9 s,
  reply dài hơn 15 % — persona "tư vấn như người thật" (được phép "ước lượng, nêu giả định") khiến gemini-2.5
  thêm số liệu/kiến thức chung ngoài tool và nói dài hơn. **mid → 4 bước 27/08:** tool +0.02, irrelevant −0.06,
  retention +0.08, style −0.20, TTFT −0.4 s, p95 −1.1 s — đúng hướng; regression duy nhất thuộc 4 bước là
  **escalate miss 1 → 3** (khách đã mua / hợp đồng bất lợi / chuyển nhượng — RULES viết lại ở bước 2 làm mờ
  quy tắc "ngoài phạm vi → escalate NGAY"). **Việc tiếp theo:** (1) siết lại escalate cho nhóm post-sale/pháp
  lý trong RULES + mô tả `escalate` (test bằng QA-310/403/409, POL-405); (2) xem lại mục "Tiền bạc" của
  persona 26/08 — chỉ cho phép con số CÓ trong kết quả tool, bỏ "ước lượng thì nói là ước lượng" với model
  2.5; (3) golden nhóm "cấm mọi %" cần reviewer duyệt lại vì CSBH thật có số.
- **Latency — A/B xen kẽ old (d3afdb9) / new (HEAD), gemini-2.5, 46 case tool, không judge, 2 lượt mỗi bên
  (16:45–17:06 cùng khung giờ):**

  | run | tool_sel | call/lượt | TTFT p50 | TTFT p90 | turn p50 | turn p95 | TTFT p50 lượt 1 tool |
  |---|---|---|---|---|---|---|---|
  | lat-old-1 | 0.724 | 1.68 | 2.86 s | 4.28 | 3.32 | 5.03 | 2.47 s |
  | lat-new-1 | 0.816 | 1.60 | 4.59 s | 6.56 | 4.95 | 7.27 | 3.88 s |
  | lat-old-2 | 0.697 | 1.61 | 2.95 s | 4.51 | 3.34 | 5.97 | 2.35 s |
  | lat-new-2 | 0.842 | 1.55 | 3.90 s | 6.14 | 4.24 | 7.48 | 3.39 s |

  Code mới chậm hơn THẬT: TTFT p50 +1.0–1.7 s, ngay cả khi so cùng số tool call (lượt 1 tool: 2.4 → 3.4–3.9 s),
  reply dài tương đương ⇒ mỗi vòng LLM chậm thêm ~0.5–0.8 s. KHÔNG do độ dài prompt: prefix chat đủ tool
  (system + schema) d3afdb9 39 651 → 118931e 52 752 → HEAD **41 788** ký tự (system 22.9k → 32.8k → 16.6k;
  schema 16.8k → 19.9k → 25.2k). Mốc `mid` cho thấy bước nhảy nằm ở 26/08 (TTFT 2.6 → 3.5 s), 4 bước 27/08
  kéo lại ~0.4 s. Đã loại trừ: `find_project.get_index` (dict cache), `analytics_vocab` (TTL 600 s),
  `finish_turn` (chạy SAU reply, không vào TTFT). **Còn mở:** bisect 3 thay đổi 26/08 (persona `b08b252`,
  tool `analyze_projects` + `[VOCAB]` trong schema, `send_media` chủ động) và đo thời gian TỪNG vòng LLM
  (trace eval hiện chỉ có `ttft_ms`/`total_ms`, `tool_calls[]` không có duration). Đổi lại, lợi ích của
  4 bước về tool/irrelevant/style/retention ở trên là có thật ở cả 4 lượt (tool_selection old 0.70–0.72
  vs new 0.82–0.84 trên cùng 46 case).
- **Kết luận tổng (gemini-2.5, cùng judge, before d3afdb9 → HEAD fix2):** tool_selection 0.832 → 0.904,
  irrelevant 0.272 → 0.176, retention 0.845 → 0.915, style 0.90 → 0.71; trả giá: TTFT +1.0–1.7 s (26/08),
  policy 15 → 21 (nêu % 7 → 9, escalate miss 0 → 3), hallucination 0.31 → 0.40 (26/08). gemini-3.7:
  tool 0.880 → 0.896, irrelevant 0.384 → 0.264, retention 0.86 → 0.95, style 0.55 → 0.08, p95 24.5 → 19.7 s;
  policy 18 → 24.
- **Các lượt đã chạy (registry):**
  A/B latency xen kẽ `lat-old-1/lat-new-1/lat-old-2/lat-new-2` (46 case tool, không judge).

## 14. Siết escalate theo chủ đề giao dịch của khách (2026-08-27, tối — mục 1 của "việc tiếp theo")

**Vấn đề:** sau 4 bước, escalate miss 0 → 3 trên gemini-2.5 (QA-310 "điều khoản bất lợi HĐMB", QA-403 "chưa
có sổ mà bán lại + phí", POL-405 "cam kết lợi nhuận có ghi vào hợp đồng không"). RULES cũ định nghĩa ngoài
phạm vi bằng **trạng thái** ("khách ĐÃ MUA hỏi hợp đồng / thanh toán / sổ hồng…") nên khách chưa mua hỏi
đúng những thứ đó bị coi là trong phạm vi → model kb_search rồi tự trả lời; tiêu chí "pháp lý phức tạp"
quá mơ hồ.

**Sửa (chỉ prompt, không code):** ranh giới theo **chủ đề**. `escalate` description + RULES chat/voice quy
tắc 2/7 + dòng bản đồ tool: GIAO DỊCH của khách — kể cả khách CHƯA mua — (điều khoản / điểm bất lợi HĐMB;
chuyển nhượng / bán lại / sang tên + phí / thuế; cam kết-bảo lãnh "có ghi vào hợp đồng không"; thanh toán /
bảo hành / sổ hồng của căn đã mua; đòi giá riêng NGOÀI chính sách; đòi gặp người thật hoặc hỏi "em là người
hay máy?" → escalate ngay, KHÔNG hỏi lại lý do) → escalate NGAY, KHÔNG kb_search trước, KHÔNG tự nêu số.
Ngược lại vẫn kb_search: pháp lý DỰ ÁN (sổ hồng lâu dài / 50 năm, giấy phép, tiến độ, "pháp lý có vấn đề
không" — QA-302, bullet "nghe nói pháp lý có vấn đề"), và chiết khấu / ưu đãi THEO CSBH (thanh toán sớm,
đóng một lần, voucher — QA-214 cấm escalate). Bỏ "pháp lý phức tạp". Nén 2 câu mục "Khi khách ngần ngại"
+ header bản đồ tool để giữ ngân sách (chat 15 993 / voice ≤ 11 000). Test +1 schema, +1 × 2 kênh.

**Đo trên 23 case escalate / pháp lý (`--case`, không judge), MUST = expect.escalated hoặc golden có escalate
(15 case), BANNED = golden cấm escalate (2 case):**

| run | code | MUST escalate | BANNED mà vẫn gọi |
|---|---|---|---|
| before-g25-old | d3afdb9 | 12/12 (theo expect) | 0/2 |
| after-g25-fix2 | HEAD trước siết | 11/15 | 1/2 (QA-214) |
| esc-g25 | siết, chưa có 2 tinh chỉnh cuối | **14/15** (còn POL-507) | 1/2 (QA-214) |
| esc-g37 (after-g37-fix2 là 11/15, 0/2) | siết, chưa có 2 tinh chỉnh cuối | **15/15** | 0/2 |
| esc-g25-r2 | r2 = + "người hay máy" → escalate ngay, + chiết khấu theo CSBH → kb_search | **15/15** | **0/2** |
| esc-g37-r2 | r2 | **15/15** | **0/2** |
| esc-g25-r3 (28 case: +QA-211, TOOL-511, MT-619/620) | r3 = "GIAO DỊCH" → "HỢP ĐỒNG" trong schema + RULES, mô tả escalate thêm "lịch xem → booking, cọc / tiến độ theo CSBH → kb_search, KHÔNG escalate" | 15/15 (QA-211 về kb_search) | 0/2 — nhưng TOOL-511 / MT-601 / MT-619 (đặt-đổi lịch) VẪN escalate thay vì booking |
| **PHÁT HIỆN 18:10** | Trace `pinned_version`: các lượt tới 15:24 (`after-g25-fix2`) chạy config `aina_test` **v4**, mọi lượt `esc-*` từ 17:23 chạy **v8** — ai đó republish trên dev; từ v8 **không lượt nào gọi `booking`** (0 so với 8–9 lần trước, `send_media`/`check_inventory` vẫn có) ⇒ booking bị tắt trong config. Ba lượt "escalate thừa" TOOL-511 / MT-601 / MT-619 là **do config**, không phải prompt (TOOL-511 r4: "Tôi không có chức năng xem hay thay đổi lịch hẹn"); r3/r4 sửa để chữa chúng là thừa (giữ r4 vì vô hại). So sánh `esc-g25-full` (v8) với `after-g25-fix2` (v4) bị nhiễu → chạy lại code TRƯỚC khi siết (7879499) trên v8 để có cặp cùng config. | | |
| esc2-g25-full (r4, v8, 100 case + judge) so esc-g25-full (r2, v8) | cùng config v8 | escalate miss 0 / banned 0 ở cả hai; irrelevant escalate 5 → 4 (đều là booking bị tắt + MT-620 get_document rỗng); tool_selection 0.864 → 0.880, irrelevant 0.248 → 0.216; policy 13 → 17, retention 0.955 → 0.775 (judge multiturn 20 case: 5 → 11 issue, nội dung khác nhau hoàn toàn — địa lý, hỏi lại loại hình — không dính booking ⇒ nhiễu một lượt của metric này rất lớn), correctness 0.62 → 0.58, style 0.66 → 0.58 | |
| esc-g25-r4 / esc-g37-r4 | r4 = quy tắc 2 liệt kê phạm vi TRONG rõ ràng "(dự án, căn, tài liệu, đặt / đổi lịch xem) → tool tương ứng, kể cả booking" — bản r3 nén thành "TRONG phạm vi → tool dữ liệu" khiến gemini-2.5 coi lịch hẹn là ngoài phạm vi | g25 14/15 (QA-310 trượt 1 lần — nhiễu), g37 **15/15** | 0/2 cả hai; booking vẫn → escalate vì config v8 tắt booking (xem phát hiện) |

**Full 100 case gemini-2.5 + judge với r2 (`esc-g25-full`) so `after-g25-fix2`:** escalate miss 3 → **0**, banned_call
0.167 → **0**, policy 21 → **13** (thấp hơn cả before 15), correctness 0.584 → 0.621, grounded 0.767 → 0.822,
hallucination 0.397 → 0.382, retention 0.915 → 0.955, style 0.706 → 0.662. Trả giá: escalate gọi THỪA ở 5 lượt
(QA-211 "đặt cọc bao nhiêu giữ căn" — nội dung CSBH; TOOL-511 / MT-601 / MT-619 đặt-đổi LỊCH XEM → lẽ ra booking;
MT-620 là `get_document` trả rỗng → auto-escalate theo thiết kế, không liên quan) → tool_selection 0.904 → 0.864,
irrelevant 0.176 → 0.248, steps 1.14 → 1.19. Chẩn đoán: chữ "GIAO DỊCH" bị gemini-2.5 hiểu rộng thành mọi việc với
khách → r3 đổi thành "HỢP ĐỒNG / pháp lý giao dịch" và ghi rõ trong mô tả `escalate`: đặt / đổi / hủy lịch → booking,
đặt cọc giữ chỗ / tiến độ thanh toán / chiết khấu theo CSBH → kb_search, KHÔNG escalate. Đo lại: r3 subset + `esc2-g25-full`.

### Kết luận §14 — cặp CÙNG config v8, cùng judge (gemini-2.5-flash, 100 case)

| metric | preesc `7879499` (trước siết) | esc2 = HEAD r4 |
|---|---|---|
| escalate MUST (15 case: expect hoặc golden có escalate) | 12/15 (miss QA-310, POL-405, +1) | **15/15** |
| banned_call (QA-214 chiết khấu theo CSBH) | 2 lượt | **0** |
| escalate thừa (irrelevant) | 4 — đều là booking bị tắt trong v8 + MT-620 `get_document` rỗng | 4 (y hệt) |
| tool_selection / arg | 0.856 / 0.979 | **0.880 / 0.989** |
| irrelevant_call / steps | 0.224 / 1.17 | 0.216 / 1.18 |
| policy_violations (nêu %) | 20 (10) | 17 (9); r2 cùng họ: 13 (8) |
| correctness / hallucination / grounded (judge) | 0.555 / 0.426 / 0.779 | 0.577 / 0.419 / **0.822** |
| context_retention (judge, 20 case) | 0.865 | 0.775 (r2: 0.955 — nhiễu một lượt của metric này ±0.1) |
| style_violation | 0.507 | 0.581 (r2: 0.662) |
| turn p50 / p95 (s) | 4.25 / 6.72 | 4.34 / 6.59 |

Thay đổi đạt đúng mục tiêu (escalate đúng chỗ, không siết quá tay: cấm-mà-gọi về 0, escalate thừa không
tăng), tool/arg/grounded nhích lên, phần còn lại trong nhiễu. gemini-3.7 subset: 15/15, 0/2 ổn định qua
r1–r4. **Lưu ý vận hành:** config tenant `aina_test` trên dev đổi v4 → v8 giữa chừng (booking bị tắt) —
mọi lượt eval sau này nên ghi `pinned_version` vào bảng so sánh (trace đã có) và tránh so hai lượt khác
version; pin version trong db-mode hiện chỉ advisory (VIEW chỉ có bản published hiện tại).
