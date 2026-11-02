# Thiết kế phần tính tiền (v1) — bảng giá + rated_usage

DDL đầy đủ: `pricing-schema.sql`. Alembic head hiện tại `0942_billing_usage_events` → migration mới `0943_billing_pricing`.
**Không sửa gì trong `billing.usage_events`.**

## Đã kiểm chứng trên DB thật
Chạy toàn bộ DDL + seed giá thử trong transaction rồi ROLLBACK:
- `billing.rate_usage()` sinh **27 dòng** từ 41 events.
- Chạy lại lần 2 → vẫn 27 dòng, không nhân bản → **idempotent** đúng như thiết kế.
- `price_coverage_gap` bắt đúng những metric tôi cố tình không set giá (cache_read, vad, tts-audio_sec, speaker_verify) → cơ chế cảnh báo hoạt động.
- Thử với giá mẫu (Gemini Flash $0.30/1M in, $2.50/1M out): 115.674 input token = $0,0347.

## 5 bảng (2 bảng bạn yêu cầu + 3 bảng để hoàn thiện)

| Bảng | Vai trò | Bắt buộc? |
|---|---|---|
| `billing.price_item` | **Giá từng loại token/đơn vị** (bạn yêu cầu) | Có |
| `billing.rated_usage` | **Tiền của từng event_id** (bạn yêu cầu) | Có |
| `billing.price_version` | Bộ chứa version của bảng giá + đơn vị tiền | Có |
| `billing.metric` | Sổ đăng ký loại đơn vị → map sang cột `usage_events` | Có |
| `billing.tenant_price_version` | Gán bảng giá cho tenant theo thời gian | Có |
| `billing.invoice` / `invoice_line` | Chốt hoá đơn theo kỳ | Giai đoạn 2 |

## Vì sao `price_item` là long-form (1 dòng / 1 metric) chứ không phải nhiều cột giá

Cách "nhiều cột" (`input_price`, `output_price`, `audio_price`…) thoạt trông đơn giản hơn nhưng sai ở 2 chỗ:

1. **Không snapshot được giá từng metric.** Muốn audit ("sao tôi bị tính thế này?") thì mỗi dòng tiền phải giữ đơn giá đã dùng. Kiểu nhiều cột cần `qty + price + amount` × 5 metric = **15 cột**, còn long-form chỉ 3 cột.
2. **Mỗi component dùng metric khác nhau.** `llm` tính theo token; `stt`/`vad` theo giây; `tts` theo `units`. Kiểu nhiều cột sẽ có phần lớn ô để trống.

Đổi lại, thêm loại đơn vị mới = `INSERT` 1 dòng vào `billing.metric`, **không migration**.

### Công thức
```
amount = quantity × unit_price / per_units
```
`per_units` để viết giá theo cách nhà cung cấp niêm yết: `$0.30 / 1 triệu token` → `unit_price=0.30, per_units=1000000`. Không phải nhập số 0,0000003.

### Khớp giá theo độ cụ thể
`price_item` khớp trên `(component, purpose, provider, model, metric)`. Để trống (`''`) = "áp cho mọi giá trị". Khi 1 event khớp nhiều dòng, chọn dòng cụ thể nhất: `model` (4) > `provider` (2) > `purpose` (1). Nhờ vậy đặt được "giá chung cho mọi model Gemini" rồi ghi đè riêng cho 1 model.

## 3 quyết định thiết kế quan trọng

### 1. Không làm tròn ở `rated_usage`
`amount` là `numeric(20,10)`. Làm tròn ở từng event rồi cộng 100.000 event lại sẽ **tích luỹ sai số**. Chỉ làm tròn **một lần** khi chốt `invoice_line`. Với VND thì làm tròn về 0 chữ số thập phân tại tầng đó.

### 2. Miễn phí phải khai tường minh bằng giá = 0
Không có dòng giá khớp ⇒ không sinh dòng tiền ⇒ **âm thầm miễn phí, không ai biết**. Đây là kiểu lỗi mất doanh thu khó phát hiện nhất. Nên:
- Muốn miễn phí (vd `call`, hoặc `purpose='summary'`) → tạo dòng giá `unit_price = 0`.
- View `billing.price_coverage_gap` phải **luôn rỗng**. Hiện chưa rỗng vì chưa có giá — đưa nó lên màn hình admin như một cảnh báo.

