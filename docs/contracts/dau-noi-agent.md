# Hợp đồng đấu nối — portal ↔ pod agent

> **2026-10-06 — bundle/`LIVE` gỡ hẳn khỏi portal, không breaking.** Portal thôi publish bundle từ
> `0966`; nay `/runtime-credentials` thôi trả `live_url` (agent parse bằng `.get(…) or ""`), và
> `bundle.md` · `scripts/agent_gia.py` đã xoá. Mọi chỗ dưới đây nhắc G-7, `LIVE`, `bundle.md`,
> `agent_gia.py` là lịch sử — agent đọc cấu hình từ `tenant_data.agent_config`.

> **2026-10-06 — bảng agent ĐỌC thêm: `tenant_data.kich_ban` (`0976`, playbook template đợt 2), không breaking.**
> `SELECT nut, role_dung FROM tenant_data.kich_ban WHERE tenant_id = $1` (RLS FORCE + `GRANT SELECT TO PUBLIC` như
> `role_config`). Không hàng ⇒ chạy template, kịch bản chỉ bật cho role `customer`; `nut` NULL ⇒ template, `role_dung`
> vẫn áp. `nut` = mảng nút lớp sale, khuôn `id, ten, nhom, bat, kenh[], dau_hieu[], lam[], tool[], cam[], khi_thieu,
> cau_ket, lan_2, chi_lan_2, nguon, buoc[{id, lam}]` — portal kiểm theo `gioiHan` agent xuất trong `playbook.json`.
> Mỗi lần ghi portal gọi `tang_version()` ⇒ agent dựng runner mới cho phiên mới. Agent deploy trước `0976`: bảng chưa
> có = không hàng. Agent ghi `meta.playbook.h` (hash nút) để `/playbook` đếm theo nút.

> **⚠️ 2026-08-19 (PHA 2) — `control.deployments` BỎ HẲN, NHỊP TIM ĐỔI KHOÁ, BREAKING:**
> `agent_heartbeats` nay khoá theo `tenant_id` — cột `deployment_id` đã bỏ cùng bảng nguồn
> (`0941`). §G-8 viết lại bên dưới. **NHỊP TIM CHẠY LẠI ĐƯỢC** — nó đã chết từ `0919`, xem
> ghi chú trong §G-8.
> **Đã sửa sẵn ở repo `odyssey-agent` cùng đợt này** (không phải việc bạn phải làm):
> `pg_heartbeat._UPSERT` → `ON CONFLICT (tenant_id)`, `beat()` bỏ tra deployment,
> `read_deployment_id` xoá, `deployment_id`/`kind` gỡ khỏi `RuntimeCredentials` ·
> `TenantPgCredential` · stash Redis · header `X-PG-Deployment`/`X-PG-Kind`.
> **Thứ tự triển khai:** Portal `0941` TRƯỚC, agent SAU — trong khoảng giữa, agent bản cũ
> ghi nhịp tim thất bại và nuốt lỗi (nó vốn đã thất bại từ `0919`), không có gì tệ hơn xảy
> ra. Chiều ngược lại cũng an toàn: agent bản mới ghi `ON CONFLICT (tenant_id)` lên bảng
> chưa migrate sẽ lỗi và cũng bị nuốt.

> **⚠️ 2026-08-19 — BỎ TRƯỜNG `deployment_id` KHỎI RESPONSE, BREAKING:** `/runtime-credentials`
> không còn trả `deployment_id` (migration `0940` bỏ `control.agent_keys.deployment_id` — khoá
> treo thẳng vào `tenant_id`). **Pod của bạn KHÔNG vỡ**: mọi chỗ trong `odyssey-agent` đã đọc
> trường này là `int | None` (`gateway/credentials.py` dùng `data.get`, `chat_proxy.py` chỉ set
> header `X-PG-Deployment` khi khác `None`), và `tenant/pg_heartbeat.py::beat()` fail-soft.
> **Hệ quả DUY NHẤT: heartbeat §G-8 ngừng ghi** — `agent_heartbeats` PK còn `(tenant_id,
> deployment_id)` NOT NULL nên không có id thì không chèn được hàng. Portal sẽ hiện workspace là
> «Mất kết nối» sau ~60s; đó là NHÃN hiển thị, cổng phục vụ vẫn là `lifecycle='active'` nên chat
> và voice không bị chặn. Đừng tra ngược `control.deployments` để lấy id — role `agent_<tenant>`
> chưa bao giờ có `SELECT` trên bảng đó, và view `agent_api.deployments` đã xoá từ `0917` (nhánh
> fallback `read_deployment_id` của bạn hỏng sẵn từ đó, chỉ chưa ai để ý vì nó nuốt lỗi).
> **Việc cần làm bên bạn:** gỡ hằng `_SQL_DEPLOY` (`storage/agent_control_store.py`) và nhánh
> fallback trong `beat()`. Không sửa thì mỗi nhịp để lại một dòng `logger.warning`, không hơn.
> **Pha 2 (chưa làm, cần bạn xong trước):** `control.deployments` bỏ hẳn, `agent_heartbeats` đổi
> khoá sang `tenant_id` — lúc đó heartbeat chạy lại và §G-8 sẽ được viết lại.

> **⚠️ 2026-08-15 — `kb.api_key` MỚI. Additive (chưa gãy gì), NHƯNG cần bạn sửa code SỚM:**
> `/runtime-credentials` nay trả thêm `kb.api_key` — một JWT chỉ-đọc, chỉ trên collection của
> chính tenant, hết hạn cùng `expires_at`. Đặt vào header `api-key` khi nối Qdrant. Hiện có thể
> là `null` (môi trường chưa bật xác thực Qdrant) ⇒ nối không kèm header, y như hôm nay.
>
> **Vì sao gấp dù chưa gãy:** trước bản này Qdrant **không có xác thực nào** — Postgres có RLS,
> kho tệp có policy theo tiền tố, còn Qdrant chỉ có *tên collection*, mà tên là thứ pod tự gõ.
> Pod hỏi `kb_<tenant khác>` thì Qdrant **trả dữ liệu**. Ngày khoá được bật, pod nào chưa đọc
> trường này sẽ `403` toàn bộ ngay giây đó. Đọc §2 mục «`kb.api_key`» và «Bật xác thực Qdrant»
> — ba bước, có thứ tự bắt buộc, không phút gián đoạn nào nếu làm đúng.

