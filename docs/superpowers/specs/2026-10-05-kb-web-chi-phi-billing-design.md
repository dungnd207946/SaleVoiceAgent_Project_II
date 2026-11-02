# Chi phí dữ liệu ngoài vào sổ usage/billing — thiết kế

Ngày: 2026-10-05 · Nhánh: backend `feat/kb-web-per-tenant`, frontend `feat/du-lieu-ngoai`

## Bối cảnh

Dữ liệu ngoài (`kb/web`) gọi ba dịch vụ tốn tiền: Qwen trên DashScope (gắn thẻ, hồ sơ, thẻ lân cận,
bản tin, soạn câu tìm), Gemini tra Google, và embedding hồ sơ. Hôm nay không lần gọi nào được ghi vào
`billing.usage_events`, nên workspace dùng dữ liệu ngoài không bị tính tiền và không ai thấy chi phí.

## Quyết định đã chốt

- **Tính tiền khách** (`billable = true`), purpose mới `kb_web`.
- **Giá vendor, không markup**, 26.000 đ/USD — cùng lệ bảng `vendor-vnd-2026-08`.
- **Tra Google tính đủ giá công bố cho mọi lượt**, không trừ 1.500 lượt miễn phí/ngày của tài khoản NobleX.
- Trần `grounding_monthly` giữ mặc định 1.000 lượt/tháng.
- Hiển thị theo **chiều dịch vụ** (màn hiện có): LLM/Embed cộng cả phần dữ liệu ngoài, thêm dịch vụ
  «Tra Google»; dòng phụ «gồm … dữ liệu ngoài»; hàng hệ thống «Dữ liệu ngoài (chạy tự động)» trong bảng
  theo khoá/người tạo. Mockup: `~/Desktop/mockup-billing-du-lieu-ngoai.html`.
- Làm cả `/billing`, `/usage` và cột chi phí trong «Nhật ký chạy» của màn Dữ liệu ngoài.

## 1. Bảng giá (migration)

Một migration mới (sau head hiện tại), số đóng băng trong file:

| component | purpose | provider | model | metric | unit_price | per_units |
|---|---|---|---|---|---|---|
| llm | kb_web | dashscope | qwen3.7-flash | input_tokens | 780 | 1.000.000 |
| llm | kb_web | dashscope | qwen3.7-flash | output_tokens | 3.380 | 1.000.000 |
| llm | kb_web | dashscope | qwen3.7-flash>32k | input_tokens | 2.600 | 1.000.000 |
| llm | kb_web | dashscope | qwen3.7-flash>32k | output_tokens | 10.400 | 1.000.000 |
| llm | kb_web | dashscope | qwen3.7-flash>256k | input_tokens | 5.200 | 1.000.000 |
| llm | kb_web | dashscope | qwen3.7-flash>256k | output_tokens | 20.800 | 1.000.000 |
| llm | kb_web | google | gemini-2.5-flash | input_tokens | 7.800 | 1.000.000 |
| llm | kb_web | google | gemini-2.5-flash | output_tokens | 65.000 | 1.000.000 |
| search | kb_web | google | gemini-2.5-flash | units | 910 | 1 |

- Chèn vào bảng giá `vendor-vnd-2026-08` (theo `code`). `price_item_bat_bien` chỉ chặn UPDATE/DELETE,
  INSERT hợp lệ. Dòng cụ thể theo `purpose/provider/model` thắng dòng wildcard nên tiền hội thoại không đổi.
- Embed dùng dòng `('embed','','text_units')` sẵn có (3.900 đ/1M ký tự), không thêm dòng.
- `billing.purpose`: `('kb_web', billable = true)`, `ON CONFLICT DO NOTHING`.
- `billing.pricing_basis`: `('search', '', 'units', 'số lượt tra Google')`.
- `GRANT INSERT ON billing.usage_events TO portal_api` + `GRANT USAGE` trên sequence identity
  + policy `tenant_insert FOR INSERT TO portal_api WITH CHECK (tenant_id = portal.current_tenant())`.
- Bậc giá Qwen tính theo số token VÀO của TỪNG lượt gọi (≤32K, 32K–256K, >256K). Trigger định giá chỉ
  thấy tổng của một dòng sổ, nên bậc được ghi vào tên model.

