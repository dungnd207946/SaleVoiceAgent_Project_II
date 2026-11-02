# M3 — Config store · Publish · Bundle (thiết kế)

> **Ngày:** 2026-07-31 · **Trạng thái:** chờ duyệt · **Repo:** `odyssey-portal-backend` (+ hợp đồng bàn giao cho `santa-hotline-agent`)
> **Chặn bởi:** M1 (xong) · M2a-BE (xong) · **Chặn:** M5 (Agent Studio) · M6 (KB)
> **Nguồn:** spec tổng §3 (M3) · `tenant-portal-control-plane-design.ref.md` §4.1, §5.5, quyết định #3·#9·#11·#22 · `ht01-quan-he-dashboard-backend-agent.md` §II.2.1

---

## 0. Spec này làm gì, không làm gì

Xây **đường sống** từ ô nhập trên portal tới cấu hình mà agent đọc được: `config_drafts` →
`config_versions` → bundle bất biến trong kho tệp → con trỏ `LIVE` → agent pull.

**Trong phạm vi:** config store có version · job `publish` · render bundle tất định ·
con trỏ `LIVE` · rollback · bảng `deployments` · ba trạng thái hiệu lực trên UI ·
hợp đồng bundle thành văn bản · agent giả chứng minh đường ống.

**Ngoài phạm vi — và vì sao:**

