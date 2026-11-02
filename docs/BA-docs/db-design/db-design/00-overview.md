# 00 · Overview — Thiết kế Database (PostgreSQL + RLS)

> Bản **overview** của bộ `docs/db-design/`. Mỗi domain có file riêng, brainstorm + chốt lần lượt. Bản này giữ: quyết định nền, taxonomy, bản đồ kho, nguyên tắc xuyên suốt, scale-ready, mối nối cross-domain, bảng Δ, chỉ mục. **Chi tiết tới field ở file từng domain.**

---

## 1. Context

Plan gốc (`docs/cms-multitenant-plan.md`) thiết kế thuần **Mongo, DB-per-tenant, "4 spine ngang hàng"**. Sau khi đối chiếu 11 doc Notion (`docs/notion/`) và cân nhắc scale, đã **chốt chuyển sang PostgreSQL + RLS** — trùng kiến trúc tham chiếu của Notion. Plan Mongo cũ + doc Notion nay chỉ là **tham khảo**; tài liệu này là thiết kế **chính thức**.

**Chú thích Δ:** `🆕` mới vs plan gốc · `✏️` đổi vs plan gốc · `📎` khớp/ràng buộc Notion · `⚠️` cố ý khác Notion.

---

## 2. Quyết định nền (đã chốt)

1. **Engine = PostgreSQL + RLS + bảng chung** — `tenant_id` trên **mọi bảng** tenant_data; **Row-Level Security** lọc tự động theo tenant; **FK tổ hợp `(tenant_id, …)`** chống tham chiếu chéo tenant; quan hệ/transaction ACID native. `📎` khớp Notion (RLS + role/grant). `⚠️` **không** dùng `VIEW agent_*` — bỏ gate đọc (KB sạch data nhạy cảm).
2. **Tenancy 2 tầng: `organizations` (parent) → `tenants` (workspace con)** — org-admin thấy các workspace con qua **RLS policy subtree**. (`organizations` = tên mới của `accounts`, tránh nhầm "tài khoản đăng nhập".)
3. **Scale-ready + convertible** — `tenant_id` là **seam duy nhất**: bắt đầu 1 Postgres shared-RLS; khi lớn → partition bảng nóng (`conversations` theo thời gian), tách **từng** tenant lớn/nhạy cảm ra **schema/DB riêng**, hoặc **Citus shard theo tenant_id** cho scale ngang — **không đổi schema/app** (§5c).
4. **Quyết định sản phẩm:** bỏ **gate đọc** (KB chỉ chứa dữ liệu hướng khách; trường nội bộ nhạy cảm không lưu trong KB); `field_definitions` tối giản; giữ `config_versions` + `tenant_verticals` (dài hạn).
5. **Qdrant** = 2 collection/workspace (`<slug>_documents` dense + `<slug>_media` hybrid); **S3** = prefix/workspace. **Phase 1-2 (Mongo) sẽ viết lại sang Postgres — hiện CHỈ thiết kế doc, chưa đụng code.**

---

## 3. Taxonomy — 4 nhóm theo *ai sở hữu & chiều dữ liệu*

```
┌─────────────────────────────────────────────────────────────┐
│ A. CONTROL PLANE  (schema `control` — metadata quản trị)     │
│   organizations·tenants·tenant_verticals·memberships·users·   │
│   field_definitions·config_versions·audit_log                 │
└───────────────────────────────┬──────────────────────────────┘
                                │  set app.tenant_id / app.org_id (từ JWT) → RLS
        ┌───────────────────────┼───────────────────────────────┐
        ▼ (bảng `tenant_data`, RLS theo tenant_id)               ▼
┌─────────────────────────────┐ ┌────────────────────────┐ ┌──────────────────────┐
│ B. KNOWLEDGE BASE           │ │ C. CRM / OPERATIONAL    │ │ D. AGENT STUDIO      │
│  (tenant CUNG CẤP, agent    │ │  (agent GHI, dashboard  │ │  (tenant CẤU HÌNH,   │
│   ĐỌC) — trục = DỰ ÁN:      │ │   đọc)                  │ │   publish→agent)     │
│  · real-estate(projects·    │ │  contacts·conversations │ │  persona·12 kỹ năng  │
│    zones·units·CSBH)        │ │  (+events)·appointments │ │  ·rào chắn → bundle  │
│  · documents (Qdrant+meta)  │ │                         │ │  (config_versions@A) │
│  · media (Qdrant+S3+meta)   │ │                         │ │                      │
└─────────────────────────────┘ └────────────────────────┘ └──────────────────────┘
```

**Vì sao gộp B:** real-estate + documents + media đều là thứ tenant curate để **agent đọc phục vụ khách** → cùng Knowledge Base, cùng nguyên tắc (freshness, cách ly, trục Dự án). Khác C (agent tự sinh) và D (cấu hình).

---

## 4. Bản đồ kho