> **⚠️ 2026-08-10 — ĐỔI TÊN ENDPOINT, BREAKING:** `POST /api/v1/agent/bootstrap` đổi thành
> `POST /api/v1/agent/runtime-credentials`. Cùng method, cùng auth (`Bearer api_key`), cùng
> response — CHỈ đổi path. Model Pydantic `BootstrapOut` đổi thành `RuntimeCredentialsOut`
> (chỉ ảnh hưởng nếu bạn generate client từ schema). Lý do: "bootstrap" không nói rõ endpoint
> trả về CÁI GÌ (credential DB/S3/Qdrant để pod chạy runtime), dễ nhầm với việc khởi tạo
> tenant/deployment. Cập nhật `scripts/agent_gia.py` phía bạn trước khi deploy lên môi trường
> dùng chung với portal.
>
> **⚠️ 2026-08-10 — BỎ HẲN `agent_api` (Postgres), BREAKING KHÁC, ĐỌC §G-6 TRƯỚC KHI ĐỘNG CODE:**
> mọi view `agent_api.*` (units/projects/zones/documents/media/tenant_status/tenant_keys/
> deployments/agent_published_config) đã bị xoá khỏi DB — nếu bạn có code đọc `db-mode` qua
> Postgres, nó sẽ vỡ ngay với `relation "agent_api.x" does not exist`. Thay vào: đọc thẳng
> `tenant_data.*` và tự lọc `status='published'` + cascade — Portal không còn làm hộ. Nếu bạn
> CHƯA từng triển khai đường đọc Postgres này (chỉ dùng `/runtime-credentials` +  poll `LIVE`
> trên kho tệp như G-1..G-2..G-7 mô tả) thì thay đổi này **không ảnh hưởng gì** tới bạn.
>
> **⚠️ 2026-08-10 — ĐỔI HÌNH DẠNG RESPONSE, BREAKING THỨ BA CÙNG NGÀY:** trường `postgres_dsn`
> (chuỗi DSN gộp sẵn) đã bỏ, thay bằng hai trường `postgres_role` + `postgres_password`. Bạn tự
> ghép với `POSTGRES_HOST`/`POSTGRES_PORT`/`POSTGRES_DATABASE` — ba biến môi trường MỚI, tĩnh,
> không phải bí mật (xem §1, G-1). Lý do: host/port/database giống nhau cho mọi tenant, không cần
> đi qua API mỗi lần; chỉ role/password mới thật sự đổi theo tenant và theo lần xoay bí mật.
>
> **⚠️ 2026-08-12 — BỎ TRƯỜNG `kind` KHỎI RESPONSE, BREAKING:** `/runtime-credentials` không còn
> trả `"kind": "chat" | "voice"`. Lý do: khoá không phân biệt kênh — MỘT khoá/deployment mở được
> CẢ `ENDPOINT_CHAT_URL` lẫn `ENDPOINT_VOICE_URL`, cùng một `postgres_role`. `kind` trước đây chỉ
> phản ánh việc đường tự phát khoá hardcode `"chat"`, không phải một thuộc tính thật của deployment
> — cột `control.deployments.kind` đã xoá (`0919_bo_cot_kind_deployments`). Nếu code của bạn đọc
> trường `kind` từ response này, hãy bỏ — không có giá trị thay thế, không cần vì không còn khái
> niệm "deployment theo kênh".
>
> **Trạng thái: PORTAL ĐÃ SHIP.** `POST /api/v1/agent/runtime-credentials` chạy được, có 37 test
> canh (`tests/modules/enrollment/`). Mọi con số và tên trường trong file này đã đối chiếu với
> code — nguồn: `src/portal/modules/enrollment/contracts.py`.
>
> **Ngày:** 2026-08-03 · **Cho:** `santa-hotline-agent` (Gói G) ·
> **Bổ sung cho:** [`bundle.md`](bundle.md) — không thay thế.
>
> `bundle.md` nói *nội dung cấu hình có gì*. File này nói *pod lấy quyền truy cập bằng cách nào*.
>
> **Mã mẫu chạy được:** `scripts/agent_gia.py` (~200 dòng) làm đúng chuỗi này — runtime-credentials
> → poll LIVE → verify sha256 → heartbeat. Đọc nó trước khi đọc hết file này.

---

## 2c. Từ điển cách đọc TTS theo tenant (mới, 2026-08-24)

`tenant_data.agent_config` có cột mới `tts_normalization jsonb` — một **object** `{term:
read_as}`, là lớp **chồng lên** `data/tts_normalize_vi.json` của repo agent, không thay nó.

**Ngữ nghĩa ghi đè, ba vế:**
1. Từ điển tenant chạy thành **một pass riêng, sớm nhất** trong các pass thay chữ — trước
   `_ROMAN_RE`/`_CODE_RE`, `strict_upper=True` (khoá viết HOA toàn bộ khớp có phân biệt
   hoa/thường).
2. Khoá nào tenant định nghĩa thì **mục nền CÙNG KHOÁ bị vô hiệu hoá** cho lượt đó. Không
   có vế này thì bản phiên âm của tenant bị chính mục nền viết lại — đo được:
   `Vietcombank → vietcombank đọc kiểu khác` ra `việt com bank đọc kiểu khác`.
3. Mọi luật nền **khác khoá** vẫn áp lên văn bản thay ra. Đó chính là thứ làm số/ngày/tiền
   bên trong bản thay ra vẫn đọc đúng.

Portal ghi cột này trong cùng giao dịch với `config_versions` lúc «Lưu và áp dụng».

