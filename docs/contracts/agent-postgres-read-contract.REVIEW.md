# Đối chiếu contract "agent đọc Postgres" với hệ Portal đang ship

> Nguồn đối chiếu: migrations `0001·0003·0005·0007·0200·0900`, `src/portal/modules/config/*`,
> `src/portal/modules/enrollment/*`, `tests/isolation/test_isolation_catalog.py`,
> `docs/contracts/dau-noi-agent.md`. Ngày: 2026-08-04.
> Kết luận ngắn: **KHÔNG ship nguyên bản.** 1/4 bề mặt là nhu cầu thật nhưng chưa build được;
> 3/4 bề mặt trùng lặp với `POST /api/v1/agent/bootstrap` đã ship; và §0 đòi đổi mô hình cách ly.

---

## A. Sai dữ kiện trong contract (họ viết theo spec Portal không có)

| Contract nói | Thực tế |
|---|---|
| `docs/api/SPEC-DB-HIEN-TAI.md`, `docs/handoff/spec.md` | **Không tồn tại.** `SPEC-DB-HIEN-TAI.md` ở gốc repo; hợp đồng agent đã ship là `docs/contracts/dau-noi-agent.md` + `bundle.md`. Mọi tham chiếu "SPEC §3.12 / §4 / §6" không kiểm chứng được. |
| "view `agent_api` owner = `portal_api`" | **Sai.** `0005` không có `ALTER VIEW … OWNER TO`; owner = role chạy migration (superuser). View vẫn là DEFINER nên vẫn đọc được `control.*` — kết luận của họ đúng, lý do thì sai. |
| `control.config_pointer` | **Không tồn tại.** Xem §B. |
| `version` "đơn điệu tăng / tenant" | **Sai với Portal.** Có rollback: `service.quay_lui()` chỉ đổi con trỏ, không sinh version mới ⇒ version đang publish **có thể giảm** (v2 → v1). Agent giả định đơn điệu tăng sẽ hỏng đúng lúc vận hành rollback. |
| `bundle_sha` "nếu view lộ; nếu không `''`" | `control.config_versions.bundle_sha` có sẵn, `NOT NULL`, `CHECK (<> '')`. Lộ được — đừng để `''`. |

**Khớp đúng, không cần sửa:** `tenants.lifecycle IN ('active','suspended','closed')`;
`agent_keys.key_sha256 = sha256(plaintext)` hex, **không salt** (`bi_mat.py:65`);
`deployments.kind CHECK IN ('chat','voice')`, `id bigserial`;
`agent_heartbeats` RLS 2-policy + `GRANT SELECT,INSERT,UPDATE TO agent_all` (`0007`) — upsert §2 chạy được y nguyên;
bất biến version còn **mạnh hơn** contract đòi: `0200` `REVOKE UPDATE, DELETE ON control.config_versions FROM portal_api`;
`ALTER DEFAULT PRIVILEGES IN SCHEMA agent_api … TO agent_all` đã có ⇒ 4 câu `GRANT SELECT` trong contract là no-op vô hại;
cổng `test_moi_view_agent_api_tu_loc_tenant` — cả 4 view đều gọi `portal.current_tenant()`, pass.

---

## B. Chặn đường: `agent_published_config` chưa build được