| Kho | Vai trò | Cách ly |
|---|---|---|
| **PostgreSQL** (1 cluster) | Nguồn sự thật: schema `control` (metadata) + bảng `tenant_data` (nghiệp vụ B/C/D) | **RLS theo `tenant_id`** + FK tổ hợp tenant_id |
| **Qdrant** | Vector knowledge | **2 collection/workspace**: `<slug>_documents` (dense e5) + `<slug>_media` (hybrid text+visual) |
| **S3** | File/media/bundle cấu hình | prefix/workspace `<slug>/` |
| **Telemetry** (sau) | Số liệu vận hành NobleX | ngoài ranh giới tenant |

`✏️` So plan gốc: **Mongo DB-per-tenant → Postgres RLS**; Qdrant **2 collection/workspace** — `_documents` (hybrid dense+sparse) + `_media` (hybrid text+visual); engine RAG ở `02b`.

---

## 5. Nguyên tắc xuyên suốt

- **Cách ly = RLS bằng cấu trúc** `📎`: `ENABLE + FORCE ROW LEVEL SECURITY` **mọi bảng tenant_data**; `tenant_id` mọi bảng; **FK tổ hợp `(tenant_id, parent_id)`** → DB cấm ref chéo tenant; **unique tổ hợp tenant_id** (vd `unique(tenant_id, project_id, unit_code)`); app dùng **role thường (không BYPASSRLS)** + `SET app.tenant_id` mỗi request. **Test cross-tenant BẮT BUỘC** (A không đọc được B).
- **Agent ĐỌC — không gate ẩn field:** KB chỉ chứa dữ liệu hướng khách. Read-layer/`VIEW` chỉ **bỏ khoá rỗng** + kèm **mốc freshness** (`📎`BR06). `⚠️` bỏ gate `agent_read` của Notion (BR09) — thay bằng "không lưu trường nội bộ nhạy cảm trong KB".
- **Agent GHI đúng 3 bảng** `📎`(HT_01 BR09): `contacts`/`conversations`/`appointments` — cưỡng chế bằng **GRANT + RLS `WITH CHECK`**.
- **Provision cả-hoặc-không** `📎`: tạo tenant = insert `tenants` + tạo **Qdrant coll** + **S3 prefix** (KHÔNG cần tạo DB/schema — dữ liệu là bảng chung RLS). **Teardown NĐ13:** `DELETE WHERE tenant_id` (FK ON DELETE CASCADE) + drop Qdrant coll + xoá S3 prefix.
- **3 bậc hiệu lực** `📎`: Bậc1 tức thì (giá/diện tích/tình trạng/tài liệu) · Bậc2 đầu cuộc (đổi dự án) · Bậc3 publish (persona/kỹ năng/rào chắn/tool schema).
- **NobleX không đọc dữ liệu tenant** `📎`: platform-admin role **không có quyền trên bảng tenant_data nghiệp vụ**; hỗ trợ = có hạn + ghi vết + khách đồng ý.

## 5b. Phân cấp 2 tầng + Phân quyền (RLS)

`organizations` → N `tenants`. `tenant_data` mang `tenant_id`; `tenants` mang `org_id`.

| Scope | JWT / GUC | Thấy | RLS policy trên tenant_data |
|---|---|---|---|
| Platform-admin | `role=platform` | control-plane; **KHÔNG** data nghiệp vụ | không cấp quyền bảng nghiệp vụ |
| Org admin | `app.org_id` | gộp workspace con | `tenant_id IN (SELECT id FROM tenants WHERE org_id = current)` |
| Workspace role | `app.tenant_id` | đúng 1 workspace (4 vai trò) | `tenant_id = current_setting('app.tenant_id')` |
| Agent | `app.tenant_id` cố định lúc boot | 1 workspace; ghi 3 bảng | read tất (không gate) + `WITH CHECK` ghi đúng tenant, đúng 3 bảng |

Đổi quyền có hiệu lực **phiên đăng nhập kế** `📎`(HT_01).

## 5c. Scale-ready — HOẠT ĐỘNG thế nào

- **Query nhanh bất kể tổng DB:** mọi index **dẫn đầu `tenant_id`** → query 1 tenant chỉ chạm slice của nó (ms), không quét toàn bảng.
- **Bảng nóng partition sẵn:** `conversations` **partition theo thời gian**; KB có thể hash theo tenant → planner prune; xoá cũ/tenant = **drop partition** (nhanh).
- **Convertible per-tenant:** vì `tenant_id` có ở mọi bảng, tách 1 tenant ra **schema/DB riêng** là *copy theo tenant_id + đổi search_path* — không đổi schema/query.
- **Scale ngang:** **Citus** shard theo `tenant_id` (thiết kế đã sẵn) khi 1 node đụng trần.
- **Báo cáo xuyên tenant:** read replica + **materialized view** (số liệu tổng tính sẵn).

---

## 6. Trục "Dự án" của Knowledge Base

Dự án là **entity neo** của B (tham chiếu bằng `project_code`, FK tổ hợp tenant_id): `zones`→`units`, `documents`, `media` đều trỏ về. Dự án `status≠published` → **cascade ẩn toàn bộ** zones/units/documents/media khỏi mọi kết quả agent `📎`(DL_01 BR11). Tài liệu chung tenant dùng `project_code="__ALL__"`. `contacts.interest_projects` (nhóm C) trỏ ngược về đây.