⚠️ **THỨ TỰ DEPLOY MỘT CHIỀU: migration portal (`0954_tts_normalization`) TRƯỚC, agent SAU.**

Đảo lại thì agent KHÔNG chết — `read_published_config` bắt `except Exception`, log một
`warning`, rồi phục vụ cache last-good trên đĩa. Hệ quả nặng hơn một lần crash: agent **đóng
băng ở bản cache cũ** và **mọi lần publish sau đó của portal bị bỏ qua**, không dấu hiệu nào
ở phía người dùng. Pod mới chưa có cache thì `_read_last_good` trả `None` — không có cấu
hình nào.

⚠️ Cột này là **OBJECT**, khác `departments`/`skills` là mảng. Bên agent nó nằm trong
`_JSON_OBJECT_COLUMNS` (giải mã bằng `or {}`), KHÔNG nằm trong `_JSON_COLUMNS` — `{}` là
falsy trong Python nên `or []` sẽ biến một từ điển rỗng thành `[]`, và `parse_config` nhận
list ở chỗ nó chờ dict.

**Đã sửa sẵn ở repo `odyssey-agent` cùng đợt này** (không phải việc bạn phải làm):
`agent_config_store._COLUMNS` + `_JSON_OBJECT_COLUMNS`, `AgentConfig.tts_normalization`,
`_normalize.set_tenant_overrides()` và một pass regex riêng chèn sớm trong
`normalize_for_voice()` (trước `_CODE_RE`, `strict_upper=True`).

⚠️ **`contracts/agent-config.json` mang khoá `voice.tts_normalization`, nhưng db-mode KHÔNG
đọc hình dạng lồng đó** — nó đọc cột phẳng ở cấp gốc của hàng. Khoá trong mẫu vàng để dành
cho ngày nào có ai đọc; hôm nay nó chưa canh gì. Xem thêm docstring
`scripts/gen_contracts.py::noi_dung_agent_config`.

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

## 1. Ba biến môi trường (đổi từ HAI, 2026-08-10 — xem G-1)

```bash
PORTAL_URL=https://portal.internal      # không có dấu / ở cuối
AGENT_API_KEY=ody_ag_<43 ký tự base64url>
POSTGRES_HOST=pg.internal
POSTGRES_PORT=5432
POSTGRES_DATABASE=odyssey
```

Ba biến sau (`POSTGRES_*`) **không phải bí mật** — chúng giống nhau cho mọi tenant, y hệt lý do
`PORTAL_URL` không đi qua API (§ "PORTAL_URL không có trong khối đó"). Response `/runtime-credentials`
giờ chỉ trả phần THẬT SỰ đổi theo tenant/lần xoay bí mật: `postgres_role` + `postgres_password`.

**Nếu bạn thấy mình cần thêm một biến nữa**, thì hoặc `/runtime-credentials` thiếu trường — báo portal — hoặc bạn
đang đi đường tắt. Đừng thêm biến; báo lại.

Khoá hiện ngay lúc phát, và **từ `0918`** cũng đọc lại được sau đó qua `GET /agent/keys`
(`KhoaOut.api_key`) — portal vẫn lưu `key_sha256` để xác thực như cũ, nhưng giờ lưu THÊM bản thô
để `/thu-agent` (frontend) dựng được `<select>` chọn khoá theo tên. Đánh đổi đã ghi rõ trong migration
`0918_agent_keys_them_cot_kho_tho.py`: `api_key` là `NULL` cho khoá tạo trước migration đó.

Mỗi tenant **đúng một deployment**, và khoá của deployment đó dùng chung cho cả `chat` lẫn `voice`
— không có khoá riêng theo kênh (từ `0919`, đọc banner breaking ở đầu file).

### Ai phát khoá — hai đường

| Đường | Ai dùng | Phạm vi |
|---|---|---|
| **Portal → Tích hợp & API** | Owner workspace tự làm | Chỉ workspace của chính họ, deployment `chat` |
| `POST /api/v1/agent/admin/deployments` | Admin nền tảng (`X-Platform-Admin-Token`) | Xuyên tenant |

Đường thứ nhất là đường thường dùng: owner vào **Tích hợp & API**, bấm Tạo khoá mới, và màn hình
hiện sẵn khối hai dòng để gửi cho bạn. Họ cũng thu hồi khoá ở đó.

### `ENDPOINT_CHAT_URL` / `ENDPOINT_VOICE_URL` — thứ bạn nhận kèm khoá

Khối mà owner copy từ portal có **ba** dòng:

```bash
ENDPOINT_CHAT_URL=wss://<tenant_id>.agents-dev.noble.vn/v1/chat
ENDPOINT_VOICE_URL=wss://<tenant_id>.agents-dev.noble.vn/v1/voice
AGENT_API_KEY=ody_ag_<43 ký tự base64url>
```

`wss://` — gateway đứng sau TLS termination. Đổi sau này thì chỉ một chỗ trong code đổi
(`url_endpoint_agent()`), không phải sửa lại tài liệu này theo tay.

Hai trường TÁCH RIÊNG vì `chat` và `voice` nối vào hai hostname khác nhau (xem §1 phía trên), dù
cùng dùng chung một khoá/deployment. `ENDPOINT_VOICE_URL` tính ra được bằng công thức thuần suy từ
`tenant_id` + domain, độc lập với việc deployment không còn phân biệt kênh.

`ENDPOINT_*_URL` **không** thay `PORTAL_URL` và **không** dùng để gọi `/runtime-credentials`. Nó nói cho bạn biết
gateway sẽ định tuyến tới pod của workspace đó từ hostname nào — tức đường mà *client* nối vào pod
bạn phục vụ, ngược chiều với `/runtime-credentials`.

