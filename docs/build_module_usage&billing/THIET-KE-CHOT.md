# Usage & Billing — THIẾT KẾ CHỐT

> ## ⚠️ CẬP NHẬT 2026-08-20 — layout `units`/`text_units` đổi
>
> Bên agent thêm cột `text_units` (ký tự) và chuẩn hoá `units` = số lần gọi cho mọi component.
> Cơ sở tính tiền đổi: `tts` và `embed` chuyển từ `units` sang `text_units`; `stt`+`conversation`
> có THÊM vế `text_units` (ký tự transcript) **cộng vào** vế thời lượng, không thay thế.
> Mọi con số ví dụ dưới đây (kể cả 4.025,26 đ) tính theo layout CŨ — hằng hiện hành là
> **4.145,26 đ**. Chi tiết: migration `0948_billing_text_units`, và mục "Layout
> `units` / `text_units`" trong `docs/contracts/usage-billing.md`.


Hợp nhất: hướng dẫn của bên agent (`portal-billing-pricing-guide-handoff-from-agent.md`)
+ thiết kế Portal (`usage-v1-simple.md`, `pricing-design.md`). **File này là bản chốt.**
DDL: `pricing-schema.sql`. Alembic head `0942_billing_usage_events` → `0943_billing_pricing`.

## 0. Kiểm chứng — hai bên ra CÙNG một số

Chạy trên DB thật (34 events, 1 phiên voice), cùng bảng giá ví dụ §4 của bên agent:

| | Kết quả |
|---|---|
| Query `CASE` của bên agent | **4.030,30 đ** |
| Engine `billing.rate_usage()` của Portal | **4.030,30 đ** |

Khớp tuyệt đối, và khớp cả bảng tính tay §6 của họ (≈4.030 đ). Nghĩa là **áp dụng được**,
và cách làm của Portal không phải một cách tính khác — nó là **cùng công thức đó, đưa từ SQL
chép tay vào bảng dữ liệu**.

Thêm hai cổng đã đo: view cảnh báo thiếu giá **rỗng**, và thử đặt giá cả hai cơ sở STT thì
DB **chặn** (`duplicate key ... price_item_stt_single_basis`).

## 1. Bốn chỗ hướng dẫn của họ làm tôi PHẢI SỬA thiết kế

### 1.1 `wall_ms` LÀ cơ sở tính tiền — tôi đã loại nó sai
Tôi ghi `wall_ms` là "latency, không tính tiền" và không đưa vào danh sách metric. Sai:
`(stt, purpose='stream')` **chỉ có** `wall_ms` (data thật: 142.777 ms, `audio_sec = 0`), và
nếu hợp đồng STT thu theo connect-time thì đó là cơ sở duy nhất. Đã thêm metric `wall_ms`.

### 1.2 `call` CÓ tính tiền — suy luận trước của tôi sai
Tôi suy từ việc bạn liệt kê 5 component (không có `call`) rằng `call` chỉ để đối chiếu.
Hướng dẫn của họ nói rõ `P_CALL_PER_MIN` là **phí nền tảng theo phút** và có tính tiền —
trong ví dụ nó là 1.187 đ / 4.030 đ, tức **29% hoá đơn**. Bỏ nó là mất gần một phần ba doanh thu.

Nỗi lo "tính trùng thời lượng" của tôi được họ trả lời đúng chỗ: điều bị cấm là
**`SUM(audio_sec)` chéo component**, không phải việc tính tiền nhiều component. Mỗi component
có đơn giá riêng phản ánh đúng thứ nó đại diện. Thiết kế của Portal **không thể** cộng giây
chéo component — mỗi dòng `rated_usage` gắn một `component` + một `metric` và chỉ **tiền** mới
được cộng. Cảnh báo của họ vì thế trở thành bất biến cấu trúc, không cần ai nhớ.

### 1.3 STT — hai cơ sở, chỉ được chọn MỘT
Họ nhấn mạnh đây là chỗ dễ sai nhất, giải pháp của họ là "đặt biến kia = 0" (kỷ luật con người).
Portal cưỡng chế ở DB:
```sql
CREATE UNIQUE INDEX price_item_stt_single_basis ON billing.price_item (price_version_id, component)
  WHERE component = 'stt' AND unit_price > 0;
```
Nhiều nhất một dòng `stt` có giá > 0 mỗi bảng giá. Dòng giá 0 vẫn khai được tường minh.
**Đã thử: DB chặn thật.**

