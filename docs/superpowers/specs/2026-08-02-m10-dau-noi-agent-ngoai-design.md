# M10 — Đấu nối agent ngoài (Agent Enrollment) (thiết kế)

> **Ngày:** 2026-08-02 · **Trạng thái:** chờ duyệt · **Repo:** `odyssey-portal-backend` + `santa-hotline-agent`
> **Chặn bởi:** M1 (role · `agent_api` · heartbeats) · M3 (`deployments` · bundle · con trỏ LIVE) · M6 (`ten_collection`)
> **Chặn:** M9 bước 3 (*"chat thử ngay"* cần pod thật) · demo end-to-end với agent thật
> **Thứ tự đề nghị: sau M4a.** Hai module không chặn nhau, nhưng bootstrap trước M4a thì pod đọc
> được một bảng gần rỗng với `field_policy_live` chưa seed ⇒ mọi cột gated về `NULL`, rồi phải sửa
> view + seed và chạy lại cổng 1. Xem M4a §11 và §5.1 của spec này.
> **Nguồn kỹ thuật:** `docs/contracts/isolation.md` · `docs/contracts/bundle.md` · spec tổng §5.4 · HT_01 §2.3, §2.4 · M4a §6.2

---

## 0. Spec này làm gì, không làm gì

Xây **đường cấp danh tính và credential** cho pod agent chạy ngoài cụm portal: từ lúc admin nền
tảng bấm *"Tạo deployment"* tới lúc pod tự lấy được `tenant_id` + DSN Postgres + khoá kho tệp +
tên collection Qdrant, rồi chạy đúng ba lớp cách ly đã có.

**Trong phạm vi:** bảng `agent_keys` · bảng `agent_credentials` · suy dẫn bí mật tất định ·
`POST /agent/v1/bootstrap` · 5 endpoint quản trị (cấp phát · phát khoá · thu hồi · xoay bí mật ·
liệt kê) · rate-limit · nhật ký · `agent_gia.py` chuyển sang bootstrap · **hợp đồng bổ sung cho
Gói G**.

**Ngoài phạm vi — và vì sao:**

| Hoãn | Vì sao |
|---|---|
| **Cách ly Redis của agent** | Kho thứ tư, chưa có cơ chế nào. Phạm vi khác hẳn (ACL Redis, đổi key prefix ở repo agent), và nó chặn M7 chứ không chặn M10. Tách thành phần riêng — xem §8 và ghi chú đã cắm vào `isolation.md §11` + spec tổng §5.6 |
| **Đường GHI của agent** (booking · lead · transcript) | Bảng chưa tồn tại (M4/M7/M8). `AGENT_WRITABLE_TENANT_DATA_TABLES` đang rỗng đúng chủ ý. M10 chỉ mở đường **đọc** + ghi heartbeat |
| **Provisioning tự động pod** (K8s/compose) | Việc của ops. M10 sinh credential và api_key; ai nạp vào pod là bước ngoài hệ |
| **UI quản trị deployment** | M10 ship API + `fake.py`. Màn hình thuộc M9 bước 3 hoặc màn admin nền tảng, chưa chốt chủ |

**Phía agent không thuộc spec này.** §7 là **hợp đồng bàn giao** — bổ sung cho
`docs/contracts/bundle.md`, không thay thế nó.

---

## 1. Vấn đề: mảnh còn thiếu, không phải kiến trúc mới

M1 · M3 · M6 đã xây xong **ba lớp cách ly cho agent**, và cả ba đều hoạt động:

| Kho | Cơ chế cách ly | Nguồn |
|---|---|---|
| Postgres | role `agent_<slug>` + RLS + view definer `agent_api.*` | `0005_agent_api.py` |
| Kho tệp | access key riêng + policy tiền tố `tenants/<id>/*` | `storage.chinh_sach_tien_to()` |
| Qdrant | collection riêng `kb_<tenant_id>` | `ten_tai_nguyen.ten_collection()` |

**Chưa có gì cấp phát và giao ba credential đó cho pod.** M3 §0 ghi thẳng: *"`deployments` có bảng,
ghi bằng tay hoặc seed"*. `seed_kho_tep.py:60` dùng `MAT_KHAU_DEV` cố định cho mọi tenant — đủ cho
dev, không dùng được ở production. Không có bảng nào ghi *"pod này thuộc tenant nào"*, không có
đường thu hồi, không có đường xoay khoá.

M10 lấp đúng khoảng trống đó. **Không xoá, không sửa, không thay thế cơ chế nào của M1/M3/M6.**

### 1.1 Vì sao `api_key` KHÔNG được làm data-plane token

Thiết kế nháp ban đầu là: *"agent gửi một api_key, portal xác định tenant, rồi agent được truy cập
tất cả dữ liệu của tenant đó"*. Vế sau không thực hiện được như mô tả, vì hai lý do:

1. **Postgres, Qdrant, MinIO không biết api_key của portal là gì.** Muốn api_key "mở" được chúng thì
   portal phải làm proxy cho cả ba — tức bỏ không dùng `agent_api` view + RLS + policy tiền tố đã
   xây. Đổi một cơ chế Postgres cưỡng chế lấy một cơ chế do code portal cưỡng chế.
2. **Nếu thay vào đó pod giữ credential "mở tất cả" rồi tự lọc theo tenant vừa xác định** — cách ly
   tụt xuống thành kỷ luật viết code. Đó đúng mô hình mà `isolation.md §3` và `M6 BR03` đã bác bỏ
   thành văn bản: *"một chỗ quên là rò dữ liệu giữa hai khách hàng, và lỗi đó im lặng"*.

**Luật một câu của spec này:**

> `api_key` nói **"tôi là ai"**. Credential nói **"tôi được làm gì"**. Không gộp hai vai.

