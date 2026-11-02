# Hợp đồng đấu nối — portal ↔ pod agent

> **Trạng thái: BẢN GIAO TRƯỚC.** Portal chưa ship endpoint `/agent/v1/bootstrap` (kế hoạch:
> `docs/superpowers/plans/2026-08-03-m10-dau-noi-agent-ngoai.md`). File này giao trước để hai bên
> làm song song. **Hình dạng request/response ở §2 là cam kết** — portal sẽ code đúng theo nó.
> Nếu portal buộc phải đổi, portal báo trước và cập nhật file này.
>
> **Ngày:** 2026-08-03 · **Cho:** `santa-hotline-agent` (Gói G) ·
> **Bổ sung cho:** [`bundle.md`](bundle.md) — không thay thế.
>
> `bundle.md` nói *nội dung cấu hình có gì*. File này nói *pod lấy quyền truy cập bằng cách nào*.

---

## 0. Đọc cái này trước: cái gì đổi, cái gì không

**Không đổi:** cách pod nhận cấu hình (poll `LIVE` mỗi 20s, verify sha256), cách pod báo trạng thái
(ghi `control.agent_heartbeats`), cấu trúc bundle, ba lớp cách ly. Toàn bộ `bundle.md` vẫn đúng
nguyên văn.

**Đổi đúng một thứ:** pod không còn nhận credential qua biến môi trường. Nó nhận **một api_key**,
gọi một endpoint, và lấy về credential.

```
TRƯỚC (hôm nay)                          SAU
────────────────────────────────         ────────────────────────────────
TENANT_ID=anphu                          PORTAL_URL=https://portal.internal
POSTGRES_URI_REAL=postgres://...         AGENT_API_KEY=ody_ag_...
S3_ACCESS_KEY=...
S3_SECRET_KEY=...                        (bốn cái kia pod TỰ LẤY VỀ)
QDRANT_COLLECTION_ROOT=document_v4
```

**Vì sao đổi:** hôm nay ops phải chạy tay bốn việc rồi copy-paste ba credential vào env của mỗi pod.
Không có bảng nào ghi *"pod này thuộc tenant nào"*, không có đường thu hồi, không có đường xoay
khoá. Và `QDRANT_COLLECTION_ROOT` là **một biến toàn hệ** — hai tenant dùng chung một collection.

**Nguyên tắc chi phối, đọc một lần rồi nhớ:**

> `api_key` nói **"tôi là ai"**. Credential nói **"tôi được làm gì"**. Không gộp hai vai.

api_key **không** phải token để gọi API dữ liệu. Nó dùng đúng một việc: đổi lấy credential lúc khởi
động (và lúc làm mới). Sau đó pod nối thẳng Postgres · Qdrant · kho tệp như hôm nay.

---

## 1. Hai biến môi trường, không hơn

```bash
PORTAL_URL=https://portal.internal      # không có dấu / ở cuối
AGENT_API_KEY=ody_ag_<43 ký tự base64url>
```

**Nếu bạn thấy mình cần thêm một biến nữa**, thì hoặc bootstrap thiếu trường — báo portal — hoặc bạn
đang đi đường tắt. Đừng thêm biến; báo lại.

Khoá do admin nền tảng phát, **hiện đúng một lần** lúc tạo deployment. Portal chỉ lưu `sha256` của
nó; không ai đọc lại được khoá thô, kể cả admin. Mất khoá ⇒ phát khoá mới, không khôi phục.

Mỗi **deployment** một khoá riêng. Một tenant có thể có hai deployment (`chat` và `voice`) ⇒ hai
khoá khác nhau, cùng trỏ về một tenant.

---

## 2. Bootstrap — hợp đồng đầy đủ

### Request

