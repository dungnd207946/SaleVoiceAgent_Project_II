# Usage v1 (đơn giản) — attribution qua agent_key_id

Chốt hướng: đo usage theo `agent_key_id`, join `usage_events → conversations`.
Giá/version giá: xem `pricing-design.md` + `pricing-schema.sql`. Tài liệu này thay thế `agent-postgres-billing-write-contract.md`
và mục 3–5 của `usage-billing-screen-design-v2.md`.

**Cập nhật sau refactor (2026-08-19):** `control.deployments` đã bị bỏ; `agent_keys` giờ gắn thẳng
`tenant_id NOT NULL` FK → `tenants`; đã có FK `conversations.agent_key_id`. Việc lưu plaintext
`api_key` là chủ ý của chủ sở hữu hệ thống — không bàn lại trong tài liệu này.

## 1. Chuỗi attribution (đã đơn giản đi 1 tầng)

```
tenants → agent_keys → conversations → usage_events
          (tenant_id)   (agent_key_id)  (tenant_id, session_id)
```

Bỏ `deployments` là đúng cho mô hình này: mỗi key thuộc trực tiếp 1 tenant, không còn tầng trung gian
vô nghĩa. **Hệ quả với spec cũ: bỏ hoàn toàn đề xuất thêm `deployment_id` vào `usage_events`** —
không còn khái niệm đó. Không cần thêm cột nào vào `usage_events` nữa.

Điều kiện kỹ thuật vẫn thoả: `conversations` có `UNIQUE (tenant_id, session_id)` → join 1-1,
không nhân đôi token.

### Đã chạy end-to-end
Kiểm tra data thật: 1 session voice, `agent_key_id = 20`, 11 events, 12.085 token, **0 orphan**.
Pipeline attribution đã hoạt động. Trước refactor là 0/12 conversations có key; giờ đã có.

### Query nền tảng
```sql
SELECT c.agent_key_id, e.component, e.purpose, e.provider, e.model,
       sum(e.input_tokens) inp, sum(e.output_tokens) outp,
       sum(e.cache_read_tokens) cr, sum(e.cache_write_tokens) cw,
       sum(e.audio_sec) audio_sec, count(*) events, bool_and(e.exact) exact
FROM billing.usage_events e
LEFT JOIN tenant_data.conversations c            -- LEFT, không INNER
       ON c.tenant_id = e.tenant_id AND c.session_id = e.session_id
WHERE e.tenant_id = :tenant AND e.occurred_at >= :from AND e.occurred_at < :to
GROUP BY 1,2,3,4,5;
```
`LEFT JOIN` là bắt buộc: nếu agent ghi usage trước khi tạo row conversations, `INNER JOIN` sẽ âm thầm
làm mất usage đó. Nhóm `agent_key_id IS NULL` hiện trên UI là **"Chưa phân loại"**, không được ẩn.
Gói thành view `billing.usage_by_key_day`.

## 2. Vấn đề mới phát hiện

### ⚠️ CAO — nguy cơ tính trùng thời lượng voice
Data thật của 1 session voice:

| component | purpose | audio_sec |
|---|---|---|
| `call` | `session` | **33,46** |
| `vad` | conversation | 32,32 |
| `call` … | | |
| `stt` | conversation | 2,45 |
| `tts` | conversation | 6,36 |
| `speaker_verify` | conversation | 2,20 |

`call` = 33,46s trông như **tổng thời lượng cuộc gọi**, còn `vad`/`stt`/`tts`/`speaker_verify`
(tổng ≈ 43s) là các đồng hồ con **nằm bên trong** cuộc gọi đó. Nếu tính tiền cả `call` lẫn các
component con thì **thu trùng cùng một quãng thời gian**, và tổng con còn lớn hơn cả cuộc gọi.

Cần chốt trước khi làm UI: `call` là **đồng hồ tổng để đối chiếu** (không tính tiền), hay là
**đơn vị tính tiền duy nhất** cho voice (và các component con chỉ để phân tích)? Màn hình phải tách
rõ 2 nhóm này, không được cộng gộp cột "Tổng audio-sec".

### ⚠️ `purpose` không phải enum cố định
Data đã xuất hiện 4 giá trị: `conversation`, `summary`, `session`, `stream`. Sẽ còn thêm.
UI/API **không hardcode** danh sách purpose — render động từ data.

### ⚠️ `provider`/`model` rỗng ở component audio
`stt`/`tts`/`vad`/`speaker_verify`/`call` có `provider = ''`, `model = ''` (default `''`, không NULL).
UI phải hiện `—`, và group-by provider/model phải gộp chúng thành nhóm "N/A" thay vì một ô trắng.

### ⚠️ Vẫn còn event không có số đo nào
`stt` + `purpose='stream'`: token = 0 **và** `audio_sec = 0`, nhưng `exact = true`. Không tính được
tiền, mà cũng không bị cờ `exact` bắt. Màn hình cần bộ đếm riêng **"event không có số đo"** —
điều kiện `input_tokens=0 AND output_tokens=0 AND audio_sec=0` — chứ không chỉ dựa vào `exact`.

## 3. Hai chỗ nên siết thêm ở DB