api_key là **bootstrap token**: dùng lúc pod khởi động (và lúc làm mới), đổi lấy bộ credential đã bị
hạ tầng giới hạn sẵn. Nó mở được **đúng một** thứ — chính bộ credential của tenant nó thuộc về.

### 1.2 Bán kính thiệt hại

| Rò cái gì | Hậu quả | Xử lý |
|---|---|---|
| `api_key` | Kẻ cầm key lấy được credential của **một** tenant | `DELETE /admin/keys/{id}` — hiệu lực tức thì cho lần bootstrap sau |
| Credential (DSN · S3 · collection) | Vẫn bị RLS + policy tiền tố + collection chặn ở **đúng một** tenant | Xoay bí mật (§3) — cả hai pod tự lấy bản mới |
| `AGENT_MASTER_KEY` | Suy được credential của **mọi** tenant | Sự cố nghiêm trọng. Xem §6 — đây là lý do có cổng test 6 |

---

## 2. Kiến trúc

```
① Admin nền tảng: POST /admin/deployments {tenant_id, kind}
     ├─ INSERT control.deployments
     ├─ cấp phát (idempotent): create_agent_role() · MinIO user_add + policy_set · tạo kb_<id>
     ├─ INSERT control.agent_keys  (lưu sha256; plaintext trả về ĐÚNG MỘT LẦN)
     └─ audit_log

② Ops nạp vào pod ĐÚNG HAI biến:
     PORTAL_URL=https://portal.internal
     AGENT_API_KEY=ody_ag_<43 ký tự base64url>

③ Pod khởi động → POST /agent/v1/bootstrap   (Authorization: Bearer ody_ag_…)
     portal: sha256(key) → agent_keys → deployments → tenant_id
     kiểm: khoá chưa thu hồi · tenant chưa suspended
     trả:  tenant_id · deployment_id · kind · postgres_dsn · storage{key,secret,prefix,endpoint,bucket}
           · kb{collection, url} · live_url · expires_at
     ghi:  agent_keys.last_used_at · audit_log

④ Pod chạy — KHÔNG đi qua portal nữa:
     Postgres   agent_api.units · agent_api.projects        ← lớp 1 + lớp 2
     Qdrant     kb_<tenant_id>                              ← M6
     Kho tệp    tenants/<tenant_id>/*                       ← M3
     poll LIVE mỗi 20s · verify sha256 · nạp nguyên khối    ← bundle.md §1
     heartbeat mỗi 20s vào control.agent_heartbeats         ← bundle.md §5

⑤ Trước khi expires_at → gọi lại ③
```

**Điểm khác duy nhất về nguyên tắc so với hôm nay:** danh tính pod hiện là `TENANT_ID` do ops gõ vào
env; sau M10 nó do portal trả về từ hàng `deployments` khớp với api_key. `bundle.md §1` vẫn đúng
nguyên văn — `tenant_id` **vẫn** là cấu hình lúc khởi động container, **vẫn không** đến từ tham số
request. M6 BR02 không bị vi phạm.

### 2.1 Bootstrap là endpoint duy nhất trả mật khẩu qua HTTP — và cái giá của nó

Nói thẳng để không ai tưởng đã miễn phí. Bù lại bằng năm điều kiện, **cả năm, không phải một**:

| Điều kiện | Cưỡng chế ở đâu |
|---|---|
| Bắt buộc TLS | Reverse proxy; app từ chối khởi động nếu `not tls_enabled` ở production |
| Chỉ nghe trên mạng nội bộ | Deploy — `/agent/v1/*` không expose ra internet |
| Rate-limit theo `key_sha256` | Redis của portal, 10 lần / 5 phút. Vượt ⇒ `429` |
| Ghi `audit_log` mỗi lần gọi | `service.py`, không phải middleware — để nó không im lặng biến mất |
| TTL ngắn, mặc định 1 giờ | `bootstrap_ttl_seconds` |

Bootstrap **không nhận cookie phiên**. Route khai `require(None, ly_do="xác thực bằng api_key của
deployment, không phải phiên người dùng")` — cổng 1 của M2a bắt route thiếu khai.

---

## 3. Bí mật suy dẫn tất định — vì sao không lưu mật khẩu

`portal.current_tenant()` (`0001_schemas_and_functions.py:41`) parse tenant **từ tên role**:

```sql
substring(session_user::text from '^agent_(.+)$')
```

Tên role **chính là** danh tính tenant. Hệ quả: mỗi tenant có **đúng một** role `agent_<slug>`, dùng
chung cho cả pod `chat` lẫn pod `voice`. Không tách role theo deployment được — `agent_anphu_chat`
sẽ parse ra tenant `anphu_chat`, một tenant không tồn tại.

**Điều này loại bỏ phương án "đổi mật khẩu mỗi lần bootstrap":** pod `voice` khởi động lại sẽ đổi
mật khẩu và đá văng pod `chat` ở lần nối kế tiếp.

Ba cách còn lại, và lý do chọn cách thứ ba:

| Cách | Vì sao không / có |
|---|---|
| Lưu mật khẩu thô trong `control` | Một `SELECT` là lộ mọi tenant. Không |
| Mã hoá tại chỗ (Fernet) rồi giải mã lúc bootstrap | Vẫn là bí mật ở trạng thái nghỉ, cộng thêm một khoá phải quản. Không hơn gì cách 3 nhưng phức tạp hơn |
| **Suy dẫn tất định từ một khoá gốc** | Không có bí mật nào nằm trong DB. Hai pod suy ra **cùng** một giá trị. Xoay khoá = tăng một số nguyên |