## 2. Ghi sổ từ worker

**`kb/web/usage.py`** (mới):

- `UsageMeter` — cộng dồn theo khoá `(component, provider, model)` các số đo
  `input_tokens`, `output_tokens`, `units`, `text_units`.
- `current_meter: ContextVar[UsageMeter | None]`. `WebLlm.ask`, `Grounding.search` và đường embed
  của `WebIndex` gọi `record_*` nếu có meter; không có meter (test, CLI tay) thì bỏ qua.
  ContextVar đi theo task asyncio con, nên `gather` trong pipeline vẫn cộng đúng meter của job.
- `qwen_model(model, prompt_tokens)` trả `model`, `model>32k` hoặc `model>256k`.
- Số đo:
  - LLM DashScope: `usage.prompt_tokens` / `usage.completion_tokens` (đã có trong response).
  - Gemini: 1 `units` cho `search` mỗi lượt gọi thành công (HTTP 2xx) + `usageMetadata.promptTokenCount`
    / `candidatesTokenCount` cho `llm`. Lượt bị trần chặn (không gọi mạng) không tính.
  - Embed: tổng `len(text)` của các đoạn đem embed, component `embed`, provider `santa-models`,
    model `multilingual-e5-large`.
- `flush(pool, tenant, session_id, seq)` mở `tenant_conn` RIÊNG (giao dịch của handler rollback khi
  job lỗi, ghi chung là mất sổ đúng lúc tiền đã tốn), ghi một dòng mỗi khoá:
  `channel = 'kb_web'`, `purpose = 'kb_web'`, `exact = true`, `ON CONFLICT ON CONSTRAINT
  usage_events_idem DO NOTHING`. Lỗi ghi sổ chỉ `log.warning`, không làm hỏng job.

**Định danh lượt chạy:**

- `core/jobs.py` thêm `current_job: ContextVar[JobRef | None]` (`id`, `attempt` = `attempts` lúc nhận việc),
  đặt trong `run_once` trước khi gọi handler. Thay đổi nhỏ, không đổi chữ ký handler.
- Handler `kbweb_run` / `kbweb_project` bọc bằng `metered(...)`: tạo meter, chạy handler trong
  `try/finally`, flush với `session_id = f"kbweb:{job.id}"`, `seq = job.attempt`. Job bị nhặt lại sau
  khi treo có `attempts` mới nên ghi dòng mới — đúng, tiền của lượt chết đã tốn.
- `kbweb_probe` không gọi LLM/Gemini: không bọc. `kbweb_purge` không tốn tiền.
- Nút «Tạo cách tìm bài» (`POST /kb-web/topics/draft`) gọi LLM trong request: meter riêng, flush với
  `session_id = f"kbweb-draft:{uuid4().hex}"`, `seq = 0`.

## 3. Billing backend

Phân biệt bằng `purpose = 'kb_web'` (có ở cả `usage_events` và `rated_usage`).

- **Đếm phiên** — `tong_quan.so_phien`, `usage_theo_ngay.so_phien`, `liet_ke_phien`: loại
  `purpose = 'kb_web'`. `doc_phien`/`event_cua_phien` giữ nguyên (đọc theo `session_id`).
- **`TongQuanOut`** thêm `chi_phi_du_lieu_ngoai` (tiền `purpose = 'kb_web'` của kỳ).
  `input/output/cache_read_tokens` vẫn cộng mọi purpose.
- **`theo_component`** — mỗi dòng thêm `chi_phi_du_lieu_ngoai` (FILTER theo purpose).
- **`theo_ngay`** — không đổi; `search` xuất hiện như một component.
- **`usage_theo_ngay`** — mỗi `(ngày, component)` thêm hai số đo lọc theo purpose:
  `token_du_lieu_ngoai` (in+out+cache_read) và `text_units_du_lieu_ngoai`.
