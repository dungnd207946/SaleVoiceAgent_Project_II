# Tenant Portal — Control Plane Core (thiết kế sub-project #1)

> **Ngày:** 2026-07-28 · **Trạng thái:** đã duyệt thiết kế, chưa viết plan
> **Repo:** `odyssey-dashboard-prototype` (greenfield)
> **Đầu vào:** prototype `Tenant Portal.dc.html` (Claude Design, project `Noble CSKH tenant portal`) ·
> `reference/santa-hotline-agent` (agent) · `reference/santa-agent-cms` (CMS đơn-tenant hiện tại)

---

## 1. Bối cảnh & mục tiêu

Noble đã có một agent CSKH chạy production (`santa-hotline-agent`, persona **Luna**) và một CMS
đơn-tenant (`santa-agent-cms`) làm tool nội bộ. Mục tiêu: dựng **sản phẩm SaaS** — bán agent chăm
sóc khách hàng theo lĩnh vực (bất động sản, tài chính, …) cho nhiều khách hàng doanh nghiệp.

Agent **đã đi được 3/4 đường tới đa-tenant** (SaaS refactor Pha 1→3 trên branch `feat/refactor2`,
chưa merge): tenant bundle chọn bằng `TENANT_ID`, provider abstraction có extras bag + custom
filter param, tool registry theo `(tenant, name)`, brand đã trung tính. Xem
`reference/santa-hotline-agent/docs/superpowers/HANDOFF-saas-refactor.md`.

**Cái còn thiếu là control plane** — nơi tenant tự cấu hình agent, nhập dữ liệu, xem vận hành.
Prototype vẽ 18 màn cho phần đó. Sub-project #1 xây **phần nền**: tenant registry, config store có
version, publish pipeline, và hợp đồng dữ liệu giữa portal và agent.

**Cảnh báo phạm vi:** toàn bộ prototype là ≥5 hệ thống độc lập. Tài liệu này **chỉ** đặc tả #1.

---

## 2. Quyết định đã chốt