### `ON DELETE SET NULL` sẽ xoá mất lịch sử quy trách nhiệm
FK hiện tại: `conversations_agent_key_id_fkey ... ON DELETE SET NULL`. Nghĩa là **xoá 1 key thì toàn
bộ usage quá khứ của key đó rơi về "Chưa phân loại"** — mất luôn thông tin ai đã dùng. Đây là điều tôi
đề xuất ở bản trước, và với module usage thì nó là lựa chọn sai.

Đã có `revoked_at` nên hướng đúng là: **thu hồi, không bao giờ DELETE**. Cách làm:
- Tầng app: endpoint xoá key chỉ set `revoked_at`, không `DELETE`.
- Hoặc siết ở DB: đổi thành `ON DELETE RESTRICT` để DB chặn hẳn việc xoá key đã có usage.

### Chống lẫn tenant — giờ mới làm được ở tầng DB
FK hiện chỉ tham chiếu `agent_keys(id)`, nên về mặt DB vẫn có thể gán key của tenant A cho conversation
của tenant B (hiện data không có ca nào, nhưng không có gì chặn). Từ khi `agent_keys` có `tenant_id`,
việc này chặn được bằng composite FK:

```sql
ALTER TABLE control.agent_keys        ADD CONSTRAINT agent_keys_tenant_id_uk UNIQUE (tenant_id, id);
ALTER TABLE tenant_data.conversations DROP CONSTRAINT conversations_agent_key_id_fkey;
ALTER TABLE tenant_data.conversations ADD  CONSTRAINT conversations_agent_key_fkey
  FOREIGN KEY (tenant_id, agent_key_id) REFERENCES control.agent_keys(tenant_id, id)
  ON DELETE RESTRICT;
```
Gộp luôn cả hai vấn đề trên vào một migration.

## 4. `agent_keys` — còn thiếu gì cho câu hỏi "user nào dùng bao nhiêu"

Hiện có: `id, tenant_id, key_sha256, key_prefix, label, api_key, created_by, created_at, revoked_at, last_used_at`.

**Tin tốt:** `created_by` đã lưu user id portal (`u_dungnd`, `u_dutn_2`) → group-by `created_by`
join `control.users` là **trả lời được ngay** "user nội bộ nào dùng bao nhiêu", không cần thêm cột.
Nên đưa vào v1.

**Còn thiếu** (chỉ cần nếu key được cấp cho user của app ngoài): `external_user_ref` — id người dùng
bên app ngoài. Hiện `label` là free-text (`"key from prod"`, `"dev"`, `"key 1"`, `"key 2"`) nên không
map được sang danh tính app. Nếu giai đoạn này key vẫn do nhân viên tự tạo trong portal thì
**bỏ qua cột này**, `created_by` là đủ.

## 5. Màn hình v1 — 3 màn

Bộ lọc chung: khoảng thời gian + channel.

**a) Overview**
KPI: Tổng token (in/out) · Thời lượng voice · Số session · Số key hoạt động.
Cột chồng theo ngày (chồng theo `component`; đổi được sang `model` / `channel` / `purpose`).
Dải cảnh báo: số event `exact=false` **và** số event không có số đo (mục 2).

**b) Usage by Key** — màn hình lõi
Bảng: Key (`label` + `key_prefix`) · Người tạo (`created_by` → tên user) · Số session ·
Input · Output · Cache read · Voice-sec · Số event · Trạng thái (active/revoked).
Sort, search, export CSV. Dòng cuối cố định: **"Chưa phân loại (không có key)"**.
Bấm 1 key → sang Sessions đã lọc.

Thêm tab **By owner**: gộp theo `created_by`, join `control.users`.

**c) Sessions** — drill-down
`usage_by_session` join `conversations` (`agent_key_id`, `customer_name`, `phone`, `source`).
Bảng: Session · Key · Khách · Channel · Bắt đầu · Turn · Token · Voice-sec · badge `exact`.
Bấm vào → timeline theo `seq`/`turn_idx`: từng event với component, purpose, model, token/giây.

Chưa làm: Invoices, Pricing. Cột Cost thêm sau, 3 màn trên không phải sửa cấu trúc.

## 6. Thứ tự làm

1. **Chốt ngữ nghĩa `call` vs component con** (mục 2) — ảnh hưởng trực tiếp cách hiển thị voice.
2. Migration: composite FK + `ON DELETE RESTRICT` (mục 3).
3. Chốt endpoint xoá key → chuyển sang set `revoked_at`.
4. View `billing.usage_by_key_day`.
5. API: `GET /usage/summary`, `/usage/by-key`, `/usage/by-owner`, `/usage/sessions`, `/usage/sessions/{id}`.
6. UI 3 màn.
7. Fix agent: event `stt/stream` không có số đo nào.

Bước 2–6 làm được ngay không cần biết giá.

## 7. Việc trong spec cũ nay BỎ
- ~~Thêm `deployment_id` vào `usage_events`~~ — `deployments` không còn.
- ~~Thêm `api_key_id`, `actor_id` vào `usage_events`~~ — đã giải quyết bằng `conversations.agent_key_id`.
- ~~Thêm `tenant_id` vào `agent_keys`~~ — đã xong.
- ~~Thêm FK `conversations.agent_key_id`~~ — đã xong (còn siết thêm ở mục 3).
- ~~Bỏ cột `api_key` plaintext~~ — chủ ý của chủ hệ thống, giữ nguyên.