`PORTAL_URL` không có trong khối đó vì nó **giống nhau cho mọi tenant** — ops đặt sẵn một lần trong
cấu hình pod. Khối copy chỉ chứa thứ thay đổi theo workspace (`AGENT_API_KEY` + hai `ENDPOINT_*_URL`).
Ba biến tĩnh ở §1 (`PORTAL_URL`, `POSTGRES_HOST/PORT/DATABASE`) vẫn tĩnh; portal chỉ không nhắc lại
những hằng số mà owner workspace không có lý do gì để biết.

Nguồn công thức: `src/portal/modules/enrollment/endpoint.py` · hằng số
`Settings.gateway_base_domain`.

---

## 2. Runtime credentials — hợp đồng đầy đủ

### Request

```http
POST /api/v1/agent/runtime-credentials HTTP/1.1
Host: portal.internal
Authorization: Bearer ody_ag_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Không body. Không query param. Không cookie — **cookie phiên bị bỏ qua hoàn toàn**, kèm cookie hợp
lệ mà thiếu `Bearer` vẫn là `401`.

### Response `200`

```jsonc
{
  "tenant_id": "anphu",
  "agent_key_id": 47,                               // `deployment_id` ĐÃ BỎ 2026-08-19

  "postgres_role":     "agent_anphu",
  "postgres_password": "<mật khẩu>",     // ghép với POSTGRES_HOST/PORT/DATABASE (§1) để nối

  "storage": {
    "endpoint":   "https://s3.internal",
    "bucket":     "odyssey",
    "access_key": "agent-anphu",
    "secret_key": "<bí mật>",
    "prefix":     "tenants/anphu/"                  // chỉ đọc/ghi được dưới tiền tố này
  },

  "kb": {
    "url":        "https://qdrant.internal",
    "collection": "kb_anphu",                       // ⚠️ DÙNG ĐÚNG CHUỖI NÀY
    "public_web_collection": "anphu_public_web",    // MỚI 2026-10-05 — kho dữ liệu web công khai CỦA tenant
    "api_key":    "<JWT>"                           // MỚI 2026-08-15 — có thể null, xem dưới
  },

  "expires_at": "2026-08-03T09:00:00Z"              // ISO 8601, UTC, TUYỆT ĐỐI
}
```

**`agent_key_id` là id của CHÍNH khoá ở header `Authorization`** (`control.agent_keys.id`), không
phải một khoá bất kỳ của workspace. Một tenant cấp nhiều khoá, nên `tenant_id` KHÔNG suy ra được
giá trị này — đừng dùng cái này thay cái kia.

Pod ghi nó vào `tenant_data.conversations.agent_key_id` (cột `bigint` NULLABLE, migration `0939`)
mỗi khi tạo một hàng phiên. Đó là đường DUY NHẤT quy một phiên về khoá đã tạo ra nó — cần cho lúc
thu hồi một khoá bị lộ, và cho việc tách số liệu theo từng pod/kênh. Không ghi thì cột là `NULL`,
nghĩa là "không biết", và không có nguồn nào backfill ngược được.

`agent_key_id` **KHÔNG bí mật** — nó là số thứ tự trong bảng, không phải bản thân khoá. An toàn để
log, khác hẳn `postgres_password`/`storage.secret_key` ở G-10.

**`expires_at` là mốc tuyệt đối, không phải TTL tương đối** — pod không phải cộng trừ, không phải
đoán lệch đồng hồ giữa hai máy. Mặc định 1 giờ.

### `kb.public_web_collection` — MỚI 2026-10-05, **additive**

Dữ liệu web công khai (hồ sơ dự án, thẻ dự án lân cận, bản tin — `docs/contracts/public-web.md`) nay là
**của riêng từng tenant**: collection `<tenant_id>_public_web`, cùng khuôn `<tenant_id>_documents`. Collection
`public_web` dùng chung đã bỏ. `kb.api_key` mở quyền đọc cho **cả hai** collection (`collection` và
`public_web_collection`). Agent suy tên bằng `collection_name(tenant_id, "public_web")` — trường này chỉ để
đối chiếu.

### `kb.api_key` — MỚI 2026-08-15, **additive**, cần bạn sửa code

Đặt vào header **`api-key`** khi nối Qdrant. `exp` của token **trùng đúng** `expires_at` ở trên, nên
một lượt làm mới credential làm mới cả token — không có mốc thứ hai phải theo dõi.

**Trước bản này Qdrant KHÔNG có xác thực nào.** Postgres có RLS, kho tệp có policy theo tiền tố,
còn Qdrant chỉ có *tên collection* — mà tên là thứ pod tự gõ vào truy vấn. Một pod hỏi
`kb_<tenant khác>` thì Qdrant **trả dữ liệu**. Token này đóng đúng khoảng đó: nó chỉ mở **hai**
collection của chính tenant (`collection` + `public_web_collection`), chỉ **đọc**, và **hết hạn**.

⚠️ **`api_key` có thể là `null`** — nghĩa là môi trường đó chưa bật xác thực Qdrant. Khi `null` thì
nối **không kèm** header, như hôm nay.

> **Hãy đọc và dùng trường này NGAY, kể cả khi nó đang `null`.** Đó chính là thứ làm bước bật khoá
> không gián đoạn: pod bản mới chạy đúng ở cả hai phía của mốc chuyển. Nếu bạn đợi tới lúc khoá được
> bật rồi mới sửa, pod sẽ chết ngay giây đó.

Hành vi đo được (Qdrant 1.19.0), **hai chỗ không như trực giác**:

| Thao tác | Kết quả |
|---|---|
| Đọc collection của mình | `200` |
| Đọc collection tenant khác | `403` |
| Ghi vào collection của mình | `403` — token chỉ đọc |
| `GET /collections` | `200`, nhưng **đã lọc**: chỉ thấy kho của mình |
| Token hết hạn · ký sai khoá | `403`, **không phải `401`** |

Hai điều rút ra: **liệt kê không bị từ chối mà bị lọc** (đừng xử lý như lỗi), và **mọi thất bại xác
thực đều `403`** — retry theo `401` sẽ không bao giờ làm mới credential.

### Bật xác thực Qdrant — ba bước, KHÔNG ĐƯỢC ĐẢO THỨ TỰ

Bật `service.api_key` là breaking: mọi pod nối không kèm khoá gãy **ngay giây đó**. Thứ tự dưới đây
không có phút gián đoạn nào, vì ở mỗi bước cả hai phía đều chạy được.

1. **Portal** đặt `QDRANT_API_KEY`. Portal bắt đầu phát JWT; Qdrant **chưa** bật khoá nên vẫn nhận
   mọi request — token gửi lên bị bỏ qua, vô hại.
2. **Agent** deploy bản đọc `kb.api_key`. Chờ mọi pod làm mới credential (**≤ 1 TTL**, mặc định 1 giờ).
   Lúc này mọi pod đã gửi token hợp lệ, mà Qdrant vẫn chưa kiểm.
3. **Qdrant** đặt `QDRANT__SERVICE__API_KEY` = **đúng chuỗi ở bước 1** + `QDRANT__SERVICE__JWT_RBAC=true`.
   Cưỡng chế bắt đầu, và mọi pod đã sẵn sàng từ bước 2.

Bước 1 và 3 dùng **chung một bí mật** — Qdrant verify JWT bằng chính `service.api_key`, không có khoá
ký thứ hai. Đặt lệch nhau thì mọi token đều `403`.

Đảo thứ tự (bật Qdrant trước) = toàn bộ pod `403` cho tới khi credential cũ hết hạn và pod lấy bản
mới. Với TTL 1 giờ, đó là tới một giờ agent không tra cứu được gì.

### Làm mới

Gọi lại **đúng endpoint đó, đúng api_key đó**. Không có refresh token, không có endpoint riêng.
`/runtime-credentials` là **idempotent**: gọi 10 lần trả về cùng credential (miễn `secret_version` chưa đổi).

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

## 2b. Feedback — hợp đồng đầy đủ (mới, 2026-08-12)

Cuối một phiên, nếu người dùng để lại đánh giá, BE của bạn (KHÔNG PHẢI trình duyệt end-user)
gọi endpoint này bằng **CHÍNH `AGENT_API_KEY`** đã dùng cho `/runtime-credentials` — không có
khoá riêng cho feedback, không có bước xác thực mới nào phải học.

⚠️ Cố ý thiết kế để khoá **không bao giờ chạm trình duyệt end-user**: nếu FE hỏi feedback của
bạn chạy trên trình duyệt khách hàng, hãy để BE của bạn nhận feedback từ FE đó rồi mới gọi
endpoint này — đừng để trình duyệt tự gọi thẳng, vì khoá này cũng mở được `/runtime-credentials`
(tức mật khẩu Postgres thật của tenant).

### Request

```http
POST /api/v1/agent/feedback HTTP/1.1
Host: portal.internal
Authorization: Bearer ody_ag_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Content-Type: application/json