Con trỏ "version nào đang live" **nằm trong kho tệp** (object `tenants/<t>/LIVE`), không nằm ở Postgres —
và đó là quyết định có chủ ý, ghi rõ ở [`service.py:231-245`](../../src/portal/modules/config/service.py#L231-L245):

- **`MAX(version)` bị loại tường minh:** sau rollback, cao nhất là v2 nhưng agent đang phục vụ v1.
- **`tenants.live_version` bị loại tường minh:** "bản sao thứ hai của một sự thật … hai bản sao thì có ngày lệch".
- Thứ tự 4 bước publish (cổng 2) đặt việc ghi `LIVE` **sau cùng**, vì `PUT` object là nguyên tử.

⇒ Muốn có view này, Portal **buộc phải** dời con trỏ vào Postgres (vd `control.config_live(tenant_id PK, version, bundle_sha)`),
ghi trong cùng transaction với `config_versions`. Nhưng nếu làm mà **vẫn giữ** object `LIVE`, ta tạo ra chính xác cái
divergence mà comment trên cảnh báo. Nên đây là quyết định một chiều: **Postgres thành sự thật duy nhất, object `LIVE` bị bỏ
hoặc chỉ còn là bản phái sinh** — và điều đó phá `bundle.md` + `dau-noi-agent.md` G-7 (poll `LIVE` 20s, verify sha256).
Đây là công việc thật, không phải "Portal đặt tên nội bộ khác".

**Câu hỏi phải chốt với team agent trước khi code:** `config` mà agent muốn là `config_versions.payload`
(**bản draft chưa render**) hay **bundle đã render** mà `bundle.md` định nghĩa? Contract §1.1 map `payload → config`,
nhưng agent hôm nay build prompt từ bundle đã render. Nếu đưa `payload`, prompt sẽ khác — im lặng, không có lỗi nào.

---

## C. Điểm nặng nhất: §0 hạ cấp mô hình cách ly

Hôm nay tenant được suy **từ tên role**: `portal.current_tenant()` =
`substring(session_user from '^agent_(.+)$')`, GUC chỉ là fallback (`0001:41`).
`0900` suy dẫn đúng một mật khẩu/tenant từ `AGENT_MASTER_KEY`; bootstrap trả `postgres_dsn`
**đã gồm role đúng** (`dau-noi-agent.md` §4: "Pod **không** cần biết quy tắc `agent_<slug>`").

Contract đòi **một role login dùng chung `odyssey_agent`** + GUC `app.tenant_id`. Hệ quả:

1. **Cách ly chuyển từ role-enforced sang app-enforced.** Hôm nay pod *không thể* đọc tenant khác vì
   không có credential của role đó. Với role dùng chung, rào chắn duy nhất là agent nhớ `SET LOCAL app.tenant_id`
   đúng mỗi transaction. Một lần quên, hoặc một connection pool tái dùng session đã `SET` (không `LOCAL`),
   là rò chéo tenant — không có lỗi nào phát ra. `0003:52-55` đã viết đúng cảnh báo này cho `portal_api`:
   một mật khẩu = quyền đọc-ghi **mọi** tenant. Cấp quyền đó cho một role **LOGIN** là tệ hơn.
2. Phá luồng enrollment đã ship (`0900`, `bi_mat.py`, `ha_tang.py`, `dau-noi-agent.md` §2 — 37 test).
3. Điểm sáng duy nhất: GUC rỗng ⇒ `current_tenant()` = `NULL` ⇒ `WHERE tenant_id = NULL` ⇒ 0 dòng.
   **Fail-closed.** Nếu chấp nhận mô hình này thì phải có test khẳng định đúng điều đó.

### Phản đề nên gửi lại team agent

**Phương án A (khuyến nghị — Portal đổi ~0 dòng).** Giữ role/tenant. "1 process, N tenant" không đòi
1 connection; nó đòi **N pool khoá theo tenant**, mỗi pool dùng DSN mà bootstrap đã trả. Cách ly vẫn do
Postgres cưỡng chế. Chi phí thuộc phía agent, và là chi phí nhỏ.

**Phương án B (nếu A bị từ chối).** Một credential nhưng vẫn để Postgres cưỡng chế phạm vi:
đổi `portal.current_tenant()` từ `session_user` sang `current_user`, `GRANT agent_<slug> TO odyssey_agent`,
agent chạy `SET LOCAL ROLE agent_<slug>` mỗi transaction. Quên `SET ROLE` ⇒ `current_user = odyssey_agent`
⇒ không khớp regex ⇒ GUC ⇒ NULL ⇒ 0 dòng, fail-closed. Tương thích ngược (`portal_api` và `agent_<slug>`
cho cùng kết quả ở cả hai biểu thức) — nhưng đây là hàm mà **mọi** policy RLS và **mọi** view `agent_api` gọi,
nên phải đi kèm cổng test riêng.

**Phương án C (contract nguyên bản, GUC-only).** Chỉ chấp nhận nếu team agent cam kết bằng test:
`SET LOCAL` (không phải `SET`), reset khi trả connection về pool, và một test rò chéo tenant.

---

## D. Ba bề mặt trùng lặp — đừng build

`POST /api/v1/agent/bootstrap` **đã ship, 37 test** ([`dau-noi-agent.md`](dau-noi-agent.md) §2) và đã trả:
`deployment_id`, xác thực api_key, kiểm tenant, `kb.collection`, prefix kho tệp, model embedding.

| Bề mặt | Nhận xét |
|---|---|
| §1.2 `tenant_status` | Bootstrap đã chặn tenant không active. |
| §1.3 `tenant_keys` | Bootstrap **chính là** đường verify key. Đẩy verify sang agent làm Portal mất `agent_keys.last_used_at` (`repo.py:102`) và mất dấu vết bootstrap trong `audit_log`. |
| §1.4 `deployments` | Bootstrap đã trả `deployment_id` — và G-8 nói rõ "lấy từ bootstrap response, không tự sinh, không đoán". |

Ba view này đi ngược **invariant có văn bản** trong `tests/isolation/test_isolation_catalog.py`:
"`deployments` — Agent có ZERO quyền trên bảng này"; "`config_drafts`/`config_versions` — Agent không đọc bảng này,
nó chỉ đọc bundle đã render trên kho tệp". Build chúng thì phải sửa cả comment lý lẽ ở đó, tức là **thu hồi một
quyết định thiết kế**, không phải thêm một view.

**Lỗ hổng trong lập luận của họ:** §1.3 dựa vào "Host của tenant này" để cách ly, nhưng **không bề mặt nào map
Host → tenant_id**. Với role dùng chung, agent phải biết tenant *trước khi* set GUC *trước khi* đọc `tenant_keys`.
Contract thiếu hẳn mắt xích đó. Nếu bootstrap vẫn còn thì không cần §1.3; nếu bỏ bootstrap thì contract thiếu 1 bề mặt.

**Câu hỏi chốt duy nhất cho team agent:** *bootstrap còn hay bỏ?*
- **Còn** ⇒ chỉ build §1.1 (sau khi giải quyết §B). Bỏ §1.2·1.3·1.4. Giữ role/tenant (phương án A).
- **Bỏ** ⇒ contract này chưa đủ: thiếu Host→tenant, `kb.collection`, model embedding, prefix kho tệp; và toàn bộ
  §C phải chốt trước.

---

## E. Việc nhỏ, đồng ý được ngay

- `ALTER ROLE … SET search_path = agent_api, public` cho phép `FROM agent_published_config` không kèm schema:
  1 dòng, chấp nhận được. Nhưng nên yêu cầu agent **schema-qualify** — SQL heartbeat của chính họ (§2) đã qualify,
  nên đây là bất đối xứng không có lý do, và search_path ở mức role là thứ dễ vỡ khi thêm schema mới.
- `deployments` không có unique trên `(tenant_id, kind)`. "Khuyến nghị ≤1 dòng" + "agent chọn `id` lớn nhất" là
  hợp đồng dựa vào thói quen. Nếu build §1.4: thêm `CREATE UNIQUE INDEX … ON control.deployments (tenant_id, kind)`
  để bất biến do DB giữ.
- §7 "Publish v1 ngay khi tạo tenant": mâu thuẫn với `config_drafts` (draft trước, publish sau) và với
  `co_ban_nhap()`. Auto-publish v1 rỗng làm hỏng dấu hiệu "chưa cấu hình lần nào". Nên phản đối; §5 đã có
  đường fail-closed cho 0 dòng rồi, không cần v1 giả.
- `GRANT agent_all TO odyssey_agent`: chỉ chạy nếu chốt phương án C.

---

## F. Thứ tự làm

1. Gửi §C + §D về team agent. **Chốt "bootstrap còn hay bỏ" và mô hình role trước khi viết migration nào.**
2. Chốt `payload` vs bundle đã render (§B).
3. Sửa 5 sai dữ kiện ở §A trong contract của họ — nhất là **version không đơn điệu tăng** (rollback).
4. Chỉ khi 1-3 xong: migration cho con trỏ live trong Postgres + `agent_api.agent_published_config` + cổng test
   (fail-closed khi GUC rỗng · view lọc tenant · con trỏ không lệch sau rollback).