### 1.4 `embed` — component tôi chưa biết
Tính theo `units` (số đoạn text), keyed `(provider, model)`, nhánh local giá 0. Chưa có trong
data (họ ghi: chỉ từ 2026-08-19). Đã khai vào bảng cơ sở tính tiền.

## 2. Chỗ Portal làm khác — và tại sao đơn giản hơn

| Hướng dẫn của họ | Portal | Lý do |
|---|---|---|
| ~15 biến `P_*` chép trong CTE | dòng trong `billing.price_item` | Đổi giá không cần sửa code. Chính họ khuyến nghị "vật chất hoá thành bảng `billing.price_*`". |
| Ba số chia khác nhau: `/1e6`, `/60`, `/60000` | một cột `per_units` | `500 đ/phút` = `unit_price=500, per_units=60`. Một công thức duy nhất `qty × unit_price / per_units`, không có số magic trong code. |
| Cờ `billable` riêng cho từng `purpose` | dòng giá `unit_price = 0` | Bớt một khái niệm. Muốn `warm_cache` là giá vốn → đặt giá 0. Bớt luôn nguy cơ "cờ bật nhưng chưa có giá". |
| Khối `CASE u.component WHEN …` 8 nhánh | `JOIN` bảng giá + `LATERAL` chọn dòng cụ thể nhất | Thêm component/provider/model mới = INSERT, không sửa query. |
| Công thức tách riêng cho voice và chat | một công thức, `channel` là chiều lọc | Tổng đúng cho cả hai; không có nhánh nào để lệch. |
| Lưới an toàn "dòng không có giá" chỉ phủ `llm`/`embed` | `billing.price_coverage_gap` phủ **mọi** cặp đã khai | Bảng `pricing_basis` (§2 của họ, đưa về dạng dữ liệu) làm view chỉ soi cặp thật sự tính tiền — không kêu nhiễu về `llm.wall_ms`, `tts.audio_sec`. Một cảnh báo kêu mọi lúc là cảnh báo không ai đọc. |

**Bỏ qua có chủ ý:** toàn bộ SQL mẫu §4 và §6 của họ — giữ làm tài liệu tham chiếu + bộ test
đối chiếu, không đưa vào production.

## 3. Bảy bảng — chốt

```
billing.usage_events        ← agent ghi, KHÔNG sửa gì (đã có)
billing.metric              ← loại đơn vị → cột nguồn (8 dòng)
billing.pricing_basis     ← component nào tính tiền bằng metric nào (11 dòng)
billing.price_version          ← bộ chứa version + currency (VND)
billing.price_item          ← đơn giá; long-form 1 dòng/metric
billing.tenant_price_version   ← gán bảng giá cho tenant theo thời gian
billing.rated_usage         ← tiền từng (event_id, metric), snapshot giá + agent_key_id
billing.invoice/_line       ← giai đoạn 2, LÀM TRÒN ở tầng này
```

Attribution: `tenants → agent_keys → conversations.agent_key_id → usage_events` (LEFT JOIN,
nhóm NULL hiện là "Chưa phân loại").

## 4. Ba bất biến không được phá

1. **Không làm tròn ở `rated_usage`** (`numeric(20,10)`). Làm tròn từng event rồi cộng 100k event
   là tích luỹ sai số. Làm tròn **một lần** ở `invoice_line`; VND về 0 chữ số thập phân.
2. **Miễn phí = dòng giá 0, không phải để trống.** Không có dòng giá ⇒ không sinh tiền ⇒ âm thầm
   miễn phí. `price_coverage_gap` phải luôn rỗng và nằm trên màn admin.
3. **`rated_usage` snapshot cả chiều lẫn giá.** Đổi giá / đổi key / xoá conversation không viết
   lại tiền quá khứ.

## 5. Bốn cạnh sắc lấy từ hướng dẫn của họ

- **`exact=false` là THIẾU, không bao giờ THỪA.** Hoá đơn tính trên số đã ghi, **không ước lượng bù**.
  Dựng cảnh báo `% dòng exact=false` trên `component='llm'` (chỉ llm mới có).
- **Dòng đến muộn.** Đường ghi là fire-and-forget có retry; lô có thể landed muộn vài phút nhưng
  vẫn mang `occurred_at` đúng. ⇒ **Không phát hành hoá đơn trước 48h sau khi kỳ đóng.**
  `rate_usage()` idempotent nên chạy lại an toàn; `invoice.status='draft'` giữ cửa đó.
- **Đừng lập hoá đơn theo lượt cho dòng audio.** `turn_idx` của audio là xấp xỉ (TTS lệch một lô).
  Tổng theo phiên/tháng luôn đúng. Timeline theo turn ở màn Sessions là **để xem**, không phải
  cơ sở tính tiền — ghi rõ trên UI.
