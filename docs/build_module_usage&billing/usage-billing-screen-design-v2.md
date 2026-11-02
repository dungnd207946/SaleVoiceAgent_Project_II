# Usage & Billing — Phân tích DB thực tế và thiết kế màn hình (v2)

> Nguồn sự thật duy nhất: `billing.usage_events` trong DB `portal` (localhost:5442).
> Mọi spec trước đó bị bỏ qua. Giá/công thức tính tiền sẽ bổ sung sau.

## 1. Hiện trạng DB (đã đọc trực tiếp)

### `billing.usage_events` — 19 cột, 20 rows
| Nhóm | Cột |
|---|---|
| Khoá | `event_id` (PK), unique idem `(tenant_id, session_id, seq, component, purpose, provider, model)` |
| Chiều (dimension) | `tenant_id`, `session_id`, `channel`, `seq`, `turn_idx`, `component`, `purpose`, `provider`, `model` |
| Số đo (measure) | `input_tokens`, `output_tokens`, `cache_write_tokens`, `cache_read_tokens`, `audio_sec`, `wall_ms`, `units` |
| Chất lượng | `exact` (bool), `occurred_at` |

Index: `(tenant_id, occurred_at)`, `(tenant_id, session_id)`.

View sẵn có:
- `billing.usage_by_session` — cộng token + tách `audio_sec` theo component (stt/tts/vad/speaker_verify/call).
- `billing.usage_by_tenant_month` — cộng theo `(tenant, tháng, component, purpose, provider, model)`.

### Dữ liệu thực tế đang có
- Chỉ 1 tenant `du_test`, channel `chat`, component `llm`, provider `gemini`, model `gemini-2.5-flash`.
- `purpose`: `conversation` (14) và `summary` (6) → **summary là chi phí nội bộ, không phải turn người dùng**.
- Đã có `cache_read_tokens` khác 0 (10.878) → **bắt buộc phải tính giá cache riêng**, không gộp vào input.
- Schema đã chừa sẵn chỗ cho voice (`audio_sec`, component stt/tts/vad/call) nhưng chưa có data.

## 2. Bốn vấn đề chặn việc ra bill (phải xử lý trước khi làm UI)

**(1) Không có chiều quy trách nhiệm (attribution).** Chỉ có `tenant_id` + `session_id`. Không biết traffic đến từ deployment nào, key nào, người nào. Đây là điều bạn đang hỏi → mục 3.

**(2) 6/20 rows có `exact=false` và toàn bộ token = 0.** Ví dụ `(du_test, e08db435d5d1, seq 0)`: input=0, output=0, exact=f. Đây là **turn không thu được tiền** — agent ghi event nhưng không lấy được usage metadata từ provider. Nếu ra bill hôm nay, ~30% turn bị mất doanh thu. Cần fix phía agent, đồng thời UI phải hiện rõ tỉ lệ này chứ không im lặng.

**(3) Không có cột giá/tiền.** Giá thay đổi theo thời gian; nếu tính tiền on-the-fly bằng bảng giá hiện tại thì **đổi giá sẽ viết lại hoá đơn quá khứ**. Bắt buộc tách 2 tầng: bảng giá có hiệu lực theo thời gian + bảng `rated_usage` chốt giá tại thời điểm rate.

**(4) `units` chưa rõ nghĩa.** Data cho thấy `units` = số thứ tự turn trong session (1,2,3...) chứ không phải "số đơn vị tính tiền". Nếu định dùng để tính tiền thì đang sai; cần bên agent xác nhận.

## 3. Trả lời câu hỏi: nên gắn usage vào API key hay gì khác?

### API key **một mình** là không đủ
Sản phẩm này là agent phục vụ khách hàng cuối qua kênh chat/voice. Người "đốt token" là **cuộc hội thoại của khách cuối**, không phải nhân viên nội bộ. Nếu chỉ gắn `api_key`, bạn sẽ thấy "key X dùng 4 triệu token" mà không biết đó là môi trường nào, agent nào, hay ai chịu chi phí.

Ngoài ra `control.agent_keys` hiện có nhưng gắn với `deployment_id`, **không phải per-user** — chưa có bảng key theo người dùng.

### Cách các sản phẩm tương tự làm
OpenAI, Anthropic Console, LangSmith đều **không** bill theo key; họ dùng một **bộ chiều quy trách nhiệm** rồi cho phép group-by bất kỳ chiều nào:

| Sản phẩm | Chiều bill | Chiều nhóm | Chiều credential | Chiều drill-down |
|---|---|---|---|---|
| OpenAI | Organization | Project | API key | Model / request |
| Anthropic | Organization | Workspace | API key | Model |
| LangSmith | Organization | Project (tracing) | API key | Trace / run |

