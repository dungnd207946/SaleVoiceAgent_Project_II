# Odyssey Portal — Kiến trúc & bản đồ module (spec tổng)

> **Ngày:** 2026-07-29 · **Trạng thái:** chờ duyệt
> **Repo:** `odyssey-portal-backend` + `odyssey-portal-frontend` — tách 2026-07-30 từ `odyssey-portal-fullstack` (đã archive)
> **Đầu vào:** `odyssey-dashboard-prototype` — chỉ đọc, không sửa. Bốn tài liệu nghiệp vụ đã copy
> sang `docs/product/`; spec control plane và plan lát 1a copy sang với đuôi `.ref.md`.

Tài liệu này **không** thay thế các tài liệu nghiệp vụ đã chốt. Nó làm đúng ba việc:

1. Chia công việc thành **9 module** có ranh giới kiểm chứng được, kèm **bảng đối chiếu 18 màn hình**.
2. Đặt **sáu cơ chế** để mỗi module xây được độc lập — người khác nhận một module là code được ngay,
   không phải đợi module khác xong và không làm vỡ module khác khi merge.
3. Chốt **cấu trúc repo** và quy ước dùng chung.

Mọi quyết định nghiệp vụ vẫn tra ở nguồn: xem §7.

---

## 1. Bối cảnh trong một đoạn

NobleX bán agent chăm sóc khách hàng dạng SaaS cho nhiều khách doanh nghiệp (sàn bất động sản
trước, tài chính sau). Agent đã chạy production. **Cái còn thiếu là control plane** — nơi tenant tự
cấu hình agent, nạp dữ liệu, xem vận hành. Prototype vẽ 18 màn cho phần đó; hai repo portal xây chúng.

Kiến trúc lớn: **một control plane đa-tenant + N data plane**. Portal là một tiến trình phục vụ mọi
workspace; mỗi workspace có một pod agent riêng với `TENANT_ID` cố định. Agent **chỉ** nói với
Postgres và kho tệp — **không bao giờ gọi Portal API**. Đó là điều làm *"control plane chết, agent
vẫn boot"* thành thật.

```
┌───────── CONTROL PLANE (hai repo) ─────────┐
│ frontend ──> backend ──> Postgres          │  control · tenant_data · agent_api
│ (React/Vite) (FastAPI)   └> Redis          │  phiên · rate limit
│                          └> S3             │  tenants/<id>/bundles/<sha>/ · LIVE
└──────────────────┬─────────────────────────┘
   ① pull bundle   │   ③ SELECT trên agent_api view (in-process, 1 hop)
   ② poll LIVE     │   ④ INSERT appointments/contacts  ⑤ UPSERT agent_heartbeats
     ┌─────────────┼─────────────┐
     ▼             ▼             ▼
 TENANT_ID=anphu  =sunrise  =haven          ← pod agent, repo KHÁC
 role agent_anphu  agent_sunrise  agent_haven
```

**Phạm vi hai repo portal:** portal (backend + frontend + worker) và **hợp đồng** mà agent tiêu thụ
(`agent_api` view, định dạng bundle). Sửa agent thật (`santa-hotline-agent`, gói G) **không** thuộc
portal. Thay vào đó backend có **agent giả trong tests**: pull bundle → verify sha256 → đọc
`agent_api` bằng role `agent_<tenant>` → ghi heartbeat. Đủ để chứng minh vòng publish end-to-end và
canh seam bundle không mục.

---

## 2. Bảng đối chiếu — 18 màn hình ↔ module

Menu là cách người dùng đi lại; module là cách chia việc để code. Hai thứ không trùng nhau, nhưng
phải phủ nhau đủ. Bảng này theo **đúng thứ tự sidebar trong `design/Tenant Portal.dc.html`**.