{
  "session_id": "sess_abc123",   // cùng session_id bạn dùng khi ghi conversations/conversation_messages
  "rating": 5,                    // bắt buộc, số nguyên 1-5
  "comment": "Trả lời nhanh"       // tuỳ chọn, mặc định "", tối đa 2000 ký tự
}
```

Không có trường `tenant_id` — **cố ý**. Tenant suy từ `api_key`, giống hệt `/runtime-credentials`.
Gửi kèm `tenant_id` trong body bị bỏ qua (schema không có trường đó, thêm vào là lỗi client, không
phải cách chọn tenant).

### Response `204` — không có body

### Mã lỗi — dùng lại đúng bảng ở §2, KHÔNG có `429`

| HTTP | `error.code` | Nghĩa |
|---|---|---|
| `401` | `INVALID_AGENT_KEY` | Thiếu header · sai định dạng · không khớp · đã thu hồi |
| `403` | `TENANT_SUSPENDED` | Workspace đang tạm ngưng |
| `422` | — (lỗi validate chuẩn FastAPI) | `rating` ngoài 1-5, `session_id` rỗng, hoặc thiếu trường bắt buộc |

Không có `429`/`RATE_LIMITED` ở endpoint này — bộ đếm 10 lần/5 phút của `/runtime-credentials` thiết
kế để chặn dò khoá của MỘT pod làm mới TTL thưa; feedback có tần suất theo lượng người dùng thật
của tenant nên không dùng chung ngưỡng đó. Gọi feedback nhiều lần cho nhiều `session_id` khác nhau
trong thời gian ngắn là bình thường, không bị chặn.

---

## 3. Mười hai yêu cầu

### G-1 · Env chỉ còn ba biến (đổi từ hai, 2026-08-10)

Gỡ khỏi cấu hình pod: `TENANT_ID` · `POSTGRES_URI_MOCK` · `POSTGRES_URI_REAL` · khoá S3 ·
`QDRANT_COLLECTION_ROOT`.

Thêm `POSTGRES_HOST`/`POSTGRES_PORT`/`POSTGRES_DATABASE` (§1) — không phải lùi bước: ba biến này
không mang bí mật, chỉ là toạ độ mạng giống nhau cho mọi tenant. Bí mật thật (`postgres_role`/
`postgres_password`) vẫn CHỈ tới từ response, không đặt tay bao giờ.

Giữ nguyên các biến **không liên quan tenant** (`STT_BACKEND`, `SHERPA_*`, khoá LLM…) — hợp đồng này
chỉ nói về credential theo tenant.

### G-2 · Fail-fast, cấm fallback

`/runtime-credentials` hỏng ⇒ **pod dừng**, không phục vụ. Cấm mọi đường lui:
- Không dùng credential cũ còn trong bộ nhớ.
- Không đọc lại từ env.
- Không cache credential ra đĩa để lần sau dùng khi portal chết.

> Fallback âm thầm là đường quay lại cấu hình sai mà không ai thấy: pod chạy tiếp, đọc dữ liệu bằng
> khoá đã thu hồi, và không có gì báo động. Một pod chết ồn ào chẩn đoán được; một pod sống mà sai
> thì không.

**Ngoại lệ duy nhất:** credential đang dùng vẫn được dùng tới `expires_at` khi gọi lại `/runtime-credentials` để *làm mới*
thất bại tạm thời. Đó không phải fallback — đó là dùng thứ chưa hết hạn.

### G-3 · Bỏ `QDRANT_COLLECTION_ROOT` 🔴

Tên collection lấy từ `kb.collection` của `/runtime-credentials`. **Không hàm nào được nhận tên collection làm
tham số** — không từ request, không từ session, không từ tool argument.

Hôm nay `.env:285` đặt `QDRANT_COLLECTION_ROOT=document_v4` cho toàn hệ và tầng RAG lọc theo
`project_id`. Một tenant thì vô hại; **hai tenant thì `kb_search` của B trả về chunk của A**.

Đây là yêu cầu **chặn production đa-tenant**, không phải việc dọn dẹp.

Kiểm tra: `grep -rn "QDRANT_COLLECTION" src/` phải chỉ còn **một** chỗ — nơi gán giá trị từ
`/runtime-credentials` response.

### G-3b · Một collection, hai named vector

Đây là **hiện trạng code**, đã đối chiếu `src/portal/modules/kb/kho_tri_thuc.py`:

| | Giá trị |
|---|---|
| Collection | `kb.collection` của `/runtime-credentials` (hôm nay = `kb_<tenant_id>`) |
| Named vector dense | tên **`dense`** · 1024 chiều · distance **COSINE** |
| Named vector sparse | tên **`bm25`** · `Modifier.IDF` |
| Truy hồi | hai `Prefetch` (`dense` + `bm25`) + `FusionQuery(RRF)` |

> **Tên vector là `bm25`, KHÔNG phải `sparse`.** Sai tên thì Qdrant **không báo lỗi** — nó coi đó là
> một vector khác và trả 0 kết quả. Đây là loại hỏng im lặng đắt nhất trong cả hợp đồng này.

**Thiết kế KB có nói tới collection `_media` thứ hai** (`02b` §5) cho `send_media`. Nó **chưa được
xây**, nên `/runtime-credentials` không hứa cái chưa có. Khi có, response thêm một trường — cộng thêm, không phá
hợp đồng, pod cũ vẫn chạy.

Payload của point hiện tại do `modules/kb` ghi (`ghi_doan`): `file_id` · `chunk_index` · `text`.
Khi RAG service của `02b` lên, payload sẽ giàu hơn (`project_id`, `doc_type`, `section`,
`source_file_url`) và **filter `project_id ∈ {dự_án_active} ∪ {"__ALL__"}` trở thành bắt buộc** —
`"__ALL__"` là sentinel cho tài liệu chung workspace, quên gộp là mất toàn bộ tri thức cấp workspace
mà không có lỗi nào báo. Portal sẽ cập nhật mục này khi payload đổi.

### G-3c · Model embedding phải TRÙNG với portal 🔴

| Vector | Model |
|---|---|
| `dense` | **`intfloat/multilingual-e5-large`** — 1024 chiều, prefix `query:` khi truy vấn (portal dùng `passage:` khi index), cosine |
| `bm25` | **BM25** với `Modifier.IDF` (Qdrant tự tính IDF) |

Nguồn sự thật: `src/portal/modules/kb/nhung.py::TEN_MO_HINH_THAT` và
`kho_tri_thuc.py::SO_CHIEU`.

Đổi model là **vector không so được với vector đã index** — kết quả trả về là rác mà không có lỗi
nào. Nếu cần đổi, đó là quyết định chung hai bên kèm reindex toàn bộ, không phải thay một dòng
config.

Endpoint của embedder **không** theo tenant, nên giữ trong env pod như hôm nay — không đi qua
`/runtime-credentials`.

### G-4 · Redis — *tách ra, sẽ có bổ sung*

Số hiệu giữ chỗ. Xem §5 — **đọc trước khi thiết kế lại phần state**, vì làm sau sẽ đắt hơn.

### G-5 · Bỏ thư mục tenant cứng trong image

`src/noble_agent/tenants/{noble, demo_acme}` phải biến mất. **Một image cho mọi tenant**; cấu hình
đến từ bundle, không từ thư mục được build vào ảnh.

### G-6 · Postgres: đọc thẳng `tenant_data`, KHÔNG còn `agent_api` 🔴 ĐỔI 2026-08-10

**⚠️ BREAKING, khác hẳn mọi bản trước file này:** schema `agent_api` (view) đã **bỏ hoàn toàn**
(migration `0917`). Nếu code của bạn đang query `agent_api.*` — kể cả `agent_api.units`,
`agent_api.projects`, `agent_api.tenant_status`, `agent_api.tenant_keys`,
`agent_api.deployments`, `agent_api.agent_published_config` — TẤT CẢ đều không còn tồn tại,
mọi câu gọi sẽ lỗi `relation "agent_api.x" does not exist`.

| Được | Không được |
|---|---|
| `SELECT` trên `tenant_data.{projects,units,zones,documents,media}` | `control.*` — **mọi bảng, trừ đúng một ngoại lệ dưới đây** |
| `SELECT`/`INSERT`/`UPDATE` trên `tenant_data.{contacts,conversations,conversation_messages,appointments}` (write-back — **đã mở**, không phải "sẽ mở") | |
| `INSERT`/`UPDATE` trên `control.agent_heartbeats` | |

**Bạn PHẢI tự lọc `status='published'`, và tự loại con của dự án cha chưa `published`.** Trước đây
view lo cả ba việc (lọc tenant · lọc published · ẩn cây con); từ `0917` chỉ còn "lọc tenant" là
Postgres cưỡng chế (qua RLS, tự động theo credential — bạn không cần viết `WHERE tenant_id = ...`
tường minh, nhưng đọc raw table nghĩa là bạn thấy CẢ draft/archived nếu không tự lọc `status`).
Với `units`/`documents`/`media`/`zones`, một dự án cha `status != 'published'` KHÔNG còn tự động ẩn
con của nó — nếu logic của bạn cần thuộc tính đó, tự `JOIN tenant_data.projects` và lọc.

Sentinel `__ALL__` (project_code hệ thống cho tài liệu/media chung toàn tenant) **vẫn còn trong
`tenant_data.projects`** — trước đây `agent_api.projects` tự loại nó khỏi danh sách dự án; giờ bạn
phải tự loại nếu liệt kê "dự án" cho khách chọn (`WHERE project_code <> '__ALL__'`), nhưng vẫn phải
GIỮ nó khi lọc `documents`/`media` theo `project_code IN (<dự_án_active>, '__ALL__')` — bỏ sót là mất
tài liệu chung toàn tenant.

**Không đổi:** không còn gate cột (KB mới không có trường thương mại nhạy cảm, cột `commission` ·
`bank_support` · `csbh_full` đã xoá khỏi hệ từ trước `0917` rồi). `control.*` vẫn đóng tuyệt đối —
`0917` còn revoke luôn một PUBLIC-grant cũ trên `control`, nên nếu code nào đó của bạn từng đọc được
`control.tenants`/`control.deployments` "tình cờ", giờ sẽ vỡ `permission denied`.

### G-7 · Nạp bundle nguyên khối

Poll `LIVE` mỗi **20s** · verify **sha256** · nạp **atomic**. Verify hỏng hoặc nạp hỏng ⇒ **giữ
nguyên bản đang chạy**, ghi `last_error`, tiếp tục phục vụ bằng bản cũ.

Chi tiết ở `bundle.md §1–§4`. Không bao giờ phục vụ cấu hình nạp nửa vời.

### G-8 · Heartbeat mỗi 20s

```sql
INSERT INTO control.agent_heartbeats
    (tenant_id, running_version, bundle_sha, agent_version)