### 3. `rated_usage` snapshot cả chiều lẫn giá
Lưu kèm `tenant_id`, `agent_key_id`, `occurred_at`, `component`, `provider`, `model`, `unit_price`, `price_version_id`. Nhờ đó **đổi giá, đổi key, hay xoá conversation đều không viết lại tiền quá khứ**. Đây chính là chỗ giải quyết vấn đề "attribution mutable" đã nêu ở `usage-v1-simple.md` mục 3.

## Phát hiện mới về cột `units` — cần xác nhận trước khi set giá

Đo trên data thật:

| component | `units` | `audio_sec` | Suy đoán |
|---|---|---|---|
| `tts` | 116, 119, 122, 178, 222, 358 | 6,1 – 24,1 | **số ký tự** |
| `llm` | 1, 2 | 0 | số lần gọi provider |
| `speaker_verify` | 1, 2 | 1,2 – 2,3 | số lần gọi |
| `stt` | 0, 1 | 2,3 | số lần gọi |

Tỉ lệ `units/audio_sec` của tts là 9–19 (không phải hằng số) ⇒ `units` **không** suy ra từ audio_sec, và 116–358 cho một câu nói đúng tầm số ký tự.

Việc này quan trọng vì **thị trường tính tiền TTS theo ký tự** (Google Cloud TTS, Azure, ElevenLabs đều vậy), không theo giây. Nếu đúng thì `tts` nên định giá bằng metric `units`, còn `stt`/`vad` bằng `audio_sec`. Schema đã hỗ trợ sẵn cả hai — chỉ cần bên agent xác nhận ngữ nghĩa `units` từng component.

## Chốt lại chuyện `call`
Bạn liệt kê 5 component có giá: `llm, vad, stt, tts, speaker_verify` — **không có `call`**. Điều này khớp với lo ngại trùng thời lượng đã nêu trước đó (`call` 33,46s ⊃ vad+stt+tts+speaker ≈ 43s). Vậy `call` là **đồng hồ tổng để đối chiếu, không tính tiền** → tạo dòng giá `call/audio_sec = 0`. Xin xác nhận.

## Ảnh hưởng tới UI

Cấu trúc 3 màn ở `usage-v1-simple.md` **không phải sửa**, chỉ thêm cột tiền:
- **Overview**: thêm KPI "Chi phí kỳ này"; thêm cảnh báo `price_coverage_gap` khác rỗng.
- **Usage by Key**: thêm cột `Cost` — đọc từ view `billing.cost_by_key_day`.
- **Sessions**: thêm cột `Cost`; timeline theo turn hiện tiền từng event (join `rated_usage` theo `event_id`).

Thêm 1 màn admin **Pricing**: CRUD `price_version` / `price_item`, gán tenant, và **preview** — áp bảng giá nháp lên usage 30 ngày qua để xem chênh lệch trước khi `status='active'`.

View sẵn dùng cho UI: `cost_by_key_day`, `cost_by_component_day`, `price_coverage_gap`, `unbillable_event`.

## Cần bạn quyết
1. **Đơn vị tiền**: bảng giá ghi bằng **VND hay USD**? Nếu nhập giá VND trực tiếp thì không cần tỷ giá. Nếu muốn pass-through giá provider (USD) rồi nhân markup và xuất hoá đơn VND thì cần thêm bảng snapshot tỷ giá — nói trước để tôi thiết kế luôn.
2. `purpose='summary'` (chi phí nội bộ) tính tiền khách hay để giá 0?
3. `call` = không tính tiền, đúng không?
4. Ngữ nghĩa `units` từng component (mục trên) — cần bên agent trả lời.
5. Có cần **gói/hạn mức** (miễn phí N token đầu, cam kết tối thiểu, vượt hạn mức) không? Nếu có thì thêm bảng `tenant_plan`; chưa cần thì bỏ qua, `tenant_price_version` là đủ.