- **Những vắng mặt là bình thường:** `purpose='memory'` có thể vắng; phiên chat không có dòng audio;
  không tra cứu KB thì không có `embed`. Đừng dựng invariant "phiên nào cũng phải có X".

## 6. Bảng giá cần nhập (form Pricing sinh từ `pricing_basis`)

| component | purpose | metric | Đơn vị nhập |
|---|---|---|---|
| `llm` | — | input / output / cache_write / cache_read | đ / 1M token, theo `(provider, model)` |
| `embed` | — | `units` | đ / đoạn text, theo `(provider, model)`; local = 0 |
| `stt` | `conversation` | `audio_sec` | đ / giây — **CHỌN MỘT** |
| `stt` | `stream` | `wall_ms` | đ / phút (`per_units=60000`) — **CHỌN MỘT** |
| `tts` | — | `units` | đ / ký tự |
| `vad` | — | `audio_sec` | đ / giây |
| `speaker_verify` | — | `audio_sec` | đ / giây |
| `call` | — | `audio_sec` | đ / phút (`per_units=60`) |

Giá vốn / không tính khách (`warm_cache`, `addressee_gate`, `semcache`) → thêm dòng
`purpose=<nhãn>, unit_price=0`, cụ thể hơn dòng wildcard nên nó thắng.

## 7. UI — 4 màn

**a) Overview** — KPI: Chi phí kỳ · Token · Thời lượng voice · Số phiên · Số key hoạt động.
Cột chồng theo ngày (theo `component`). Dải cảnh báo: `price_coverage_gap` khác rỗng ·
`% exact=false` (llm) · số event không có số đo nào.

**b) Usage by Key** — Key (`label`+`key_prefix`) · Người tạo (`created_by`) · Phiên · Token ·
Voice-sec · **Chi phí** · Trạng thái. Dòng cuối "Chưa phân loại". Tab **By owner** gộp `created_by`.

**c) Sessions** — Phiên · Key · Khách · Channel · Turn · Token · Voice-sec · Chi phí · badge `exact`.
Bấm vào → timeline theo `seq`, mỗi event hiện component/purpose/model/số lượng/tiền.

**d) Pricing (admin)** — form sinh từ bảng §6, CRUD `price_version`/`price_item`, gán tenant,
**preview** áp bảng giá nháp lên usage 30 ngày để xem chênh lệch trước khi `status='active'`.

View sẵn: `cost_by_key_day`, `cost_by_component_day`, `price_coverage_gap`, `unbillable_event`.

## 8. Thứ tự làm

1. Migration `0943_billing_pricing` (7 bảng + 2 function + 4 view).
2. Migration siết attribution: composite FK `(tenant_id, agent_key_id)` + `ON DELETE RESTRICT`;
   endpoint xoá key chuyển sang set `revoked_at`.
3. Nhập bảng giá thật (§6) → xác nhận `price_coverage_gap` rỗng.
4. Job `rate_usage()` chạy hằng ngày + re-run cửa sổ 48h.
5. API: `/usage/summary`, `/usage/by-key`, `/usage/by-owner`, `/usage/sessions`, `/usage/sessions/{id}`, `/pricing/*`.
6. UI 4 màn.
7. Test đối chiếu: giữ query §4 của bên agent làm bài canh — engine phải ra cùng số. Đã xanh.

## 9. Đã chốt

- **STT thu theo GIÂY** → `(stt,'conversation')/audio_sec` có giá; `(stt,'stream')/wall_ms` = 0.
  DB chặn nếu ai đó đặt giá cả hai.
- **Nhãn không nằm trong công thức thì không tính tiền** → `memory`, `warm_cache`,
  `addressee_gate`, `semcache` đặt `billable = false`. Sáu nhãn còn lại (`conversation`,
  `summary`, `suggestions`, `embed`, `stream`, `session`) tính khách — đúng danh sách
  `nhan_tinh` ở §4 của bên agent.
- **Currency: VND.** Biên lợi nhuận gộp thẳng vào `unit_price`, không có hệ số markup riêng,
  không cần bảng tỷ giá.
- Điền giá thật vào `pricing-seed.sql` (mọi chỗ `<...>`), rồi kiểm ba view phải rỗng.

### ⚠️ Sửa một lỗi trong thiết kế của tôi mà quyết định này làm lộ ra