```http
POST /api/v1/agent/v1/bootstrap HTTP/1.1
Host: portal.internal
Authorization: Bearer ody_ag_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Không body. Không query param. Không cookie — **cookie phiên bị bỏ qua hoàn toàn**, kèm cookie hợp
lệ mà thiếu `Bearer` vẫn là `401`.

### Response `200`

```jsonc
{
  "tenant_id": "anphu",
  "deployment_id": 12,
  "kind": "chat",                                   // "chat" | "voice"

  "postgres_dsn": "postgresql://agent_anphu:<mật khẩu>@pg.internal:5432/odyssey",

  "storage": {
    "endpoint":   "https://s3.internal",
    "bucket":     "odyssey",
    "access_key": "agent-anphu",
    "secret_key": "<bí mật>",
    "prefix":     "tenants/anphu/"                  // chỉ đọc/ghi được dưới tiền tố này
  },

  "kb": {
    "url":        "https://qdrant.internal",
    "collection": "kb_anphu"                        // ⚠️ DÙNG ĐÚNG CHUỖI NÀY
  },

  "live_url": "tenants/anphu/LIVE",                 // object để poll — xem bundle.md §1

  "expires_at": "2026-08-03T09:00:00Z"              // ISO 8601, UTC, TUYỆT ĐỐI
}
```

**`expires_at` là mốc tuyệt đối, không phải TTL tương đối** — pod không phải cộng trừ, không phải
đoán lệch đồng hồ giữa hai máy. Mặc định 1 giờ.

### Làm mới

Gọi lại **đúng endpoint đó, đúng api_key đó**. Không có refresh token, không có endpoint riêng.
Bootstrap là **idempotent**: gọi 10 lần trả về cùng credential (miễn `secret_version` chưa đổi).

Đề nghị: làm mới khi còn **1/4 TTL** (≈15 phút). Sớm hơn là tự tạo tải; muộn hơn là không còn chỗ
để thử lại.

### Bốn mã lỗi

| HTTP | `error.code` | Nghĩa | Pod nên làm gì |
|---|---|---|---|
| `401` | `INVALID_AGENT_KEY` | Thiếu header · sai định dạng · không khớp · **đã thu hồi** | **Dừng hẳn.** Không thử lại vòng lặp. Báo ops |
| `403` | `TENANT_SUSPENDED` | Workspace đang tạm ngưng | Dừng phục vụ. Thử lại thưa (5–10 phút) |
| `409` | `NOT_PROVISIONED` | Cấp phát chưa xong — `message` nói thiếu cái gì | Thử lại sau 30s. Nếu quá 5 phút, báo ops |
| `429` | `RATE_LIMITED` | Quá 10 lần / 5 phút cho một khoá | Backoff. Nếu gặp mã này ở vận hành bình thường thì vòng lặp làm mới của bạn sai |

Hình dạng lỗi thống nhất toàn portal:

```jsonc
{ "error": { "code": "INVALID_AGENT_KEY", "message": "Khoá đấu nối không hợp lệ" } }
```

> **`401` cố ý không phân biệt** *"khoá không tồn tại"* với *"khoá đã thu hồi"* — cùng mã, cùng câu
> chữ. Đừng parse `message` để đoán; nó sẽ không nói cho bạn biết đâu.

---

## 3. Mười hai yêu cầu

### G-1 · Env chỉ còn hai biến

Gỡ khỏi cấu hình pod: `TENANT_ID` · `POSTGRES_URI_MOCK` · `POSTGRES_URI_REAL` · khoá S3 ·
`QDRANT_COLLECTION_ROOT`.

Giữ nguyên các biến **không liên quan tenant** (`STT_BACKEND`, `SHERPA_*`, khoá LLM…) — hợp đồng này
chỉ nói về credential theo tenant.

### G-2 · Fail-fast, cấm fallback

Bootstrap hỏng ⇒ **pod dừng**, không phục vụ. Cấm mọi đường lui:
- Không dùng credential cũ còn trong bộ nhớ.
- Không đọc lại từ env.
- Không cache credential ra đĩa để lần sau dùng khi portal chết.

> Fallback âm thầm là đường quay lại cấu hình sai mà không ai thấy: pod chạy tiếp, đọc dữ liệu bằng
> khoá đã thu hồi, và không có gì báo động. Một pod chết ồn ào chẩn đoán được; một pod sống mà sai
> thì không.

**Ngoại lệ duy nhất:** credential đang dùng vẫn được dùng tới `expires_at` khi bootstrap *làm mới*
thất bại tạm thời. Đó không phải fallback — đó là dùng thứ chưa hết hạn.

### G-3 · Bỏ `QDRANT_COLLECTION_ROOT` 🔴

Tên collection lấy từ `kb.collection` của bootstrap. **Không hàm nào được nhận tên collection làm
tham số** — không từ request, không từ session, không từ tool argument.

Hôm nay `.env:285` đặt `QDRANT_COLLECTION_ROOT=document_v4` cho toàn hệ và tầng RAG lọc theo
`project_id`. Một tenant thì vô hại; **hai tenant thì `kb_search` của B trả về chunk của A**.

Đây là yêu cầu **chặn production đa-tenant**, không phải việc dọn dẹp.

Kiểm tra: `grep -rn "QDRANT_COLLECTION" src/` phải chỉ còn **một** chỗ — nơi gán giá trị từ
bootstrap response.

### G-4 · Redis — *tách ra, sẽ có bổ sung*

Số hiệu giữ chỗ. Xem §5 — **đọc trước khi thiết kế lại phần state**, vì làm sau sẽ đắt hơn.

### G-5 · Bỏ thư mục tenant cứng trong image

`src/noble_agent/tenants/{noble, demo_acme}` phải biến mất. **Một image cho mọi tenant**; cấu hình
đến từ bundle, không từ thư mục được build vào ảnh.

### G-6 · Postgres: chỉ view, không bảng

| Được | Không được |
|---|---|
| `SELECT` trên `agent_api.units` · `agent_api.projects` | `tenant_data.*` — **bất kỳ bảng nào** |
| `INSERT`/`UPDATE` trên `control.agent_heartbeats` | `control.*` — mọi bảng khác |

Quyền đã chặn ở Postgres (`test_role_privileges.py` cổng 5 canh), nhưng code không nên thử: một lỗi
`permission denied` lúc chạy khó chẩn đoán hơn là không viết câu đó.

**Vì sao view chứ không bảng:** view là **definer** và nó cưỡng chế hai thứ mà bảng gốc không có —
lọc tenant, và gate cột theo `field_policy_live` (ba trường thương mại `commission` ·
`bank_support` · `csbh_full` về `NULL` nếu workspace chưa bật). Đọc thẳng bảng là đi vòng qua cả hai.

### G-7 · Nạp bundle nguyên khối

Poll `LIVE` mỗi **20s** · verify **sha256** · nạp **atomic**. Verify hỏng hoặc nạp hỏng ⇒ **giữ
nguyên bản đang chạy**, ghi `last_error`, tiếp tục phục vụ bằng bản cũ.

Chi tiết ở `bundle.md §1–§4`. Không bao giờ phục vụ cấu hình nạp nửa vời.

### G-8 · Heartbeat mỗi 20s

```sql
INSERT INTO control.agent_heartbeats
    (tenant_id, deployment_id, running_version, bundle_sha, agent_version)