Điểm chung: **API key là chiều *lọc*, không phải chiều *bill*.** Đơn vị bill là org/tenant; đơn vị phân bổ nội bộ là project/workspace/deployment.

### Đề xuất cho Odyssey — thêm 3 cột vào `usage_events`

| Cột mới | Ý nghĩa | Nguồn |
|---|---|---|
| `deployment_id bigint NULL` | Agent deployment nào tạo ra usage. **Đây là chiều phân bổ chính** (tương đương "Project" của OpenAI). | `control.deployments` |
| `api_key_id bigint NULL` | Credential nào xác thực request. Chiều lọc + để thu hồi key khi thấy bất thường. | `control.agent_keys` (mở rộng) |
| `actor_id text NULL` | Ai sở hữu key đó (user nội bộ). Trả lời đúng câu hỏi "user nào dùng bao nhiêu". | `control.users.id` |

Kèm theo, cần mở rộng `control.agent_keys` để hỗ trợ key theo người: thêm `tenant_id`, `owner_user_id`, `scope` (`deployment` | `user`), `name`. Mỗi người tự tạo key của mình → `actor_id` được suy ra từ key khi ghi event.

**Quan trọng — thứ tự ưu tiên khi thiết kế UI:**
`tenant` (đơn vị ra hoá đơn) → `deployment` (phân bổ chi phí) → `api_key` / `actor` (ai gây ra) → `session` → `event`.

Với traffic khách cuối (không có API key vì đến qua widget/Zalo/điện thoại), `api_key_id` và `actor_id` sẽ NULL — UI phải gộp thành nhóm **"End-user traffic"** thay vì ẩn đi, nếu không tổng theo key sẽ không khớp tổng hoá đơn. Đây là lỗi phổ biến nhất của dashboard usage.

### Lưu ý kỹ thuật khi thêm cột
Unique index idempotency hiện tại là `(tenant_id, session_id, seq, component, purpose, provider, model)`. **Không thêm** `api_key_id` vào index này — nếu thêm, cùng một turn gửi lại với key khác sẽ tạo bản ghi trùng và tính tiền 2 lần.

## 4. Kiến trúc dữ liệu đề xuất (3 tầng)

```
Tầng 1 — SỰ KIỆN (immutable)
  billing.usage_events            ← agent ghi, không bao giờ sửa
        + deployment_id, api_key_id, actor_id

Tầng 2 — BẢNG GIÁ (versioned)
  billing.price_book(id, name, currency, effective_from, effective_to)
  billing.price_item(price_book_id, component, provider, model, purpose,
                     metric, unit_price, unit_size)
        metric ∈ input_tokens | output_tokens | cache_write | cache_read | audio_sec
  billing.tenant_plan(tenant_id, price_book_id, effective_from,
                      commit_amount, included_units, overage_rate)

Tầng 3 — ĐÃ ĐỊNH GIÁ (chốt giá, có thể tính lại)
  billing.rated_usage(event_id, price_book_id, metric, quantity,
                      unit_price_snapshot, amount, rated_at)
  billing.invoice / invoice_line(tenant_id, period, status, total)
```

Lý do tách tầng 3: hoá đơn tháng trước phải bất biến kể cả khi đổi giá. Đây là chuẩn của mọi hệ thống metered billing (Stripe Billing Meters, Metronome, Orb).

## 5. Thiết kế màn hình

### 5.1 Cây điều hướng
```
Usage & Billing
├── Overview            (tenant admin — sức khoẻ chi tiêu)
├── Usage Explorer      (phân tích đa chiều — màn hình lõi)
├── Sessions            (drill-down tới từng hội thoại)
├── API Keys            (quản lý key + usage theo key/người)
├── Invoices            (hoá đơn theo kỳ)
└── Pricing & Plans     (platform admin — bảng giá, gói)
```

### 5.2 Overview
Bộ lọc chung toàn module: **khoảng thời gian** (Today / 7d / 30d / This month / Custom) + **deployment**.

- 4 thẻ KPI: **Chi phí kỳ này** (+ % so kỳ trước), **Tổng token**, **Số session**, **Chi phí / session**.
- Biểu đồ cột chồng theo ngày, chồng theo `model` (mặc định) — đổi được sang `deployment` / `purpose` / `channel`.
- Bảng Top 5 deployment theo chi phí.
- **Dải cảnh báo chất lượng dữ liệu**: `% events có exact=false` và `% events token=0`. Đang là 30% → không được giấu. Kèm link tới danh sách event lỗi.
- Thanh tiến độ hạn mức (nếu plan có `included_units` / budget).

