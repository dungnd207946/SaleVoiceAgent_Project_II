# Odyssey — Agent Interface Contract

**Tài liệu quy chuẩn liên team (living standard).** Đặc tả **mọi giao diện** mà repo
`odyssey-agent` (lớp **Agent**) phơi ra và tiêu thụ trong quan hệ với **Dashboard** và
**Backend (Portal API)**. Đây là hợp đồng để 3 team phát triển song song mà không phải
họp lại từng tính năng, và là mốc để phía Agent bám vào khi code — chốt trước, không sửa sau.

- **Nguồn nghiệp vụ (source of truth):** Notion **HT_01 — "Quan hệ Dashboard · Backend · Agent"** (v1.4). Tài liệu này là *hiện thực hoá phía Agent* của HT_01; khi hai bên lệch, HT_01 thắng về nghiệp vụ, tài liệu này thắng về định dạng byte trên dây.
- **Phạm vi:** CHỈ lớp Agent (repo `odyssey-agent`). Dashboard và Backend là hệ thống riêng; ở đây chỉ mô tả *mặt tiếp giáp* mà hai lớp đó phải tôn trọng ở phía bên kia.
- **Trạng thái hạng mục:** ✅ đã implement · ◑ có một phần · ○ mục tiêu (chưa build).

| Phiên bản | Ngày | Người viết | Thay đổi |
|---|---|---|---|
| v0.1 | 2026-07-30 | Agent team | Bản đầu. 5 contract (C1–C5) map theo 4 luồng + ngoại lệ HT_01. C1 đã implement (slice #2), C2/C5 partial (slice #1/#2), C3/C4 target. Nêu open: N6/N7/N9. |

---

## 0. Nguyên tắc bất biến (đọc trước mọi thứ khác)

Đây là "xương sống". Vi phạm bất kỳ dòng nào dưới đây là phá kiến trúc, không phải chọn phong cách.

| # | Luật | Hỏng thì mất gì |
|---|---|---|
| **BR01** | Agent **KHÔNG BAO GIỜ** gọi Portal API. Agent chỉ nói với **kho dữ liệu** (Postgres) và **kho tệp** (MinIO/S3), cộng các service tính toán dùng chung (STT/TTS/LLM/embed). | Nếu agent gọi Portal, backend chết là agent chết → mất lời hứa **E01**. |
| **BR02** | Backend **KHÔNG BAO GIỜ** gọi xuống agent. Mọi thứ đi lên đều do **agent chủ động đẩy** (đọc / ghi / gửi nhịp tim). | Backend không biết địa chỉ container (cấp phát là việc ops). Gọi xuống = thêm một phụ thuộc phải quản. |
| **BR03** | Ngoại lệ **duy nhất** cho BR01/BR02: nút **"Thử ngay"** trên Dashboard — và nó phải đi qua **đúng kênh khách hàng cuối dùng** (chính là C1 ingress). | Thử qua đường tắt riêng thì bài thử không chứng minh được gì. |
| **E01** | Backend/Portal chết → agent **vẫn phục vụ khách hàng cuối** bằng gói cấu hình trong đệm đĩa. | Đây là lời hứa bán hàng, không phải khẩu hiệu. |

**Hệ quả cho tài liệu này:** ngoài **C1 (ingress)**, KHÔNG có REST API nào giữa Agent và Backend. Bốn contract còn lại là **hợp đồng trên kho chung + agent chủ động** (agent đọc C2/C4, agent ghi C4/C3). Nếu một team thấy mình đang thiết kế "Backend gọi endpoint trên Agent" — dừng lại, đó là BR02.

### Bản đồ contract ↔ luồng HT_01

```
Dashboard ──(A: config)──▶ Backend ──(ghi kho tệp)──▶  [Kho tệp]  ◀──(đọc)── Agent      = C2
Dashboard ──(B: data)────▶ Backend ──(ghi Postgres)──▶ [Postgres] ◀──(đọc)── Agent      = C4 (đọc)
Agent ──(C: kết quả, ghi thẳng)──▶ [Postgres] ──(Portal đọc)──▶ Dashboard                = C4 (ghi)
Agent ──(D: nhịp tim, đẩy)──▶ [Kho]  ──(Portal đọc + suy ra trạng thái)──▶ Dashboard    = C3
Dashboard ──(E: "Thử ngay", ngoại lệ BR03)──▶ Gateway ──▶ Agent (đúng kênh khách cuối)  = C1
```

| Contract | Luồng | Ai đọc | Ai ghi | Kênh | Trạng thái |
|---|---|---|---|---|---|
| **C1 — Ingress** | E + khách cuối | Agent (nhận) | Provider backend (gửi) | WSS per-tenant qua Gateway | ✅ |
| **C2 — Config bundle + versioning** | A | Agent | Backend (Xuất bản) | Kho tệp (MinIO/S3) | ◑ |
| **C3 — Heartbeat** | D | Backend/Dashboard | Agent (đẩy) | Kho (tệp → Postgres `platform` khi có SP-E) | ◑ (agent write side ✅ SP-D) |
| **C4 — Data plane** | B, C | Agent (VIEW) + Backend | Backend (nhập) + Agent (3 bảng) | Postgres `tenant_data` + Qdrant | ○ |
| **C5 — Provisioning / allocation** | cross-cutting | — | Backend/ops | CLI/library `noble-tenant` + kho | ◑ |

---

## C1 — Ingress Contract (kênh khách hàng cuối + "Thử ngay") ✅

**Đây là giao diện DUY NHẤT đi VÀO agent.** Provider backend (client server-to-server) hoặc
nút "Thử ngay" của Dashboard đều dùng nó. Đã hiện thực trong slice #2 (`gateway/`), phần dưới
là hợp đồng chốt — client khác phải viết đúng theo đây.

### C1.1 Địa chỉ & xác thực

- **Endpoint (per-tenant):** `wss://<tenant_id>.<GATEWAY_BASE_DOMAIN>/v1/voice` (voice) hoặc `/v1/chat` (chat). `<tenant_id>` là subdomain; Gateway suy tenant từ **Host header** (so khớp hậu tố theo **ranh giới dấu chấm** trên base domain — chống host giả `t1.evil.com`).
- **Xác thực:** header `Authorization: Bearer tnt_<token>`. Credential được cấp per-tenant (xem C5), verify **CHỈ** với creds của **đúng tenant suy từ Host** (một cred hợp lệ của tenant A trình trên subdomain của tenant B ⇒ **từ chối**).
- **Nguồn verify:** cache TTL đọc từ kho tệp (`gateway/registry.py`), **KHÔNG BAO GIỜ** gọi Portal API live (E01) — Portal chết vẫn mở được cuộc mới.

### C1.2 Bắt tay (handshake)

- **Frame đầu tiên** sau khi mở WS PHẢI là **1 text frame JSON**:
  ```json
  {"identity": {"full_name": "Nguyễn Văn A", "phone": "09xxxxxxxx"}, "call_id": "abc-123"}
  ```
  - `identity`: object các trường `Customer` (ánh xạ **verbatim**, không mã hoá/thêm tiền tố — vd `identity["phone"] → Customer.phone`). Rỗng ⇒ phiên vô danh.
  - `call_id`: chuỗi định danh cuộc gọi phía provider (dùng đặt tên room, xem C1.3).
- Quá **10 giây** không gửi handshake ⇒ Gateway đóng **4008** `handshake_timeout`.

### C1.3 Voice (`/v1/voice`)

Sau handshake, khung dữ liệu theo `voice/service/protocol.py`:

| Chiều | Loại frame | Nội dung |
|---|---|---|
| Provider → Agent | **binary** | PCM16 mono little-endian **16 kHz** (khung ~20 ms = 640 B khuyến nghị) |
| Provider → Agent | text | JSON control (dành riêng — hiện bỏ qua) |
| Agent → Provider | **binary** | PCM16 mono **24 kHz** (tiếng agent, gồm cả câu chào mở đầu) |
| Agent → Provider | text | JSON event UI — event ĐẦU TIÊN luôn là `{"type":"session_id","session_id":"<tên room>"}`, các event còn lại xem `docs/api/gateway-voice-ws-spec.md` §3 |

Cơ chế cầu nối (Gateway, minh bạch với client): mint token LiveKit → join room tên
`<tenant_id>-<call_id>-<ms>-<hex>` → dispatch agent tên **`agent-<tenant_id>`** (xem C5.3) →
đặt `identity` vào **participant metadata** để worker seed `Customer` → relay audio hai chiều.

`session_id` gửi cho provider **chính là tên room đó** — cũng là `session_id` worker ghi vào
`tenant_data.conversations`. Provider KHÔNG suy được nó từ `call_id` mình gửi (`ms`+`hex` sinh
ở server), nên phải lưu lại nếu cần ghi feedback cuối phiên hay tra hội thoại về sau.

### C1.4 Chat (`/v1/chat`)

Reverse-proxy tới `/chat` của worker; Gateway tự gửi `{"type":"set_customer","identity":{…}}`
trước rồi relay hai chiều. Hợp đồng message:

- **Client → Agent:** `{"type":"user_text","text":"..."}`.
- **Agent → Client:** các message `type` ∈ `{session_id, customer_ok, metrics, token, tool_start, tool_done, done, error, suggestions}` (JSON text frames). `done` mang `ttft_ms`/`tokens`.

### C1.5 Mã đóng WS (chuẩn)

| Code | reason | Khi nào |
|---|---|---|
| **4001** | `bad_host` / `tenant_inactive` / `no_bearer` / `bad_credential` | Xác thực thất bại (Host không ra tenant / tenant không active / thiếu Bearer / cred sai hoặc cross-tenant) |
| **4004** | `unknown_route` | Path không phải `/v1/voice` hoặc `/v1/chat` |
| **4008** | `handshake_timeout` | Không gửi frame handshake trong 10 s |

> ⚠️ **Việc nhỏ đã biết:** client gửi **2 header `Host` trùng** làm Gateway crash `1011` thay vì auth-reject sạch. Không phải lỗ hổng (không cấp quyền), nhưng client phải gửi đúng 1 Host.

### C1.6 Suy biến

- Portal/Backend chết → **không ảnh hưởng** (verify từ cache, **E01**).
- Cred bị thu hồi → cuộc **đang chạy** không bị cắt; cuộc **mới** bị từ chối sau khi cache TTL hết.

---

## C2 — Config Bundle & Versioning Contract (Luồng A) ◑

Backend đóng gói cấu hình thành **bản phát hành bất biến** trong kho tệp; Agent **đọc**, không
bao giờ Backend đẩy xuống (BR02). Slice #1 đã có bundle *in-place*; SP-C **nâng lên có phiên bản**.

### C2.1 Layout kho tệp — HIỆN TẠI (slice #1, in-place, sẽ bị thay)

Prefix `<tenant_id>/` trên bucket `TENANT_BUCKET` (mặc định `hotline-tenants`):

```
<tenant_id>/manifest.toml        # cấu hình (xem C2.3)
<tenant_id>/persona/*            # SOUL.md, RULES.md, PROMPT_TEMPLATE.md, CUSTOMER_PROFILE.md, config.json
<tenant_id>/tools/*              # custom tool (tuỳ chọn)
<tenant_id>/_meta.json           # {tenant_id, status, version:int, bundle_hash, created_at, updated_at}
<tenant_id>/_creds.json          # credential (C5) — KHÔNG thuộc bundle_hash
```

`bundle_hash = "sha256:" + sha256(Σ path+content, sắp theo path)`; loại trừ `_meta.json`/`_creds.json`.
**Hạn chế:** `write_bundle` GHI ĐÈ tại chỗ ⇒ chưa đáp ứng BR06 (bất biến, quay lui).

### C2.2 Layout kho tệp — MỤC TIÊU (SP-C, bất biến + con trỏ) ○

```
<tenant_id>/versions/<n>/manifest.toml     # snapshot BẤT BIẾN của version n
<tenant_id>/versions/<n>/persona/*
<tenant_id>/versions/<n>/tools/*
<tenant_id>/versions/<n>/version.json      # {version:n, bundle_hash, field_policy, created_at, created_by, parent_version}
<tenant_id>/pointer.json                   # {published_version:int, updated_at, updated_by}
<tenant_id>/_meta.json                     # {tenant_id, status, published_version, latest_version}  (chỉ mục cho list)
<tenant_id>/_creds.json                    # C5
```

Luật (map thẳng HT_01):

- **BR06 — bất biến:** `versions/<n>/` không bao giờ ghi đè; `n` tăng dần đơn điệu. **Quay lui = ghi `pointer.json` trỏ về `n` cũ, KHÔNG tạo version mới** (YC06).
- **BR07 — thứ tự Xuất bản:** ghi **snapshot version trước** (gồm cả `field_policy` = cột nào agent được đọc), **ghi `pointer.json` sau**, trong cùng một giao dịch logic. Không được để "prompt v12, gate v11".
- **BR04 — mọi thay đổi qua Xuất bản:** không có đường sửa thẳng bản đang chạy.
- **Cổng kiểm cấu trúc (E08, §II.2.2):** TRƯỚC khi ghi snapshot, chạy `tenant/validation.py` (manifest parse được · `enabled` tool resolve được · persona files đủ · rào chắn không rỗng · custom tool parse AST). **Rẻ, đồng bộ, ~vài trăm ms.** KHÔNG gộp với bộ test hành vi (tốn LLM, hàng phút) — dịch vụ test chết KHÔNG được làm "không ai xuất bản được gì".

### C2.3 Manifest schema (`manifest.toml`)

```toml
tenant_id   = "<slug>"
data_source = "nbx"            # provider dữ liệu (mirror NOBLE_DATA_SOURCE giai đoạn này)
persona_dir = "persona"

[tools]
enabled = ["find_project", "kb_search", "booking", ...]   # danh sách tool được chào
rankers = ["feng_shui"]        # ranker tuỳ chọn (rỗng = tắt overlay)
media_channel = "noblex_app"

[brand]
company  = "Noble"
app_name = "NobleX"
```

### C2.4 Ngữ nghĩa nạp phía Agent (SP-C) ○

- **Bậc độ trễ 3 (§II.2.1):** thay đổi cấu hình có hiệu lực ở **cuộc hội thoại MỚI**.
- **Dò con trỏ ~20 giây** (YC03) ở nền, KHÔNG nằm trên đường hội thoại (độ trễ giọng nói).
- **Ghim theo cuộc (BR05, YC04):** cuộc bắt đầu ở version nào **giữ nguyên** version đó tới khi kết thúc; cấm đổi giữa cuộc (giữ prompt-cache của LLM, tránh giật độ trễ toàn hệ).
- **Kiểm tổng (E04):** sau khi materialize `versions/<n>/`, tính lại hash so với `version.json.bundle_hash`; lệch ⇒ **giữ bản tốt gần nhất**, KHÔNG nạp nửa vời, phát tín hiệu lỗi qua nhịp tim (C3).
- **Đệm đĩa (E01):** giữ bản đã nạp gần nhất trên đĩa; kho tệp/Backend chết ⇒ boot bằng bản đệm.

### C2.5 Suy biến

| Mã | Tình huống | Agent làm gì |
|---|---|---|
| E03 | Đã Xuất bản nhưng agent chưa nạp | Dùng bản cũ; nhịp tim báo `running_version < published` → Dashboard hiện "Đang áp dụng" |
| E04 | Tải gói nhưng kiểm tổng sai | Giữ nguyên bản cũ; nhịp tim mang `last_error` |

---

## C3 — Heartbeat Contract (Luồng D) ◑

Agent **chủ động đẩy** nhịp tim; Backend/Dashboard **suy ra** trạng thái (BR11) — không ai bấm tay.

> **Trạng thái (SP-D, 2026-07-30):** phía **Agent ghi đã hiện thực** trên kho tệp
> (`tenant/heartbeat.py::HeartbeatEmitter`, ghi `<t>/_heartbeat.json` mỗi ~20 s),
> wire vào **CẢ HAI transport**: aiortc `server/http.py` (task loop chính, build_fn
> = full runner) và LiveKit `transport/livekit/worker.py::_start_heartbeat` (daemon
> thread + loop riêng, build_fn = materialize+checksum-only vì process dispatch không
> dựng full runner). N7 **đã chốt** (xem §C3.3). Còn lại là phía Backend/Dashboard
> (suy trạng thái §C3.4 — hệ của họ), và chuyển sang Postgres `platform` (SP-E) là
> follow-up (cùng shape).

### C3.1 Định dạng (shape chốt — vị trí có thể đổi, shape KHÔNG đổi)

```json
{
  "tenant_id": "noble",
  "running_version": 12,          // version cấu hình agent ĐANG phục vụ
  "published_version_seen": 12,   // version cao nhất agent thấy ở pointer.json
  "status_hint": "serving",       // "starting" | "loading" | "serving" | "degraded"
  "last_error": null,             // hoặc {code, message, ts}
  "started_at": "2026-07-30T04:00:00Z",
  "ts": "2026-07-30T04:03:53Z"    // dấu thời gian nhịp tim này
}
```

### C3.2 Vận chuyển

- **SP-D (không phụ thuộc Postgres):** ghi `<tenant_id>/_heartbeat.json` trên **kho tệp** (agent chỉ được nói với kho tệp + kho dữ liệu — BR01). Ghi đè mỗi nhịp.
- **Khi có SP-E:** CÓ THỂ chuyển sang Postgres schema `platform` (telemetry của NobleX, A25) — **cùng shape ⇒ không đổi contract**, chỉ đổi vị trí. Dashboard đọc qua Portal.

### C3.3 Nhịp & ngưỡng (N7 — ĐÃ CHỐT khi build SP-D)

- Agent phát mỗi **~20 giây** (`NOBLE_HEARTBEAT_SEC`, khớp chu kỳ dò cấu hình). Đây
  cũng chính là **poller cấu hình** — mỗi beat đọc thẳng `pointer.json`.
- **Tươi:** `now - ts ≤ 60 s`. **Cũ (Mất kết nối):** `> 60 s`. (60 s = 3 chu kỳ.)
- **"Đang áp dụng" quá lâu:** `> 2 phút` với `running_version < published` ⇒ coi là **lỗi** (E03).
- **Quan trọng:** 60 s / 2 phút là **suy luận phía Backend/Dashboard** (§C3.4). Agent
  CHỈ phát mỗi 20 s + shape trung thực; agent không tự phán "cũ/lỗi". Beat chủ động
  build version đã publish (qua đường cache chung của hội thoại) nên `running_version`
  tự đuổi kịp `published` kể cả khi worker rảnh — điều kiện để suy luận E03 đúng. Kho
  tệp chết lúc đọc ⇒ **bỏ qua beat** (ts cũ dần → "Mất kết nối", trung thực).

### C3.4 Bảng suy trạng thái (Backend/Dashboard, §II.2.5)

| Trạng thái | Điều kiện | Ý nghĩa cho khách/Dashboard |
|---|---|---|
| `Đang cấp` | chưa có nhịp tim nào | container đang lên (E07) |
| `Đang áp dụng` | tươi nhưng `running_version < published` | ≤ 20 s; quá 2 phút → E03 |
| `Sẵn sàng` | tươi + version khớp | mở "Thử ngay" |
| `Mất kết nối` | nhịp tim cũ | E02 — **báo lỗi thật**, không giả vờ đang chạy |

---

## C4 — Data-Plane Contract (Luồng B đọc / C ghi) ○

Mục tiêu SP-E (**N5 chốt A18** — Postgres + RLS). Đây là contract **mặt tiếp giáp phía Agent**;
DDL đầy đủ là deliverable của SP-E. Agent đọc **trong tiến trình, một chặng** tới Postgres (BR01,
lý do độ trễ giọng nói) — KHÔNG qua Portal.

### C4.1 Cách ly (BR08/BR09 — do Postgres cưỡng chế, không do agent tự nhớ lọc)

- Mỗi tenant có **role Postgres riêng + mật khẩu riêng**; container agent chỉ có thông tin đăng nhập của **đúng một tenant** (`TENANT_ID` đóng băng).
- **RLS theo hàng** + `VIEW agent_*` **gate theo cột** (cột nào agent được đọc do `field_policy` của version đang phục vụ quy định — xem C2.2).
- Lời hứa kiểm chứng được: **workspace A không đọc được workspace B** — một lỗi code trong agent không được thành rò rỉ chéo.

### C4.2 Quyền của Agent

| Thao tác | Được phép | Ghi chú |
|---|---|---|
| ĐỌC | CHỈ qua `VIEW agent_*` (dự án · căn · tài liệu meta) | không đọc bảng cấu hình (BR09) |
| GHI | CHỈ 3 bảng: `conversations`, `appointments`, `contacts` | không đụng bảng cấu hình dù bị chiếm quyền (BR09) |

Nội dung 3 bảng agent ghi (map N5/N5b):

- **`conversations`** — bản ghi **làm phẳng** (tự mang tên khách, dự án, đã chuyển sales chưa → màn danh sách **không cần nối bảng**); kèm **log gọi kỹ năng** (tên + tham số + **kết quả**) và **con trỏ version cấu hình**; giữ **6 tháng**; **mang số điện thoại** để xoá được theo NĐ 13. (Vá 3 khiếm khuyết bản ghi thoại hiện tại: thiếu skill-call · không chỉ mục · không xoá theo SĐT.)
- **`appointments`** — lịch agent đặt và lịch người sửa là **cùng một bảng**.
- **`contacts`** — hồ sơ tích luỹ theo SĐT (gộp khái niệm với "user snapshot" cũ).

### C4.3 Qdrant (tri thức)

- **Một collection riêng mỗi tenant** (A13). Contract đặt tên: `<QDRANT_PREFIX>_<tenant_id>` (chốt prefix ở SP-E). Backend ghi lúc tải tài liệu; Agent chỉ đọc.

### C4.4 Suy biến

| Mã | Tình huống | Agent làm gì |
|---|---|---|
| E05 | Postgres chết | **Nói thật** là chưa tra được dữ liệu + mời chuyển người thật; KHÔNG bịa |
| E06 | Qdrant chết | Trả lời câu chung, **không dẫn được tài liệu** |

> ✅ **N9 ĐÃ CHỐT (2026-07-30): Fixed store.** Đóng băng Santa/Mongo ở một nhánh riêng;
> Odyssey (`feat/agent`) migrate **toàn bộ** đường ghi (3 bảng + snapshot) sang Postgres.
> Mỗi nhánh code chỉ biết 1 kho — KHÔNG lớp abstraction ghi chọn-theo-config. Hệ quả cho
> SP-E: viết thẳng Postgres, không cần seam mongo↔postgres ở đường ghi. **Còn chặn kỹ thuật:**
> (1) cần **Postgres thật** (hiện repo chỉ có scaffold config chết — chưa driver/DDL/endpoint);
> (2) chốt **ai sở hữu DDL + cấp role per-tenant** (C5.1 BR12): agent-side `noble-tenant` hay Backend/ops.

---

## C5 — Provisioning / Allocation Contract (BR12) ◑

Tạo/sửa/tắt tenant. Slice #1/#2 đã có phần MinIO + credential; SP-E thêm Postgres role + Qdrant.

### C5.1 Toàn-bộ-hoặc-không (BR12)

Cấp phát một tenant phải tạo tài nguyên ở **cả ba kho hoặc không tạo gì**: (1) bundle + `_meta.json`
trên kho tệp; (2) `_creds.json` (credential); (3) **[SP-E]** role Postgres + hàng `tenant_data` gốc;
(4) **[SP-E]** Qdrant collection. Cấp nửa vời tạo workspace hỏng khó chẩn đoán hơn workspace chưa cấp
⇒ phải rollback-khi-lỗi-một-phần.

### C5.2 Bề mặt hiện có (CLI/library `noble-tenant`) ✅◑

- Bundle: `create` · `update` · `disable` · `list` · `validate` · `import-from-package`.
- Credential: `issue-cred <tenant>` (trả **plaintext một lần**, lưu **chỉ hash salted SHA-256**) · `revoke-cred` · `list-creds`.
- `endpoint_url(tenant)` = `TENANT_ENDPOINT_TEMPLATE.format(tenant_id=…)` → `wss://<tenant>.<base>/…`; Backend trả cho provider lúc provisioning.

### C5.3 Tên dispatch agent — MỘT nguồn sự thật

`tenant/naming.py::agent_dispatch_name(tenant_id) → "agent-<tenant_id>"`. Dùng đồng bộ ở **3 nơi**:
worker LiveKit đăng ký · app-mint token (`server/app_session.py`) · Gateway (`gateway/livekit_bridge.py`).
Có test khoá 3 nơi đồng thuận — **giữ xanh**.

> ⚠️ **OPS PREREQ:** dispatch rule / SIP trunk / config deploy nào còn đặt tên cũ `noble-hotline-agent`
> phải chuyển sang `agent-<tenant>`, và worker deploy phải đăng ký tên mới — nếu không **cả** voice NobleX-app
> lẫn voice Gateway đều không có agent join room. Trên **LiveKit Cloud dùng chung**, đừng để hai worker
> đăng ký trùng tên (cướp cuộc gọi).

### C5.4 Credential (chi tiết)

- Định dạng: `tnt_` + `token_urlsafe(32)`. So khớp bằng `hmac.compare_digest` trên hash salted SHA-256.
- Plaintext **không bao giờ** lưu; trả về **đúng một lần** lúc issue. `_creds.json` không thuộc `bundle_hash`.

---

## 6. Ma trận suy biến (tổng hợp, phần liên quan Agent)

Nguyên tắc xuyên suốt HT_01: **hệ thống được phép hỏng, KHÔNG được phép nói dối.**

| Mã | Tình huống | Khách hàng cuối | Contract liên quan |
|---|---|---|---|
| **E01** | Backend/Portal chết, agent sống | **Không ảnh hưởng** — agent chạy bằng gói đệm đĩa | C1 (verify cache), C2 (đệm) |
| **E02** | Agent chết, backend sống | Cuộc gọi tới workspace **thất bại** | C3 (nhịp tim cũ → "Mất kết nối") |
| **E03** | Xuất bản xong, agent chưa nạp | Đang dùng bản **cũ** | C2.5, C3 |
| **E04** | Tải gói về nhưng kiểm tổng sai | Đang dùng bản **cũ** (không nạp nửa vời) | C2.4 |
| **E05** | Postgres chết, agent sống | Không tra được dữ liệu — nói thật + mời người thật | C4.4 |
| **E06** | Qdrant chết | Trả lời chung, không dẫn tài liệu | C4.4 |
| **E07** | Cấp container chậm/lỗi | "Đang cấp" — khách vẫn đi tiếp | C3, C5 |
| **E08** | Nhập liệu/cấu hình sai định dạng | Báo lỗi **theo dòng** trước khi ghi, không ghi một phần | C2.2 (cổng kiểm), C5.1 |

---

## 7. Quyết định còn mở (không tự chốt trong tài liệu này)

| # | Câu hỏi | Đề xuất / trạng thái | Ai quyết | Chặn gì |
|---|---|---|---|---|
| **N6** | Đường `/api/v1/sales/*` hiện tại (không có phạm vi tenant) xử lý sao | Nếu giữ tạm cho Noble thì **phải có ngày tắt** | Sản phẩm + BA | Không chặn C1–C3 |
| **N7** | Ngưỡng nhịp tim "cũ" | ✅ **CHỐT: 60 s / 2 phút** (gấp 3 và 6 chu kỳ 20 s); cadence `NOBLE_HEARTBEAT_SEC=20`. Chốt khi build SP-D 2026-07-30. | Kỹ thuật | — (đã gỡ chặn C3) |
| **N9** | Đường **ghi** của agent chọn kho theo config hay đóng băng Santa nhánh riêng | ✅ **CHỐT: Fixed store** (2026-07-30) — đóng băng Santa/Mongo ở nhánh riêng; Odyssey (`feat/agent`) migrate TOÀN BỘ đường ghi sang Postgres, code mỗi nhánh chỉ biết 1 kho (KHÔNG lớp abstraction ghi chọn-theo-config). | Sản phẩm + kiến trúc | — (đã gỡ chặn SP-E; còn chặn kỹ thuật: cần Postgres thật + chốt chủ DDL) |

---

## 8. Thứ tự hiện thực (tham chiếu — mỗi slice có spec/plan/TDD riêng)

1. **SP-C** — C2 (config versioning + nạp-ghim-theo-cuộc). Không cần hạ tầng mới; nối thẳng slice #1.
2. **SP-D** — C3 (heartbeat + suy trạng thái). Nhỏ; khép kín luồng config cùng SP-C (YC05).
3. **SP-E** — C4 (Postgres + RLS + Qdrant riêng). Lớn nhất; **chốt N9 trước**; cần Postgres thật.

C1 (ingress) và C5 (phần MinIO+cred) đã có từ slice #1/#2 và được tài liệu này chốt làm chuẩn.