| # | Quyết định | Bị loại |
|---|---|---|
| 1 | **Control plane + N data plane.** Portal đa-tenant; mỗi tenant một pod agent với `TENANT_ID` cố định. Workspace switcher = phạm vi RBAC, **không** phải runtime đa-tenant. | Runtime đa-tenant thật · hybrid pooled+dedicated |
| 2 | **Vertical = template do dev ship + tenant khai thêm field.** Tenant thêm field riêng vào entity có sẵn, đánh dấu field nào agent đọc/lọc được (dùng `ExtraFieldSpec`/`ToolParamSpec` đã có). **Không** cho tự tạo entity mới. | Metadata engine tự khai entity · chỉ-BĐS |
| 3 | **Config seam = bundle bất biến + con trỏ.** Publish render bundle (giữ đúng định dạng file agent đang đọc), agent pull theo con trỏ, cache đĩa. Rollback = đổi con trỏ. | Agent gọi Config API · git + CI/CD |
| 4 | **Portal là system of record duy nhất.** Một đường đọc cho agent. | CMS + adapter · chỉ BYOD |
| 5 | **Provisioning bằng CI job, portal TỰ KÍCH HOẠT ngay khi tạo workspace** (sửa 2026-07-28 — xem §6.5). Không phải ops bấm tay sau khi khách xong onboarding: việc cấp pod chạy song song với lúc khách nạp dữ liệu + sửa persona. | K8s operator · pool pod cấp trước (**pool là ảo** — §6.5) |
| 6 | **Agent đọc trực tiếp Postgres qua VIEW.** In-process, 1 hop — bảo vệ TTFA của voice. | Data API HTTP · mirror riêng cho agent |
| 7 | **Greenfield.** Không fork `santa-agent-cms`; tái dùng chọn lọc ở mức service. | Đa-tenant-hoá CMS hiện tại |
| 8 | **Nhập liệu ở #1 = tay + file.** Adapter API + schedule + nút Sync để sau. | Importer NBX định kỳ trong #1 |
| 9 | **`version` = int tăng dần**, hiển thị `vN`. | `v3.2/v3.3` như prototype |
| 10 | **Platform admin (NobleX) KHÔNG đọc được `tenant_data`.** | Admin thấy tất cả "cho tiện" |
| 11 | **Session pin config version.** Phiên đang chạy giữ version nó khởi tạo. Không có cờ `force_immediate`. | Swap ngay giữa phiên |
| 12 | **`workspace` = `tenant`, quan hệ 1:1** (chốt 2026-07-28 — xem §2.2). Một khách trả tiền = một workspace = một agent. Trong UI dùng **một từ `workspace`**; `tenant` chỉ còn trong tài liệu kỹ thuật. | `tenant` 1:N `workspace` |
| 13 | **Knowledge cách ly theo tenant: mỗi tenant một collection riêng** (chốt 2026-07-29 — xem §5.6). Cách ly **do cấu trúc**, không do câu lệnh lọc. Xoá tenant = drop collection. | Collection dùng chung + filter `tenant_id` |
| 14 | **Persona = template của platform + biến của tenant** (chốt 2026-07-29 — xem §5.7). Tenant không thấy file prompt; portal render `SOUL.md`/`RULES.md` lúc publish. | Tenant sửa thẳng markdown |
| 15 | **Media lấy theo danh mục thuần** (chốt 2026-07-29). Agent truyền `project_code` + `category`; trả ảnh trong đúng danh mục theo thứ tự tenant sắp. **Bỏ tìm ngữ nghĩa khỏi MVP**, bỏ tham số `query` khỏi `send_media`. | Dịch vụ hybrid E5 + SigLIP2 trên `media_v2` (bỏ được cả dịch vụ lẫn GPU embedding ảnh) |
| 16 | **MVP nhận video tự upload**, không chỉ link (chốt 2026-07-29). | Chỉ nhận link YouTube |
| 17 | **Gỡ `floor` và `tower` khỏi schema `search_units`** (chốt 2026-07-29) — `nbx_mongo` không có hai trường đó và bỏ qua filter âm thầm. | Bổ sung dữ liệu tầng/toà |
| 18 | **Dữ liệu vận hành của tenant về Postgres + RLS** (chốt 2026-07-29 — xem §5.8, §7.4). Ranh giới là **dữ liệu của ai**, không phải công nghệ nào: cái gì thuộc tenant thì nằm sau **một** cơ chế cách ly duy nhất. `session_metrics` **không vào `tenant_data`** vì nó là telemetry của NobleX, không phải dữ liệu tenant — nó đi schema `platform` (quyết định #20). | Giữ Mongo với collection riêng mỗi tenant (cách ly **thật**, không bị loại vì kém — bị loại vì thành hai kho cho cùng một loại dữ liệu) · agent đẩy qua Portal API |
| 19 | **CÓ lưu bản ghi thoại, giữ 6 tháng** (chốt 2026-07-29 — xem §5.2.1). Nội dung ở kho tệp, `conversations.transcript_uri` giữ con trỏ. **Lưu bản ghi lượt + con trỏ `config_version`, KHÔNG lưu system prompt đã render.** ⚠️ Đây là **chữ, không phải tiếng** — xem cảnh báo §5.2.1 | Không lưu (mất khả năng đối chất + không kiểm được rào chắn + không có gì để xoá theo NĐ 13) · lưu cả ChatML training format (nhân đôi persona mỗi cuộc gọi cho zero thông tin) |
| 20 | **Odyssey KHÔNG dùng Mongo** (chốt 2026-07-29 — xem §7.1.1). Sau #18 + #19 nó chỉ còn giữ `session_metrics`; đưa nốt vào schema `platform` trong Postgres, **không RLS**. ⚠️ Đây là *"Odyssey không dùng"*, **không phải** *"gỡ code Mongo khỏi agent"* — xem §7.1.2. **Quyết định này có điều kiện đảo ngược, ghi ở §7.4.2** | Giữ Mongo cho một bảng đo độ trễ (một CSDL phải vận hành · sao lưu · giám sát, đổi lấy gần như không gì) · đẩy telemetry qua OTEL (Phoenix đã nối sẵn nhưng **không** bắt STT/TTS/VAD — đúng phần độ trễ đau nhất — nên phải tự phát span, thêm việc mà chưa ai cần) · **kiến trúc lai** Postgres lõi + kho document cho audit/event/custom field — **hợp lệ về nguyên tắc**, loại vì cả ba loại đó trong Odyssey đã có chỗ tốt hơn và custom field buộc phải ở Postgres để giữ cổng VIEW (§7.4.2) |
| 21 | **Tech stack đã chốt** (chốt 2026-07-29 — xem §10). Cơ sở: **gần đúng stack CMS đang chạy production**, đổi đúng hai thứ (kho theo #18 · Tailwind 3→4). Ba điểm khác thói quen hiện tại của đội, đều có lý do cưỡng chế được: **`asyncpg` thô không ORM** + **migration SQL thuần** (bốn điều kiện §5.8 nằm ở tầng kết nối và DDL — ORM che chúng đi, §10.4) · **`PyJWT` + `bcrypt` thay `passlib`/`python-jose`** (§10.5) · **job qua bảng `jobs` + `SKIP LOCKED`**, không `BackgroundTasks` | **ORM** (che DDL, không giúp gì ở tầng cách ly) · **Celery/RabbitMQ** (2–4 loại job, Postgres đã ở đó — cùng lập luận #20) · **Next.js** (giá trị của nó là server; hệ đã có server Python không đổi được, và Server Component đọc DB trực tiếp = **hai bản cài đặt cho một lời hứa cách ly**, §10.6) · **K8s operator** (trái #5) · **kho metrics riêng** (chưa có người trực) |
| 22 | **Kho tệp = MinIO tự dựng** (chốt 2026-07-29 — xem §7.4.3, đóng N10). Nhánh `tenants/` (bundle + bản ghi hội thoại) đặt **trong nước**; bucket ảnh dự án giữ nguyên chỗ hiện tại. Lý do chính **không phải chi phí mà là pháp lý**: #19 đưa nội dung hội thoại vào kho tệp, đặt ngoài Việt Nam là chuyển dữ liệu cá nhân ra nước ngoài (NĐ 13 Điều 25) — tự dựng **làm câu hỏi đó biến mất** thay vì phải trả lời. Cách ly bằng **policy theo tiền tố `tenants/<id>/*` cho từng access key**, cổng test 7 kiểm đúng cơ chế này. ⚠️ Hệ quả nhận: **sao lưu/phục hồi là việc của NobleX** — kho tệp mang cả retention 6 tháng (#19) lẫn khả năng agent boot khi Postgres chết (E01), mất nó là vỡ hai lời hứa cùng lúc | S3/mây (rẻ hơn vận hành, đổi lấy nghĩa vụ hồ sơ pháp lý cho thứ nhạy cảm nhất trong hệ + phí ra mạng cho luồng đọc 20 giây/lần) · dùng chung bucket ảnh hiện có (trộn dữ liệu cá nhân với ảnh công khai vào một ranh giới cách ly — trái BR15) |

### 2.2 `workspace` và `tenant` là cùng một thứ — và vì sao phải ghi ra

Prototype tự chọi trong đúng một câu ở màn Users: *"Chỉ áp dụng trong **workspace** này — NobleX
không truy cập được dữ liệu **tenant**"*. Attribute trong CSS thì tên là `data-ten` (tenant), còn
switcher lại ghi *"Workspace của bạn"*. Không ghi rõ thì mỗi người dev sẽ tự chọn một nghĩa.

**Chốt: cùng một thực thể.** `control.tenants.id` là khoá duy nhất, và nó đồng thời là:

| Vai | Chỗ dùng |
|---|---|
| Khoá cách ly hàng | `RLS` trên mọi bảng `tenant_data` |
| Danh tính runtime | biến `TENANT_ID` của container agent |
| Đường dẫn cấu hình | `tenants/<id>/LIVE` + `tenants/<id>/bundles/<sha>/` |
| Phạm vi knowledge | tên collection Qdrant của tenant (§5.6) |

Bốn thứ này dùng **chung một khoá**. Đổi mô hình sang 1:N về sau nghĩa là đổi cả bốn cùng lúc —
đắt nhất trong toàn bộ thiết kế. Nên nếu muốn đổi thì phải đổi **trước** khi lát 1a chạy.

**Workspace switcher** vì vậy chỉ có nghĩa với người là thành viên của **nhiều khách hàng**: nhân
viên triển khai của NobleX, hoặc agency vận hành hộ nhiều sàn. Tenant Admin bình thường thấy đúng
một workspace — với họ switcher nên ẩn. Prototype hiển thị 3 workspace là để **minh hoạ** cơ chế,
không phải mô tả trường hợp phổ biến.

**Ràng buộc kèm theo — đừng gắn hoá đơn vào `tenants`.** Đây là chỗ hedge duy nhất còn rẻ. Gói cước
vốn ngoài MVP nên đường nối đang mở sẵn: nếu về sau một tập đoàn cần 3 workspace, ta thêm bảng
`accounts` **phía trên** `tenants` (một `account` sở hữu N `tenant`) — thay đổi **thêm vào**, không
phải đánh lại khoá RLS. Ngược lại, gắn `plan` + chu kỳ thanh toán vào `tenants` bây giờ thì lúc tách
phải sửa đúng cái khoá cách ly. Vì vậy cột `plan` đã được **gỡ khỏi `tenants`** (§5.1).

**Hệ quả chưa giải quyết:** quyết định #5 (provisioning manual/ops) + 1:1 nghĩa là *"Tạo workspace
mới"* **không phải nút self-service** — bấm vào là sinh một khách hàng trả tiền mới, cần ops cấp pod.
Điều đó chọi với tài liệu sản phẩm §18/§20, nơi bước 3 của onboarding (*chat thử ngay*) được coi là
bước "aha" không được đẩy xuống sau. Chat thử cần pod. Hai chỗ này phải hoà giải trước khi làm gói H.

### 2.1 Tại sao greenfield (§7 chi tiết)

`santa-agent-cms` đơn-tenant tới tận schema: `customers` key `phone` **unique toàn cục**; CMS
**không sở hữu schema của chính nó** (doc của nó: *"đọc/ghi thẳng vào collection mà 2 agent tạo và
duy trì"*, *"hầu hết collection do agent làm chủ (ghi), CMS chỉ đọc"*); Mongo sai store cho dữ liệu
control plane (config version, RBAC, quota, invoice, audit đều là quan hệ); nợ đã thành văn
(`BaseRepo` nuốt lỗi Mongo → bảng UI rỗng im lặng, `StatsPage` N+1, ADR 0004 bị thực tế phản lại);
và ranh giới tin cậy **ngược nhau** (CMS = tool nội bộ admin thấy tất cả; portal hứa *"NobleX không
truy cập được dữ liệu tenant"*). Chi phí retrofit ≈ chi phí viết mới, kèm nợ và kèm store sai.

---

## 3. Phân rã sub-project

```
1. Control plane core  ← TÀI LIỆU NÀY
   tenant/workspace · config store · publish–version–rollback · binding data plane
   tenant data store + hợp đồng đọc · auth + tenant scope · nhập liệu tay/file
2. Agent Studio        persona editor · tool toggles · guardrails · diff · kênh
3. Vertical data plane BĐS đầy đủ (Project/Unit + extras UI) → Tài chính là vertical #2
4. Ops surfaces        Hội thoại · Lịch hẹn · Chất lượng (eval service) · Cần bổ sung · Tài liệu
5. Platform            RBAC đầy đủ · API key · webhook · audit · metering/billing
```

`santa-agent-cms` đã có bản chạy được của phần lớn #4 và một phần #5 → rủi ro của hai cái đó thấp.

#1 chỉ làm **form thô** cho persona + entity `units`, đủ để chứng minh vòng publish end-to-end.
Giao diện đẹp là việc của #2/#3. #1 cũng ship **một** vertical template (`realestate`) để seed draft
khi tạo tenant; `finance` chỉ có schema rỗng (§5.2).

**#1 vẫn lớn — implementation plan nên chia lát theo thứ tự phụ thuộc:**

```
1a  Postgres schema + RLS + VIEW + role/kết nối (§5.8) + 7 cổng test  ← làm trước, gate isolation
1b  Config store + publish/rollback + bundle render
1c  Agent: loader từ storage + bundle poller + heartbeat
1d  Agent: facade multi-version AgentDef (§7.1 #3 — lát rủi ro nhất)
1e  Provider portal (asyncpg) + golden test đối chiếu nbx
1f  Auth + tenant scope + nhập liệu tay/file
1g  Provisioning flow + trạng thái suy ra từ heartbeat
```

---

## 4. Kiến trúc

```
┌───────────────── CONTROL PLANE (greenfield, đa-tenant) ─────────────────┐
│                                                                         │
│  Portal Web ──> Portal API ──> Postgres                                 │
│  (React/Vite)   (FastAPI)       ├── schema control                      │
│                                 │     tenants · tenant_verticals        │
│                                 │     users · memberships               │
│                                 │     config_drafts · config_versions   │
│                                 │     field_policy_live                 │
│                                 │     deployments · agent_heartbeats    │
│                                 │     jobs                              │
│                                 │                                       │
│                                 └── schema tenant_data   ← RLS bật      │
│                                       projects · units                  │
│                                       loan_products · rate_schedules    │
│                                       insurance_plans                   │
│                                       appointments · contacts           │
│                                       VIEW agent_*   ← HỢP ĐỒNG ĐỌC     │
│                    │                                                    │
│                    │ publish → render bundle bất biến                   │
│                    ▼                                                    │
│              Object storage (S3/MinIO)                                  │
│                tenants/<id>/bundles/<sha256>/…    (content-addressed)   │
│                tenants/<id>/LIVE                  (con trỏ, JSON)       │
└────────────────────────────┬───────────────────────────────────────────┘
     ① pull bundle           │      ③ SELECT trên VIEW (in-process, 1 hop)
     ② poll con trỏ LIVE     │      ④ INSERT appointments / contacts
                             │      ⑤ UPSERT agent_heartbeats
     ┌───────────────────────┼───────────────────────┐
     ▼                       ▼                       ▼
TENANT_ID=noble        TENANT_ID=anphu        TENANT_ID=sunrise
 noble_agent pod        noble_agent pod        noble_agent pod
 role agent_noble       role agent_anphu       role agent_sunrise
```

**Agent chỉ nói với Postgres + object storage. Không bao giờ gọi Portal API.** Đó là điều làm
"control plane chết, agent vẫn boot" thành thật (có cache bundle).

### 4.1 Năm seam

**① + ② Bundle & con trỏ.** Agent đọc `tenants/<id>/LIVE` → pull bundle theo checksum → verify →
cache đĩa → `tomllib` parse **y nguyên như hiện tại**.

**Poll, không push** — vì provisioning là manual/ops nên portal **không biết địa chỉ pod**. Chu kỳ
20s. Publish → live trong ≤20s. Portal biết đã áp dụng vì agent ghi `agent_heartbeats.running_version`.

**③ Đọc — hai cơ chế, hai việc:**

| Cơ chế | Bảo vệ |
|---|---|
| **RLS** + role `agent_<tenant>` | **Hàng.** Postgres cưỡng chế, không phụ thuộc agent có nhớ filter |
| **VIEW `agent_*`** | **Cột** (gate `GATED`) + **ổn định schema** (portal refactor table tự do miễn giữ view) |

**④ Ghi.** Agent chỉ ghi 2 thứ: `booking` → `appointments`, `update_customer` → `contacts`. Role
write hẹp đúng 2 bảng, không đụng bảng CMS.

**⑤ Heartbeat.** Bảng hẹp riêng, không phải `deployments`.

---

## 5. Data model

### 5.1 Schema `control`

| Bảng | Cột chính | Ghi chú |
|---|---|---|
| `tenants` | `id` (slug, PK — **chính là `TENANT_ID`**), `name`, `status`, `live_version`, `created_at` | `status`: `provisioning · ready · suspended · closed`. **Không có cột `plan`** — xem §2.2: hoá đơn phải nằm ở bảng `accounts` tách riêng, thêm sau, để không đánh lại khoá cách ly |
| `tenant_verticals` | `tenant_id`, `vertical` (`realestate·finance`), `enabled_at` | Bật lĩnh vực = 1 hàng |
| `users` | `id`, `email`, `password_hash`, `name`, `is_platform_admin`, `totp_secret` | |
| `memberships` | `user_id`, `tenant_id`, `role` | Workspace switcher = query bảng này |
| `config_drafts` | `tenant_id` (PK), `payload jsonb`, `updated_at`, `updated_by` | **Một draft/tenant** — prototype chỉ vẽ một bản nháp |
| `config_versions` | `tenant_id`, `version` (int), `payload jsonb`, `bundle_sha`, `note`, `published_at`, `published_by` | `UNIQUE(tenant_id, version)`, **immutable** sau khi ghi |
| `field_policy_live` | `tenant_id`, `entity`, `field`, `is_core`, `agent_readable`, `filterable`, `match_op`, `label_vi`, `type`, `enum_values` | **Bản hiệu lực** — VIEW đọc bảng này để cưỡng chế gate |
| `deployments` | `id`, `tenant_id`, `kind` (`chat·voice`), `endpoint`, `provisioned_at` | Ops ghi khi cấp pod xong |
| `agent_heartbeats` | `tenant_id`, `deployment_id`, `running_version`, `bundle_sha`, `agent_version`, `last_error`, `last_seen_at` | **Agent ghi**, portal đọc |
| `jobs` | `id`, `tenant_id`, `kind`, `state`, `actor`, `started_at`, `finished_at`, `count`, `message`, `force` | Khuôn `sync_job_service`. `kind` ở #1: `publish · import`. (`rag_build`/`media_build` thêm ở #4 — enum mở rộng được, không cần migration cấu trúc.) |

**`is_platform_admin`** cho quyền **control plane** (tạo tenant, cấp pod, xem job) và **không** cho
đọc `tenant_data`. Hỗ trợ khách cần grant tạm thời, có hạn, ghi audit — thuộc #5. Nếu bây giờ nới
"cho tiện" thì lời hứa *"NobleX không truy cập được dữ liệu tenant"* thành sai và sửa sau rất đau.

### 5.2 Schema `tenant_data` — RLS bật trên mọi bảng

```
projects        tenant_id · code · name · slug · type · region · location · investor
                status · is_hot · sort_hot · overview jsonb · lat · lng · extras jsonb
units           tenant_id · code · project_code · unit_type · status · direction
                price_vnd · price_tts_vnd · area_m2 · area_build_m2 · bedrooms · floor
                fund_type · commission · bank_support · csbh_full · csbh_brief
                gift · legal · extras jsonb
loan_products   tenant_id · code · name · rate_pct · term_months · conditions · extras jsonb
rate_schedules  tenant_id · product_code · effective_from · effective_to · rate_pct
insurance_plans tenant_id · code · name · premium · benefits · exclusions · extras jsonb
─────────────── agent ghi ───────────────
appointments    tenant_id · project_code · customer_name · phone · slot_at · status
                channel · session_id · assignee_id
contacts        tenant_id · phone · name · project_interest · purpose · updated_at
                snapshot_text          ← hồ sơ tích luỹ (gộp từ user_snapshots)
conversations   tenant_id · session_id (unique) · phone · customer_name · channel
                started_at · ended_at · duration_sec · project_code · outcome
                summary · key_facts jsonb · open_actions jsonb · events jsonb
                transferred_to_sales · followed_up_by · followed_up_at · follow_up_notes
                transcript_uri         ← con trỏ kho tệp, NULL nếu không lưu thoại
```

**`conversations` gộp ba thứ, không phải ba bảng** (quyết định #18):

| Nguồn cũ (Mongo) | Về đâu | Vì sao |
|---|---|---|
| `hotline_call_summaries` | thân bảng `conversations` | Là bản ghi vận hành — thứ tenant lọc, sắp xếp, xuất báo cáo |
| `hotline_call_events` | cột `events jsonb` | ≤1 KB, TTL 30 ngày, chỉ dùng để gỡ lỗi. Không đáng một bảng |
| `hotline_user_snapshots` | cột `contacts.snapshot_text` | **Trùng khái niệm với `contacts`** — cùng là thông tin tích luỹ về một người theo số điện thoại. Để hai chỗ là tự tạo câu hỏi "cái nào đúng" |
| `session_metrics` | **ở lại Mongo** | Độ trễ · TTFA · thời gian gọi tool = telemetry của NobleX, **không phải dữ liệu tenant**. Không có lý do đưa vào `tenant_data` |

**`transcript_uri` là con trỏ, không phải nội dung.** Bản ghi thoại là khối chỉ-ghi-thêm ~30 KB, ghi
một lần đọc hiếm — để trong hàng của một bảng truy vấn thường xuyên là làm phình bảng đó vô ích. Nội
dung nằm ở kho tệp (cùng nơi chứa bundle), hàng `conversations` chỉ giữ đường dẫn. Xoá theo số điện
thoại vẫn nguyên tử ở phía Postgres; tệp dọn theo sau bằng job.

### 5.2.1 Bản ghi thoại — CÓ lưu, giữ 6 tháng (quyết định #19)

> **⚠️ Đính chính 2026-07-29 (sau khi rà lại code).** Bản trước của mục này ghi *"nội dung hội
> thoại chỉ sống ở Redis TTL 24 giờ + một tệp `.txt` trên đĩa pod"* — **sai**. Có một collection
> Mongo **`agent_messages`** đang lưu bản ghi thoại theo từng lượt (`storage/agent_messages.py`,
> ghi fire-and-forget mỗi lượt ở `orchestrator.py:268`, CMS đọc để hiện màn chi tiết). Quyết định
> #19 **không đổi**, nhưng phần việc **nhỏ hơn** đã nói — có sẵn điểm xuất phát — và ba khiếm
> khuyết dưới đây là thật, phải xử lý chứ không phải viết mới từ đầu.

`agent_messages` lưu `{session_id, role: caller|agent, content, created_at}`. Ba khiếm khuyết:

| # | Khiếm khuyết | Hệ quả |
|---|---|---|
| 1 | **Bỏ hẳn `tool` và `system`** (`_ROLE_MAP` chỉ ánh xạ `user`/`assistant`) | Không trả lời được *"vì sao agent nói thế"* — **đúng lý do chính đã quyết lưu**. Bản ghi hiện tại đối chất được lời nói, không đối chất được hành vi |
| 2 | **Không có index nào** — `connection.py` không tạo index cho collection này | `get_session_messages` **quét toàn bộ collection** mỗi lần mở màn chi tiết. Càng nhiều cuộc gọi càng chậm, không có điểm dừng |
| 3 | **Không TTL, và doc không mang `phone`** | Lớn vô hạn; và **xoá theo số điện thoại (NĐ 13) chưa làm được** — phải tra `session_id` qua bảng khác trước |

Vậy #19 = **chuyển + vá**, không phải xây mới: đưa nội dung sang kho tệp (đường dẫn theo tenant),
bổ sung tool call + kết quả, gắn hạn 6 tháng, và xoá được theo số điện thoại qua
`conversations.transcript_uri`.

> ### ⚠️ Đây là CHỮ, không phải TIẾNG — và P6 dễ làm người đọc tưởng ngược lại
>
> P6 ghi retention áp cho *"ghi âm · transcript · hồ sơ khách tích luỹ"*. Nhưng **hệ thống hiện
> không ghi âm ở bất kỳ đâu**: đường web/LiveKit stream audio rồi bỏ; `telephony_recordings_dir`
> trong config **không có code nào trong `src/` đọc hay ghi**. Quyết định #19 cho ra **văn bản**.
>
> Muốn tenant **nghe lại** cuộc gọi thì đó là quyết định riêng, đắt hơn một bậc lớn: ~1 MB mỗi
> phút so với ~30 KB mỗi cuộc, cộng phơi nhiễm pháp lý khác (giọng nói là dữ liệu sinh trắc). Chưa
> ai yêu cầu — ghi ra để không ai tưởng #19 đã bao gồm.

**Lưu gì trong một bản ghi:**

| Lưu | Không lưu | Vì sao |
|---|---|---|
| Lượt khách nói · lượt agent trả lời | | Nội dung chính |
| **Tên kỹ năng được gọi + tham số + kết quả trả về** | | Đây mới là thứ trả lời *"vì sao agent nói thế"*. Thiếu nó thì không đối chất được, cũng không kiểm được rào chắn — tức mất đúng hai lý do đã quyết lưu |
| **Con trỏ `config_version`** | ~~system prompt đã render~~ | Persona **đã được đánh phiên bản và lưu bất biến** (§6.1). Muốn biết agent lúc đó chạy luật nào thì tra version. Lưu prompt mỗi cuộc gọi là nhân đôi ~10 KB cho **zero** thông tin mới |
| | ~~định dạng ChatML training~~ | `qwen_transcript.py` sinh ChatML để huấn luyện — kèm cả system prompt và định nghĩa kỹ năng mỗi lần. Đó là artifact khác mục đích, giữ riêng nếu còn cần |

**Xoá theo số điện thoại (NĐ 13) — luồng phải nguyên tử ở phía chỉ số:**

```
xoá(phone) → TRANSACTION: chọn transcript_uri của mọi conversations có phone đó
                          xoá các hàng đó + contacts.snapshot_text
             ─ commit ─
             job dọn tệp theo danh sách uri (idempotent, chạy lại được)
```

Hàng đi trước, tệp theo sau. Ngược lại — xoá tệp trước rồi commit hỏng — để lại hàng trỏ vào tệp
không còn: dashboard hiện lỗi cho một cuộc gọi lẽ ra không tồn tại.

> **Lời hứa retention chỉ đáng tin bằng job thực thi nó.** 6 tháng giờ nằm trong hợp đồng với
> khách; job xoá quá hạn phải **có giám sát và cảnh báo khi không chạy**. Hứa mà không dọn còn tệ
> hơn không hứa — vì đã nói với khách rồi.

**Ai được đọc — chưa chốt, gắn vào N4.** Bản ghi thoại là thứ nhạy cảm nhất trong hệ: tên, số điện
thoại, ngân sách, hoàn cảnh gia đình của khách hàng cuối. Ma trận vai trò (N4, **vẫn chưa có người
nhận**) phải trả lời vai trò `Viewer` có đọc được không. Kèm một ràng buộc hạ tầng: **BR10 (NobleX
không đọc `tenant_data`) phải áp cả cho kho tệp**, không chỉ Postgres — đường dẫn bản ghi thoại
phải dùng thông tin đăng nhập theo tenant, nếu không thì lời hứa thủng ở đúng chỗ nhạy nhất.

**Giá lưu VND int**, không phải tỷ — theo `spec_provider.md` của agent. Đơn vị "tỷ" chỉ là chuyện
hiển thị/nhập liệu ở UI; đổi đơn vị làm **ở biên nhập**, không ở tầng đọc. Đây chính là bug
`tỷ → ×1e9` mà `nbx_mongo` đã phải xử lý — đưa về một chỗ duy nhất.

Ba bảng Finance **tạo schema nhưng để rỗng** — khớp prototype: *"Bật một lĩnh vực là có sẵn schema…
Trước khi có bản ghi, agent sẽ từ chối trả lời thay vì suy đoán."*

### 5.3 `field_policy_live` — một chỗ trả lời "agent được đọc gì"

Phủ cả hai loại field:

| | `is_core` | Ví dụ | Cưỡng chế bằng |
|---|---|---|---|
| Cột thật, nhạy cảm thương mại | `true` | `commission`, `bank_support`, `csbh_full` | `CASE WHEN … THEN col ELSE NULL` trong VIEW |
| Key trong `extras jsonb` do tenant khai | `false` | `fund_type`, `phi_quan_ly` | hàm `gated_extras()` lọc key |

Và phủ luôn **2 tier của agent**:

- `agent_readable = true` → tier 1 → `ExtraFieldSpec` (hiện trong prompt với `label_vi`)
- `filterable = true` + `match_op` → tier 2 → `ToolParamSpec` (bơm vào tool schema; 6 toán tử
  `eq · substring · gte · lte · exists · contains`)

Màn "khai trường" của portal ghi vào đúng một bảng, và Pha 1+2 của agent tiêu thụ được ngay.

### 5.4 Hợp đồng đọc — `VIEW agent_*`

```sql
CREATE VIEW tenant_data.agent_units
  WITH (security_invoker = true) AS      -- BẮT BUỘC — xem cảnh báo dưới
SELECT u.tenant_id, u.code, u.project_code, u.unit_type, u.status,
       u.price_vnd, u.area_m2, u.direction, u.bedrooms, u.fund_type,
       CASE WHEN pol('unit','commission')   THEN u.commission   END AS commission,
       CASE WHEN pol('unit','bank_support') THEN u.bank_support END AS bank_support,
       CASE WHEN pol('unit','csbh_full')    THEN u.csbh_full    END AS csbh_full,
       tenant_data.gated_extras('unit', u.extras) AS extras
FROM tenant_data.units u;
```

> **`security_invoker = true` là chỗ dễ mất isolation nhất trong toàn bộ thiết kế.**
> Mặc định Postgres chạy view bằng quyền **người tạo view** → RLS của role `agent_<tenant>` **bị bỏ
> qua**, agent đọc được hàng của mọi tenant. Yêu cầu **Postgres ≥ 15** (sàn cứng; dùng bản mới nhất).
> Phải có test tích hợp chuyên bắt cái này (§9).

`pol(entity, field)` và `gated_extras(entity, extras)` tra `control.field_policy_live` theo tenant
hiện tại.

### 5.5 Bundle

```
tenants/<id>/bundles/<sha256>/
  manifest.toml     data_source="portal" · [tools].enabled · rankers
                    media_channel · [brand] · vertical
  persona/          SOUL.md · RULES.md · PROMPT_TEMPLATE.md
                    CUSTOMER_PROFILE.md · config.json
  extras.toml       ExtraFieldSpec + ToolParamSpec (render từ field_policy)
tenants/<id>/LIVE   {"version": 12, "bundle": "sha256:…"}
```

Giữ **đúng định dạng file agent đang đọc** → `loader.py` chỉ đổi chỗ lấy file, không đổi cách parse.
`data_source="portal"` là provider mới duy nhất.

**Content-addressed** giải ba vấn đề: không orphan khi transaction rollback; republish config y
nguyên thì dedupe miễn phí; rollback không cần render lại.

**Trùng lặp có chủ đích:** bundle mang extras để agent **dựng tool schema + render nhãn**; VIEW mới
là chỗ **cưỡng chế**. Bundle lệch cũng không rò được dữ liệu.

### 5.6 Knowledge — một collection mỗi tenant

**Quyết định #13 (chốt 2026-07-29).** Tầng RAG hiện **không có một chữ `tenant` nào**: tên collection
là một biến môi trường duy nhất toàn hệ thống (`QDRANT_COLLECTION`), và filter là theo `project_id`,
không theo tenant. Với một tenant thì vô hại; với hai tenant thì `kb_search` của B trả về chunk của A.

```
tenants/<id>/  ← bundle (object storage)
kb_<tenant_id>  ← collection Qdrant riêng, tạo LÚC TẠO TENANT
```

| | |
|---|---|
| Tên collection | Sinh từ `tenant_id` theo quy tắc cố định **trong code**. Không cấu hình tay, không nhận từ client |
| Tạo lúc nào | Cùng transaction tạo tenant, **trước khi có tài liệu nào**. Collection rỗng là hợp lệ |
| Agent đọc | Đúng collection của tenant nó phục vụ; `tenant_id` lấy từ `TenantContext` (đã cố định lúc boot), **không từ tham số tool** |
| Manifest | Thêm trường trỏ tới collection — không có thì portal không biết render màn Tài liệu của tenant nào |
| Xoá tenant | Drop collection. Nghĩa vụ Nghị định 13, không phải việc dọn dẹp |

**Vì sao không dùng chung collection rồi filter theo `tenant_id`.** Rẻ hơn ở quy mô lớn, nhưng nó đặt
isolation vào tay *người viết query nhớ thêm điều kiện* — đúng cái mô hình mà §5.4 đã bác bỏ cho
Postgres khi chọn RLS thay vì "code tự filter". Một chỗ quên là rò dữ liệu giữa hai khách hàng, và
lỗi đó **im lặng**: query vẫn trả kết quả, chỉ là kết quả của người khác.

> **Cổng test bắt buộc thứ 5.** Bốn cổng ở §9 chỉ phủ Postgres. Thêm: truy vấn với `TenantContext`
> của tenant A phải trả **0 chunk** của tenant B. Cùng hạng với test cross-tenant read.

Đặc tả nghiệp vụ đầy đủ (luồng, màn hình, mã lỗi, 12 business rule): tài liệu **KB_01** trên Notion.

### 5.7 Persona — template của platform, tenant chỉ điền biến

**Quyết định #14 (chốt 2026-07-29).** Người dùng portal là trưởng phòng kinh doanh sàn BĐS, không
phải kỹ sư prompt. Cho họ sửa thẳng markdown là giao một thứ họ không đánh giá được hậu quả.

Đọc `tenants/noble/persona/RULES.md` thật — 184 dòng — thì tỉ lệ như sau:

| Phần | ~dòng | Ai sở hữu |
|---|---|---|
| Bắt buộc gọi tool trước khi trả lời · giao thức booking 3 bước · giải mã tên dự án (`find_project`) · xử lý `ESCALATE_SIGNAL` · `send_media` gọi âm thầm · cấm markdown vì TTS | 110 | **Platform khoá** |
| Tool catalog · khối phong thuỷ | 25 | **Render từ `[tools].enabled` + `rankers`** |
| Phạm vi pre/post-sale · danh sách `department` · câu từ chối · xưng hô | 20 | **Tenant điền** (8 ô, đều có mặc định) |
| Giọng điệu · độ dài trả lời | 10 | **Tenant chọn preset** (nội dung do N3 viết) |

Giao thức booking 3 bước được **cưỡng chế bằng code guard** trong `schedule_viewing` — sửa prompt mà
không sửa guard là vỡ. Đó là lý do 110 dòng kia phải nằm ngoài tầm tay tenant.

**Render đúng một chỗ.** Portal render toàn bộ lúc publish; bundle chứa markdown thuần. Hiện
`load_agent_def` render jinja lần nữa lúc boot (`agent_name`, `brand`) — hai chỗ cùng render một
template là cách chắc chắn nhất để portal và agent hiểu khác nhau. Bỏ luôn đường `NOBLE_AGENT_NAME`
đè `config.json`: với tenant thì portal phải là chủ tên agent.

> **Hai lỗi phải sửa trước khi làm màn Agent Studio** — đã kiểm trong code, không phải suy đoán.
>
> **(1) Tool catalog là text tĩnh.** `grep -rn 'Tool catalog' src/` chỉ trả về chính `RULES.md`;
> không có code nào lọc bảng 15 dòng đó theo `[tools].enabled`. Tắt `booking` ⇒ `build_schemas`
> bỏ schema, nhưng prompt vẫn dạy gọi ⇒ LLM không emit được tool call nên **trả lời bằng lời**:
> hứa đặt lịch rồi không có `appointments` nào được ghi. Khối phong thuỷ cùng loại — Phase 3d strip
> params `birth_year/gender/menh/zodiac` theo `rankers`, nhưng đoạn RULES dạy truyền chúng thì không.
>
> **(2) `RULES.md` không dùng biến brand.** `load_agent_def` truyền `brand` vào `env.from_string(...).render(...)`,
> nhưng đếm token trong file: **`{{ agent_name }}` ×5, `{{ brand.* }}` ×0**. Còn hardcode ở dòng 172
> (`"Em là chuyên viên NobleX."`), 179 (`"bất động sản NobleX"`), 173 và 176 (mã `NCLB`/`SLC`, tên
> `"Noble Crystal Long Biên"`). Agent của tenant khác sẽ tự xưng nhân viên NobleX.

Đặc tả nghiệp vụ đầy đủ (16 business rule, luồng, màn hình, mã lỗi): tài liệu **AG_01** trên Notion.

### 5.8 Mô hình kết nối & vai trò — RLS chỉ đúng khi cả bốn điều kiện cùng đúng

Spec trước nhắc `role agent_<tenant>` và `security_invoker` như dữ kiện đã biết, nhưng chưa viết
portal nối bằng gì, ai tạo role, và mật khẩu đi đường nào. Không có mục này thì lát **1a** không
code được.

```
Dashboard ──HTTP+phiên──> Portal API ──role `portal_app`──┐
                          (MỘT tiến trình, MỌI tenant)     │ mỗi txn:
                                                           │ SET LOCAL app.current_tenant
                                                           ▼
                    ┌──────────────────────────────────────────────────┐
                    │                    POSTGRES                      │
                    │  schema `control`     KHÔNG RLS.                 │
                    │                       Chỉ `portal_app` có GRANT; │
                    │                       agent không được cấp quyền │
                    │                       nên không thấy nó tồn tại  │
                    │                                                  │
                    │  schema `tenant_data` RLS + FORCE trên mọi bảng  │
                    │                       VIEW agent_*               │
                    │                       (security_invoker = true)  │
                    │                                                  │
                    │  chủ sở hữu = `portal_owner` — CHỈ chạy migration│
                    │  không tiến trình nào phục vụ bằng role này      │
                    └──────────────────────────────────────────────────┘
                         ▲              ▲              ▲
                    agent_noble    agent_anphu    agent_sunrise
                    pod noble       pod anphu      pod sunrise
```

**Hai cách xác định tenant, vì hai bản chất khác nhau:**

| | Agent | Portal API |
|---|---|---|
| Nối bằng | `agent_<tenant>` — **mỗi tenant một role** | `portal_app` — **một role duy nhất** |
| Tenant lấy từ | **Tên role** (`current_user`) | Biến phiên `app.current_tenant`, đặt lại mỗi giao dịch |
| Tự đổi được không | **Không** — không đổi được `current_user` | Có → phải đặt từ membership đã xác thực, không từ input |

Agent phục vụ đúng một tenant suốt đời; portal đổi tenant theo từng request. Gộp về **một** policy
duy nhất phải rà soát:

```sql
CREATE FUNCTION current_tenant() RETURNS text LANGUAGE sql STABLE AS $$
  SELECT COALESCE(
    NULLIF(substring(current_user FROM '^agent_(.+)$'), ''),
    current_setting('app.current_tenant', true)
  )
$$;

CREATE POLICY tenant_isolation ON conversations USING (tenant_id = current_tenant());
```

Không xác định được tenant → `NULL` → `tenant_id = NULL` không bao giờ đúng → **0 hàng**. Hỏng thì
trả rỗng, không trả nhầm của người khác. Đó là chiều hỏng đúng.

**Bốn điều kiện — cả bốn đều hỏng ÂM THẦM nếu sai:**

| # | Điều kiện | Sai thì sao |
|---|---|---|
| 1 | `ALTER TABLE … FORCE ROW LEVEL SECURITY` | Postgres **không áp** RLS cho role sở hữu bảng. `portal_app` vừa sở hữu vừa phục vụ ⇒ RLS bật cũng vô nghĩa, mọi test một-tenant vẫn xanh |
| 2 | `portal_owner` (migration) ≠ `portal_app` (runtime); không role runtime nào có `BYPASSRLS` | Như trên |
| 3 | VIEW `agent_*` khai `WITH (security_invoker = true)` (PG 15+) | Mặc định view chạy bằng quyền **chủ view** ⇒ RLS của bảng dưới xét theo `portal_owner`, **không** theo `agent_noble`. Cách ly biến mất, không có lỗi nào |
| 4 | `SET LOCAL` **trong giao dịch tường minh**, không bao giờ `SET` trần | Với connection pool: request A đặt `noble`, trả connection về pool, request B (`anphu`) nhận đúng connection đó và **kế thừa `noble`**. Chỉ hiện khi có tải thật |

Điều kiện 4 kéo theo một luật cho tầng repo: **mọi truy vấn `tenant_data` phải nằm trong giao
dịch** — không có đường đọc ngoài giao dịch. (pgbouncer chế độ transaction-pooling tương thích
`SET LOCAL`, **không** tương thích `SET`.)

**Cách ly ≠ phân quyền — hai cơ chế, đừng gộp.** Mục này chỉ giải quyết *"hàng này thuộc workspace
nào"*. Nó **không** trả lời *"người này có được xoá không"*. Một `Viewer` đọc đúng workspace của
mình đi qua RLS sạch sẽ; chặn họ xoá là việc của tầng Portal API. Đặc tả vai trò và ma trận quyền
đầy đủ: **PQ_01** (`docs/product/2026-07-29-pq01-phan-quyen.md`).

Hai điều PQ_01 ràng buộc ngược lên mục này:

- **Vai trò đọc từ `memberships` mỗi request**, không từ JWT. Rẻ vì điều kiện 4 đã buộc mọi request
  nằm trong một giao dịch — đọc thêm một hàng đi cùng chuyến.
- **Quyền hỗ trợ của NobleX là một hàng `memberships` có `expires_at`**, không phải cờ `BYPASSRLS`
  hay một nhánh kiểm tra riêng. Cờ bỏ qua tạo một đường code mà quyết định #10 không áp dụng.

**Hệ quả lên cấp phát.** Thêm một khách giờ là bốn việc, đúng nguyên tắc cả-bốn-hoặc-không:

1. `INSERT` hàng `tenants`
2. `CREATE ROLE agent_<slug>` + mật khẩu ngẫu nhiên + `GRANT` hẹp (chỉ `SELECT` trên view `agent_*`;
   chỉ `INSERT`/`UPDATE` trên `appointments` · `contacts` · `conversations`)
3. Đẩy mật khẩu vào nơi pod đọc được (secret của CI/K8s) — **việc này trước đây không ai ghi ra**
4. Tạo collection Qdrant + thư mục kho tệp

---

## 6. Luồng

### 6.1 Publish

```
POST /api/v1/tenants/{id}/config/publish
  ▼
job(kind=publish, state=running, actor=…)
  │
  ├─ 1. VALIDATE  (fail-fast — không tạo version nếu fail)
  │      manifest      tool names ∈ registry · rankers ∈ known
  │                    vertical đã bật · [brand] không rỗng
  │      persona       jinja2 render được · không còn {{ }} sót
  │                    SOUL/RULES không rỗng
  │      field_policy  filterable ⇒ match_op ∈ 6 toán tử
  │                    enum_values chỉ với type=enum · maps_to tồn tại
  │      tool schema   build_schemas(enabled) + bơm extras → không lỗi
  │      ── warning, KHÔNG block ──
  │                    vertical bật mà 0 bản ghi
  │                    N bản ghi thiếu field bắt buộc
  │
  ├─ 2. RENDER  → bundle, tính sha256
  ├─ 3. UPLOAD  → tenants/<id>/bundles/<sha256>/…
  │
  ├─ 4. TRANSACTION ───────────────────────────────────┐
  │      version = max+1            (cấp TRONG txn)    │
  │      INSERT config_versions(version, payload, sha) │
  │      REWRITE field_policy_live  ← từ payload       │
  │      UPDATE tenants.live_version = version         │
  │     ───────────────────────────────────────────────┘
  │
  ├─ 5. WRITE tenants/<id>/LIVE = {"version":12,"bundle":"sha256:…"}
  └─ job → success
```

**Thứ tự 4 trước 5 là có chủ đích.** Đổi ngược — ghi `LIVE` trước rồi commit — agent sẽ pull bundle
`v12` trong khi `field_policy_live` vẫn `v11`: **prompt mới, gate cũ, sai âm thầm**. Với thứ tự
hiện tại, hỏng ở bước 5 chỉ tạo *"DB nói v12, agent còn v11"* — portal thấy ngay
(`live_version ≠ running_version`) và job retry ghi `LIVE` (idempotent).

**Ranh giới với eval.** Validate ở đây là kiểm tra **cấu trúc, rẻ, đồng bộ**. "Chạy 24 kiểm thử"
của prototype là kiểm tra **hành vi**, tốn LLM call, thuộc #4. Publish ở #1 **không được** phụ
thuộc eval — eval chết là không ai publish được. Quan hệ đúng: eval là **cổng khuyến nghị trên UI**,
không phải cổng chặn kỹ thuật.

### 6.2 Reload phía agent — session pin version

```
BOOT
  read LIVE → pull bundle → verify sha256 → cache đĩa → TenantContext → serve

MỖI 20s
  GET LIVE
  ├─ không đổi → thôi
  └─ đổi → pull bundle mới → verify sha
           ├─ OK   → nạp thành version MỚI, GIỮ version cũ trong cache
           │         UPSERT agent_heartbeats(running_version=…)
           └─ FAIL → GIỮ NGUYÊN version đang chạy
                     ghi heartbeats.last_error, thử lại lượt sau
```

Không bao giờ phục vụ config nạp nửa vời.

**Session pin:** phiên mới nhận version mới; **phiên đang chạy giữ version nó khởi tạo** cho tới khi
kết thúc. `session:{sid}:meta` mang thêm `config_version`; agent giữ vài version gần nhất trong
cache đĩa. Hai lý do:

1. Persona không đổi giữa cuộc hội thoại.
2. **Không bust prompt cache** — system prompt nằm đầu mọi request; đổi giữa phiên là reprocess toàn
   bộ prefix. Agent đã phải xây `NOBLE_SUMMARY_WARM_CACHE` để tránh đúng chuyện này. Publish mà bust
   cache mọi phiên đang chạy thì mỗi lần xuất bản là một cú spike latency trên toàn bộ khách đang gọi.

Khớp câu prototype đã viết: *"Khách đang được phục vụ bởi v3.2"*.

**Không có `force_immediate`.** Đánh đổi đã biết và chấp nhận: sửa một rào chắn đang nói sai thì
cuộc gọi 20 phút đang chạy vẫn dùng bản cũ tới khi kết thúc.

### 6.3 Rollback

```
POST /config/rollback {version: 11}
  └─ TRANSACTION
       REWRITE field_policy_live  ← từ config_versions[11].payload
       UPDATE tenants.live_version = 11
     WRITE LIVE = {"version":11,"bundle":"<sha của v11>"}
```

Không render lại, không tạo version mới. `v12` vẫn trong `config_versions` để publish lại được.

> **Bất biến:** publish và rollback dùng **chung một hàm** cho đoạn transaction + ghi `LIVE`. Hai
> đường riêng là cách chắc chắn nhất để `field_policy_live` lệch khỏi `live_version`.

### 6.4 Nhập liệu — tay + file

```
Upload CSV/XLSX → PARSE → VALIDATE → DRY-RUN report
                                       ├─ thêm     N hàng
                                       ├─ cập nhật M hàng
                                       ├─ XOÁ      K hàng   (chỉ chế độ Thay thế)
                                       └─ lỗi      L hàng + lý do từng dòng
                  → user xác nhận → APPLY (1 transaction, cả-hoặc-không)
```

Hai chế độ: `Thêm/cập nhật` (mặc định) và `Thay thế toàn bộ` (phải bấm xác nhận riêng, **luôn hiện
số hàng sẽ xoá trước khi apply**). Không bao giờ apply mà không qua dry-run.

Đổi đơn vị (tỷ → VND int) làm ở bước PARSE.

Noble lên portal bằng **một lần** export NBX → CSV → import, không cần job định kỳ.

### 6.5 Provisioning — cấp pod SONG SONG với onboarding

```
① Portal: tạo workspace  (onboarding bước 1)
     tenants(status=provisioning) · config_drafts ← seed từ template vertical
     └─ NGAY LẬP TỨC kích hoạt CI job cấp pod  TENANT_ID=<slug>
     │
     ├──────────────── hai nhánh chạy SONG SONG ────────────────┐
     ▼                                                          ▼
② Khách làm bước 2–3 (15–40 phút người thật)          ③ CI: pod boot
     nhập dự án/quỹ căn · sửa persona                      read LIVE → pull bundle
     publish v1 ĐƯỢC PHÉP                                  UPSERT agent_heartbeats
     ▼                                                          │
     └──────────────────────────┬───────────────────────────────┘
                                ▼
④ Portal thấy heartbeat tươi + running_version == live_version
     → status = ready   (SUY RA, không ai bấm)
     → bước 3 mở ô Thử ngay
```

**Vì sao đổi thứ tự.** Bản trước để ③ **sau** ②, tức pod chỉ có sau khi khách đã xong onboarding —
nhưng bước 3 của wizard (*chat thử ngay*) là bước "aha" của cả sản phẩm và nó **cần pod**. Việc cấp
pod không cần tức thì; nó chỉ cần **nhanh hơn một người nạp dữ liệu và sửa persona**, tức 15–40 phút.
Kích hoạt ở bước 1 là đủ, và không cần thêm hạ tầng nào: vẫn đúng một CI job như quyết định #5, chỉ
đổi **ai bấm** — portal gọi pipeline trigger thay cho một người.

**Trạng thái bước 3 đọc từ đâu.** Không có state mới: `status` vẫn suy ra từ `agent_heartbeats`
(§6.5 ④) và `live_version` vs `running_version`.

| Trạng thái | Điều kiện | Ô Thử ngay |
|---|---|---|
| `Đang cấp` | chưa có heartbeat nào | khoá, hiện tiến trình, cho đi tiếp bước 4 rồi quay lại |
| `Đang áp dụng` | heartbeat tươi nhưng `running_version < live_version` | khoá, ≤20s (chu kỳ poll §6.2) |
| `Sẵn sàng` | heartbeat tươi + version khớp | mở |
| `Mất kết nối` | heartbeat cũ | khoá + báo lỗi thật, không giả vờ đang chạy |

**Suy biến có chủ đích:** nếu ③ chậm hoặc lỗi, bước 3 hiện `Đang cấp` và khách vẫn đi tiếp được —
xấu nhất thì onboarding thành hai pha (làm bước 1–2, quay lại sau), đúng phương án dự phòng. Khác
biệt là hai pha là **trường hợp xấu nhất**, không phải mặc định.

`status` suy ra từ heartbeat nên **tự lành**: pod chết → heartbeat cũ → `Mất kết nối`; pod lên lại →
tự về `ready`. Không có trạng thái phải sửa tay.

> **Vì sao "pool pod cấp trước" là phương án ảo — đã kiểm trong code agent.**
> `TENANT_ID` bị đóng băng qua **ba** singleton tầng process: `config.get_settings()` → `_settings`
> (đọc env một lần); `tenant/loader.py` → `_ctx_singleton`; `agent/facade.py` → `_runner_singleton`.
> Nên **không thể gán tenant cho một container đã boot** — pool muốn nhận tenant phải restart, tức
> không nhanh hơn tạo mới. Muốn pool thật thì phải phá cả ba singleton, và đó chính là runtime
> đa-tenant mà quyết định #1 đã loại. Ba singleton này cũng là lý do lát **1d** (facade giữ map
> `version → AgentDef`) là lát đắt nhất: nó phá singleton thứ ba.

---

## 7. Diff phía `santa-hotline-agent`

### 7.1 Đổi

| # | Chỗ | Việc |
|---|---|---|
| 1 | `tenant/loader.py` | `get_tenant_context()` đọc bundle từ object storage thay vì đĩa package: read `LIVE` → pull → verify sha → cache dir → **`tomllib` parse y nguyên** |
| 2 | `tenant/bundle.py` *(mới)* | poller 20s · cache nhiều version · upsert `agent_heartbeats` |
| 3 | `agent/facade.py` + `storage/models.py` | `Meta` thêm `config_version`; facade giữ **map `version → AgentDef`** thay vì một `AgentDef` singleton |
| 4 | `data/providers/portal.py` *(mới)* | asyncpg, đọc `agent_*` VIEW, implement đúng `DataProvider` Protocol hiện có. `extra_specs`/`tool_params` lấy từ `extras.toml` trong bundle |
| 5 | `data/providers/__init__.py` | `get_provider()` đọc `ctx.data_source` thay vì `settings.noble_data_source` |
| 6 | `agent/tools/booking.py`, `update_customer.py` | ghi `appointments` / `contacts` (Postgres) thay vì `hotline_bookings_flat` / `customers` (Mongo) |
| 7 | `storage/call_summaries.py` | ghi `conversations` (Postgres) thay vì `hotline_call_summaries`. Gộp `call_events` vào cột `events jsonb` **cùng lượt ghi** thay vì insert rời từng sự kiện |
| 8 | `agent/memory/`, `storage/user_snapshots.py` | đọc/ghi `contacts.snapshot_text` thay vì `hotline_user_snapshots`. Khoá đổi từ `phone` toàn cục sang `(tenant_id, phone)` — **`phone` unique toàn cục là đúng chỗ đơn-tenant lộ ra** (§2.1) |
| 9 | `storage/agent_messages.py` → mới `storage/transcript.py` | ghi bản ghi thoại lên **kho tệp** (đường dẫn + đăng nhập theo tenant) thay vì collection `agent_messages`; trả `uri` cho `conversations.transcript_uri`. **Phải vá 3 khiếm khuyết §5.2.1**: bổ sung `tool` call + kết quả · bỏ được việc quét toàn bảng · xoá được theo số điện thoại. Không tái dùng định dạng ChatML của `qwen_transcript.py` |

### 7.1.1 Kiểm kê Mongo — sau #18 + #19 gần như rỗng

Đếm mọi collection agent chạm tới (`grep -rhoE '\bdb\.[a-z_]+'`), phân loại theo đích:

| Collection | Sau #18 / #19 | Ghi chú |
|---|---|---|
| `hotline_call_summaries` · `hotline_call_events` · `hotline_user_snapshots` · `hotline_bookings_flat` · `customers` | → `tenant_data` | quyết định #18 |
| `agent_messages` | → kho tệp | quyết định #19 |
| `project_du_an` · `project_can_ho` · `nbx_projects` · `nbx_units` | → `tenant_data.projects/units` | §7.1 #4–#5 |
| `conversations` · `bookings` | **code chết** | `session_store.py` — `create_index` đã gỡ từ 2026-07-08 |
| `noble_profiles` | cache 30 ngày của **API hồ sơ nội bộ NobleX** | Tính năng riêng của Noble, không phải nền tảng. Hoặc thành phần mở rộng theo tenant, hoặc bỏ |
| `outbound_briefs` · `outbound_calls` | **ngoài MVP** | Gọi ra — quyết định P3 chốt kênh MVP chỉ còn API |
| `session_metrics` | → **schema `platform`** (Postgres, không RLS) | Telemetry: `{component, operation, duration_ms}` + tổng hợp P50/P95/P99. **Không chứa dữ liệu khách** |

**Kết luận (quyết định #20): Odyssey không dùng Mongo.** Không phải vì Mongo dở, mà vì sau #18 +
#19 **không còn gì cho nó làm** — một cơ sở dữ liệu phải vận hành, sao lưu, giám sát, đổi lấy đúng
một bảng đo độ trễ.

### 7.1.2 Không dùng ≠ gỡ code — ranh giới phải giữ

`santa-hotline-agent` là **một codebase phục vụ hai deploy**: Santa đang chạy thật trên Mongo, và
Odyssey đang xây trên Postgres. Nên #20 nói *Odyssey không dùng Mongo*, **không** nói *xoá
`mongo_client.py`*.

> **Rủi ro rộng hơn #20, phải xử lý ở mức kế hoạch:** §7.1 viết các mục #6–#9 dưới dạng *"ghi X
> **thay vì** Y"*. Đọc nguyên văn thì mỗi mục đó **làm Santa hỏng** ngay khi merge. §7.3 lại giả
> định *"CMS cứ chạy tiếp làm tool nội bộ Noble, nghỉ sau"* — hai điều này không thể cùng đúng.
>
> Phải chốt một trong hai, **trước lát 1e**: (a) đường ghi chọn theo `ctx.data_source` giống đường
> đọc ở #5 — Santa giữ nhánh Mongo, Odyssey đi nhánh Postgres; hoặc (b) Santa đóng băng ở một
> nhánh git riêng và không nhận thay đổi nữa. Đề xuất **(a)**: nó tái dùng đúng cơ chế #5 đã có,
> và không tạo ra một nhánh git phải nuôi.

**Thêm vào §7.1 diff:**

| # | Chỗ | Việc |
|---|---|---|
| 10 | `metrics/store.py` | ghi `platform.session_metrics` (Postgres) thay cho collection Mongo. Kèm quyết định về `storage/resilience.py` — hàng đợi thư chết trên Redis hiện **viết riêng cho Mongo**; hoặc chuyển theo, hoặc bỏ và chấp nhận mất telemetry khi ghi lỗi (chấp nhận được: đây là số đo, không phải dữ liệu khách) |

**#7 và #8 đến từ quyết định #18.** `metrics/store.py` **không** trong danh sách — `session_metrics`
ở lại Mongo (telemetry của NobleX, không phải dữ liệu tenant). Việc #8 kèm một đổi khoá thật: hồ sơ
tích luỹ hiện khoá theo `phone` **toàn cục**, sang portal phải là `(tenant_id, phone)` — cùng một số
điện thoại gọi hai khách hàng khác nhau là hai hồ sơ, không phải một.

**#3 là thay đổi cấu trúc lớn nhất.** Hiện `facade` dựng **một** `TurnRunner` singleton từ một
`agent_def`. Session-pin buộc nhiều `agent_def` sống song song. Đây là chỗ tốn nhất và dễ sai nhất —
nên làm thành **một lát riêng có test riêng**.

**#5 chính là việc agent đã cố ý hoãn** — `HANDOFF-saas-refactor.md` mục B.1:
*"Provider-through-`TenantContext` cutover… Làm thành lát riêng."* Giờ bị buộc phải làm. Nó đã được
lường trước và có test canh.

### 7.2 KHÔNG đổi — phần quan trọng nhất của rủi ro

Turn loop · `orchestrator` invariants · `runner` · prompt builder (jinja2) · tool registry /
dispatcher / `schemas.build_schemas` · `custom_params.py` (engine lọc tier-2) · RAG Qdrant ·
semcache · voice pipeline · mọi transport · Redis 3-key session state · memory snapshot.

**Agent không biết portal tồn tại.** Nó chỉ biết "bundle đến từ đâu" và "provider tên là `portal`".

### 7.3 Tái dùng từ `santa-agent-cms`

Nhấc ở mức service, **không fork repo**. CMS cứ chạy tiếp làm tool nội bộ Noble, nghỉ sau.

| Nhấc | Mức |
|---|---|
| `services/media_search/` (captioner, embedders, video_describer, storage_s3, webp) | **Code** — nặng, đã chạy, gần như không dính tenant |
| `services/rag/` (`nbx_rag_build`, `qdrant_core`) | **Code** — đường build Qdrant đã có thật |
| `sync_job_service` (state · actor · drift · background) | **Pattern**, viết lại ~150 dòng |
| JWT HS256 15m + refresh opaque Redis 7d rotate | **Mô hình**, code mới vì cần tenant scope |
| `nbx_sales_api_mapping.md` · `nbx_projects_ingest_handover.md` · `cms_db_state.md` | **Đầu vào spec** |

**Chủ động không kế thừa:** `BaseRepo` nuốt lỗi Mongo → bảng UI rỗng im lặng. Repo mới **fail loud**
— lỗi store nổi lên UI thành lỗi, không thành danh sách rỗng.

### 7.4 Dữ liệu vận hành — ĐÃ CHỐT (N5)

**Chốt 2026-07-29: về Postgres + RLS** (quyết định #18). Schema ở §5.2, mô hình kết nối ở §5.8,
diff agent ở §7.1 #7–#8.

**Lý do quyết định không phải "Mongo kém".** Mongo cách ly thật được — collection riêng mỗi tenant
+ role trỏ đúng collection đó là ranh giới do máy chủ cưỡng chế, không phải quy ước code. Cái bị
loại là **hai kho cho cùng một loại dữ liệu**, vì ba thứ:

1. **`session_metrics` tách khỏi `tenant_data`** (sang schema `platform`, quyết định #20) chính là
   bằng chứng ranh giới nằm ở **dữ liệu của ai**, không phải công nghệ nào. Cái gì thuộc tenant thì
   nằm sau **một** cơ chế cách ly duy nhất — để lời hứa *"NobleX không đọc được dữ liệu workspace"*
   kiểm chứng bằng **một** bài test.
2. **`user_snapshots` và `contacts` là cùng một khái niệm.** Để hai kho, hai cách xoá, là tự tạo câu
   hỏi "cái nào đúng" mà không ai trả lời được.
3. **Xoá theo số điện thoại (NĐ 13).** Một kho = một giao dịch. Hai kho = hai lệnh xoá không chung
   giao dịch; hỏng giữa chừng thì đã xoá nửa vời mà không chứng minh được với khách.

**Lập luận đã bị hạ xuống, ghi lại để không ai dựng lại nó:** ban đầu tôi lấy "màn Hội thoại cần nối
dữ liệu" làm lý do chính. Sai — `call_summaries` **đã được cố ý làm phẳng** (tự mang
`customer_name`/`project_code`/`phone`/`transferred_to_sales`), nên **màn danh sách không cần nối
gì**. Việc nối chỉ cần ở màn chi tiết, khách hàng 360 và số liệu tổng quan.

**Bản ghi thoại — ĐÃ CHỐT 2026-07-29: có lưu, giữ 6 tháng** (quyết định #19, chi tiết §5.2.1). Ba
lý do là ba câu trước đó không trả lời được: khách phàn nàn lấy gì đối chất · rào chắn có chạy đúng
không · xoá theo NĐ 13 thì xoá cái gì. **Cảnh báo kèm theo: đây là chữ, không phải tiếng** — hệ
thống không ghi âm ở bất kỳ đâu, xem §5.2.1.

### 7.4.1 Bối cảnh gốc — vì sao đây từng là khoảng trống 🔴

§7.1 #6 chỉ chuyển **hai** đường ghi: `booking` → `appointments`, `update_customer` → `contacts`.
Nhưng agent còn ghi **bốn** thứ nữa mà bảng đó không nhắc:

| Ghi ở | Vào | Màn dashboard sống bằng nó |
|---|---|---|
| `storage/call_summaries.py` | `hotline_call_summaries` | **Hội thoại** + hộp handoff |
| `storage/call_events.py` | `hotline_call_events` | Hội thoại (dòng thời gian) |
| `metrics/store.py` | `session_metrics` | Tổng quan (số liệu) |
| `storage/user_snapshots.py` | `hotline_user_snapshots` | Khách hàng 360 |

**Vì sao chặn.** Hôm nay dashboard đọc bốn thứ đó qua `/api/v1/sales/*` — **nằm trên chính tiến
trình agent** (`server/http.py:110`), xác thực bằng **một API key tĩnh dùng chung
(`NOBLE_SALES_API_KEY`), không có phạm vi tenant nào**. Đường đó không dùng lại được cho nhiều khách
hàng. §3 xếp Ops surfaces vào sub-project #4 với ghi chú *"đã có bản chạy được → rủi ro thấp"*, nhưng
bản chạy được đó đứng trên nền không có ranh giới tenant — rủi ro thấp về **giao diện**, không phải
về **cách ly**.

Kết quả rà: bốn thứ đó **không cùng bản chất**, và gộp làm một là lý do nó từng trông đắt —
xem §7.4 cho cách tách và §5.2 cho schema.

**Dung lượng — con số thật, đo từ shape của doc:** `call_summaries` là ~18 trường scalar + một đoạn
tường thuật LLM cap 600 token ⇒ **~3 KB một cuộc gọi**, KHÔNG phải bản ghi thoại. 50 tenant × 100
cuộc/ngày ≈ **5,5 GB/năm**. Mối lo dung lượng ban đầu là không có thật. (Bản ghi thoại thô mới là
~30 KB/cuộc — và nó đi kho tệp, không vào bảng.)

**Các câu hỏi kèm theo — vẫn mở:**

- ~~**N8**~~ — **đã chốt 2026-07-29**: quyết định #20, Odyssey không dùng Mongo. Thay bằng câu
  hỏi mới **N9** — đường ghi của agent chọn theo `data_source` hay đóng băng Santa ở nhánh riêng?
  (§7.1.2, đề xuất phương án (a), **phải chốt trước lát 1e**).
- **N6** — `/api/v1/sales/*` giữ tạm cho Noble hay viết lại ngay? Nếu giữ tạm **phải có ngày tắt**.
- **N7** — ngưỡng "nhịp tim cũ" chưa có số. Bảng trạng thái §6.5 và suy biến §8 đều dựa vào nó.
  Đề xuất `60s` (→ `Mất kết nối`) và `2 phút` (→ `Đang áp dụng` thành lỗi) — gấp 3 và gấp 6 chu kỳ
  poll 20s.
- ~~**N10**~~ — **đã chốt 2026-07-29: MinIO tự dựng** (quyết định #22, chi tiết §7.4.3). Hết chặn
  gói A và cổng test thứ bảy.

Chi tiết quan hệ ba lớp: [`docs/product/2026-07-29-ht01-quan-he-dashboard-backend-agent.md`](../../product/2026-07-29-ht01-quan-he-dashboard-backend-agent.md).

---

### 7.4.2 Phương án lai (Postgres lõi + kho document) — đã cân nhắc, kèm điều kiện đảo ngược

**Phương án:** Postgres giữ dữ liệu lõi quan hệ có RLS; một kho document giữ phần bán cấu trúc —
event log, audit trail, custom field do tenant tự khai. Đây là kiến trúc phổ biến và **hợp lệ**; ghi
ra đây để không ai phải tranh luận lại từ đầu, và để biết khi nào thì nó đúng.

**Vì sao không chọn ở MVP — tra từng loại workload vào hệ này:**

| Loại | Trong Odyssey nằm ở đâu | Nhận xét |
|---|---|---|
| Custom field tenant tự khai | `extras jsonb` trên `properties`/`units`/`loan_products`… (§5.3) | Đã document-shaped, đã trong Postgres |
| Event log | `events jsonb` trên `user_snapshots` — `hotline_call_events` gộp thành một cột, ≤1 KB (§5.2) | Đã gộp, không cần kho riêng |
| Audit trail | Chưa xây (§5.1) | **Ứng viên thật duy nhất** — xem ngưỡng bên dưới |

**Với custom field, Postgres không phải "cũng làm được" — nó là chỗ duy nhất giữ được lời hứa.**
Cổng quyết định key nào trong `extras` được agent đọc là **VIEW `agent_*` đọc `field_policy_live`**
(§5.3). Nếu giá trị custom field ở kho document còn chính sách field ở Postgres thì cổng đó không
còn là cổng — nó tụt xuống thành đoạn lọc ở tầng ứng dụng, tức chỉ đúng khi lập trình viên nhớ gọi.
Đúng loại lỗi im lặng mà §5.8 dựng ra để chống.

**Audit — lập luận lai đứng vững nhưng chưa tới ngưỡng.** Audit đúng khuôn document: shape khác nhau
theo loại sự kiện, chỉ ghi thêm, đọc thưa, giữ lâu hơn dữ liệu nghiệp vụ. Nhưng nguồn sinh của nó là
đổi cấu hình · publish · cấp-thu quyền hỗ trợ · đăng nhập — cỡ **vài trăm dòng/ngày cho toàn nền
tảng**. Một cột `jsonb` + index BRIN theo thời gian chạy việc này nhiều năm.

**Chi phí chia sẻ được và chi phí không chia sẻ được.** Santa đã chạy Mongo trong production, nên
phần **vận hành** (sao lưu, giám sát, người biết dùng) coi như đã trả. Nhưng Santa **đơn tenant** —
Mongo của nó không có role scope theo tenant vì không cần. Làm Mongo đa tenant nghĩa là dựng mới
collection-per-tenant + role giới hạn + một cổng test cho nó, **song song** với cơ chế RLS. Phần
cách ly không chia sẻ được gì.

**Ghi cho sòng phẳng:** *"một cơ chế cách ly duy nhất"* (BR15) hiện **đã không đúng nguyên văn** —
kho tệp là kho thứ hai, không có RLS, giữ bằng tiền tố đường dẫn + khoá (§5.4; **cổng test thứ bảy
ở §9 canh đúng chỗ này**, và nó phụ thuộc N10). Nên khung đúng không phải *"một hay hai kho"* mà là:
**khoản thuế đó đã phải trả một lần vì blob buộc phải là blob; câu hỏi là có trả lần thứ hai một
cách tự nguyện không.**

**Điều kiện đảo ngược — mở lại quyết định #20 nếu MỘT trong ba xảy ra:**

1. Roadmap có **tenant tự định nghĩa cả entity mới**, không chỉ field. `field_policy_live` mô hình
   hoá được field động, **không** mô hình hoá được entity động.
2. Audit vượt **~10 triệu dòng** hoặc phải giữ **>2 năm**.
3. Chốt **N9** theo hướng (a) và nhánh Mongo dù sao cũng phải nuôi lâu dài — lúc đó chi phí biên
   đúng là gần bằng không.

**Đường lùi rẻ vì đã chọn `jsonb`:** chuyển một bảng `jsonb` sang kho document sau này là việc cơ
học. Chiều ngược lại — tách sẵn rồi phát hiện cần join và cần chung giao dịch — thì không.

### 7.4.3 Nơi đặt kho tệp — ĐÃ CHỐT (N10)

**Chốt 2026-07-29: MinIO tự dựng** cho nhánh `tenants/` (quyết định #22).

| | |
|---|---|
| `tenants/<id>/LIVE` · `tenants/<id>/bundles/<sha>/` · bản ghi hội thoại | **MinIO tự dựng**, trong nước |
| Ảnh dự án (`noble-cms-media`, `noblex-agent-media`) | **Giữ nguyên chỗ hiện tại** — ảnh căn hộ không phải dữ liệu cá nhân |

**Ba lý do:**

1. **Bản ghi hội thoại ở trong nước.** Quyết định #19 đưa nội dung hội thoại vào kho tệp — tên, số
   điện thoại, ngân sách, hoàn cảnh gia đình của khách hàng cuối. Tệp nằm trên máy chủ ngoài Việt Nam
   là **chuyển dữ liệu cá nhân ra nước ngoài**, kéo theo nghĩa vụ hồ sơ đánh giá tác động (NĐ 13
   Điều 25). Tự dựng trong nước **làm câu hỏi pháp lý đó biến mất**, không phải trả lời nó.
2. **Bundle bị pod đọc mỗi 20s × N workspace.** Cùng mạng thì nhanh và không tốn phí ra mạng.
3. **Chuẩn S3 nên code không phụ thuộc lựa chọn này.** Đổi sang mây về sau là đổi endpoint +
   credential, không đổi code (§10.1).

**Hệ quả phải nhận — nói thẳng vì nó là chi phí thật:**

| Hệ quả | Vì sao nặng |
|---|---|
| **Sao lưu và phục hồi giờ là việc của NobleX** | Kho tệp giữ **hai** thứ mang lời hứa: bản ghi hội thoại (retention 6 tháng nằm trong hợp đồng, #19) và bundle (thứ giúp agent boot khi Postgres chết, E01 §8). **Mất kho tệp là vỡ cả hai lời hứa cùng lúc.** Phải có chế độ sao lưu **ra một nơi khác** + một lần diễn tập phục hồi thật, không phải chỉ bật snapshot |
| **Một node không có dự phòng** | MinIO một node = một ổ đĩa. Với hợp đồng 6 tháng thì đây là rủi ro phải xử ở mức hạ tầng, không phải mức code |
| **Cấp phát workspace nay gồm MinIO** | BR12 (*tạo tài nguyên ở cả ba kho hoặc không tạo gì*) nay là: hàng `tenants` + role Postgres + collection Qdrant + **tiền tố `tenants/<id>/` và một credential giới hạn đúng tiền tố đó** |

**Cách cưỡng chế cách ly:** MinIO cho gắn policy theo tiền tố đường dẫn cho từng access key. Mỗi
workspace một key, phạm vi đúng `tenants/<id>/*`. **Cổng test thứ bảy (§9) kiểm chính cơ chế này** —
key của workspace A `GET` một đường dẫn dưới `tenants/B/` phải bị từ chối.

**Phương án bị loại:** S3/mây (rẻ hơn về vận hành, nhưng đổi lấy một nghĩa vụ hồ sơ pháp lý cho thứ
nhạy cảm nhất trong hệ, và phí ra mạng cho một luồng đọc 20 giây một lần) · dùng chung bucket ảnh
hiện có (trộn dữ liệu cá nhân với ảnh công khai vào một ranh giới cách ly — trái BR15).

## 8. Suy biến

| Hỏng gì | Hành vi |
|---|---|
| Object storage chết **lúc boot**, có cache | Chạy bằng bundle cache. Ghi `last_error`. |
| Object storage chết **lúc boot**, không cache | **Fail loud** — pod không lên. Thà không lên hơn phục vụ không có persona. |
| `LIVE` không đọc được **giữa lúc chạy** | Giữ version hiện tại, thử lại 20s sau |
| Checksum lệch | Giữ version hiện tại, `last_error`, **không** nạp |
| **Postgres chết** | Tool trả `ESCALATE_SIGNAL` → `dispatcher._auto_escalate` chuyển người thật |
| Publish: validate fail | Không tạo version, job `failed`, **không gì đổi** |
| Publish: txn fail | Bundle orphan (content-addressed, vô hại), không gì đổi |
| Publish: ghi `LIVE` fail sau commit | `live_version ≠ running_version` → portal hiện `Đang xuất bản`, job retry |
| RLS cấu hình sai | Bắt bằng test tích hợp bắt buộc (§9) |
| Import file lỗi dòng | Dry-run báo từng dòng, apply cả-hoặc-không |

**Postgres chết không làm agent crash** — nó rơi vào đúng cơ chế `ESCALATE_SIGNAL` + auto-escalate
agent đã xây sẵn. Khách được chuyển cho người thật với lời giải thích, không nghe agent bịa. Không
phải thiết kế mới, chỉ là dùng đúng thứ đã có.

---

## 9. Kiểm thử

**Unit** — luật validate · render bundle · checksum · `field_policy → extras.toml` · dry-run import
· đổi đơn vị tỷ→VND.

**Tích hợp (Postgres thật, testcontainers) — sáu cổng bắt buộc:**

1. **Cross-tenant read = 0 hàng.** Hai tenant, hai role; role A `SELECT` view thấy 0 hàng của B.
   Đây là test canh `security_invoker = true` — thiếu nó thì isolation vỡ âm thầm.
2. **Gate cột.** `agent_readable=false` ⇒ cột về `NULL`, key extras bị lọc.
3. **Nguyên tử publish/rollback.** Kill giữa txn ⇒ `field_policy_live` và `live_version` không bao
   giờ lệch.
4. **`status` suy ra từ heartbeat.** Heartbeat cũ ⇒ `Mất kết nối`; tươi + version khớp ⇒ `ready`.
5. **Chủ sở hữu không bỏ qua RLS** (§5.8 điều kiện 1–2). Nối bằng role sở hữu bảng ⇒ vẫn bị RLS
   chặn. Bỏ `FORCE ROW LEVEL SECURITY` đi ⇒ **test phải đỏ**. Không có cổng này thì mọi test
   một-tenant vẫn xanh trong khi cách ly đã vỡ.
6. **Rò rỉ qua connection pool** (§5.8 điều kiện 4). Chạy xen kẽ hai request khác tenant trên **cùng
   một pool**; request không `SET LOCAL` phải trả **0 hàng**, không phải kế thừa tenant của request
   trước. Đây là lỗi chỉ hiện khi có tải thật — không test thì không bao giờ thấy ở dev.

**Tích hợp kho tệp (MinIO thật trong container) — cổng thứ bảy:**

7. **Cách ly theo tiền tố đường dẫn.** Khoá của tenant A `GET` một đường dẫn dưới `tenants/B/` ⇒
   phải bị **từ chối**, không phải trả tệp. Chạy cho cả hai loại nội dung: `bundles/` và bản ghi
   hội thoại.

   **Vì sao cổng này không thay thế được bằng sáu cổng trên.** Postgres và kho tệp cưỡng chế bằng
   hai cơ chế khác hẳn nhau:

   | Postgres | Kho tệp |
   |---|---|
   | Máy chủ **từ chối câu truy vấn** — sai tenant thì 0 hàng, không lách được | Chỉ kiểm *"khoá này có quyền vào tiền tố đường dẫn này không"* |

   Một lỗi ghép đường dẫn — `tenants/` cộng với một biến bị nhầm — là workspace A đọc được bản ghi
   hội thoại của workspace B. Postgres không cho chuyện đó xảy ra; **kho tệp thì có thể**. Đây là
   chỗ dữ liệu nhạy cảm nhất trong hệ (§5.2.1), và sáu cổng trên **không cổng nào chạm tới nó**.

   **Chạy được từ 2026-07-29** — N10 đã chốt MinIO tự dựng (quyết định #22, §7.4.3), nên test dựng
   MinIO thật trong container. Cơ chế cần kiểm: **policy theo tiền tố đường dẫn gắn cho từng access
   key** — mỗi workspace một key, phạm vi đúng `tenants/<id>/*`. Đây là cổng canh lời hứa *"NobleX
   không đọc được dữ liệu workspace"* ở nửa mà RLS không với tới.

**Contract test — hai repo dùng chung fixture.** Bundle do portal render phải parse được bằng
**`loader.py` + `load_agent_def` thật của agent**. Chạy ở cả hai repo trên cùng một fixture (fixture
là **file**, không phải code Python dùng chung — hai repo có thể khác phiên bản Python). Không có
cái này thì seam bundle sẽ mục: portal thêm khoá vào `manifest.toml`, agent bỏ qua im lặng, không ai
phát hiện tới lúc persona không ăn.

**E2E** — tạo tenant → nhập data → publish → agent giả pull → heartbeat → portal hiện `ready` +
`running_version`.

**Phát biểu lại bất biến của agent.** Bất biến hiện tại là *"behaviour-identical cho
`TENANT_ID=noble`"*, đo bằng bộ test cũ với baseline **8 lỗi cố định**. Việc #5 (đổi provider) và #6
(đổi đích ghi) **phá bất biến đó bằng thiết kế**. Phát biểu mới:

> Behaviour-identical **với cùng một tập dữ liệu**: so `provider=portal` (Postgres) với
> `provider=nbx` (Mongo) trên bộ dữ liệu Noble đã import. **Không** phải "byte-identical với hôm nay".

Cần **golden test đối chiếu 2 provider** — chạy cùng bộ query qua `nbx_mongo` và qua `portal`,
assert DTO ra giống nhau. Đây là cách duy nhất chứng minh view mapping + đổi đơn vị đúng, và cũng là
thứ chứng minh migrate Noble không mất dữ liệu.

Điều kiện chạy được test này: **import một lần** dữ liệu Noble (export NBX → CSV → §6.4) vào
`tenant_data` với `tenant_id='noble'`, trong khi `nbx_projects`/`nbx_units` trên Mongo vẫn còn. Hai
nguồn cùng tồn tại là cơ hội đối chiếu — **chỉ có một lần**, trước khi Mongo bên đó nghỉ. Nên xếp
lát `1e` **trước** khi ai đó dọn `nbx_*`.

---

## 10. Tech stack — ĐÃ CHỐT 2026-07-29 (quyết định #21)

Dùng **bản mới nhất** của mọi thành phần; pin cụ thể lúc scaffold.

**Cơ sở của quyết định: đây gần đúng stack `santa-agent-cms` đang chạy production** — không phải lựa
chọn theo sở thích. Đối chiếu: CMS dùng FastAPI · Pydantic v2 · uvicorn · Redis 5 · React 18 · Vite 5
· TS 5 · TanStack Query v5 · react-hook-form · zod. Odyssey đổi **đúng hai thứ**: kho (`motor` →
`asyncpg`, theo #18) và CSS (Tailwind 3 → 4, lý do bên dưới).

### 10.1 Backend

| | |
|---|---|
| Ngôn ngữ | **Python 3.13** · quản gói bằng **`uv`** (agent đã dùng `uv.lock`; CMS còn `requirements.txt`, không có lock thật) |
| Web | FastAPI · Pydantic v2 · uvicorn |
| DB | **Postgres — sàn cứng ≥ 15** vì `security_invoker`; dùng bản mới nhất |
| Truy cập DB | **`asyncpg` thô — KHÔNG ORM** (§10.4) |
| Migration | **SQL thuần** + runner nhỏ (§10.4) |
| Cache | Redis — refresh token + rate limit |
| Kho tệp | **MinIO tự dựng** (chốt 2026-07-29, quyết định #22 — xem §7.4.3), giao tiếp chuẩn **S3**, client **`aioboto3`** (CMS dùng `boto3` — đồng bộ, chặn event loop; publish có upload nằm trên đường người dùng chờ). Cách ly bằng **policy theo tiền tố `tenants/<id>/*` cho từng access key** |
| Job | Bảng **`jobs`** đã có (§5.1) làm hàng đợi: `SELECT … FOR UPDATE SKIP LOCKED` + tiến trình worker riêng. **Không** dùng `BackgroundTasks` của FastAPI như CMS — nó chết cùng tiến trình và không để lại dấu vết nào |
| Job theo giờ | `cron` trên máy chủ gọi một lệnh, **ghi một hàng vào `jobs`**. Không dùng scheduler trong tiến trình. Ghi vào `jobs` là cách rẻ nhất để *"job xoá quá hạn phải có giám sát"* (quyết định #19) thành thật, không phải khẩu hiệu |
| Auth | **`PyJWT` + `bcrypt` gọi trực tiếp** (§10.5) |
| Test | pytest · **testcontainers** — Postgres thật + MinIO thật (§9, cổng 1–7) |

### 10.2 Frontend

| | |
|---|---|
| Nền | React 18 · Vite · TypeScript strict (no `any`) |
| CSS | **Tailwind CSS 4** · shadcn/ui |
| Router | **`@tanstack/react-router`** (CMS đã dùng; ăn khớp TanStack Query, route có kiểu) |
| Data fetching | `@tanstack/react-query` v5 |
| Form | react-hook-form + zod |

### 10.3 KHÔNG dùng — ghi ra để không ai đề xuất lại

| Bị loại | Vì |
|---|---|
| **ORM** (SQLAlchemy…) | §10.4 |
| **Celery / RabbitMQ** | Có 2–4 loại job, mỗi ngày vài chục lần. Postgres đã ở đó và bảng `jobs` đã có. Cùng lập luận #20: một hạ tầng phải vận hành · sao lưu · giám sát là chi phí trả mãi |
| **Next.js** | §10.6 |
| **K8s operator** | Quyết định #5 đã chốt CI job; pod thủ công là có chủ đích |
| **Kho metrics riêng** (Prometheus/Grafana) | `agent_heartbeats` + `jobs` + `platform.session_metrics` đã là bề mặt vận hành. Thêm khi có người trực |

### 10.4 Vì sao `asyncpg` thô và migration SQL thuần

Sẽ có người đề nghị SQLAlchemy *"cho năng suất"*. **Đừng** — và lý do không phải khẩu vị.

Cả **bốn** điều kiện hỏng-âm-thầm ở §5.8 nằm ở **tầng kết nối và DDL**, không ở tầng câu truy vấn:

```sql
ALTER TABLE … ENABLE ROW LEVEL SECURITY;
ALTER TABLE … FORCE ROW LEVEL SECURITY;                 -- thiếu: chủ bảng đi xuyên RLS
CREATE VIEW agent_x WITH (security_invoker = true) …;    -- thiếu: view chạy bằng quyền người tạo
SET LOCAL app.current_tenant = …;                        -- ngoài giao dịch: rò qua connection pool
```

ORM **không giúp gì** ở đó và **che chúng đi**. Migration do ORM sinh tự động sẽ không có ba dòng
đầu, và không ai review nổi một file Python sinh tự động để phát hiện thiếu.

SQL thuần thì mỗi migration là một file **đọc được, diff được, review được** — và **cổng test 5 của
§9 kiểm đúng nó** (bỏ `FORCE ROW LEVEL SECURITY` đi thì test phải đỏ).

### 10.5 Vì sao không dùng lại hai thư viện auth của CMS

§7.3 ghi *"dùng lại khuôn `santa-agent-cms` cho đăng nhập"*. Khuôn đó đứng trên hai thư viện phải
xem lại **trước khi** copy:

| CMS đang ghim | Vấn đề |
|---|---|
| `passlib[bcrypt]>=1.7,<2` | **1.7.4 là bản cuối, ra 2020.** Với `bcrypt` 4.1+ nó ném `AttributeError` vì đọc metadata phiên bản theo cách cũ — và CMS **không ghim `bcrypt`**, nên nó lấy bản mới nhất |
| `python-jose[cryptography]>=3.3,<4` | Ít bảo trì; hai CVE năm 2024 (nhầm lẫn thuật toán · JWE gây cạn tài nguyên), sửa ở 3.4.0. Ghim `>=3.3` **cho phép giải về đúng bản có lỗi** |

**Chốt: `PyJWT` + `bcrypt` gọi trực tiếp**, bỏ lớp bọc `passlib`. Hai thư viện, đều còn bảo trì,
không có lớp trung gian nào để mục. Muốn theo khuyến nghị OWASP thì dùng `argon2id` (qua `pwdlib`)
thay `bcrypt` — quyết định này để mở, cả hai đều chấp nhận được.

⚠️ **Dùng lại khuôn = dùng lại thiết kế** (bảng `users`/`memberships`, luồng mời, `audit_log`),
**không phải** copy `requirements.txt`.

### 10.6 Vì sao không Next.js

Giá trị chính của Next.js là **server của nó**. Hệ này đã có server, viết bằng Python — và không đổi
được, vì agent là Python và contract test §9 cần `loader.py` thật của agent.

| Next.js bán | Ở Odyssey |
|---|---|
| SSR / SEO | **Mọi trang đều sau đăng nhập.** SEO bằng không, và trang có auth không cache được ở tầng nào dù có SSR |
| API routes · Server Actions | Backend là FastAPI, đã chốt |
| Server Component đọc DB trực tiếp | **Chặn thật** — xem dưới |

**Chỗ chặn thật:** cách ly được cưỡng chế bằng **role của kết nối + `SET LOCAL` trong giao dịch**.
Muốn Server Component đọc Postgres trực tiếp thì phải dựng lại toàn bộ kỷ luật §5.8 **lần thứ hai,
trong Node** — tức **hai bản cài đặt cho một lời hứa cách ly**, đúng kiểu hỏng BR15 nói. Còn nếu
Next chỉ gọi lại FastAPI thì ta đang nuôi một tiến trình Node **để chuyển tiếp request**.

**Khi nào Next.js đúng ở NobleX:** trang marketing công khai, hoặc cổng cho khách hàng cuối có nhu
cầu SEO. Lúc đó nó là **một app riêng**, không nhét vào portal.

**Tailwind 4** bỏ `tailwind.config.ts`, chuyển sang `@theme` trong CSS. Có lợi ở đây vì prototype
vốn đã dùng CSS variable → map thẳng sang `@theme`, không cần lớp trung gian.

**Design token theo prototype**, không theo CMS (mục tiêu ngược nhau — CMS nhắm *continuity* với
dashboard cũ):

```css
--ac:  #0d7a5f    /* accent */    --acs: #e7f2ee    --acd: #0a5e49
bg #f6f5f2 · text #14161a · border #e7e5e0 / #d9d7d1
muted #6f7580 / #8a8f98 / #a0a4ab
font: 'Be Vietnam Pro' (UI) · 'JetBrains Mono' (số)
```

Song ngữ VI/EN — prototype dùng cặp `data-l="vi"` / `data-l="en"`; portal thật dùng i18n bình thường.

---

## 11. Lệch với prototype — phải sửa prototype

| # | Prototype | Phải thành |
|---|---|---|
| 1 | "Xuất bản" áp dụng tức thì | `Đang xuất bản → Đã áp dụng (vN)` — poll 20s |
| 2 | Version `v3.2 / v3.3` | `v12` (int tăng dần) |
| 3 | Màn Lĩnh vực có "**Tự định nghĩa · tự khai trường**" | Bỏ khỏi MVP (quyết định #2) |
| 4 | Workspace switcher | Giữ nguyên UI, nhưng nghĩa là **phạm vi RBAC**, không phải runtime đa-tenant |
| 5 | "Tạo workspace mới" → sẵn sàng ngay | Có 4 trạng thái `Đang cấp · Đang áp dụng · Sẵn sàng · Mất kết nối` (§6.5). Cấp pod kích hoạt ở **bước 1**, chạy song song bước 2–3, nên bình thường bước 3 đã `Sẵn sàng`. **Và nút này không phải self-service** — bấm là sinh một khách hàng trả tiền mới (§2.2) |
| 6 | "Chạy 24 kiểm thử" như cổng trước khi xuất bản | **Cổng khuyến nghị**, không chặn publish (#4) |
| 7 | "sửa hàng loạt tại đây ghi đè toàn bộ danh sách" | Bắt buộc qua **dry-run + xác nhận**, hiện số hàng sẽ xoá |
| 8 | Nút Sync + schedule ở màn Tích hợp & API | Hoãn — chỉ có khi làm adapter API (quyết định #8) |
| 9 | 3 màn `audit` / `settings` / `onboarding` không có trong bản tải về | Dựng theo **nghiệp vụ + hook CSS còn lại**, không đợi thiết kế. Đúng quy trình theo quyết định W1 (§11.1) |

### 11.1 File thiết kế gốc là brainstorm, không phải yêu cầu

**Quyết định W1 (chốt 2026-07-28).** File `Tenant Portal.dc.html` trả lời câu *"sản phẩm nên giải
quyết vấn đề gì cho ai"* — và trả lời tốt. Nó **không** trả lời câu *"xây cái gì"*: nó được vẽ trước
khi đọc code, nên có chỗ vẽ tính năng chưa tồn tại (Tài chính, tiếp quản, CSAT, hạn mức) và đặt sai
tên tool (`create_appointment` thay vì `booking(action=schedule)`).

Vì vậy bảng §11 ở trên **không phải danh sách nợ phải trả**. Mỗi dòng lệch là một trong hai thứ:

- **việc phải xây** → vào sổ quyết định rồi làm, hoặc
- **ý đã bỏ** → xoá khỏi prototype, ghi lý do.

Không có lựa chọn thứ ba là "sửa thực tế cho khớp thiết kế".

Hệ quả cho người thực thi: **không ai phải đi xin ảnh thiết kế để xác nhận một màn.** Nếu một màn
không có trong bản tải về, dựng nó từ nghiệp vụ và từ các hook CSS còn lại — CSS đã tài liệu hoá đầy
đủ state model, nên hành vi tái dựng được. Đó là cách 3 màn ở dòng 9 đã được dựng.

---

## 12. Ngoài phạm vi / hoãn có chủ đích

**Không làm ở #1:**

- Schema-per-tenant / DB-per-tenant. Một `tenant_data` + RLS. Isolation thật đã có ở tầng pod;
  nhân schema theo tenant là nhân chi phí migration mà không mua thêm gì.
- Event bus (Kafka/NATS). Năm seam là SQL + object storage. Thêm khi #4/#5 thực sự cần fan-out.
- Version cho **dữ liệu nghiệp vụ**. Chỉ **config** có version/rollback. Audit dữ liệu thuộc #5.
- Adapter API + schedule sync + nút Sync (quyết định #8).
- K8s operator (quyết định #5).
- Grant hỗ trợ có hạn cho platform admin (quyết định #10) — thuộc #5.
- Cờ `force_immediate` khi publish (quyết định #11).

**Còn hoãn ở agent, không đụng ở #1:** dời core field Noble-specific vào extras (spec Part 1 của
agent); `media_channel` full channel-abstraction.

---

## 13. Rủi ro

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| **#3 facade multi-version `AgentDef`** — thay đổi cấu trúc lớn nhất trong agent | Cao | Lát riêng, test riêng, làm trước các lát khác |
| **`security_invoker` sai → mất isolation âm thầm** | Cao | Test tích hợp cross-tenant là cổng bắt buộc, không được skip |
| **Migrate Noble sai/mất dữ liệu** | Cao | Golden test đối chiếu `provider=portal` vs `provider=nbx` |
| **Seam bundle mục** giữa 2 repo | Trung bình | Contract test chạy ở cả hai repo trên cùng fixture file |
| **Postgres mới bên cạnh Mongo** — thêm một store phải vận hành | Trung bình | Chấp nhận có chủ đích: dữ liệu control plane là quan hệ thuần, và RLS là thứ khiến isolation không phụ thuộc code agent |
| **RLS bật nhưng không có hiệu lực** — chủ bảng bỏ qua RLS, hoặc view thiếu `security_invoker`, hoặc `SET` rò rỉ qua pool. Cả ba **không có triệu chứng** | Cao | §5.8 bốn điều kiện + cổng test 1 · 5 · 6 (§9). Cổng 5 và 6 là hai cổng hay bị bỏ nhất |
| **Đổi khoá hồ sơ `phone` → `(tenant_id, phone)`** (§7.1 #8) — cùng số gọi hai khách hàng là hai hồ sơ | Trung bình | Test hai tenant cùng số điện thoại, hồ sơ không lẫn |
| ~~Dữ liệu vận hành chưa có kho (N5)~~ | — | **Đã chốt 2026-07-29** — quyết định #18, §7.4 |
| Poll 20s làm publish không tức thì | Thấp | UX nói thật trạng thái (§11) |

### 13.1 Bản tải về của file thiết kế không đầy đủ — ghi lại như dữ kiện, không phải rủi ro

`get_file` của Design MCP giới hạn 256 KiB nên bản tải về dừng ở 262.144 byte. Có: toàn bộ
`<style>` (state model đầy đủ), app shell, 15 màn. Không có: đuôi màn `billing`, ba màn
`audit` / `settings` / `onboarding`, và block `<script data-dc-script>`.

**Đây không phải việc cần xử lý.** Theo quyết định W1 (§11.1), file thiết kế là brainstorm nên
thiếu một phần của nó không chặn gì cả. CSS còn đủ để tái dựng hành vi, và ba màn kia đã được dựng
từ nghiệp vụ. Ghi lại ở đây chỉ để ai đọc `design/Tenant Portal.dc.html` không tưởng file bị lỗi.

Lưu ý: `support.js` chỉ là dc-runtime chung (React template renderer), không implement `data-goto`
hay `style-hover` — lớp tương tác của prototype đã được viết lại từ state model trong CSS.

---

## 14. Tài liệu tham chiếu

- Prototype: `Tenant Portal.dc.html` — Claude Design project `389d2c41-f050-40c1-8dd3-7358bdc2bb81`
- Agent: `reference/santa-hotline-agent/` — `CLAUDE.md` ·
  `docs/superpowers/HANDOFF-saas-refactor.md` · `docs/BA/spec_provider.md` · `docs/BA/spec_tool.md`
- CMS: `reference/santa-agent-cms/` — `docs/cms_db_state.md` ·
  `docs/nbx_projects_ingest_handover.md` · `docs/nbx_sales_api_mapping.md` · `docs/design-system.md`
  · `docs/rbac.md` · `docs/adr/0004-mongo-shared-schema-contract.md`