| Sidebar | `data-screen` | Module | MVP? |
|---|---|---|---|
| **▸ Vận hành** | | | |
| Tổng quan | `dashboard` | **M7** | ✅ |
| Hội thoại ⑫ | `convos` | **M7** | ✅ chỉ xem |
| Lịch hẹn | `appts` | **M7** | ✅ + phân công |
| Chất lượng | `quality` | — | ❌ hoãn (eval ⚠ · CSAT ✗) |
| **▸ Kiến thức** | | | |
| Lĩnh vực ▸ Bất động sản | `projects` | **M4** | ✅ |
| Lĩnh vực ▸ *(form dự án)* | `pform` | **M4** | ✅ |
| Lĩnh vực ▸ *(form quỹ căn)* | `uform` | **M4** | ✅ |
| Lĩnh vực ▸ Tài chính | `finance` | — | ❌ hoãn (vertical #2) |
| Lĩnh vực ▸ Quản lý lĩnh vực | `domains` | **M4** | ✅ thu gọn |
| Tài liệu | `kb` | **M6** | ✅ |
| Cần bổ sung ⑫ | `gaps` | **M7** | ✅ |
| **▸ Cấu hình** | | | |
| Agent & Kênh | `agent` | **M5** | ✅ |
| Tích hợp & API | `api` | **M8** | ✅ tối thiểu |
| Users & Phân quyền | `users` | **M2a** danh sách · **M2b** đổi vai trò/mời | ✅ |
| Nhật ký & Dữ liệu ② | `audit` | **M8** | ⏸ một phần |
| Gói cước & Usage | `billing` | — | ❌ hoãn (chỉ *ghi nhận* token ở M8) |
| **▸ Chân sidebar** | | | |
| Workspace switcher | — | **M2a** | ✅ |
| *(không có trong nav)* | `settings` | **M8** | ⏸ một phần |
| *(không có trong nav)* | `onboarding` | **M9** | ✅ |

**18/18 màn có chỗ.** 15 vào MVP, 3 hoãn — lý do ở `docs/product/2026-07-28-phan-bien-…md` §19.

Hai module **không xuất hiện trong sidebar** vì thiết kế mặc định chúng đã tồn tại:

| Module | Vì sao vẫn phải có |
|---|---|
| **M1** nền cách ly | *"Hàng này thuộc workspace nào"* — Postgres cưỡng chế. Sai thì không phải bug, là rò dữ liệu giữa hai khách hàng. Không retrofit được. |
| **M3** kho tệp + publish | Đường agent nhận cấu hình (bundle bất biến + con trỏ LIVE). Không có nó thì mọi thứ sửa ở màn *Agent & Kênh* không tới được agent. |

---

## 3. Bản đồ module

| M | Tên | Lớp | Sở hữu | Nguồn nghiệp vụ |
|---|---|---|---|---|
| **M1** | Nền cách ly đa-tenant + hạ tầng dùng chung | BE | 4 schema · role · `current_tenant()` · helper cách ly · `tenants` · `field_policy_live` · `projects`/`units` lõi · `agent_api` view · **`jobs` + worker + handler registry** · **`agent_heartbeats` + `derive_tenant_status()`** | `slice-1a.ref.md` + sửa C1/C2/C3 · spec §5.4, §5.8 |
| **M2a** | Auth · Workspace · App shell | BE+FE | `users` · `memberships` · phiên · workspace switcher · app shell + nav registry · **chỗ cắm `require(action)`** | `pq01-phan-quyen.md` §II.2.3 · spec §5.8 |
| **M2b** | Phân quyền đầy đủ ·*hoãn — chờ chốt* | BE+FE | 4 vai trò × 13 nhóm hành động · `invitations` · chặn gỡ admin cuối · quyền hỗ trợ có hạn · nhật ký đọc bản ghi thoại | `pq01-phan-quyen.md` toàn bộ |
| **M3** | Kho tệp · Config store · Publish | BE | client S3 (`aioboto3`) + policy tiền tố · `config_drafts` · `config_versions` · `tenants.live_version` · `deployments` · bundle render + con trỏ LIVE · `apply_config_version()` · trigger cấp pod · **agent giả** | spec §5.5, §6.1–6.3, §6.5, §7.4.3 |
| **M4** | **Dữ liệu BĐS** ·*~1/4 công sức, nên 2 người* | BE+FE | cột đầy đủ `projects`(~40)/`units`(~45) · màn khai trường 3 cờ · import CSV/XLSX · media dự án | gói B · DL_01 · DL_02 |
| **M5** | Agent Studio | BE+FE | persona template + 8 biến · 12 tool toggle · 6 rào chắn · chat thử | gói C · spec §5.7 · AG_01 |
| **M6** | Tài liệu KB | BE+FE | Qdrant collection/tenant · parse→chunk→embed→index · trạng thái file | gói D · spec §5.6 · KB_01 |
| **M7** | Vận hành | BE+FE | `conversations` · `contacts` · `appointments` · KPI · Cần bổ sung | gói E |
| **M8** | Kết nối · Nhật ký · Lưu trữ | BE+FE | API key/tenant + rate limit · `audit_log` · retention 6 tháng + job xoá · xoá theo SĐT · ghi nhận token | gói F |
| **M9** | Onboarding | FE | wizard 4 bước · trạng thái từ heartbeat · trigger cấp pod | gói H · spec §6.5 |
| **M10** | **Đấu nối agent ngoài** ·*thêm 2026-08-02* | BE | `agent_keys` · `agent_credentials` · bí mật suy dẫn tất định · `POST /agent/v1/bootstrap` · 5 endpoint quản trị · hợp đồng Gói G | gói G · `specs/2026-08-02-m10-dau-noi-agent-ngoai-design.md` |

> **Vì sao M10 tồn tại:** M1 · M3 · M6 xây xong **ba lớp cách ly cho agent**, nhưng **không module
> nào cấp phát và giao credential cho pod**. M3 §0 ghi thẳng *"`deployments` ghi bằng tay hoặc seed"*.
> M10 lấp đúng khoảng trống đó — không xoá, không sửa, không thay thế cơ chế nào của M1/M3/M6.
> Nó **chặn M9 bước 3** (*"chat thử ngay"* cần pod thật) và chặn demo end-to-end với agent thật.

### 3.1 Thứ tự thi công

```
M1 ──> M2a ─┬──> M3   (giao được cho người khác, song song — xem §3.3)
            ├──> M4   (2 người)
            ├──> M5   (dev với FakePublisher; nút Áp dụng khoá tới khi M3 xong)
            ├──> M6
            ├──> M7   (đọc dữ liệu agent ghi; dev bằng seed)
            ├──> M8
            ├──> M9   (xâu chuỗi M4·M5·M6 — làm cuối, đừng cắt)
            └──> M2b  (hoãn — chờ chốt ranh giới quyền admin, §3.4 · §3.5)
```

**Hai module tuần tự, phần còn lại song song.** Đường găng: **M1 → M2a → M3 → M5** (khớp *A → C → G*
của work packages: cho tới khi agent đọc được dữ liệu portal và cấu hình được persona thì không có
gì để demo).

**Vì sao M1 và M2a không song song được** — nói trước để không ai lỡ kế hoạch:

| | Vì sao |
|---|---|
| **M1 trước tất cả** | Nó là schema + cơ chế cách ly + hạ tầng dùng chung. Không có nó thì không có bảng nào để đọc. Bù lại: nó **không có UI**, và plan chi tiết đã có sẵn ở `slice-1a.ref.md`. |
| **M2a trước mọi module có UI** | Mọi màn đều sau đăng nhập; mọi request đều cần đặt phạm vi workspace từ membership đã xác thực. M2a cũng ship app shell mà 7 module kia treo màn lên. |

#### Sửa 2026-07-30 — M2a tách thành M2a-FE và M2a-BE

Dòng "M2a trước mọi module có UI" ở trên gộp **hai** ràng buộc khác nhau, và điều đó làm kế hoạch
chặt hơn thực tế:

| Ràng buộc | Có chặn dev FE của 7 module không? |
|---|---|
| M2a ship **app shell + nav registry** mà 7 module treo màn lên | **Có** — không có shell thì không có chỗ treo |
| Mọi màn đều **sau đăng nhập**, mọi request cần phạm vi workspace | **Không** — cơ chế ② (mỗi module ship `fake.py` + MSW handler) làm dev màn được trên phiên giả |

Nên M2a chia hai, thi công lệch nhau:

- **M2a-FE** — app shell · nav registry · design token · 18 route rỗng · phiên giả bằng MSW.
  **Đã xong 2026-07-30.** Không phụ thuộc backend nào.
- **M2a-BE** — `users` · `memberships` · phiên JWT · chỗ cắm `require(action)` **cùng check CI của
  nó trong cùng một PR** (Luật 4).

Hệ quả: **bảy module có UI bắt đầu được ngay sau M2a-FE**, không chờ M2a-BE. Cái vẫn phải chờ
M2a-BE là *ghép màn vào API thật*, không phải *dựng màn*.

Điều kiện để việc tách này không sinh nợ: mỗi nav item khai `requiredActions` **từ ngày đầu** (§4⑤),
kể cả khi chưa ai kiểm. Không làm vậy thì lúc M2b vào phải rà lại 18 màn, và bỏ sót một cái là một
mục nav hiện với người không có quyền. Hôm nay điều kiện đó do
`odyssey-portal-frontend/tests/nav-registry.test.ts` canh.

### 3.2 Vì sao `jobs` và `agent_heartbeats` ở M1, không ở M3

Bản chia đầu tiên gán chúng cho M3. Sai — cả hai là **hạ tầng dùng chung**, không phải nghiệp vụ
config, và để chúng ở M3 là buộc bốn module đợi một module:

| Thứ | Ai cần | Nên ở |
|---|---|---|
| `control.jobs` + tiến trình worker | **M4** (import file) · **M6** (build index) · **M8** (job xoá quá hạn) · M3 (publish) | **M1** |
| `control.agent_heartbeats` + `derive_tenant_status()` | **M2a** (badge trạng thái workspace ở shell) · **M9** (bước 3 wizard) · M3 | **M1** |

`agent_heartbeats` ở M1 cũng nhất quán về khái niệm: M1 sở hữu **toàn bộ seam agent** — `agent_api`
view là đường agent **đọc**, `agent_heartbeats` là đường agent **ghi**. Cùng một hợp đồng, cùng một
người sở hữu.

Worker dùng **handler registry** giống nav registry (§4⑤): mỗi module ship `modules/<m>/jobs.py` khai
handler của nó, worker tự gom. Thêm một loại job **không sửa file của M1**.

### 3.3 M3 giao được cho người khác — và cái giá của việc hoãn nó

Sau §3.2, hoãn M3 **không chặn kỹ thuật** module nào. Nhưng nó có giá về sản phẩm, ghi rõ ở đây để
người quyết định biết mình đang đánh đổi gì:

| Module | Hoãn M3 thì |
|---|---|
| M4 · M6 · M7 · M8 | ✅ **Không chặn.** M4 ghi `field_policy` vào `config_drafts` (gate đã test được ở M1 cổng 2 bằng seed `field_policy_live` trực tiếp) · M6 sinh tên collection từ `tenant_id` **trong code**, không lấy từ bundle · M8 dùng `jobs` ở M1 |
| **M5** Agent Studio | ⚠️ **Xây được, chạy chưa đủ.** Toàn bộ form code được với `FakePublisher`. Nhưng nút **Áp dụng phải khoá kèm lời giải thích thật** — persona sửa xong mà agent không nhận được. Không được để nút bấm rồi im lặng không làm gì |
| **M9** Onboarding | ⚠️ **Bước 3 inert.** Bước 1·2·4 xây được. Bước 3 *"chat thử ngay"* cần pod thật ⇒ cần M3 kích hoạt cấp pod, nên nó sẽ hiện `Đang cấp` mãi |

Tài liệu định hướng §20 nói thẳng: *"nếu phải cắt, cắt bước 4 — đừng đẩy bước 3 xuống sau"*. Bước 3
là chỗ khách lần đầu thấy agent nói bằng dữ liệu **của chính họ**; mọi bước trước nó là chi phí. Nên
**khuyến nghị: M3 làm song song, đừng để cuối.**

**Điều kiện bắt buộc để người khác nhận M3:** `odyssey-portal-backend/docs/contracts/config-publish.md` + spec M3 phải viết
**trước khi M4 và M5 bắt đầu**, kể cả khi chưa ai code M3. M5 cần `FakePublisher` có kiểu để code
được; M4 cần biết ghi `field_policy` vào `config_drafts` theo hình dạng nào. **Viết contract sớm,
thi công muộn** — đó là cái làm việc giao module thành thật.

### 3.4 Ba quyết định hoãn có chủ đích — và điều kiện của từng cái

**Chốt 2026-07-29 với người quyết định:** ưu tiên dựng **hệ thống quản lý/vận hành** trước; ba câu
dưới đây quyết sau. Hoãn được — nhưng **mỗi cái có một điều kiện phải làm ngay**, nếu không thì lúc
quyết sẽ thành retrofit.

| Hoãn | Vì sao hoãn được | ⚠️ Điều kiện phải làm **bây giờ** |
|---|---|---|
| **Agent nhận cấu hình bằng image riêng hay bundle + con trỏ** | Thuộc M3, mà M3 đã hoãn. M1/M2a không biết đến nó. Cấu hình vẫn lưu ở `config_drafts`/`config_versions` bất kể agent nhận nó bằng cách nào | Không có. Đây là hoãn **sạch** — cấu hình là dữ liệu trong Postgres, cách chuyển nó tới agent là chuyện của M3 |
| **Ai bấm được "Tạo workspace"** (self-service · chỉ admin · duyệt) | Thuộc M9 | Không có. M1/M2a chỉ cần *"có một đường tạo workspace"* |
| **Admin nền tảng có đọc được `tenant_data` không** | Vì **M1 mặc định làm bản chặt** | **Mặc định chặt.** Không tạo role `BYPASSRLS` (sửa lỗi C3). Chặt → nới sau là **thêm vào** (một hàng `memberships`, hoặc một role mới): một migration. Nới → chặt sau mới là viết lại |

**Vì sao chiều "chặt trước, nới sau" là chiều rẻ:** spec nguồn §5.1 nói *"nếu bây giờ nới 'cho tiện'
thì lời hứa NobleX không truy cập được dữ liệu tenant thành sai và sửa sau rất đau"*. Chiều đau là
**nới → chặt**. Nên hoãn quyết định mà mặc định chặt là hedge rẻ nhất, không phải trì hoãn rủi ro.

### 3.5 Vì sao tách M2a / M2b

`phân quyền xây sau` (chốt 2026-07-29) buộc tách, vì M2 gộp hai thứ khác bản chất:

| | Hoãn được? |
|---|---|
| **Xác thực** — đăng nhập, phiên, "người này thuộc workspace nào" | **Không.** Mọi màn đều sau đăng nhập, và `tenant_conn()` cần membership đã xác thực để đặt phạm vi |
| **Phân quyền** — 4 vai trò, 13 nhóm hành động, thư mời, quyền hỗ trợ | **Được** |

> ⚠️ **Điều kiện — cùng khuôn với `enforce_tenant_isolation()` ở §4③.** Nếu M2a ship endpoint **không
> có chỗ khai quyền**, M2b thành *"rà toàn bộ endpoint và thêm kiểm tra"* — đúng kiểu retrofit đau nhất,
> và bỏ sót một endpoint là một lỗ hổng không ai thấy.
>
> **Bắt buộc: M2a ship `require(action: str)` làm FastAPI dependency, và MỌI endpoint khai `action`
> của nó từ ngày đầu.** Lúc đầu `require()` chỉ kiểm *"có phải thành viên workspace này không"*. M2b
> **chỉ đổi phần thân** của `require()` sang tra ma trận vai trò — **không sửa endpoint nào**.
>
> Kèm một test canh, cùng hạng với catalog test: **quét mọi route đã đăng ký; route nào không khai
> `action` ⇒ CI đỏ.** Danh sách 13 nhóm hành động lấy từ `pq01-phan-quyen.md`; M2a chỉ cần **tên**
> hành động, chưa cần ma trận.

Nguyên tắc chung cho cả ba chỗ (`enforce_tenant_isolation` · `require(action)` · handler registry):
**viết chỗ cắm một lần, đổi ruột sau.** Đó là cái làm "hoãn quyết định" khác với "để lại nợ".

### 3.6 Hai chỗ hoà giải giữa các tài liệu nguồn

Hai tài liệu đã chốt nói khác nhau ở hai chỗ. Ghi lại quyết định để không ai tranh luận lại.

**(a) Versioning persona.** `work-packages` gói C nói *"Lưu → áp dụng, chưa versioning"*; spec §5.5
buộc agent đọc config qua **bundle bất biến + con trỏ LIVE**.

> **Chốt: cơ chế version có từ M3, UI version hoãn.** Cơ chế không hoãn được — không có bundle +
> con trỏ thì agent không có đường nhận cấu hình nào khác. Hoãn đúng phần **giao diện**: màn lịch sử
> version và màn diff. **Rollback giữ lại**, vì với cơ chế đã có nó chỉ là đổi con trỏ (~10 dòng);
> bỏ đi không tiết kiệm gì mà mất đường lùi.

**(b) `security_invoker`.** Spec §5.4 ghi `WITH (security_invoker = true)` là **bắt buộc**; plan lát
1a sửa lỗi **C1** nói nó **sai nghiêm trọng**.

> **Chốt: theo C1 — view definer ở schema riêng `agent_api`.** `security_invoker` khiến Postgres
> kiểm quyền người gọi **trên bảng gốc**, nghĩa là agent phải được `GRANT SELECT ON tenant_data.units`
> — và khi có quyền đó, agent query thẳng bảng gốc, **bỏ qua toàn bộ gate cột**. Cơ chế "view lo cột"
> bị vô hiệu. Bản đúng: view definer, agent có `USAGE` trên `agent_api` + `SELECT` trên view và
> **zero privilege** trên `tenant_data`. Vì definer view chạy bằng quyền owner nên RLS của owner
> không áp — **view phải tự lọc tenant trong `WHERE`**, và tenant suy từ **`session_user`** chứ không
> phải `current_user` (trong definer view `current_user` trả về owner của view).

Hai chỗ sửa còn lại của plan 1a cũng được nhận: **C2** (`tenants.lifecycle` là cột lưu ∈
`{active, suspended, closed}`; trạng thái hiển thị `provisioning · publishing · ready · disconnected`
là **hàm thuần** của lifecycle + heartbeat + `live_version`) và **C3** (không tạo role `BYPASSRLS`
khi chưa cần).

---

## 4. Sáu cơ chế để module xây độc lập

Yêu cầu: một người nhận M4 phải code được mà không đợi M3, và merge được mà không làm vỡ M6.
Không tự nhiên mà có — sáu cơ chế dưới đây là cái mua nó.

### ① Mặt tiền module, cấm import chéo ruột

```
src/portal/
├─ core/                       ← shared kernel: config · db · auth deps · errors · logging
│                                (M1 KHÔNG có thư mục module — code của nó ở đây)
└─ modules/
   ├─ auth/{router,service,repo,contracts,fake}.py
   ├─ config/{router,service,repo,contracts,fake}.py
   └─ …
```

> **Thư mục module bỏ tiền tố số (2026-07-30, M2a-BE).** Bản trước ghi `m1_foundation/` ·
> `m2_auth/` · `m3_config/`. Tiền tố là **siêu dữ liệu lịch thi công, không phải nghĩa** — và ba cơ
> chế tưởng móc vào nó thì kiểm lại đều không: dải revision nằm trong *tên file* migration chứ
> không phải tên thư mục · `make test-module M=auth` chạy y hệt · CI không path-filter job nào
> (§4⑥). Cái tiền tố thật sự cho là thứ tự khi `ls`, không đủ để đánh đổi bằng một tên không nói
> lên nội dung. Bù lại bằng bảng đối chiếu module ↔ thư mục ở §3.
>
> `m1_foundation/` bỏ hẳn, không đổi tên: M1 không có router nào, code của nó ở `core/`. Một thư
> mục module rỗng là chỗ để người sau nhét bừa vào.

**Luật:** module chỉ được import `portal.core.*` và `portal.modules.<khác>.contracts`. Import
`service.py` / `repo.py` / `router.py` của module khác là **lỗi CI** — một test đọc AST của cây
`modules/`, không phải quy ước trong đầu ai.

Frontend cùng luật:

```
src/
├─ components/ui/              ← shadcn primitives (dùng chung, không nghiệp vụ)
├─ lib/                        ← api client · i18n · utils
├─ routes/                     ← TanStack Router file-based
└─ features/
   ├─ auth/{api,components,nav.ts}
   └─ …
```

Sáu thư mục `features/` đã đổi tên bỏ tiền tố cùng lúc với backend (2026-07-30): `auth` ·
`realestate` · `agent` · `kb` · `ops` · `platform`. `features/deferred/` giữ nguyên — nó không phải
tên module.

`features/<m>/` chỉ import `lib/`, `components/`, `i18n/`. Cấm `features/*` gọi nhau — canh bằng
eslint boundary rule **và** `tests/module-boundaries.test.ts`. Cần thứ của module khác ⇒ import
`features/<khác>/contracts`, mặt tiền công khai của nó.

> **`packages/contracts` đã bỏ (2026-07-30).** Bản trước của spec này khai một package workspace
> chứa types sinh từ OpenAPI của backend. **Tách FE/BE thành hai repo git làm nó bất khả thi** —
> không có workspace dùng chung giữa hai repo.
>
> **Cách FE lấy type của backend là quyết định còn treo, thuộc M2a-BE** — module đầu tiên có API
> thật. Không quyết bây giờ: hôm nay FE chạy hoàn toàn trên MSW, chưa có OpenAPI nào để sinh type,
> nên quyết sớm là quyết trong hư không. Ba hướng để M2a-BE cân: commit `openapi.json` vào repo FE
> rồi sinh type tại chỗ · publish npm package từ repo BE · sinh type trong CI của FE từ OpenAPI của
> một backend đang chạy.
>
> Cùng lúc đó M2a-BE phải dựng lại **contract test hai phía** — tách repo cũng cắt mất `make check`
> chạy được cả FE lẫn BE. Hai việc là cùng một đường nối, cân một lần.

### ② Mỗi module ship kèm `fake.py` + MSW handler

Đây là thứ làm song song chạy được **thật**. Người làm M4 không đợi M3: họ code với
`config.fake.FakePublisher`. Frontend không đợi backend: MSW handler trả fixture
viết tay ở `src/lib/msw/handlers.ts`. Fake có test riêng — nên khi bản thật xong, thay một dòng.
Nguồn **kiểu** cho fixture là quyết định treo của M2a-BE, xem ghi chú ở ① bên trên.

**`contracts.py` chứa gì:** `Protocol` (giao diện service) + DTO Pydantic. Không chứa logic, không
import `repo`. Đây là file duy nhất module khác được đọc.

### ③ Sở hữu bảng rõ ràng + cưỡng chế cách ly bằng catalog test

Đây là chỗ khác plan 1a. Bản gốc để M1 tạo **10 bảng `control` + 7 bảng `tenant_data`** — nghĩa là
M1 phải biết trước cột của cả 8 module. Không xây độc lập được.

**Luật mới: M1 sở hữu *cơ chế* cách ly + *neo danh tính*. Mỗi module tự sở hữu bảng của nó.**

- M1 ship **`control.enforce_tenant_isolation('<bảng>')`** — helper DDL bật `ENABLE ROW LEVEL
  SECURITY` + `FORCE ROW LEVEL SECURITY` + policy `tenant_isolation` + grant chuẩn, trong **một** lời
  gọi.
- Module sau tự tạo bảng, **gọi helper đó**.
- **Cổng canh (M1 cổng 6):** một test quét `pg_class` / `pg_policies` — **mọi bảng trong
  `tenant_data` phải có RLS + FORCE + policy `tenant_isolation`**. Module thêm bảng mà quên gọi
  helper ⇒ **CI đỏ ngay**, không phải chờ ai review nhớ ra.

Nhờ vậy bốn điều kiện hỏng-âm-thầm (§5.1 dưới) được viết **một lần** ở M1 và **cưỡng chế mãi mãi**,
thay vì lặp lại 9 lần — mỗi lần một cơ hội sai.

### ④ Migration: mỗi module một dải số, cấm sửa bảng của module khác

| Module | Dải revision |
|---|---|
| M1 | `0001`–`0099` |
| M2a | `0100`–`0149` |
| M2b | `0150`–`0199` |
| M3 | `0200`–`0299` |
| M4 | `0300`–`0399` |
| M5 | `0400`–`0499` |
| M6 | `0500`–`0599` |
| M7 | `0600`–`0699` |
| M8 | `0700`–`0799` |
| M9 | `0800`–`0899` |
| M10 | `0900`–`0999` |

Hai người cùng thêm migration thì chỉ đụng nhau ở **một dòng `down_revision`** — việc cơ học lúc
merge, không phải xung đột logic. Cần cột mới trên bảng của module khác ⇒ **đi qua contract**, không
tự `ALTER`.

Ngoại lệ ghi rõ: **M4 được `ALTER` `tenant_data.projects`/`units`** để thêm ~40/~45 cột còn lại —
đây là phần mở rộng đã hẹn trước, không phải phá luật. M1 chỉ tạo cột lõi đủ chứng minh cách ly.

### ⑤ Nav + route tự khai, shell không phải sửa

TanStack Router file-based: `src/routes/_app/<module>/…` — thêm file là thêm route, không sửa router
trung tâm. Nav: mỗi module export `features/<m>/nav.ts`; shell gom bằng **đúng một mảng ở một file**
(`src/lib/nav-registry.ts`). Thêm module = thêm **một dòng**, conflict tối thiểu.

Nav item khai kèm `requiredActions: string[]` — shell tự ẩn mục người dùng không có quyền. **Ẩn nút
không phải bảo vệ** (PQ_01 §II.2.1): quyền vẫn phải kiểm ở tầng API, ẩn chỉ để đỡ rối mắt.

### ⑥ Test + CI tách theo module, cổng cách ly luôn chạy

```
tests/
├─ isolation/       ← 6 cổng của M1 + catalog test.  CHẠY CHO MỌI PR
├─ api/             ← cổng của vỏ API: mọi route khai action · require() từ chối action lạ
├─ modules/auth/ …
└─ contract/        ← bundle do portal render phải parse được bằng loader thật của agent
```

`make test-module M=m4` chạy riêng một module. CI **không** path-filter job nào — mọi job chạy cho
mọi merge request, và `isolation` là cổng không ai đi vòng được. Module nào cũng merge độc lập được
vì ranh giới module do test canh (§4①), không phải do CI lọc theo đường dẫn.

**Sổ hợp đồng** `docs/contracts/<seam>.md` **trong repo sở hữu seam đó**: mỗi seam liên-module một file — endpoint, DTO, ai sở
hữu, đổi thì ai cần biết. Đổi contract = sửa file đó. Đây là thứ làm *"không ảnh hưởng module khác"*
kiểm chứng được thay vì là lời hứa.

---

## 5. Cách ly đa-tenant — hợp đồng dùng chung

Chi tiết đầy đủ bằng lời thường: **`odyssey-portal-backend/docs/contracts/isolation.md`**. Ở đây chỉ tóm điều mọi module
phải biết.

### 5.1 Ba lớp, mỗi lớp một câu hỏi

| Lớp | Trả lời | Cưỡng chế bởi |
|---|---|---|
| **Hàng** | *"hàng này thuộc workspace nào"* | **Postgres RLS** — tự thêm điều kiện vào mọi query, kể cả query lập trình viên quên |
| **Cột** | *"agent được đọc cột nào"* | **`agent_api` view definer** đọc `control.field_policy_live` |
| **Hành động** | *"người này có được xoá không"* | **Portal API**, kiểm ở mọi endpoint (PQ_01) |

> **Lớp 1 không thay được lớp 3.** Một `Viewer` đọc đúng workspace của mình đi qua RLS sạch sẽ; chặn
> họ xoá dự án là việc của tầng API. Gộp hai thứ này là nhầm lẫn kinh điển, và hậu quả là một lỗ
> hổng không ai thấy khi đọc code.

### 5.2 Hai cách xác định tenant

| | Agent | Portal API |
|---|---|---|
| Nối bằng | `agent_<slug>` — **mỗi workspace một role** | `portal_api` — **một role cho mọi workspace** |
| Tenant lấy từ | **`session_user`** | `SET LOCAL app.tenant_id`, đặt lại **mỗi giao dịch** |
| Tự khai tenant khác? | **Không** — không đổi được `session_user` | Có ⇒ **phải** đặt từ membership đã xác thực, tuyệt đối không từ input client |

```sql
CREATE FUNCTION portal.current_tenant() RETURNS text LANGUAGE sql STABLE AS $$
  SELECT COALESCE(
    NULLIF(substring(session_user FROM '^agent_(.+)$'), ''),
    current_setting('app.tenant_id', true)
  )
$$;
```

Không xác định được ⇒ `NULL` ⇒ `tenant_id = NULL` không bao giờ đúng ⇒ **0 hàng**. Hỏng thì trả
rỗng, không trả nhầm của người khác. **Đó là chiều hỏng đúng.**

### 5.3 Bốn điều kiện — cả bốn hỏng ÂM THẦM nếu sai

| # | Điều kiện | Sai thì sao | Cổng canh |
|---|---|---|---|
| 1 | `FORCE ROW LEVEL SECURITY` trên mọi bảng `tenant_data` | Postgres **không áp** RLS cho role sở hữu bảng ⇒ RLS bật cũng vô nghĩa, **mọi test một-tenant vẫn xanh** | Cổng 3 |
| 2 | `portal_migrator` (DDL) ≠ `portal_api` (runtime); không role runtime nào `BYPASSRLS` | Như trên | Cổng 5 |
| 3 | Agent đọc qua **`agent_api` view definer**, có **zero privilege** trên `tenant_data` | Agent query thẳng bảng gốc ⇒ **bỏ qua toàn bộ gate cột** | Cổng 1 · 2 · 5 |
| 4 | `SET LOCAL` **trong giao dịch tường minh**, không bao giờ `SET` trần | Connection pool: request A đặt `anphu`, trả về pool, request B (`sunrise`) nhận đúng kết nối đó và **kế thừa `anphu`**. Chỉ hiện khi có tải thật | Cổng 4 |

Điều kiện 4 kéo theo **một luật cho mọi module**: mọi truy vấn `tenant_data` phải nằm trong một giao
dịch, đi qua `portal.core.db.tenant_conn()`. **Không có đường đọc ngoài giao dịch.**
(pgbouncer transaction-pooling tương thích `SET LOCAL`, **không** tương thích `SET`.)

### 5.4 Chỗ cố tình KHÔNG linh hoạt

`control.tenants.id` là **một khoá dùng cho bốn việc cùng lúc**:

| Vai | Chỗ dùng |
|---|---|
| Khoá cách ly hàng | policy RLS trên mọi bảng `tenant_data` |
| Danh tính runtime | biến `TENANT_ID` của container agent |
| Đường dẫn cấu hình | `tenants/<id>/LIVE` · `tenants/<id>/bundles/<sha>/` |
| Phạm vi knowledge | tên collection Qdrant |

Đổi mô hình *1 khách = 1 workspace* sang *1 khách = N workspace* là đổi **cả bốn cùng lúc** — đắt
nhất trong toàn bộ thiết kế. Nên chỗ này rắn là **có chủ đích**.

**Hedge rẻ đã đặt sẵn:** nếu về sau một tập đoàn cần 3 workspace, thêm bảng `accounts` **phía trên**
`tenants` (một `account` sở hữu N `tenant`) — thay đổi *thêm vào*, không đánh lại khoá cách ly. Vì
vậy cột `plan` **không** được gắn vào `tenants`; hoá đơn không bao giờ gắn vào khoá cách ly.

⚠️ **Nếu biết trước có khả năng một khách hàng cần nhiều workspace, phải nói trước khi M1 chạy.**

### 5.5 Cái làm refactor về sau rẻ

| Cơ chế | Đổi tốn gì |
|---|---|
| **Một chỗ duy nhất mỗi khái niệm**: `portal.current_tenant()` · `control.enforce_tenant_isolation()` · `tenant_conn()` | Đổi cách xác định tenant = sửa **một hàm SQL** |
| Agent nói chuyện qua **view**, không qua bảng | Refactor bảng thoải mái (đổi tên cột, tách bảng, thêm index) miễn giữ view. Đây chính là lý do view tồn tại |
| **Migration SQL thuần**, mỗi file có header tiếng Việt giải thích *vì sao* | Đọc được, diff được, review được — không phải file Python sinh tự động mà không ai review nổi |
| **6 cổng test** | Thứ khiến refactor **dám làm**: sửa xong chạy test, vỡ thì biết ngay chỗ nào |

### 5.6 ⚠️ Kho thứ tư — Redis của agent, chưa có cơ chế *(bổ sung 2026-08-02)*

§5.1 khai **ba** lớp / ba kho. Khi thiết kế M10 phát hiện kho thứ tư đang chạy mà chưa tài liệu nào
phủ: `santa-hotline-agent` lưu `session:<id>:meta|:customer|:state` — **tên, số điện thoại, ngân
sách, hoàn cảnh khách hàng cuối** — vào một Redis **dùng chung**, key **không mang `tenant_id`**.

Không nhầm với Redis của portal (`sess:<id>`, chỉ `user_id` + `tenant_id`, xem `contracts/auth.md`)
— hai tiến trình khác nhau, hai kho khác nhau.

| | |
|---|---|
| **Ai làm** | Chưa giao. **Không thuộc M10** (M10 chỉ cấp ba credential kia) |
| **Chặn gì** | Đưa **tenant thứ hai** lên production. Phải xong trước **M7** (`conversations`) |
| **Hướng** | Redis ACL user theo tenant + key pattern cưỡng chế `~t:<tenant_id>:*`, credential cấp qua bootstrap của M10 |
| **Đọc ở đâu** | `contracts/isolation.md §11` (luật R01–R04 + cổng 9) · spec M10 §8 |

> **Ai xây M7 · M8 hoặc chạm tới trạng thái hội thoại của agent: đọc `isolation.md §11` trước.**

---

## 6. Cấu trúc repo & quy ước

```
odyssey-portal-backend/            FastAPI · uv · Python 3.13
├─ src/portal/
│  ├─ core/               config · db{pool,session} · auth · errors · logging
│  ├─ modules/m*_*/       router · service · repo · contracts · fake
│  ├─ worker/             tiến trình đọc bảng `jobs` (FOR UPDATE SKIP LOCKED)
│  └─ main.py             gom router
├─ migrations/versions/   op.execute() SQL thuần — KHÔNG ORM, không autogenerate
├─ tests/{unit,isolation,integration,modules,contract}/
├─ pyproject.toml · alembic.ini · Dockerfile
├─ deploy/                docker-compose prod · nginx · runbook ràng buộc production
├─ docker-compose.dev.yml postgres 18 · redis · minio   (dev; prod: Aurora + S3)
├─ docs/{product,contracts,superpowers}/
├─ .gitlab-ci.yml         lint · unit · isolation (không path-filter) · integration
└─ Makefile               dev · migrate · test · test-module M=<module> · lint · worker

odyssey-portal-frontend/           React 18 · Vite · TS strict · Tailwind 4 · shadcn/ui
├─ src/{routes,features,components,lib,i18n,styles}/
├─ tests/ · package.json · Dockerfile · vite.config.ts
├─ public/fonts/          font tự host
├─ docs/{product,superpowers}/
├─ .gitlab-ci.yml         lint · test · build
└─ Makefile               install · dev · test · lint · build · routes
```

**`docs/product/` và spec kiến trúc này có ở CẢ HAI repo** (chốt 2026-07-30): cả FE và BE đều cần
chúng, và mỗi repo clone về phải làm việc được ngay mà không cần repo thứ ba. Nguồn sự thật của
`docs/product/` là repo `odyssey-dashboard-prototype` — sửa ở đó trước, rồi đồng bộ sang cả hai.

History 29 commit của thời monorepo còn ở repo `odyssey-portal-fullstack` (đã archive).

### 6.1 Tech stack — đã chốt

| | |
|---|---|
| Backend | Python 3.13 · `uv` · FastAPI · Pydantic v2 · uvicorn |
| DB | **Aurora PostgreSQL** ở production (chốt 2026-07-30, devops chuyển lúc deploy); dev/test container Postgres bản mới nhất. Sàn cứng ≥ 15. ⚠️ major dev **không** khớp Aurora và **không có gì tự động kiểm** — khoảng hở đã biết, xem `deploy/README.md` §6.1 · **`asyncpg` thô, KHÔNG ORM** · migration **SQL thuần** qua Alembic `op.execute()` |
| Cache | Redis — refresh token · rate limit |
| Kho tệp | **Amazon S3** ở production (chốt 2026-07-30, **thay quyết định #22** — xem ghi chú dưới bảng); dev/test **MinIO** cùng giao thức S3. Client `aioboto3` (async — publish có upload nằm trên đường người dùng chờ). Cách ly bằng **policy theo tiền tố `tenants/<id>/*`**: IAM policy ở prod, policy theo access key ở dev |
| Job | Bảng `jobs` + `FOR UPDATE SKIP LOCKED` + **tiến trình worker riêng**. Không `BackgroundTasks`. Job theo giờ: `cron` gọi một lệnh **ghi một hàng vào `jobs`** |
| Auth | **`PyJWT` + `bcrypt` gọi trực tiếp** — không `passlib`, không `python-jose` |
| Frontend | React 18 · Vite · TS **strict, no `any`** · Tailwind **4** (`@theme`, không `tailwind.config.ts`) · shadcn/ui · TanStack Router + Query v5 · react-hook-form + zod |
| Test | pytest · **testcontainers** (Postgres thật + MinIO thật — **không** chạy trên Aurora/S3 thật) · Vitest + MSW · Playwright cho E2E |

> **Kho tệp đổi từ MinIO tự dựng sang Amazon S3 (chốt 2026-07-30) — thay quyết định #22.**
> #22 chọn MinIO tự dựng **vì lý do pháp lý, không phải kỹ thuật**: quyết định #19 đưa nội dung
> hội thoại (tên, số điện thoại) vào kho tệp, và đặt ngoài Việt Nam là **chuyển dữ liệu cá nhân
> ra nước ngoài (NĐ 13 Điều 25)**. Tự dựng trong nước *làm câu hỏi đó biến mất thay vì phải trả
> lời*; cột "bị loại" của #22 ghi đúng phương án nay được chọn — *"S3/mây"*.
>
> Chuyển sang S3 nghĩa là **câu hỏi đó quay lại và đã được trả lời**: có sign-off pháp lý
> (2026-07-30). Và phạm vi rộng hơn #22 từng cân — `contacts`/`appointments`/`conversations` (M7)
> nằm trong `tenant_data`, nên **Aurora cũng thuộc cùng nghĩa vụ**, không chỉ kho tệp. Hai thứ
> phải giữ cùng nhau về sau: *hồ sơ NĐ 13* và *vùng đặt dữ liệu của cả Aurora lẫn S3*.
>
> Nguyên văn #22 vẫn ở `docs/product/2026-07-28-tenant-portal-control-plane-design.ref.md` — file
> đó là bản copy từ `odyssey-dashboard-prototype` (**nguồn sự thật**) nên không sửa ở hai repo này;
> cập nhật repo prototype là việc riêng. Chi tiết vận hành: `odyssey-portal-backend/deploy/README.md` §6–§7.


**Không dùng — ghi ra để không ai đề xuất lại:** ORM · Celery/RabbitMQ · Next.js · K8s operator ·
kho metrics riêng. Lý do đầy đủ ở `2026-07-28-tenant-portal-control-plane-design.ref.md` §10.3–§10.6.

### 6.2 Quy ước

| | |
|---|---|
| Comment / docstring | **Tiếng Việt** (khớp codebase hiện có). Mỗi file migration có header giải thích *vì sao*, không chỉ *cái gì* |
| Lint BE | ruff, line-length **120**, rules `E,F,W,I,UP,B,SIM` |
| Lint FE | eslint + boundary rule (cấm import chéo `features/*`) · prettier |
| Tiền | **`bigint` VND**, không phải tỷ. Không cột nào tên `*_ty`. Đổi đơn vị làm **ở biên nhập** |
| Thời gian | `timestamptz`, UTC trong DB, đổi múi giờ ở tầng hiển thị |
| i18n | VI/EN, VI mặc định. Prototype dùng cặp `data-l` — portal thật dùng i18n bình thường |
| `match_op` | Đúng **6 toán tử**: `eq · substring · gte · lte · exists · contains`. Là `CHECK` constraint, không phải quy ước |
| Lỗi store | **Fail loud.** Không kế thừa `BaseRepo` nuốt lỗi của CMS — lỗi store nổi lên UI thành lỗi, không thành danh sách rỗng |
| API | `/api/v1/…`, phân trang cursor, lỗi có `code` máy đọc được + `message` người đọc được (PQ_01 §II.4) |

### 6.3 Design token — theo prototype, không theo CMS

```css
@theme {
  --color-ac:  #0d7a5f;   /* accent */
  --color-acs: #e7f2ee;   /* accent soft */
  --color-acd: #0a5e49;   /* accent deep */
  --color-bg:  #f6f5f2;   --color-fg: #14161a;
  --color-border:  #e7e5e0;  --color-border-strong: #d9d7d1;
  --color-muted:   #6f7580;  --color-muted-2: #8a8f98;  --color-muted-3: #a0a4ab;
  --font-sans: 'Be Vietnam Pro', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;   /* mọi con số */
}
```

Font woff2 đã có sẵn ở `odyssey-dashboard-prototype/assets/fonts/` (Be Vietnam Pro 400/500/600/700 +
JetBrains Mono 400/500, có subset Vietnamese) — copy sang, không tải lại từ CDN.

Prototype là **brainstorm, không phải yêu cầu** (quyết định W1). Lấy layout · state model · design
token từ nó; lấy **hành vi** từ tài liệu nghiệp vụ. Ba màn `audit`/`settings`/`onboarding` không có
markup trong bản tải về — dựng từ nghiệp vụ + hook CSS còn lại, **không đợi ảnh thiết kế**.
Chín chỗ prototype lệch thực tế: xem `…control-plane-design.ref.md` §11.

---

## 7. Nguồn sự thật — tra ở đâu

| Câu hỏi | Tra ở |
|---|---|
| Sản phẩm giải quyết vấn đề gì · phạm vi MVP · 7 quyết định sản phẩm | `docs/product/2026-07-28-phan-bien-prototype-va-dinh-huong-san-pham.md` §19–§22 |
| Gói việc · phụ thuộc · nợ kỹ thuật · việc **không** làm ở MVP | `docs/product/2026-07-28-work-packages-mvp.md` |
| Vai trò · 13 nhóm hành động · quyền hỗ trợ có hạn · mã lỗi | `docs/product/2026-07-29-pq01-phan-quyen.md` |
| Quan hệ Dashboard · Backend · Agent · business rule | `docs/product/2026-07-29-ht01-quan-he-dashboard-backend-agent.md` |
| 22 quyết định kỹ thuật · schema · bundle · publish · suy biến · tech stack | `docs/product/2026-07-28-tenant-portal-control-plane-design.ref.md` |
| SQL chi tiết của nền cách ly · ba sửa lỗi C1/C2/C3 | `docs/product/2026-07-28-slice-1a.ref.md` |
| Layout · state model · design token · 18 màn | `odyssey-dashboard-prototype/design/Tenant Portal.dc.html` (chỉ đọc) |
| Agent thật — provider Protocol · loader · định dạng bundle | `/home/dungnd/Dungnd/dev/santa-hotline-agent` (chỉ đọc) |

Đặc tả `DL_01` · `DL_02` · `AG_01` · `KB_01` nằm trên Notion — **chưa có trong repo**. Module cần
chúng (M4 · M5 · M6) phải lấy về trước khi viết spec riêng.

---

## 8. Ngoài phạm vi portal

| | Ở đâu |
|---|---|
| Sửa agent thật (gói G): provider `portal` · bundle loader · facade multi-version · ghi `conversations`/`transcript` · ghi nhận token | Repo `santa-hotline-agent` |
| Vertical Tài chính (màn `finance`) | Sau MVP — dự án riêng |
| Gói cước · thanh toán (màn `billing`) | Sau MVP. MVP chỉ **ghi nhận** token ở M8 |
| Bộ kiểm thử hồi quy · CSAT (màn `quality`) | Sau MVP |
| Live-chat tiếp quản · Zalo OA · CRM · webhook · crawl web | Sau MVP |
| 2FA · SSO · vai trò tuỳ chỉnh · yêu cầu xuất/xoá dữ liệu của khách | Sau MVP (PQ_01 §III) |
| Sao lưu kho tệp + diễn tập phục hồi (A21) — với S3 là versioning + lifecycle, nhưng **nghĩa vụ không chuyển sang AWS** | **Hạ tầng, không phải code** — nhưng là việc bắt buộc: kho tệp mang cả retention 6 tháng lẫn khả năng agent boot khi Postgres chết. Mất nó là vỡ hai lời hứa cùng lúc |
| Bốn việc không phải của dev: **N1** bảng phân loại *Kết quả* · **N2** định nghĩa "đủ dữ liệu cho agent" · **N3** ba biến thể persona | BA / sales / người sở hữu nội dung. **N1 chặn M7 · N2 chặn M4 · N3 chặn M5** |

---

## 9. Rủi ro

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| **RLS bật nhưng không có hiệu lực** — chủ bảng bỏ qua RLS · view sai chế độ · `SET` rò qua pool. Cả ba **không có triệu chứng** | Cao | §5.3 bốn điều kiện + cổng 1·3·4·5. Cổng 3 và 4 là hai cổng hay bị bỏ nhất |
| **Module sau thêm bảng mà quên bật cách ly** | Cao | Catalog test (cổng 6) quét `pg_class`/`pg_policies` — chạy cho **mọi** PR |
| **Cách ly kho tệp** — một lỗi ghép đường dẫn là workspace A đọc được bản ghi hội thoại của B. Postgres không cho chuyện đó xảy ra; kho tệp thì có thể | Cao | Cổng 7 ở M3: MinIO thật trong container, credential của A `GET` `tenants/B/*` phải bị **từ chối**. ⚠️ Cổng này chứng minh **cơ chế**, không chứng minh IAM policy production viết đúng — hai cú pháp khác nhau |
| **Cách ly knowledge** — filter thay vì cấu trúc | Cao | Cổng RAG ở M6: query của A trả **0 chunk** của B. Collection riêng mỗi tenant, tên sinh trong code |
| **Import chéo module** làm mất tính độc lập âm thầm | Trung bình | Test AST ở ①, eslint boundary ở FE. Vỡ luật = CI đỏ, không phải review bắt |
| **Seam bundle mục** giữa portal và agent | Trung bình | Contract test: bundle portal render phải parse được bằng `loader.py` thật của agent, fixture là **file** (hai repo có thể khác phiên bản Python) |
| **N1 · N2 · N3 chưa có tên người và ngày** | Trung bình | Chúng chặn M7 · M4 · M5. M1 → M3 không bị chặn, nên chạy trước và đòi song song |
| **M4 bị đánh giá thấp** — nó là một CMS, không phải hai cái form | Trung bình | Ước lượng ~1/4 công sức MVP, nên 2 người |

---

## 10. Định nghĩa "xong" cho spec tổng này

- [ ] Mỗi module có một spec riêng ở `docs/superpowers/specs/`, **mở đầu bằng bảng đối chiếu §2**
- [ ] Mỗi spec module tự chứa: contract vào/ra · danh sách file · cổng test · định nghĩa "xong" —
      để người khác nhận là code được, không phải đi hỏi lại
- [ ] `odyssey-portal-backend/docs/contracts/isolation.md` giải thích cách ly bằng lời thường, không giả định người đọc
      biết RLS là gì
- [ ] Sáu cơ chế §4 có cơ chế cưỡng chế (test / lint), không chỉ là quy ước viết ra