VALUES (…)
ON CONFLICT (tenant_id) DO UPDATE
    SET running_version = excluded.running_version,
        bundle_sha      = excluded.bundle_sha,
        last_error      = '',
        last_seen_at    = now()
```

`tenant_id` là thứ DUY NHẤT cần — không tra id nào, không đoán. `control.deployments` đã bỏ
(`0941`).

⚠️ **NHỊP TIM ĐÃ CHẾT SUỐT `0919` → `0941`, và không bên nào phát hiện.** `beat()` chỉ dùng pool
tenant khi `cred.kind == self._kind`; `kind` biến mất khỏi response `/runtime-credentials` ở
`0919` nên `cred.kind` luôn `''`, không bao giờ khớp `'chat'`/`'voice'`, và mọi lượt beat rơi
xuống nhánh `SELECT control.deployments` bằng role `agent_<tenant>` — role chưa bao giờ có SELECT
ở đó. Câu lệnh ném, `beat()` nuốt, trả `False`. Mọi test bên agent đều TIÊM `read_deployment_id`
giả nên đường thật chưa từng chạy.

Hai bài học đã ghim thành test (`tests/unit/tenant/test_pg_heartbeat_writer.py`): đừng tiêm một
lối thoát mà production không có, và một hàm nuốt mọi exception cần một bài canh những bảng nó
ĐƯỢC PHÉP chạm.

⚠️ **HAI POD CỦA CÙNG MỘT TENANT NAY ĐÈ LÊN NHAU** — một hàng mỗi workspace, không phải một hàng
mỗi pod. Portal vốn đã đọc hàng `last_seen_at` mới nhất nên bốn chip trạng thái không đổi; nhưng
nếu bên bạn cần phân biệt pod chat với pod voice thì bảng này KHÔNG còn trả lời được.

Portal suy bốn chip trạng thái từ đúng bảng này (`bundle.md §5`). Gửi thưa hơn **60 giây** ⇒ portal
báo Mất kết nối cho khách hàng nhìn thấy.

### G-9 · `/chat/ws` trả `tools_used`

Kèm mỗi câu trả lời, danh sách kỹ năng agent đã gọi trong lượt đó.

Nợ từ M5 §7. Đây là cách **duy nhất** người dùng thấy được bật/tắt kỹ năng có tác dụng thật — không
có nó thì màn Agent Studio là 12 công tắc không ai kiểm chứng được.

### G-10 · Cấm log runtime-credentials response

Không `logger.*`, không `print`, không APM span, không breadcrumb, không `repr()` trong except.
Response chứa **mật khẩu Postgres** và **secret key S3**.

An toàn để log: `tenant_id` · `deployment_id` · `agent_key_id` · `kb.collection` · `expires_at`.

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
| `postgres_role` đã đúng tên role | Pod **không** cần biết quy tắc `agent_<slug>` — chỉ cần ghép với `POSTGRES_HOST/PORT/DATABASE` tĩnh |
| `kb.collection` đã là tên đầy đủ | Pod **không** cần biết quy tắc `kb_<tenant_id>` |
| `storage.prefix` đã gồm dấu `/` cuối | Nối chuỗi trực tiếp, không xử lý biên |
| `/runtime-credentials` idempotent | Gọi lại nhiều lần vô hại; retry an toàn |
| Xoay bí mật **không** ngắt kết nối đang mở | Postgres chỉ hỏi mật khẩu lúc nối mới. Pod có trọn một chu kỳ TTL để chuyển |
| Hai deployment cùng tenant nhận **cùng** `postgres_role`/`postgres_password` | Pod `chat` và `voice` không đá nhau |
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
| Credential | Cấp qua chính `/runtime-credentials` (thêm khối `redis` vào response — cộng thêm, không phá hợp đồng §2) |

**Đề nghị làm ngay bây giờ, dù chưa chốt:** đưa việc dựng key qua **một hàm** thay vì nối chuỗi rải
rác. Khi G-4 chốt, đổi một hàm rẻ hơn đổi ba mươi chỗ.

Chi tiết: `docs/contracts/isolation.md §11`.

---

## 6. Bốn cách hỏng và dấu hiệu nhận biết

| Triệu chứng | Nguyên nhân thường gặp | Tra ở đâu |
|---|---|---|
| `401 INVALID_AGENT_KEY` | Khoá bị thu hồi · gõ thiếu ký tự · dùng khoá của môi trường khác | Hỏi admin: `control.agent_keys.revoked_at` |
| `409 NOT_PROVISIONED` | Role Postgres hoặc collection Qdrant chưa tạo | `message` nói thiếu cái gì. Admin bấm cấp phát lại |
| Nối được nhưng truy vấn trả **0 hàng** | Chưa dự án nào ở `status = 'published'` | Admin: `GET /admin/deployments` → `san_sang_du_lieu` |
| `kb_search` trả **0 chunk** dù có tài liệu | Chưa embed xong · hoặc **quên `"__ALL__"`** trong filter (G-3b) | Đếm point trong `<slug>_documents` |
| `kb_search` trả chunk **không liên quan** | Model embedding lệch với RAG service (G-3c) | So model đang dùng với `02b` §2 |

**Ba dòng cuối là loại hỏng tệ nhất:** pod chạy đúng, không lỗi nào, và agent tư vấn bằng kết quả
rỗng hoặc sai. Im lặng và trông như đang hoạt động. Nếu agent bỗng "không biết gì", kiểm ba thứ đó
**trước** khi debug phía agent.

---

## 7. Chỗ tra khi lệch

| Câu hỏi | Nguồn |
|---|---|
| `/runtime-credentials` trả những trường nào | `src/portal/modules/enrollment/contracts.py::RuntimeCredentialsOut` |
| Tên role · collection · khoá S3 sinh ra sao | `src/portal/core/ten_tai_nguyen.py` |
| Policy tiền tố kho tệp | `src/portal/core/storage.py::chinh_sach_tien_to` |
| Tên named vector · số chiều · model | `src/portal/modules/kb/kho_tri_thuc.py` · `nhung.py` |
| Vì sao ba lớp cách ly như vậy | [`isolation.md`](isolation.md) |
| Tool nào có filter nào | `contracts/tools.json` |

> `scripts/agent_gia.py` là **spec sống**. Nó không giả lập LLM, không giả lập tool — nó làm đúng
> phần hợp đồng này quan tâm: runtime-credentials → poll LIVE → verify sha → heartbeat. Khi có mâu thuẫn giữa
> file này và `agent_gia.py`, **mã thắng** và file này phải sửa.

---

## 9. Kèm theo file này

File này **không tự đủ**. Nó tham chiếu bốn thứ nằm ở repo `odyssey-portal-backend` mà bạn không có:

| Gửi kèm | Vì sao cần |
|---|---|
| `docs/contracts/bundle.md` | **Bắt buộc.** G-7 · G-8 chỉ nói "theo `bundle.md`". Toàn bộ hợp đồng nhận cấu hình và nhịp tim ở đó |
| `scripts/agent_gia.py` | **Bắt buộc.** Mã mẫu chạy được cho G-1 · G-2 · G-7 · G-8. Ngắn hơn phần văn bản mô tả nó |
| `docs/build_module_knowledgebase/02b-rag-service.md` | Chỉ khi bạn làm phần RAG nâng cao. G-3b nói hiện trạng; file đó nói hướng đi (media collection, `"__ALL__"`, caption) |
| `contracts/tools.json` | G-12 — danh sách tool và filter hợp lệ |
| `docs/contracts/isolation.md` §11 | Chỉ nếu bạn định làm phần Redis ở §5 |

**Không cần gửi:** spec và plan M10 (`docs/superpowers/`) — chúng là việc nội bộ của portal.

## 10. Chạy thử ngay ở dev

Portal đã ship. Ba lệnh là có một pod giả chạy đúng chuỗi hợp đồng này:

```bash
make up            # postgres · redis · minio · migrate · seed
make seed-agent    # cấp phát 1 deployment + IN RA api_key
make api           # (cửa sổ khác) bật portal ở :8100
make agent-gia KEY=ody_ag_...     # pod giả: runtime-credentials → poll LIVE → heartbeat
```

`make agent-gia` nhận **đúng một** tham số. Không TENANT, không DSN, không khoá S3 — đó là bằng
chứng G-1 hoạt động.

Đối chiếu hình dạng response bằng schema thật thay vì đọc bằng mắt:

```bash
uv run python -c "
from portal.modules.enrollment.contracts import RuntimeCredentialsOut
import json; print(json.dumps(RuntimeCredentialsOut.model_json_schema(), indent=2, ensure_ascii=False))"
```

**Có câu hỏi hoặc thấy hợp đồng lệch code: hỏi trước khi code.** Đổi hợp đồng lúc này rẻ; đổi sau khi
hai bên đã code thì không.

---

## 8. Thứ tự đề nghị cho bên agent

Không phụ thuộc portal ship xong — bốn việc đầu làm được ngay:

1. **G-3 · G-3b · G-3c** — bỏ `QDRANT_COLLECTION_ROOT`; named vector `dense` + **`bm25`**; khớp model
   embedding. *Chặn production đa-tenant, và độc lập hoàn toàn với `/runtime-credentials`.*
2. **G-5** — bỏ thư mục tenant cứng.
3. **G-11 · G-12** — serializer bỏ khoá rỗng; gỡ hai filter. *Không phụ thuộc gì cả.*
4. **§5** — gom việc dựng Redis key về một hàm.
5. **G-1 · G-2** — client runtime-credentials. *Cần portal ship endpoint; test được bằng một stub trả JSON §2.*
6. **G-6 · G-7 · G-8** — đường đọc `tenant_data` (không còn `agent_api`), nạp bundle, heartbeat theo credential mới.
7. **G-9** — `tools_used`.

Mục 6–7 cần portal ship trước. Xem §10 để biết cái gì test được ngay.