| Hoãn | Vì sao |
|---|---|
| `field_policy_live` → `extras.toml` | Bảng đã có từ M1 nhưng cột đầy đủ của `projects`/`units` thuộc M4. Render extras bây giờ là render một bảng gần rỗng. Thêm sau **không** đổi hình dạng bundle — chỉ thêm một file. |
| Provisioning tự động (§6.5) | Demo chạy một pod dựng tay. `deployments` có bảng, ghi bằng tay hoặc seed. |
| S3 cho media / bản ghi thoại | Thuộc M7·M8. M3 chỉ dùng kho tệp cho bundle. |
| Diff hai version trên UI | Sau MVP (quyết định #9 chỉ yêu cầu `vN`). |

**Phía agent (Gói G) không thuộc spec này.** Spec này giao lại **hợp đồng** `docs/contracts/bundle.md`
+ agent giả làm spec sống. Người nhận Gói G code theo hợp đồng, không đoán.

---

## 1. Kiến trúc

```
src/portal/modules/config/
  router.py      6 endpoint, mỗi cái khai action (cổng 1 của M2a)
  service.py     nghiệp vụ + tinh_trang_thai() — hàm thuần
  repo.py        SQL asyncpg thô
  contracts.py   pydantic v2 — hình dạng payload
  bundle.py      render() — HÀM THUẦN, payload -> dict{path: bytes}
  jobs.py        register("publish", handle_publish)
  fake.py        dữ liệu giả cho FE (cơ chế ② của spec tổng)
src/portal/core/storage.py   client aioboto3 dùng chung, tiền tố tenants/<id>/*
scripts/agent_gia.py         đóng vai pod: poll LIVE, pull, verify, heartbeat
docs/contracts/bundle.md     hợp đồng bàn giao Gói G
```

**Một nguyên tắc chi phối cả module:** `bundle.py` **không chạm I/O**. Nó nhận `payload` trả về
`dict{đường_dẫn: bytes}`. Upload là việc của `service.py`. Nhờ vậy toàn bộ phần dễ sai nhất —
nội dung bundle — test được bằng unit test không cần MinIO.

### Migration `0200_config_store.py`

| Bảng | Cột | Ghi chú |
|---|---|---|
| `control.config_drafts` | `tenant_id` PK · `payload jsonb` · `schema_version int` · `updated_at` · `updated_by` | Đúng **một** nháp mỗi tenant |
| `control.config_versions` | `tenant_id` · `version int` · `payload jsonb` · `bundle_sha text` · `note` · `published_at` · `published_by` | `UNIQUE(tenant_id, version)` · **bất biến** |
| `control.deployments` | `id` · `tenant_id` · `kind ('chat'\|'voice')` · `endpoint` · `provisioned_at` | Đóng nốt chỗ M1 để trống |

Đồng thời gắn FK `agent_heartbeats.deployment_id → deployments.id` — M1 cố ý để trống chỗ này
([`0007_agent_heartbeats.py:11`](../../../migrations/versions/0007_agent_heartbeats.py)).

**Bất biến cưỡng chế bằng Postgres, không bằng nội quy:** `REVOKE UPDATE, DELETE ON config_versions
FROM portal_api`. Một hàng đã publish thì tầng ứng dụng **không có đường** sửa. Rollback không sửa
hàng nào — nó ghi con trỏ.

---

## 2. Hình dạng `payload`

**Luật một câu: `payload` chứa đúng những gì tenant đổi được. Không hơn.**

Rào chắn (6 cái) và khung `RULES.md` là **template của platform** — chúng vào bundle lúc render,
không đi qua `payload`. Để chúng trong `payload` là mở đường cho tenant sửa thứ đáng lẽ khoá, và
làm mọi bản nháp phình lên vì chép lại thứ không đổi.

```jsonc
{
  "schema_version": 1,
  "brand":   { "name": "An Phú Land", "short_name": "An Phú", "vertical": "realestate" },
  "persona": { "agent_name": "...", "tone": "than_thien|chuyen_nghiep|nhiet_tinh", ... },
  "tools":   { "enabled": ["kb_search", "booking", ...] }   // 12 tool
}
```

**Không có `kb.collection` trong payload.** Tên collection Qdrant suy ra từ `tenant_id` lúc render —
đó là một trong bốn vai của `control.tenants.id` (spec tổng §5.4). Đưa nó vào payload là cho tenant
sửa được khoá cách ly knowledge của chính mình. M6 chỉ dùng lại quy tắc suy ra ấy.

**Danh sách đầy đủ 8 biến `persona` do M5 chốt** (nguồn AG_01). M3 chỉ cần biết `persona` là một
object có `schema_version` bao ngoài; thêm biến thứ 9 về sau **không** đổi gì trong M3 vì
`bundle.render()` đọc theo tên biến mà template khai, không theo danh sách cứng. Trong lúc chờ M5,
M3 dùng đúng hai biến đã biết chắc — `agent_name` và `tone` — đủ để chứng minh đường ống.

`schema_version` có mặt **từ hàng đầu tiên**. Đổi hình dạng payload về sau mà không có nó nghĩa là
phải đoán bản cũ theo hình dạng — và các hàng `config_versions` là bất biến, không migrate được.

`contracts.py` là **nguồn sự thật duy nhất** của hình dạng này. M5 dựng form từ đúng model đó.

---

## 3. Hợp đồng bundle

```
tenants/<id>/bundles/<sha256>/
  manifest.toml        data_source="portal" · [tools].enabled · [brand] · vertical · kb.collection
  persona/
    SOUL.md            markdown ĐÃ RENDER — không còn jinja
    RULES.md           template platform + 6 rào chắn + tool catalog SINH từ [tools].enabled
    PROMPT_TEMPLATE.md
    CUSTOMER_PROFILE.md
    config.json
tenants/<id>/LIVE      {"version": 12, "bundle": "sha256:..."}
```

**Render đúng một chỗ — portal.** Agent hiện render jinja lần nữa lúc boot (`load_agent_def`). Hai
chỗ cùng render một template là cách chắc nhất để portal và agent hiểu khác nhau. Bundle mang
markdown đã render xong; Gói G bỏ lượt render thứ hai. Ghi rõ trong `bundle.md`.

**Tool catalog sinh từ `[tools].enabled`,** không phải 15 dòng text tĩnh như `RULES.md` hiện tại.
Không làm vậy thì tắt `booking` xong agent mất schema nhưng prompt vẫn dạy gọi → agent hứa đặt lịch
rồi không tạo lịch nào. Đây là một trong ba khoản nợ đã ghi sổ ở gói C.

**Không có `{{ brand.* }}` hardcode.** `RULES.md` hiện hardcode "NobleX" ở 4 chỗ. Template dùng ở
M3 phải trung tính; agent của An Phú Land không được tự xưng nhân viên NobleX.

### Render tất định — tính chất phải giữ

Cùng `payload` → cùng `sha256`, luôn luôn. Nghĩa là **cấm** trong bundle: timestamp, UUID, thứ tự
key phụ thuộc dict, đường dẫn tuyệt đối, số phiên bản build. Thiếu tính chất này thì publish hai
lần không đổi gì vẫn sinh sha mới, và mất luôn cách kiểm "bundle này đúng do payload kia sinh ra".

---

## 4. Luồng publish

```
PUT  /config/draft      ghi config_drafts                      → Bản nháp — chưa ai thấy
POST /config/publish    INSERT jobs(kind='publish') → job_id   → Đang áp dụng
   worker:
     1. đọc draft.payload  (validate lại bằng contracts.py — không tin hàng cũ trong DB)
     2. bundle.render(payload) -> dict{path: bytes}          hàm thuần
     3. sha256 trên nội dung đã sắp xếp theo đường dẫn
     4. upload tenants/<id>/bundles/<sha>/*                   file trước
     5. INSERT config_versions(version = max+1, bundle_sha)
     6. PUT tenants/<id>/LIVE                                 CON TRỎ GHI CUỐI CÙNG
   agent (Gói G): poll LIVE mỗi 20s → pull → verify sha → cache đĩa → heartbeat
```

**Vì sao con trỏ ghi cuối:** `PUT` một object là nguyên tử ở S3. Upload hỏng giữa chừng thì `LIVE`
vẫn trỏ bản cũ — agent không bao giờ thấy bundle nửa vời. Không cần transaction hai pha, không cần
dọn rác gấp (bundle mồ côi vô hại, dọn bằng job định kỳ sau).

**Rollback = ghi lại `LIVE` trỏ sha cũ.** Không render lại, không sinh version mới. Bundle cũ còn
nguyên trong kho vì content-addressed.

**Publish đi qua job, không đồng bộ.** Được audit, retry, và dùng lại đúng khuôn `jobs` của M1
(`kind` là `text` tự do — không cần migration). Người dùng đằng nào cũng phải chờ và theo dõi tới
lúc heartbeat xác nhận, nên gắn nó vào một HTTP request không đổi được trải nghiệm.

---

## 5. Ba trạng thái hiệu lực

HT01 §II.2.1 nói đây là phần quan trọng nhất của giao diện: *nói "Đã lưu" cho một thay đổi persona
chưa xuất bản là nói dối người dùng.*

```python
def tinh_trang_thai(draft, version_moi_nhat, live, heartbeat) -> TrangThai:
    """Hàm THUẦN. Không I/O. Toàn bộ logic ba bậc nằm ở đây và chỉ ở đây."""
```

Endpoint trả **hai thứ tách bạch** — AG_01 §II.3 phân biệt chúng và UI cần cả hai:

**`trang_thai_agent`** — chip 4 giá trị, suy ra từ agent đang chạy, **không phải cờ trong portal**:

| Điều kiện | Giá trị | Chip |
|---|---|---|
| chưa có heartbeat nào | `dang_cap` | Đang cấp |
| `heartbeat.running_version != live.version` | `dang_ap_dung` | Đang áp dụng |
| bằng nhau | `san_sang` | Sẵn sàng |
| `heartbeat.last_seen_at` quá 60s | `mat_ket_noi` | Mất kết nối |

**`co_ban_nhap`** — boolean: `draft.updated_at > version.published_at`. Đây là trạng thái của
**form**, không phải của agent; gộp nó vào chip là trộn hai thứ khác bản chất. Có nháp mà agent vẫn
Sẵn sàng là tình huống bình thường — agent đang phục vụ tốt bản cũ.

Để là hàm thuần vì đây là chỗ **dễ sai mà không ai thấy**: sai một nhánh thì UI nói dối, và không có
test nào đỏ nếu logic nằm rải trong router. Một hàm, một bảng test theo bảng trên.

---

## 6. API

| Method | Đường dẫn | Action | Trả về |
|---|---|---|---|
| GET | `/api/v1/config/draft` | `agent_config.read` | payload + `schema_version` |
| PUT | `/api/v1/config/draft` | `agent_config.write` | payload đã ghi |
| GET | `/api/v1/config/status` | `agent_config.read` | trạng thái §5 + `version` |
| POST | `/api/v1/config/publish` | `agent_config.publish` | `{job_id}` |
| GET | `/api/v1/config/versions` | `agent_config.read` | danh sách `vN` (cursor) |
| POST | `/api/v1/config/versions/{v}/rollback` | `agent_config.publish` | `{job_id}` |

Ba action này **đã có** trong `contracts/actions.json` từ M2a — không thêm action mới, không đụng
cổng parity. Mọi route khai action, giữ cổng 1 xanh.

---

## 7. Agent giả

`scripts/agent_gia.py` — một tiến trình ~100 dòng: đọc `TENANT_ID` → poll `LIVE` mỗi 20s → pull
bundle → **verify sha256** → ghi `agent_heartbeats(running_version, bundle_sha, last_seen_at)`.

Nó phục vụ ba việc cùng lúc: chứng minh đường ống thông trước khi Gói G bắt đầu · làm **spec sống**
cho người nhận Gói G (đọc 100 dòng nhanh hơn đọc 400 dòng văn bản) · là fixture cho cổng test 6.

Nó **không** giả lập LLM, không giả lập tool. Nó chỉ làm đúng phần hợp đồng M3 quan tâm.

---

## 8. Cổng test

Đánh số tiếp: M1 có 7 cổng cách ly, M2a có 11. M3 thêm 7.

| # | Cổng | Đỏ khi nào |
|---|---|---|
| 1 | **Render tất định** — cùng payload render 2 lần → cùng sha, byte-for-byte | Lọt timestamp/UUID vào bundle |
| 2 | **Con trỏ ghi cuối** — mô phỏng upload hỏng ở bước 4 → `LIVE` không đổi | Ai đó đảo thứ tự bước 5·6 |
| 3 | **`config_versions` bất biến** — `UPDATE`/`DELETE` bằng `portal_api` bị Postgres từ chối | Ai đó cấp lại quyền |
| 4 | **Rollback không render lại** — sha sau rollback bằng sha version cũ | Rollback đi nhầm đường publish |
| 5 | **Cách ly tiền tố** — key của tenant A không đọc được `tenants/B/*` | Policy tiền tố sai |
| 6 | **Đầu-cuối với agent giả** — publish → heartbeat báo đúng `running_version` | Bất kỳ mắt xích nào đứt |

Cổng 6 **không** chờ đủ chu kỳ 20 giây: agent giả nhận `--poll-once` để test kích một vòng rồi
kiểm. Test ngủ 20 giây là test chậm và chớp tắt; chu kỳ 20s là quyết định vận hành, không phải thứ
cần chứng minh lại ở CI.
| 7 | **Parity hợp đồng** — cây file `bundle.render()` sinh ra khớp bảng trong `bundle.md` | Code và hợp đồng trôi khỏi nhau |

Cổng 7 dùng lại đúng nếp `contracts/` của M2a: **hợp đồng là file, test so với file**, không so với
trí nhớ.

---

## 9. Việc kéo theo

- Thêm `aioboto3` vào `pyproject.toml` (chưa có). MinIO đã có sẵn trong `docker-compose.dev.yml`.
- Tạo access key theo tenant + policy tiền tố ở `make dev-seed` — cổng 5 cần nó.
- `make agent-gia TENANT=<id>` để chạy agent giả.

## 10. Bàn giao Gói G

Ngay khi spec này được duyệt, gửi người nhận Gói G: `docs/contracts/bundle.md` · `scripts/agent_gia.py` ·
mục §3 và §4 của tài liệu này. Họ chạy song song được với M5·M6 — nếu đợi tới lúc M6 xong mới bàn
giao thì Gói G thành nút cổ chai cuối cùng của cả đợt.