```python
# src/portal/modules/enrollment/bi_mat.py — HÀM THUẦN, không I/O
def dan_xuat(loai: str, tenant_id: str, version: int, master: bytes) -> str:
    """loai ∈ {"pg", "s3"}. Trả chuỗi base64url 43 ký tự."""
    thong_diep = f"{loai}:{tenant_id}:{version}".encode()
    return base64.urlsafe_b64encode(hmac.new(master, thong_diep, hashlib.sha256).digest()).decode().rstrip("=")
```

Portal chỉ lưu `version` — một `int` trong `control.agent_credentials`. Xoay bí mật:

```
version += 1  →  ALTER ROLE agent_<slug> PASSWORD <mới>  →  MinioAdmin.user_add(khoa, <mới>)
```

Cả hai pod lấy bản mới ở lần làm mới TTL kế tiếp. Kết nối Postgres đang mở **không** bị ngắt — chỉ
lần nối mới mới cần mật khẩu mới, nên xoay khoá không gây gián đoạn cuộc gọi đang chạy.

`bi_mat.py` là **hàm thuần**, đúng nếp `bundle.render()` (M3) và `kb/parse.py` (M6): phần dễ sai
nhất, test được không cần Postgres, MinIO hay Qdrant.

> **`AGENT_MASTER_KEY` là bí mật hạng cao nhất trong hệ.** Nó không nằm trong repo, không nằm trong
> `.env` được commit, không có giá trị mặc định. App **từ chối khởi động** ở production nếu nó rỗng
> hoặc ngắn hơn 32 byte — không phải cảnh báo, là `SystemExit`. Đổi nó = mọi tenant phải xoay bí mật.

---

## 4. Kiến trúc code

```
src/portal/core/khoa_api.py       sinh_khoa() · bam_khoa() · gioi_han_nhip()   ← DÙNG CHUNG với M8 (§9)
src/portal/modules/enrollment/
  bi_mat.py      dan_xuat()                                    ← HÀM THUẦN, riêng M10
  contracts.py   pydantic v2 — BootstrapOut · DeploymentIn/Out · KhoaOut
  repo.py        SQL asyncpg thô
  service.py     cap_phat() · xac_thuc_khoa() · xoay_bi_mat() · thu_hoi()
  router.py      6 endpoint, mỗi cái khai action
  fake.py        dữ liệu giả cho FE (cơ chế ② của spec tổng)
migrations/versions/0900_agent_enrollment.py
scripts/agent_gia.py                    ← sửa: bootstrap thay vì đọc env
docs/contracts/dau-noi-agent.md         ← hợp đồng bàn giao Gói G (§7)
```

**Không có `ha_tang.py`.** Ba client hạ tầng đã có chủ và M10 **dùng lại**, không bọc thêm một lớp:
`core/storage.py` (`KhoTep`, `chinh_sach_tien_to`) từ M3 · `modules/kb/kho_tri_thuc.py` +
`core/ten_tai_nguyen.ten_collection()` từ M6 · `MinioAdmin` theo đúng nếp `scripts/seed_kho_tep.py`.
Thêm một lớp bọc là tạo chủ thứ hai cho cùng một khái niệm — đúng cái §5.5 spec tổng cảnh báo.

> **Ranh giới module:** `ten_collection()` nằm ở `core/ten_tai_nguyen.py` chứ không ở `modules/kb/`
> chính vì lý do này (commit `c4a1de9`, *"cổng ranh giới module bắt đúng"*). M10 gọi nó trực tiếp,
> không import ruột của `kb`.

**Vì sao module mới chứ không mở rộng `config`:** M3 sở hữu `deployments` như một bảng *hồ sơ triển
khai*. M10 thêm **xác thực và cấp phát** — nghiệp vụ khác, vòng đời khác, người gọi khác (admin nền
tảng, không phải người dùng workspace). Nhét vào `config` là hai chủ cho một module, đúng cái lỗi mà
M5 §9 đã tránh khi từ chối tạo module mới cho payload.

`enrollment` **đọc** `control.deployments` và **thêm FK** vào nó — không `ALTER` cột nào của M3, đúng
luật §4 của spec tổng (dải migration `0900`–`0999`).

### Migration `0900_agent_enrollment.py`

| Bảng | Cột | Ghi chú |
|---|---|---|
| `control.agent_keys` | `id bigserial PK` · `deployment_id bigint NOT NULL` FK→`deployments(id)` ON DELETE CASCADE · `key_sha256 text NOT NULL UNIQUE` · `key_prefix text NOT NULL` · `label text NOT NULL DEFAULT ''` · `created_at timestamptz` · `created_by text` · `revoked_at timestamptz` · `last_used_at timestamptz` | **Không cột nào chứa plaintext.** `key_prefix` là 8 ký tự đầu, chỉ để admin nhận diện trên UI |
| `control.agent_credentials` | `tenant_id text PK` FK→`tenants(id)` ON DELETE CASCADE · `secret_version int NOT NULL DEFAULT 1` · `rotated_at timestamptz` · `rotated_by text` | Một hàng mỗi tenant. Không chứa bí mật, chỉ chứa số phiên bản |

Bảng hẹp riêng thay vì thêm cột vào `deployments` — cùng lý do `0007_agent_heartbeats.py` viết ra:
một bảng bị ghi thường xuyên không nên là neo danh tính của thứ khác. `agent_keys.last_used_at` được
ghi mỗi lần bootstrap.

Cả hai bảng nằm ở schema `control` và **mang `tenant_id` gián tiếp** (qua `deployment_id`) hoặc trực
tiếp ⇒ phải khai báo theo `isolation.md §6.0`, nếu không **cổng 6 của M1 đỏ**. Chúng là dữ liệu
control-plane (chỉ `portal_api` đọc, agent **không** có `SELECT`), không phải dữ liệu tenant — khai
báo đúng chỗ đó là một phần của migration này.

### API