### 5.3 Usage Explorer — màn hình quan trọng nhất
Một bảng pivot, người dùng tự chọn:

- **Group by** (chọn nhiều, có thứ tự): `deployment` → `api_key` → `actor` → `model` → `purpose` → `component` → `channel` → `day`.
- **Cột số liệu**: Input / Output / Cache write / Cache read / Audio sec / Events / **Cost**.
- **Chia nhỏ chi phí**: cột Cost bấm vào bung ra thành các thành phần metric — vì `cache_read` giá khác `input` (data đã có 10.878 cache-read token), người dùng cần thấy tiết kiệm được bao nhiêu nhờ cache.
- Toggle **Exclude internal purposes** — tách `summary` khỏi `conversation`. Đây là câu hỏi thực tế: "chi phí phục vụ khách" vs "chi phí vận hành nội bộ".
- Export CSV.

Query nền: `usage_events` group-by động; đủ nhanh với index `(tenant_id, occurred_at)`, sau này thêm rollup ngày khi data lớn.

### 5.4 Sessions
Dựa trên `usage_by_session`, join `tenant_data.conversations` để lấy `phone`, `customer_name`, `project`.

Cột: Session ID · Khách hàng · Channel · Bắt đầu · Số turn · Input/Output token · Cache read · Cost · badge `exact`.

Bấm vào → **timeline theo turn** (`seq` / `turn_idx`): mỗi dòng là một event với model, token, chi phí. Đây là màn hình để trả lời khiếu nại "sao tháng này đắt thế" — chỉ ra chính xác session/turn nào tốn.

### 5.5 API Keys
Hai phần trên cùng một trang:
1. **Quản lý key** — tạo/đặt tên/thu hồi. Hiện plaintext **đúng một lần** lúc tạo (DB chỉ giữ `key_sha256` + `key_prefix`). Cột: Tên · Prefix · Chủ sở hữu · Deployment · Tạo lúc · Dùng lần cuối · Trạng thái.
2. **Usage theo key** — token + cost 30 ngày, sparkline. Cộng thêm dòng **"End-user traffic (no key)"** để tổng khớp hoá đơn.

Kèm tab **By member**: gộp theo `actor_id` join `control.users` → trả lời trực tiếp "user nào dùng bao nhiêu".

### 5.6 Invoices
Danh sách theo kỳ + trang chi tiết: dòng hoá đơn theo `(component, provider, model, metric)` với quantity × unit_price = amount, lấy từ `rated_usage` (giá đã chốt). Nút *Recalculate* chỉ mở cho kỳ `draft`.

### 5.7 Pricing & Plans (platform admin)
CRUD `price_book` / `price_item` với `effective_from`. Gán plan cho tenant. Có **preview**: áp bảng giá mới lên usage 30 ngày qua để xem chênh lệch trước khi kích hoạt.

## 6. Việc cần làm theo thứ tự

| # | Việc | Phụ thuộc |
|---|---|---|
| 1 | Bên agent xác nhận ngữ nghĩa `units`; fix các event `exact=false` token=0 | Agent team |
| 2 | Migration: thêm `deployment_id`, `api_key_id`, `actor_id` vào `usage_events` (NULL-able, không đụng unique index) | — |
| 3 | Mở rộng `control.agent_keys`: `tenant_id`, `owner_user_id`, `scope`, `name` | #2 |
| 4 | Agent truyền attribution khi ghi event | #2, #3 |
| 5 | Bảng `price_book` / `price_item` / `tenant_plan` | Chờ công thức giá |
| 6 | `rated_usage` + job rate hàng ngày | #5 |
| 7 | API đọc: `/usage/summary`, `/usage/explore`, `/usage/sessions`, `/usage/keys` | #2 |
| 8 | UI Overview + Usage Explorer + Sessions | #7 |
| 9 | UI API Keys + Invoices + Pricing | #6 |

Bước 1–4, 7, 8 làm được ngay **không cần biết giá** — chỉ hiển thị token thay vì tiền, cột Cost thêm sau.

## 7. Câu hỏi cần bạn quyết

1. `purpose='summary'` có tính tiền khách không, hay là chi phí nội bộ Noblex chịu?
2. Đơn vị ra hoá đơn là `tenant` — có cần chia tiếp theo `deployment` để nội bộ khách tự phân bổ không?
3. Traffic khách cuối (không có API key) chiếm bao nhiêu %? Nếu ~100% thì màn "By member" ít giá trị, nên ưu tiên "By deployment".
4. Bán theo **pass-through** (giá gốc provider × markup) hay **giá niêm yết riêng** không phụ thuộc provider? Việc này quyết định có cần lộ `provider`/`model` ra cho khách hàng thấy hay không.