## 7. Mối nối cross-domain

- **Template lĩnh vực → KB (B):** real-estate dùng **template `real_estate`** (code) khai đủ schema + enum → **không `custom_fields`**. `field_definitions`@A chỉ dùng cho vertical khác/mở rộng. Agent lọc theo **field CORE cố định** (code).
- **CRM (C) ↔ KB (B):** `contacts.interest_projects` ↔ `projects`.
- **Agent (D) → mọi nơi:** persona/kỹ năng đang bật quyết định tool nào chạy.

---

## 8. Bảng Δ tổng hợp

**So với plan gốc (Mongo):**
1. `✏️` **Engine Mongo → PostgreSQL + RLS**; DB-per-tenant → bảng chung RLS + `tenant_id` mọi bảng + FK tổ hợp.
2. `✏️` "4 spine ngang hàng" → **4 nhóm** (A control · B knowledge-base trục Dự án · C operational · D config).
3. `✏️` C = `contacts`/`conversations`(phẳng, +events)/`appointments`; bỏ spine `events`/`interactions`.
4. `✏️` gộp real-estate + documents + media thành **Knowledge Base** (`02`/`02a`/`02b`); Qdrant **2 coll/workspace**: `_documents` + `_media`, **cả hai hybrid**.
5. `🆕` `organizations`, `tenant_verticals`, `memberships`, `config_versions`, Agent Studio (D), `zones` (phân khu).
6. `✏️` real-estate dùng **template lĩnh vực** khai đủ schema → **không `custom_fields`** (field_definitions@A dành cho vertical khác/mở rộng).
7. `🆕` real-estate: `zones`, `sale_phase`, visibility `status` cascade, quick-fact tách field, `num_floors`; không lưu field nội bộ nhạy cảm.
8. `✏️` `_documents` **hybrid** (dense e5 + sparse BM25, RRF); `_media` **hybrid** (text e5 + visual SigLIP2, RRF).

**So với Notion (giờ phần lớn KHỚP):**
- `📎` **Khớp:** Postgres + RLS + role/tenant; quan hệ + transaction ACID; Qdrant/workspace; cách ly bằng cấu trúc; agent ghi 3 bảng; config_versions publish/poll.
- `⚠️` **Cố ý khác:** (1) **bỏ gate đọc** `agent_read` (BR09) — KB chỉ chứa data hướng khách; (2) telemetry để sau (Notion để Mongo); (3) chi tiết mô hình config theo thiết kế của ta.

---

## 9. Chỉ mục bộ doc (`docs/db-design/`)

| File | Nhóm | Tóm tắt |
|---|---|---|
| `00-overview.md` | — | Bản này |
| `01-control-plane.md` | A | schema `control`: organizations·tenants·tenant_verticals·memberships·users·field_definitions·config_versions·audit_log |
| `02-knowledge-base.md` | B | **Nguyên tắc chung KB** (vertical-agnostic): anchor, visibility `status`, freshness, cách ly, bộ cột chung, pattern RAG, cơ chế template |
| `02a-real-estate-template.md` | B | **Template lĩnh vực BĐS**: projects·zones·units·CSBH·docs·media, enum thật, 2 collection Qdrant, luồng CSBH/pháp lý, `rag_config` |
| `02b-rag-service.md` | B | **RAG service** (generic): 5 module (embed·vision·caption·chunk·store) + orchestrator + schema `rag_config`/`PROFILES` |
| `03-operational.md` | C | contacts·conversations(+events)·appointments (agent write-scope) |
| `04-agent-config.md` | D | persona 3 tầng·12 kỹ năng·rào chắn·config_versions (publish/poll) |

---

## 10. Quyết định còn MỞ

1. `conversation_events`: cột JSONB + job dọn 30d vs bảng partition-by-day drop cũ *(chốt ở `03-operational`)*.
2. transcript N5b: `transcript_ref` nullable ngay, nội dung (S3) sau *(khuyến nghị)*.
3. Tên 4 vai trò + vai trò nào đọc bản ghi thoại (N4).
4. Bộ trường "đủ dữ liệu" bắt buộc cho Dự án/Căn (N2).
5. Ngưỡng freshness cụ thể (giờ/ngày/tháng).
6. Số rào chắn 4 hay 6 (Notion mâu thuẫn).
7. Giới hạn dung lượng/định dạng media.
8. Chọn Postgres managed vs tự vận hành; bật `pg_cron` (job dọn) — xác nhận khi triển khai.

---

## 11. Cách tiến hành

Brainstorm + chốt **từng domain** theo thứ tự A(`01`) → B(nguyên tắc `02` · template BĐS `02a` · RAG `02b`) → C(`03-operational`) → D(`04-agent-config`); mỗi phần xong mới viết file. Chỉ thiết kế doc, chưa đụng code. Plan Mongo cũ giữ ở `docs/cms-multitenant-plan.md` để tham khảo.