Tôi từng đề xuất bỏ cờ `billable` của bên agent, dùng "dòng giá = 0" thay thế. **Cách đó
không chạy.** Độ ưu tiên khớp giá là `model (4) + provider (2) + purpose (1)`, nên dòng
`warm_cache giá 0` (điểm 1) **thua** dòng `gemini-2.5-flash giá 2500` (điểm 6) — nhãn giá vốn
vẫn bị tính tiền đầy đủ.

Cờ `billable` là một phép **LỌC**, còn giá là phép **KHỚP** — hai việc trực giao, gộp lại thì
sinh xung đột thứ tự ưu tiên. Đã lấy lại đúng thiết kế của họ: bảng `billing.purpose`
(10 dòng, `code` + `billable`), lọc TRƯỚC khi khớp giá. Bên agent đúng ở chỗ này.

Một điểm bổ sung: nhãn **chưa khai** trong `billing.purpose` thì **mặc định TÍNH TIỀN**, và
hiện ở view `billing.purpose_unclassified`. Chọn chiều này vì mặc định-không-tính là mất
doanh thu âm thầm, còn mặc định-tính thì sai lệch sẽ có người phát hiện.

Kiểm chứng lại sau khi thêm cờ: tổng vẫn **4.030,30 đ**, cả ba view cổng đều rỗng.

## 10. Hướng dẫn của họ đã nêu rõ công thức chưa?

**Cấu trúc công thức: RÕ VÀ ĐỦ.** §1 cho biết biến nào nhân với cột nào kèm đơn vị (4 dòng LLM,
1 embed, 6 audio), §3 cho công thức tổng, §4 cho SQL chạy được, §6 cho ví dụ tính tay có số thật.
Tôi đã dựng lại độc lập bằng engine bảng giá và ra **đúng cùng một con số** — nên công thức của
họ không mơ hồ chỗ nào về mặt cấu trúc.

**Nhưng CHƯA đủ để phát hành hoá đơn — thiếu 3 thứ, và có 1 chỗ tự mâu thuẫn:**

### Thiếu 1 — Giá thật
Mọi số trong tài liệu đều được đánh dấu "VÍ DỤ". Đây là phần bạn cấp, đã có khung ở
`pricing-seed.sql`.

### Thiếu 2 — Quy tắc làm tròn
§4 của họ `round(..., 0)` ở mức `GROUP BY (tenant, channel, tháng)`, nhưng tài liệu **không nói
đó là chính sách**. Làm tròn ở mức nào là quyết định có ảnh hưởng tới số tiền cuối:
tròn từng event rồi cộng ≠ cộng rồi tròn một lần. Thiết kế Portal chốt: **không tròn ở
`rated_usage`, tròn một lần ở `invoice_line`, VND về 0 chữ số thập phân.**

### Thiếu 3 — Thuế VAT
Không nhắc một chữ. Hoá đơn VND ở Việt Nam thì đây không phải chi tiết nhỏ. Cần bạn chốt:
đơn giá đã gồm VAT chưa, hay `invoice` cần thêm `vat_rate` + `total_gom_vat`. Nếu chọn phương án
sau thì thêm 2 cột vào `billing.invoice`, không ảnh hưởng gì tới `rated_usage`.

### Mâu thuẫn — §1.1 nói Gemini không có cache, data nói ngược lại
§1.1 viết: *"Provider không có cache (vd Gemini OpenAI-compat hiện tại) thì hai cột cache luôn 0,
đặt giá bao nhiêu cũng không phát sinh tiền."*

Data thật: `gemini-2.5-flash` có **`cache_read_tokens = 35.548`**. Và chính §4 của họ đặt
`cr_1m = 625`, §6 của họ tính `35548 × 625 = 22 đ` — tức hai mục sau đã coi cache là có thật,
chỉ câu trong ngoặc ở §1.1 là lỗi thời.

Hệ quả nếu tin §1.1: ai đọc câu đó rồi đặt `cache_read = 0` sẽ mất khoản này. Hiện chỉ
22/4.030 đ (0,55%) nên dễ bỏ qua, **nhưng nó sẽ lớn lên** khi prompt caching được dùng nhiều
hơn — và mất theo kiểu im lặng, vì đặt giá 0 là hợp lệ nên `price_coverage_gap` không báo.
`pricing-seed.sql` vì thế ghi chú thẳng ở dòng đó: *"KHÁC 0 trên data thật, đừng bỏ"*.

### Những thứ họ KHÔNG cần nêu (đúng phạm vi)
Biên lợi nhuận — họ nói rõ ở §1 là gộp vào đơn giá do Portal đặt. Gói/hạn mức/cam kết tối thiểu —
thuộc tầng plan của Portal, chưa làm, và `tenant_price_version` đã đủ cho v1.