| Method | Đường | Xác thực | Ai gọi |
|---|---|---|---|
| `POST` | `/agent/v1/bootstrap` | Bearer api_key của deployment | Pod agent |
| `POST` | `/admin/deployments` | Header `X-Platform-Admin-Token` | Admin nền tảng |
| `GET` | `/admin/deployments` | Header `X-Platform-Admin-Token` | Admin nền tảng |
| `POST` | `/admin/deployments/{id}/keys` | Header `X-Platform-Admin-Token` | Admin nền tảng |
| `DELETE` | `/admin/keys/{id}` | Header `X-Platform-Admin-Token` | Admin nền tảng |
| `POST` | `/admin/tenants/{id}/rotate-secrets` | Header `X-Platform-Admin-Token` | Admin nền tảng |

Đường trong router viết tương đối; tiền tố do `api/app.py` gắn — một chỗ duy nhất, theo `auth.md`.

### KHÔNG thêm action mới — vì sao, và cái gì thay thế

Bản trước của spec này đề xuất hai action `platform_admin.*`. **Sai, và sai theo cách CI bắt được
ngay.** Ba test khoá cứng con số 13:

| File | Khẳng định |
|---|---|
| `tests/api/test_actions.py:8` | `len(ALL_ACTIONS) == 13` |
| `tests/api/test_contracts.py:46` | `contracts/actions.json` có đúng 13 |
| `tests/modules/auth/test_login.py:57` | Response đăng nhập trả đúng 13 |

Con số 13 đến từ **PQ_01 §3.1** và là tripwire cố ý. Tệ hơn con số: M2a phát **cả 13 action cho mọi
user** (`Principal.actions` = cả 13), nên thêm `platform_admin.manage` vào đó là **phát quyền quản
trị nền tảng cho mọi người dùng workspace**.

Sai lầm gốc là về khái niệm, không phải về con số: **13 nhóm của PQ_01 là quyền *trong một
workspace*.** `Principal` mang `tenant_id`, `require()` trả về `Principal` đã gắn workspace. Admin
nền tảng hành động **xuyên tenant** — họ không có `tenant_id` để mang. Nhét vai đó vào `Principal`
là ép hai khái niệm khác nhau vào một kiểu dữ liệu.

**Cách làm:** một cổng riêng, không đi qua `ACTIONS`.

```python
# src/portal/core/auth/quan_tri_nen_tang.py
async def require_quan_tri_nen_tang(x_platform_admin_token: str = Header(default="")) -> None:
    """Cổng quản trị NỀN TẢNG — xuyên tenant, không phải quyền workspace.

    KHÔNG dùng ACTIONS: 13 nhóm của PQ_01 là quyền TRONG một workspace và
    M2a phát cả 13 cho mọi user. Thêm vào đó = phát quyền nền tảng cho mọi người.
    """
```

Route quản trị khai `_: None = require(None, ly_do="token quản trị nền tảng, không phải phiên
workspace")` để qua cổng `test_moi_route_khai_action.py` của M2a, **cộng** dependency ở trên. Hai
thứ khác nhau: `require(None, …)` nói *"route này cố ý không dùng action"*; dependency nói
*"nhưng nó vẫn có cổng riêng"*.

`PLATFORM_ADMIN_TOKEN` đọc từ env, so bằng `hmac.compare_digest`. Rỗng ở production ⇒ app **không
khởi động** — cùng luật với `AGENT_MASTER_KEY` (§3).

> **Đây là giải pháp tạm, và ghi rõ là tạm.** Khi M2b chốt ma trận quyền và định nghĩa vai *quản trị
> nền tảng* thật (có bảng, có người, có nhật ký ai là ai), `require_quan_tri_nen_tang()` đổi ruột —
> **chữ ký giữ nguyên**, nên không route nào phải sửa. Đó là lý do nó là một hàm chứ không phải
> `Depends(...)` viết thẳng trong router. Xem §11.

### Hình dạng lỗi

Theo `auth.md` — module raise `LoiPortal`, không tự trả JSON.

| Mã | HTTP | Khi nào |
|---|---|---|
| `INVALID_AGENT_KEY` | 401 | Không có header · key sai định dạng · không khớp hàng nào · **đã thu hồi** — **một mã cho cả bốn** |
| `TENANT_SUSPENDED` | 403 | Key hợp lệ nhưng tenant đang bị tạm ngưng |
| `RATE_LIMITED` | 429 | Quá 10 lần bootstrap / 5 phút cho cùng một key |
| `NOT_PROVISIONED` | 409 | Deployment tồn tại nhưng cấp phát chưa xong (role/collection/khoá thiếu) — trạng thái **hỏng**, không phải rỗng |
| `INVALID_ADMIN_TOKEN` | 401 | Thiếu · sai `X-Platform-Admin-Token` trên bất kỳ route `/admin/*` nào |

Bốn nhánh của `INVALID_AGENT_KEY` dùng **cùng câu chữ**, cùng lý do ba mã 401/403 của M2a dùng cùng
câu chữ: khác `message` là máy dò phân biệt được key nào có thật. Có test canh.

---

## 5. Trạng thái cấp phát

Cấp phát chạm bốn hệ (Postgres role · MinIO user · MinIO policy · Qdrant collection) và **không thể
nằm trong một transaction** — ba trong bốn ở ngoài Postgres. Cách xử lý, giống hệt lựa chọn của M6 §2:

**Idempotent, đồng bộ trong cùng request, không đẩy vào job nền.** Cả bốn thao tác đều là mili-giây
và đều chịu được gọi lại. `cap_phat()` gọi lại nhiều lần cho ra cùng kết quả:

| Thao tác | Idempotent bằng cách |
|---|---|
| `create_agent_role()` | **Không sửa hàm SQL của M1.** `service.py` kiểm `pg_roles` trước: chưa có ⇒ gọi `create_agent_role()`; đã có ⇒ `ALTER ROLE … PASSWORD`. Nhánh rẽ nằm ở M10, hàm của M1 giữ nguyên |
| `MinioAdmin.user_add` | `seed_kho_tep.py:59` đã có nếp gỡ rồi thêm lại |
| `MinioAdmin.policy_set` | Ghi đè |
| Tạo collection Qdrant | M6 đã có bước backfill idempotent trong `make dev-seed` — dùng lại |

Hỏng giữa chừng ⇒ hàng `deployments` có nhưng cấp phát thiếu ⇒ bootstrap trả `NOT_PROVISIONED`, và
admin bấm lại là xong. **Không có trạng thái nửa vời im lặng** — cùng tinh thần BR12 của M5.

### 5.1 Cấp phát xong ≠ agent nói được — kiểm tra sẵn sàng dữ liệu

M4a §1 chỉ ra một cách hỏng mà cấp phát **không** bắt được:

> *"Bootstrap thành công, `SELECT` chạy sạch, và trả về một căn hộ có 19 cột trong đó
> `field_policy_live` rỗng ⇒ `pol()` trả `false` cho mọi trường"*

Nghĩa là pod chạy đúng, không lỗi nào, mà agent tư vấn bằng một payload toàn `NULL`. Đây là loại
hỏng tệ nhất — **im lặng và trông như đang hoạt động**.

`cap_phat()` **không** coi đây là lỗi (workspace mới tinh chưa có dữ liệu là hợp lệ, đúng như M6 nói
*"kho rỗng là hợp lệ"*), nhưng nó **phải nói ra**. `GET /admin/deployments` trả thêm một khối
chẩn đoán, **chỉ đọc, không chặn gì**:

```jsonc
"san_sang_du_lieu": {
  "field_policy_rows": 0,      // ⚠️ chưa chạy seed_bds.py  → mọi cột gated về NULL
  "projects_agent_enabled": 0, // ⚠️ agent_api.units trả 0 hàng vì mệnh đề ② của M4a §6.1
  "kb_chunks": 0               // kho rỗng — hợp lệ, chỉ để admin biết
}
```

Ba con số này là **đọc thuần**, không cache, không cờ lưu trong DB. Lưu chúng thành trạng thái là
tạo một chỗ nữa để lệch với sự thật.

> **Ranh giới:** M10 **đọc và hiển thị**; M10 **không** seed `field_policy_live` — đó là
> `scripts/seed_bds.py` của M4a (BR01: bộ trường mẫu là của platform). M10 đọc bảng của M4a qua
> `COUNT(*)`, không import gì từ `modules/realestate/`.

---

## 6. Tám cổng test

| # | Cổng | Đỏ khi nào | File |
|---|---|---|---|
| 1 | Bootstrap bằng key của A → dùng DSN trả về `SELECT` `agent_api.units` thấy **0 hàng** của B | Cách ly vỡ ở đúng chỗ M10 mở ra | `test_bootstrap_cach_ly.py` |
| 2 | Key đã `revoked_at` ⇒ **401**, và `message` **giống hệt** key không tồn tại | Có đường dò key nào có thật | `test_thu_hoi_khoa.py` |
| 3 | Bootstrap hai lần liên tiếp ⇒ **cùng** `postgres_dsn`; hai deployment `chat`+`voice` của cùng tenant cùng nối được | Pod anh em đá nhau | `test_bi_mat_tat_dinh.py` |
| 4 | Xoay bí mật ⇒ mật khẩu **cũ** bị Postgres từ chối, mật khẩu **mới** vào được | Xoay khoá không có tác dụng thật | `test_xoay_bi_mat.py` |
| 5 | Tenant `suspended` ⇒ **403**, không trả credential nào | Workspace đóng vẫn phục vụ được | `test_bootstrap_suspended.py` |
| 6 | Quét **động** mọi cột `text` của `agent_keys`/`agent_credentials`: không giá trị nào khớp mật khẩu vừa suy dẫn. Và `caplog` của một lần bootstrap không chứa chuỗi bí mật nào | Bí mật rò vào DB hoặc log | `test_khong_ro_bi_mat.py` |
| 7 | `POST /agent/v1/bootstrap` kèm cookie `odyssey_session` hợp lệ nhưng **không** có Bearer ⇒ 401 | Hai đường xác thực lẫn vào nhau | `test_bootstrap_khong_nhan_cookie.py` |
| 8 | `agent_gia.py` chạy **chỉ** với `PORTAL_URL` + `AGENT_API_KEY` ⇒ pull được bundle, verify sha khớp, ghi được heartbeat | Đường ống đứt ở đâu đó giữa bootstrap và bundle | `test_agent_gia_end_to_end.py` |
| 9 | Tenant chưa seed `field_policy_live` ⇒ `GET /admin/deployments` phải báo `field_policy_rows: 0`, **không** báo sẵn sàng | Cách hỏng im lặng của M4a §1 lọt qua | `test_san_sang_du_lieu.py` |

> **Cổng 1 chỉ có nghĩa khi có dữ liệu thật.** Với bảng gần rỗng nó vẫn xanh — 0 hàng của B là đúng
> ngay cả khi A cũng 0 hàng. Fixture của cổng 1 **phải** seed dữ liệu cho **cả hai** tenant qua
> `seed_bds.py` (M4a) và bật `agent_enabled`, nếu không cổng này chứng minh một mệnh đề rỗng. Đây là
> lý do cụ thể của "thứ tự đề nghị: sau M4a" ở đầu spec.

Cổng 6 và 8 quan trọng hơn vẻ ngoài. Cổng 6 là cổng **quét động**, cùng hạng với cổng 5/6 của M1:
nó bắt được người thêm cột `password_cache` sáu tháng nữa. Cổng 8 là cổng duy nhất chứng minh
**toàn bộ** chuỗi thông — nó là lý do `agent_gia.py` phải chuyển sang bootstrap **trước** khi Gói G
bắt đầu, đúng vai "spec sống" mà M3 §7 đã giao cho nó.