VALUES (…)
ON CONFLICT (tenant_id, deployment_id) DO UPDATE
    SET running_version = excluded.running_version,
        bundle_sha      = excluded.bundle_sha,
        last_error      = '',
        last_seen_at    = now()
```

`deployment_id` lấy từ **bootstrap response**, không tự sinh, không đoán.

Portal suy bốn chip trạng thái từ đúng bảng này (`bundle.md §5`). Gửi thưa hơn **60 giây** ⇒ portal
báo Mất kết nối cho khách hàng nhìn thấy.

### G-9 · `/chat/ws` trả `tools_used`

Kèm mỗi câu trả lời, danh sách kỹ năng agent đã gọi trong lượt đó.

Nợ từ M5 §7. Đây là cách **duy nhất** người dùng thấy được bật/tắt kỹ năng có tác dụng thật — không
có nó thì màn Agent Studio là 12 công tắc không ai kiểm chứng được.

### G-10 · Cấm log bootstrap response

Không `logger.*`, không `print`, không APM span, không breadcrumb, không `repr()` trong except.
Response chứa **mật khẩu Postgres** và **secret key S3**.

An toàn để log: `tenant_id` · `deployment_id` · `kind` · `kb.collection` · `expires_at`.

### G-11 · Bỏ khoá rỗng trước khi đưa vào ngữ cảnh LLM

`_serialize.py` phải **bỏ hẳn khoá** có giá trị `NULL`/rỗng, không đưa `"field": null` vào prompt.

**Vì sao portal không làm được:** một SQL view trả về **tập cột cố định**. Nó không có cách "bỏ
khoá". Nên luật này chỉ cưỡng chế được ở chỗ nó thực sự hỏng — phía agent.

Hiện **7 trên 18 khoá luôn rỗng**, gần 40% payload là nhiễu.

> Đây là **điều kiện đánh đổi**: portal đồng ý đưa `floor` · `building` · `zone` lên view (chúng
> hữu ích khi *đọc* — agent nói *"Toà S2.03"* cho khách) với điều kiện agent không nhồi khoá rỗng
> vào ngữ cảnh. Không có G-11 thì ba cột đó bị rút khỏi view.

### G-12 · Gỡ filter `floor` và `tower` khỏi `schemas.py`

Tool schema của kỹ năng tra căn không được khai hai filter đó.

Portal seed `filterable = false` cho chúng, nhưng **tool schema là artefact của repo agent** —
portal không với tới được. Nếu schema vẫn khai, LLM sẽ gọi với `floor=14`, tầng bị bỏ qua ở tầng
truy vấn, và agent đọc kết quả **như thể đúng**. Khách hỏi *"căn tầng 14"* nhận về căn tầng bất kỳ.

Nguồn sự thật về tool: `contracts/tools.json` của portal. Cờ `filterable` ở đó quyết định filter nào
hợp lệ.

---

## 4. Điều portal cam kết lại

| Cam kết | Nghĩa với bạn |
|---|---|
| `expires_at` là mốc tuyệt đối UTC | Không phải đoán TTL, không phải bù lệch đồng hồ |
| `postgres_dsn` đã gồm role đúng | Pod **không** cần biết quy tắc `agent_<slug>` |
| `kb.collection` đã là tên đầy đủ | Pod **không** cần biết quy tắc `kb_<tenant_id>` |
| `storage.prefix` đã gồm dấu `/` cuối | Nối chuỗi trực tiếp, không xử lý biên |
| Bootstrap idempotent | Gọi lại nhiều lần vô hại; retry an toàn |
| Xoay bí mật **không** ngắt kết nối đang mở | Postgres chỉ hỏi mật khẩu lúc nối mới. Pod có trọn một chu kỳ TTL để chuyển |
| Hai deployment cùng tenant nhận **cùng** `postgres_dsn` | Pod `chat` và `voice` không đá nhau |
| Đổi hình dạng response = báo trước + cập nhật file này | Không có đổi âm thầm |

---

## 5. 🔴 Cảnh báo sớm — Redis là kho thứ tư, chưa có cơ chế

**Chưa phải yêu cầu. Đọc trước để không phải làm lại.**

`santa-hotline-agent` lưu trạng thái hội thoại vào Redis:

```
session:<id>:meta · session:<id>:customer · session:<id>:state
```

Nội dung là **tên, số điện thoại, ngân sách, hoàn cảnh gia đình của khách hàng cuối**. `.env:357`
trỏ tới một Redis dùng chung. **Key không mang `tenant_id`; không cơ chế nào chặn hai tenant đọc key
của nhau.**

Ba kho kia đều có cách ly cưỡng chế bằng hạ tầng — Postgres có RLS, kho tệp có policy tiền tố,
Qdrant có collection riêng. Redis hiện **không có gì**.

**Hướng đang chốt** (sẽ thành G-4):

| | |
|---|---|
| Key prefix | `t:<tenant_id>:session:<id>:*` — sinh từ **một hàm duy nhất**, không nhận tham số nào khác |
| Cưỡng chế | Redis ACL user với pattern `~t:<tenant_id>:*` — chặn ở **server**, không ở kỷ luật code |
| Credential | Cấp qua chính bootstrap (thêm khối `redis` vào response — cộng thêm, không phá hợp đồng §2) |

**Đề nghị làm ngay bây giờ, dù chưa chốt:** đưa việc dựng key qua **một hàm** thay vì nối chuỗi rải
rác. Khi G-4 chốt, đổi một hàm rẻ hơn đổi ba mươi chỗ.

Chi tiết: `docs/contracts/isolation.md §11`.

---

## 6. Bốn cách hỏng và dấu hiệu nhận biết

| Triệu chứng | Nguyên nhân thường gặp | Tra ở đâu |
|---|---|---|
| `401 INVALID_AGENT_KEY` | Khoá bị thu hồi · gõ thiếu ký tự · dùng khoá của môi trường khác | Hỏi admin: `control.agent_keys.revoked_at` |
| `409 NOT_PROVISIONED` | Role Postgres hoặc collection Qdrant chưa tạo | `message` nói thiếu cái gì. Admin bấm cấp phát lại |
| Nối được, `agent_api.units` trả **0 hàng** | Chưa dự án nào bật *Agent dùng* (`agent_enabled`) | Admin: `GET /admin/deployments` → `san_sang_du_lieu.projects_agent_enabled` |
| Trả hàng nhưng mọi cột thương mại là `NULL` | `field_policy_live` chưa seed cho workspace | `san_sang_du_lieu.field_policy_rows` |

**Hai dòng cuối là loại hỏng tệ nhất:** pod chạy đúng, không lỗi nào, và agent tư vấn bằng một
payload rỗng hoặc toàn `NULL`. Im lặng và trông như đang hoạt động. Nếu agent bỗng "không biết gì",
kiểm hai con số đó **trước** khi debug phía agent.

---

## 7. Chỗ tra khi lệch

| Câu hỏi | Nguồn |
|---|---|
| Bootstrap trả những trường nào | `src/portal/modules/enrollment/contracts.py::BootstrapOut` |
| Tên role · collection · khoá S3 sinh ra sao | `src/portal/core/ten_tai_nguyen.py` |
| Policy tiền tố kho tệp | `src/portal/core/storage.py::chinh_sach_tien_to` |
| Một pod tối thiểu chạy ra sao | `scripts/agent_gia.py` — **~100 dòng, đọc nó trước khi đọc lại file này** |
| Bundle có những tệp nào · sha tính thế nào | [`bundle.md §3`](bundle.md) |
| Vì sao ba lớp cách ly như vậy | [`isolation.md`](isolation.md) |
| Tool nào có filter nào | `contracts/tools.json` |

> `scripts/agent_gia.py` là **spec sống**. Nó không giả lập LLM, không giả lập tool — nó làm đúng
> phần hợp đồng này quan tâm: bootstrap → poll LIVE → verify sha → heartbeat. Khi có mâu thuẫn giữa
> file này và `agent_gia.py`, **mã thắng** và file này phải sửa.

---

## 8. Thứ tự đề nghị cho bên agent

Không phụ thuộc portal ship xong — bốn việc đầu làm được ngay:

1. **G-3** — bỏ `QDRANT_COLLECTION_ROOT`, đưa tên collection thành một biến runtime đọc từ một chỗ
   duy nhất. *Chặn production đa-tenant, và độc lập hoàn toàn với bootstrap.*
2. **G-5** — bỏ thư mục tenant cứng.
3. **G-11 · G-12** — serializer bỏ khoá rỗng; gỡ hai filter. *Không phụ thuộc gì cả.*
4. **§5** — gom việc dựng Redis key về một hàm.
5. **G-1 · G-2** — client bootstrap. *Cần portal ship endpoint; test được bằng một stub trả JSON §2.*
6. **G-6 · G-7 · G-8** — rà lại đường đọc và heartbeat theo credential mới.
7. **G-9** — `tools_used`.

**Câu hỏi hoặc thấy hợp đồng thiếu chỗ nào: báo lại trước khi code**, đừng đoán. Đổi hợp đồng lúc
này rẻ; đổi sau khi hai bên đã code thì không.