- **`theo_key` / `theo_owner`** — khoá nhóm thêm cờ `du_lieu_ngoai` (`purpose = 'kb_web'`): usage của
  dữ liệu ngoài thành MỘT hàng riêng (`agent_key_id = NULL`, `du_lieu_ngoai = true`), tách khỏi hàng
  «Chưa phân loại» (`agent_key_id = NULL`, `du_lieu_ngoai = false`). `so_phien` của hàng này = 0.
- **`_COMPONENT_TIEN`** thêm `search` ⇒ `DongKeyOut`/`DongOwnerOut`/`PhienUsageOut` có `chi_phi_search`.
- Hợp đồng `docs/contracts/usage-billing.md` cập nhật các trường mới.

## 4. Nhật ký chạy của Dữ liệu ngoài

- `JobOut` thêm `chiPhi: Decimal | None` = tổng `rated_usage.amount` của các event có
  `session_id = 'kbweb:' || job.id`. Tính trong `admin_repo.list_jobs` bằng subquery (RLS tenant).
- Chỉ trả khi người xem có `billing.read`; không có quyền thì `null` và FE ẩn cột.
- Job chưa ghi sổ (đang chạy, probe, purge) ⇒ `null`, FE hiện «—».

## 5. Frontend

**`/billing`** — đúng mockup:
- `component-hien.ts`: nhãn `search` = «Tra Google».
- Thẻ Chi phí: dòng phụ «gồm X ₫ dữ liệu ngoài» khi `chi_phi_du_lieu_ngoai > 0`.
- Thẻ «Theo từng dịch vụ»: dòng phụ «gồm X ₫ dữ liệu ngoài» (hoặc «toàn bộ là dữ liệu ngoài» khi bằng
  `chi_phi`).
- Bảng «Theo khoá» / «Theo người tạo»: cột Tra Google; hàng hệ thống «Dữ liệu ngoài (chạy tự động)»
  (Người tạo «—», Phiên «—»). Bảng «Theo phiên» thêm cột Tra Google, không có hàng dữ liệu ngoài.

**`/usage`**:
- Tab mới «Tra Google» (`ma: 'search'`, `donVi: 'so'` = lượt, `doTu: units`).
- Tab LLM và Embed có hai đường qua `duong2`: «Hội thoại» (tổng − dữ liệu ngoài) và «Dữ liệu ngoài».
- Bảng lượng dùng theo người tạo (`BangLuotDungUsage`) có hàng hệ thống «Dữ liệu ngoài».
- Số phiên không đếm lượt chạy dữ liệu ngoài.

**Dữ liệu ngoài › Tổng quan › Nhật ký chạy**: cột «Chi phí» (`chiPhi`, định dạng ₫) giữa «Người chạy» và
«Kết quả»; ẩn cả cột khi mọi hàng `chiPhi === null` do thiếu quyền.

MSW fake cập nhật cho các trường mới.

## 6. Test

Backend:
- `usage.py`: cộng dồn theo khoá; bậc Qwen ở 32.000/32.001/256.001 token; flush ghi đúng
  `session_id/seq/channel/purpose`; flush hai lần cùng `seq` chỉ một dòng; job lỗi vẫn flush.
- Migration: event `search` 620 lượt ⇒ 564.200 đ; event Qwen `purpose = kb_web` dùng dòng riêng; event
  `llm` purpose `conversation` vẫn 19.500/97.500; `portal_api` INSERT được cho tenant mình, không cho
  tenant khác.
- Billing: `so_phien` không đếm `kbweb:*`; `theo_key`/`theo_owner` có hàng dữ liệu ngoài tách khỏi
  «Chưa phân loại», tổng `chi_phi` các hàng = `tien_tenant()`; `chi_phi_du_lieu_ngoai` đúng;
  `usage_theo_ngay` có hai số đo mới.
- Nhật ký: `chiPhi` đúng tổng của job; `null` khi thiếu `billing.read`.
- `make test-isolation` xanh.

Frontend: nhãn Tra Google; dòng phụ thẻ; hàng hệ thống; tab Tra Google; hai đường LLM/Embed; cột Chi phí
nhật ký ẩn khi thiếu quyền. `npm run build` + `npm run lint` + test.

## Ngoài phạm vi

Trừ lượt miễn phí của Google; giá Gemini 3 (tính theo query); hoá đơn; cảnh báo chi phí theo trần.