---

## 7. Hợp đồng bàn giao Gói G — mười yêu cầu cho `santa-hotline-agent`

Bổ sung cho `docs/contracts/bundle.md`, không thay thế. Sẽ ghi thành
`docs/contracts/dau-noi-agent.md` khi spec này được duyệt.

| # | Yêu cầu | Vì sao |
|---|---|---|
| **G-1** | Env của pod chỉ còn **`PORTAL_URL` + `AGENT_API_KEY`**. Gỡ `POSTGRES_URI_MOCK` · `POSTGRES_URI_REAL` · khoá S3 · `TENANT_ID` | Ops không còn copy-paste credential; gõ nhầm tenant là chuyện không còn tồn tại |
| **G-2** | Bootstrap lúc khởi động; làm mới trước `expires_at`. **Fail-fast** — cấm fallback về credential cũ trong env hoặc trên đĩa | Fallback âm thầm là đường quay lại cấu hình sai mà không ai thấy |
| **G-3** | **Bỏ `QDRANT_COLLECTION_ROOT`** (hiện `.env:285` = `document_v4`, một biến toàn hệ). Tên collection lấy từ `kb.collection` của bootstrap. **Không hàm nào nhận tên collection làm tham số** | M6 BR01 · BR03. Hiện tại hai tenant dùng chung collection ⇒ `kb_search` của B trả chunk của A |
| **G-4** | **Redis: tách khỏi M10.** Số hiệu giữ chỗ để hợp đồng không bị đánh số lại khi phần Redis nhập vào | Xem §8 · `isolation.md §11` |
| **G-5** | Bỏ `src/noble_agent/tenants/{noble, demo_acme}` cứng trong image | Cấu hình đến từ bundle, không từ thư mục trong image. Một image cho mọi tenant |
| **G-6** | Postgres: đọc **chỉ** `agent_api.*`; ghi **chỉ** `control.agent_heartbeats`. Không chạm `tenant_data.*`, không chạm bảng `control` nào khác | Quyền đã chặn (`test_role_privileges.py` cổng 5), nhưng code không nên thử — lỗi permission lúc chạy khó chẩn đoán hơn là không viết |
| **G-7** | Poll `LIVE` mỗi 20s · verify sha256 · nạp **nguyên khối**; hỏng thì **giữ bản đang chạy** | `bundle.md §1` · BR12 của M5: *"hỏng thì không gì đổi"* |
| **G-8** | Heartbeat mỗi 20s, `deployment_id` lấy từ bootstrap response | `bundle.md §5`. Portal suy 4 chip trạng thái từ đây; thưa hơn 60s ⇒ portal báo Mất kết nối |
| **G-9** | `/chat/ws` trả **`tools_used`** kèm mỗi câu trả lời | M5 §7 — nợ từ trước. Đây là cách duy nhất người dùng thấy bật/tắt kỹ năng có tác dụng thật |
| **G-10** | Cấm log · trace · APM span chứa bootstrap response | Nó chứa mật khẩu Postgres và secret key S3 |
| **G-11** | `_serialize.py` **bỏ hẳn khoá** có giá trị `NULL`/rỗng trước khi đưa vào ngữ cảnh LLM | Nguồn: **M4a §6.2**. View SQL trả tập cột **cố định** — nó không bỏ khoá được, nên `BR03` chỉ cưỡng chế được ở phía agent. Hiện 7/18 khoá luôn rỗng, gần 40% payload. Đây là **điều kiện** để `floor`/`building`/`zone` được lên view (M4a §2.5b) |
| **G-12** | Gỡ hai filter `floor` và `tower` khỏi `schemas.py` của kỹ năng tra căn | Nguồn: **M4a §6.2** (quyết định #17 · BR04 · BR15). Portal seed `filterable = false`, nhưng tool schema là artefact của repo agent — portal không với tới được |

> **G-11 và G-12 đến từ M4a, không phải M10.** M4a §10 ghi: *"`docs/contracts/dau-noi-agent.md` —
> thêm G-11 và G-12. Nếu M10 chưa ship, ghi tạm vào spec M10 §7."* Đây là chỗ ghi tạm đó. Khi M10
> ship `dau-noi-agent.md`, cả 12 mục đi cùng nhau — Gói G nhận **một** hợp đồng, không phải hai.

**Điều portal hứa lại với Gói G:**

- Bootstrap response có `expires_at` tuyệt đối (ISO 8601, UTC) — pod không phải đoán TTL.
- `postgres_dsn` đã gồm role đúng; pod **không** cần biết quy tắc đặt tên role.
- `kb.collection` đã là tên đầy đủ; pod **không** cần biết quy tắc `kb_<tenant_id>`.
- Bootstrap idempotent: gọi 10 lần trả cùng credential (cùng `secret_version`).
- Xoay bí mật **không** ngắt kết nối đang mở — pod có trọn một chu kỳ TTL để chuyển.

---

## 8. Kho thứ tư — Redis của agent (TÁCH RA, KHÔNG THUỘC M10)

`isolation.md` khai **ba** kho, mỗi kho một cơ chế. Có **kho thứ tư** chưa tài liệu nào nhắc tới:

`santa-hotline-agent` lưu trạng thái hội thoại vào Redis theo key `session:<id>:meta` ·
`session:<id>:customer` · `session:<id>:state` (`tests/integration/unified/test_booking_flow.py:110-116`).
Nội dung là **tên, số điện thoại, ngân sách, hoàn cảnh gia đình của khách hàng cuối** — đúng thứ mà
`isolation.md §6.1` gọi là *"thứ nhạy cảm nhất trong hệ"*. `.env:357` cho thấy nó trỏ tới một Redis
dùng chung. **Key không có `tenant_id`, không cơ chế nào chặn hai tenant đọc key của nhau.**

**Vì sao tách khỏi M10:** phạm vi khác hẳn (ACL Redis + đổi key prefix trong repo agent + có thể
tách instance), và nó không chặn M10 — bootstrap vẫn cấp được ba credential kia. Nhưng nó **chặn
việc đưa tenant thứ hai lên production**.

**Hướng đề xuất khi làm phần đó:** Redis ACL user theo tenant với key pattern cưỡng chế
`~t:<tenant_id>:*`, credential cấp qua chính bootstrap của M10 (thêm khối `redis` vào response —
thay đổi cộng thêm, không phá hợp đồng). Cưỡng chế ở server Redis, không ở kỷ luật code — cùng lý do
chọn RLS thay vì filter tay.

Ghi chú đã cắm vào: `docs/contracts/isolation.md §11` · spec tổng §5.6 · spec này §0.

---

## 9. Hoà giải với M8 — hai loại "API key", đừng gộp

Bản đồ module giao cho **M8** phần *"API key/tenant + rate limit"* (gói F). Nghe trùng với M10, nhưng
là hai thứ khác nhau và **không nên dùng chung bảng**:

| | M10 · `agent_keys` | M8 · API key của tenant |
|---|---|---|
| Ai phát | Admin **nền tảng** | Admin **workspace** |
| Cho ai dùng | Pod agent do NobleX vận hành | Hệ thống của **khách hàng** tích hợp vào |
| Mở được gì | Credential hạ tầng (DSN · S3 · collection) | Endpoint REST của portal, phạm vi hẹp |
| Bán kính khi rò | Toàn bộ dữ liệu một tenant | Đúng những endpoint đã cấp |
| Mạng | Chỉ nội bộ | Internet |

Gộp hai thứ này là để một khoá của khách hàng có đường lấy DSN Postgres. **Không gộp.**

Nhưng **dùng chung phần cơ khí**: hàm băm khoá, sinh khoá, và bộ rate-limit Redis nên ở
`core/`, không nằm trong `modules/enrollment/`. M10 viết trước ⇒ M10 đặt chúng ở
`core/khoa_api.py` và M8 dùng lại. Ghi vào contract để M8 không viết lại lần hai.

---

## 10. Việc kéo theo

- Thêm `agent_master_key` · `bootstrap_ttl_seconds` vào `core/config.py`; app từ chối khởi động ở
  production nếu khoá gốc rỗng hoặc < 32 byte.
- `scripts/seed_kho_tep.py`: bỏ `MAT_KHAU_DEV`, gọi `bi_mat.dan_xuat()` — dev và production đi cùng
  một đường code, không phải hai.
- `scripts/agent_gia.py`: chuyển sang bootstrap. Nó là fixture của cổng 8.
- `make dev-seed`: tạo sẵn một deployment + api_key cho tenant demo, in ra màn hình.
- Hai action mới trong `core/auth/actions.py` (xem §4).
- Thêm mục *"đấu nối agent"* vào `docs/contracts/` index.

---

## 11. Còn treo

- **Ai là "admin nền tảng"** — M2b hoãn nên chưa có vai trò thật. M10 dùng một token tĩnh trong env
  (`PLATFORM_ADMIN_TOKEN`, §4) — **không biết ai đang gọi**, nên `audit_log.actor` ghi
  `"platform_admin"` chứ không ghi tên người. Đây là nợ đã biết: khi M2b có vai thật,
  `require_quan_tri_nen_tang()` đổi ruột và `actor` mới ghi được tên. **Chặn UI, không chặn API.**
- **TTL 1 giờ có đúng không** — đánh đổi giữa cửa sổ thiệt hại khi rò và tải lên portal. Cần một số
  liệu thật từ ops trước khi chốt.
- **Xoay `AGENT_MASTER_KEY`** — hiện chưa có quy trình. Đổi nó là mọi tenant phải xoay bí mật; cần
  một đường xoay theo lô, và nó chưa được thiết kế.
- **Deployment `kind='voice'`** — spec này giả định pod voice bootstrap giống hệt pod chat. Chưa xác
  minh với `santa-hotline-agent` là luồng telephony có nhu cầu credential khác không.

---

## 12. Δ do KB viết lại và tầng organization *(2026-08-03)*

### Organization: không đổi gì

`0102_organizations.py` cố ý giữ `org_id` **dừng ở schema `control`** — nó không xuống `tenant_data`,
không vào `portal.current_tenant()`, và agent pod không biết tổ chức tồn tại. Khoá cách ly vẫn là
`tenant_id`, đúng một khoá. **Không sửa dòng nào của M10.**

### KB mới: bốn chỗ phải sửa trong plan

Nguồn: `docs/build_module_knowledgebase/` (`00-overview` · `02-knowledge-base` · `02b-rag-service`)
và `01-control-plane` §*tenants*.

| # | Chỗ sửa | Từ | Thành |
|---|---|---|---|
| 1 | `contracts.KbOut` (T5) | `collection: str` | `documents: str` · `media: str` |
| 2 | `core/ten_tai_nguyen.py` | `ten_collection(tenant_id) -> "kb_{id}"` | hai hàm theo `tenants.slug`: `{slug}_documents` · `{slug}_media` |
| 3 | `ha_tang_ngoai.tao_collection_neu_thieu` (T6) | tạo **một** collection | tạo **hai**, named vectors khác nhau (`dense`+`sparse` / `text`+`visual`) |
| 4 | `service.san_sang_du_lieu` (T7) | `field_policy_rows` · `projects_agent_enabled` | `field_policy_live` và `agent_enabled` **không còn** — đếm `projects WHERE status='published'` |

**Việc kéo theo:** `tenants` cần bốn cột mà `01-control-plane` khai nhưng migration **chưa có** —
`slug` · `qdrant_documents_coll` · `qdrant_media_coll` · `s3_prefix`. Chúng thuộc control plane (nhóm
A), **không thuộc M10**. M10 **đọc** chúng. Nếu chúng chưa tồn tại khi M10 thi công, M10 tạm suy tên
từ `tenants.id` như hôm nay và đổi sang đọc cột khi nhóm A ship — đổi một hàm trong
`ten_tai_nguyen.py`.

### Hai quyết định — ĐÃ CHỐT 2026-08-03

#### (a) Lớp đọc: giữ `agent_api`, nhưng nó gác **hiển thị**, không gác **cột**

KB mới bỏ gate cột — đúng, và M10 theo. Nhưng `agent_api` **không** biến mất, vì nó còn một việc thứ
hai mà thiết kế mới vẫn cần:

| | Cũ | Chốt mới |
|---|---|---|
| Gate **cột** (`commission` · `bank_support` · `csbh_full` · `field_policy_live`) | View che | **Bỏ hẳn.** KB không lưu trường nhạy cảm nữa (`02` §1) — không còn gì phải che |
| Gate **hiển thị** (`status='published'` + cascade theo anchor cha) | Chưa có | **View lo.** Đây là lý do `agent_api` tiếp tục tồn tại |
| Lọc tenant | View tự lọc (definer) | Giữ nguyên |

**Vì sao không để agent tự lọc `published`:** `02` §3 bắt *"anchor `status≠published` ⇒ ẩn toàn bộ
cây con"*. Đó là một `EXISTS` join lên bảng cha — đúng loại điều kiện mà `isolation.md §1` đã chứng
minh là **không được** giao cho người viết query nhớ: một chỗ quên là dự án nháp lọt ra cho khách,
và lỗi đó **im lặng**. Cùng lập luận đã chọn RLS thay vì `WHERE tenant_id` viết tay.

Nói cách khác: bỏ gate cột là **giảm** thứ view phải làm, không phải **xoá** view.

```sql
-- 0401_agent_doc_kb.py — hình dạng chốt. Không CASE WHEN pol(), không gated_extras.
CREATE VIEW agent_api.projects AS
SELECT p.*   -- KB đã sạch dữ liệu nhạy cảm nên lấy hết cột, không gate
  FROM tenant_data.projects p
 WHERE p.tenant_id = portal.current_tenant()      -- ① cách ly
   AND p.status = 'published';                    -- ② hiển thị

CREATE VIEW agent_api.zones AS
SELECT z.*
  FROM tenant_data.zones z
 WHERE z.tenant_id = portal.current_tenant()
   AND z.status = 'published'
   AND EXISTS (SELECT 1 FROM tenant_data.projects p                -- ③ cascade anchor
                WHERE p.tenant_id = portal.current_tenant()
                  AND p.code = z.project_code
                  AND p.status = 'published');
-- units · documents · media: cùng khuôn ③
```

Quyền agent **không đổi**: `USAGE` trên `agent_api` + `SELECT` trên view, **zero privilege trên
`tenant_data`**. Nghĩa là `isolation.md §5` còn đúng nguyên văn, chỉ mục §5 nói về gate cột thì đánh
dấu là đã bỏ.

**Hệ quả cho M10:** cổng test 1 (T9) **không bị chặn** — nó vẫn `SELECT agent_api.units`. G-6 của hợp
đồng gỡ nhãn ⏳.

> Hình dạng chi tiết của từng view (bảng nào, cột nào) vẫn thuộc **Task 6 của plan KB**. M10 chỉ chốt
> **nguyên tắc**: agent đọc qua `agent_api`, view lo tenant + hiển thị, không lo cột.

#### (b) Tiền tố kho tệp: giữ `tenants/<tenant_id>/`

`s3_prefix` của `01-control-plane` là **cột dẫn xuất**, giá trị `"tenants/<id>/"`, không phải
`"<slug>/"`.

| | |
|---|---|
| Vì sao | `bundle.md §1` đã là hợp đồng **có cổng test** (cổng 7 của M1) và `storage.chinh_sach_tien_to()` đã sinh policy theo tiền tố đó. `s3_prefix = "<slug>/"` mới là thiết kế trên giấy |
| Đánh đổi | Đường dẫn dài hơn 8 ký tự. Đó là toàn bộ cái giá |
| Nếu chọn ngược lại | Phải đổi `bundle.md` · `chinh_sach_tien_to()` · `duong_dan_bundle()` · `duong_dan_live()` · cổng 7 · và di chuyển mọi object đã có ở dev |

**Một tiền tố, một policy MinIO.** Bundle, media, tài liệu gốc đều nằm dưới `tenants/<tenant_id>/`.

### Phạm vi vẫn là chỉ-đọc

Thiết kế mới cho agent ghi ba bảng `contacts` · `conversations` · `appointments`. Ba bảng đó thuộc
nhóm **C** (`03-operational.md`), **chưa tồn tại**. M10 không chờ chúng: khi nhóm C ship, nó gọi
`control.grant_agent_write()` cho ba bảng đó và **M10 không phải sửa gì** — credential đã đúng, role
đã đúng, chỉ thêm grant. Đó chính là lý do `grant_agent_write()` tồn tại từ M1.

### Còn đúng nguyên vẹn

api_key làm bootstrap token · bí mật suy dẫn tất định (§3) · hai bảng `0900` · cổng quản trị nền tảng
(§4) · thu hồi · xoay khoá · rate-limit · G-1 · G-2 · G-5 · G-7 đến G-12. **Đổi ở KB không chạm cơ
chế đấu nối** — nó chỉ đổi *nội dung* của khối `kb` trong bootstrap response.
