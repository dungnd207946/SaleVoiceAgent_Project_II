# Nạp kiến thức cho agent — Design

**Ngày:** 2026-08-11
**Phạm vi:** `odyssey-portal-backend` (module `kb`, `realestate`) + `odyssey-portal-frontend` (feature `realestate`)
**Trạng thái:** đã chốt với người yêu cầu, chờ lập kế hoạch thi công

## 1. Vấn đề

Đường ghi Qdrant đã hoàn chỉnh và chạy được (module `kb`: chunk → embed → upsert, hai collection `<slug>_documents`/`<slug>_media`), nhưng **không có giao diện nào kích hoạt nó**. Bốn endpoint đã ship (`POST /projects/{code}/sync-kb`, `POST /media/{id}/recaption`, `GET /projects/{code}/enrich-status`, `GET /projects/kb-sync-status`) và `POST /kb/{entity}/{id}/reindex` hiện chỉ gọi được bằng `curl` — quét toàn bộ repo frontend không có một lời gọi nào.

Bốn vấn đề đi kèm:

1. **Người dùng không biết Qdrant có còn đúng hay không.** Không có tín hiệu nào trên màn hình.
2. **Mỗi lần đồng bộ là re-embed toàn bộ dự án.** `content_hash` được tính và ghi vào `kb_index_state` nhưng không nơi nào đọc ra để so — bước thoát sớm mà spec ingest §6.2 quy định chưa từng được cài.
3. **Kết quả enrich vô hình.** Job `kb_enrich` ghi caption/`body` vào Aurora, nhưng FE coi hai ô đó là "nhập tay" (docstring `OMedia.tsx`, `TaiLieuTab.tsx` ghi rõ `⚠ NHẬP TAY`) và không hiện trạng thái nào, nên người dùng không biết có mô tả tự động, không biết chờ bao lâu, không biết mình được sửa.
4. **Xoá và unpublish không dọn point.** `service.delete_cascade()` đã viết xong và có test, `handle_delete` nhận `anchor_code` để gọi nó — nhưng **không route nào enqueue job đó**. Đường tự lan duy nhất tồn tại hôm nay là `PATCH documents` khi đổi loại tài liệu. Hệ quả đo được: xoá một ảnh hay unpublish một dự án để lại point sống mãi, và agent tiếp tục gửi dữ liệu đã ẩn cho khách.

## 2. Quyết định thiết kế

| # | Quyết định | Vì sao |
|---|---|---|
D1 | Nạp kiến thức **chỉ chạy khi người dùng bấm**, hai lựa chọn: *chỉ phần mới thay đổi* và *nạp lại toàn bộ dự án* | Người yêu cầu muốn kiểm soát: embed tốn tiền, và nội dung do AI sinh phải qua mắt người trước khi tới tay khách |
D2 | Delta xác định bằng **so `content_hash`**, không bằng `updated_at` | Bấm Lưu mà không sửa gì cũng đẩy `updated_at`; so hash là phép duy nhất không tốn tiền embed cho nội dung không đổi |
D3 | **Xoá/unpublish vẫn tự động** dọn point, không chờ ai bấm | Dữ liệu đã xoá còn nằm trong Qdrant là agent gửi tài liệu/ảnh đã xoá cho khách. Rủi ro này không đáng để đổi lấy tính nhất quán của khẩu hiệu "hoàn toàn thủ công" |
D4 | Badge suy từ **`updated_at` vs `indexed_at`**, không từ hash | Badge phải tính cho cả trang danh sách trong một request — không thể chunk+hash từng record. Chấp nhận báo thừa; nó tự hết sau lần bấm đầu (xem D5) |
D5 | Job thoát sớm vì hash giống **vẫn chạm `indexed_at`**, ghi `state='skipped'` | Không có nó, badge không bao giờ về xanh: `updated_at` vẫn lớn hơn `indexed_at`, người dùng bấm lại mãi mà con số không giảm |
D6 | Thay ảnh/tệp ⇒ **tạo lại mô tả, đè lên mô tả cũ** | Ảnh đã khác thì mô tả cũ là SAI, và giữ nó là agent tả nhầm ảnh cho khách mà không ai biết vì ô vẫn có chữ. Chỉ đè khi ảnh/tệp đổi; sửa riêng caption thì không chạy gì |
D7 | Từ ngữ trên màn: **"nạp kiến thức cho agent"** | Người dùng không phải kỹ thuật. Nói rõ đích đến (agent trả lời khách) thay vì "index"/"kho vector"/"đồng bộ" — họ hiểu được tại sao phải bấm |
D8 | Badge + nút ở **cả** danh sách dự án **và** header trang chi tiết | Danh sách: quét một lượt biết dự án nào cần sờ tới. Chi tiết: đang sửa thì thấy ngay trạng thái, không phải quay ra |
D9 | `handle_reconcile` **vẫn để `NotImplementedError`** | Badge `stale` đã cho người dùng thấy lệch và tự bấm được. Lưới tự động bù event mất là việc riêng, ngoài scope |
D10 | `kb_index_state` **thêm cột `project_code`** | FK `projects → zones/documents/media` là `ON DELETE CASCADE`, nên xoá một dự án làm row con biến mất trong cùng giao dịch; job cascade chạy sau ở worker hỏi Postgres "dự án này có con nào" sẽ nhận về rỗng và point cây con sống mãi. Sổ `kb_index_state` **không** có FK tới bảng nguồn nên dòng sổ sống sót — nó là nơi duy nhất còn biết "dự án này đã từng nạp những gì". Cột này cũng làm phần badge gọn hẳn: `GROUP BY project_code` một câu thay vì JOIN 4 bảng nguồn rồi gộp |

### 2.1 Đánh đổi đã chấp nhận tường minh

**D4 báo thừa.** Bấm Lưu trên một dự án mà không sửa gì làm badge chuyển sang "△ 1 mục chưa nạp". Người dùng bấm nạp, worker so hash thấy giống, không gọi embed, ghi `skipped` và chạm `indexed_at` — badge về xanh, thông báo nói "1 mục đã kiểm, 0 mục có nội dung mới". Báo thừa tốn đúng một cú bấm.

Phương án chính xác 100% (thêm cột `source_hash` trên 4 bảng, cập nhật ở mọi đường ghi) đã bị loại: quên cập nhật ở một đường ghi — kể cả script vá dữ liệu — là badge **sai âm**, tức nói "đã nạp" khi chưa. Sai âm nguy hiểm hơn báo thừa vì không có dấu hiệu nào.

## 3. Ba luồng sau khi đổi

```
① NẠP KIẾN THỨC — chỉ khi người dùng bấm
   [Nạp kiến thức cho agent ▾]
     ├ Chỉ phần mới thay đổi (8 mục)  → kb_sync_project { mode: 'delta' }
     └ Nạp lại toàn bộ dự án           → kb_sync_project { mode: 'full' }   (có hộp xác nhận)
        └→ collections.create()  (idempotent, cứu tenant mới)
        └→ N job kb_index con, mỗi job mang { project_code, mode }:
             đọc row → dựng directive → chunk → hash
               ├ mode='delta' và hash == kb_index_state.content_hash
               │     → state='skipped', chạm indexed_at, KHÔNG gọi embed
               └ khác, hoặc mode='full'
                     → embed → delete_by_record → upsert → state='indexed'

② DỌN KHI XOÁ — tự động, không chờ ai bấm
   DELETE .../media/{id}              → kb_delete_index { entity: 'media', record_id }
   DELETE .../documents/{id}          → kb_delete_index { entity: 'documents', record_id }
   DELETE .../zones/{code}            → N job kb_delete_index (xem §3.1)
   PATCH  zone status→'draft'         → N job kb_delete_index (xem §3.1)
   DELETE /projects/{code}            → kb_delete_index { anchor_code }
   PATCH  project status→'draft'      → kb_delete_index { anchor_code }
   PATCH  documents đổi loại          → kb_delete_index { doc_type: <loại cũ> }
                                        (BỎ nửa index lại — để người dùng bấm)

   Nhánh cascade cấp DỰ ÁN (`anchor_code` có mặt) đọc danh sách cần xoá từ SỔ
   `kb_index_state` theo `project_code`, KHÔNG từ 4 bảng nguồn (D10) — row
   nguồn đã bị `ON DELETE CASCADE` xoá trước khi worker chạy tới.

③ MÔ TẢ TỰ ĐỘNG (enrich) — tự động, hiện ngay lên màn để người dùng sửa
   POST  .../media                    → kb_enrich
   POST  .../documents (có fileUrl)   → kb_enrich
   PATCH .../media đổi mediaUrl       → kb_enrich { force: true }     (D6)
   PATCH .../documents đổi fileUrl    → kb_enrich { force: true }     (D6)
   POST  /media/{id}/recaption        → kb_enrich { force: true }     (đã có)
   PATCH chỉ sửa caption/body         → không job nào
```

Luồng ③ **không chạm Qdrant một dòng nào** — nó chỉ dựng bản nháp trong Aurora. Đưa nội dung tới agent luôn là việc của luồng ①. Ranh giới này giữ nguyên như thiết kế hiện tại.

### 3.1 Xoá một phân khu — trường hợp riêng, phải chụp danh sách trước

Cascade cấp dự án đọc được từ sổ vì sổ mang `project_code` (D10). Cấp phân khu **không**: sổ không có `zone_code`, và thêm cột thứ hai chỉ để phục vụ một route là quá mức.

Hình dạng dữ liệu thật (`0400_kb_real_estate`):

| Bảng | Có `zone_code`? | Bị cascade khi xoá zone? | Có index lên Qdrant? |
|---|---|---|---|
`media` | có (nullable) | có | có |
`units` | có | có | **không** (không nằm trong `embed_sources`) |
`documents` | **không** — chỉ thuộc dự án | không | có |

Nên xoá một phân khu chỉ ảnh hưởng point của **chính phân khu đó** và của **media gắn phân khu đó**. Route phải đọc danh sách id media thuộc phân khu **trước** khi `DELETE` (lúc đó row còn), rồi enqueue một job xoá cho từng id cộng một job cho chính phân khu. Một phân khu thường có ít media nên N job là chấp nhận được, và mỗi job là một dòng sổ riêng nên lỗi một mục không kéo cả mẻ.

Unpublish phân khu đi cùng đường: row còn nên chụp được, và cách làm giống nhau giữ hai nhánh không lệch.

## 4. Backend

### 4.1 Migration

Một migration, hai việc trên `tenant_data.kb_index_state`:

**(a) `state` thêm giá trị `'skipped'`** vào `CHECK` (hiện là `queued`/`indexing`/`indexed`/`error`/`deleted`). `DROP CONSTRAINT kb_index_state_state_check` rồi `ADD CONSTRAINT` với 6 giá trị. Không có giá trị này thì lần nạp delta không phân biệt được "đã embed lại" với "đã kiểm, không đổi", và panel không nói được "5 mục cập nhật, 3 mục không đổi".

**(b) `+ project_code text NOT NULL DEFAULT ''`** (D10) + index `(tenant_id, project_code)`. Nullable-bằng-chuỗi-rỗng thay vì `NULL` để mọi câu đếm không phải xử lý ba trạng thái.

Backfill trong cùng migration, một câu `UPDATE … FROM` cho mỗi bảng nguồn (4 câu):

```sql
UPDATE tenant_data.kb_index_state s SET project_code = z.project_code
  FROM tenant_data.zones z
 WHERE s.entity = 'zones' AND s.record_id = z.id AND s.tenant_id = z.tenant_id;
-- projects: lấy chính project_code của nó; documents/media: tương tự zones
```

**Dòng sổ có record nguồn đã bị xoá trước khi migration này chạy sẽ giữ `project_code = ''`** — không backfill được từ đâu, cùng loại giới hạn như `KhoaOut.api_key = None` ở `0918`. Point tương ứng (nếu còn) chỉ dọn được bằng `reindex` một-record hoặc bằng reconcile khi đợt sau cài. Không cố sửa ở đây; số này nhỏ và đường sửa đã có.

Không tạo bảng mới nên không gọi `control.enforce_tenant_isolation()` — bảng này đã bật RLS từ `0501`/`0913`.

`revision` phải nối vào head hiện hành (`0918_agent_keys_them_cot_kho_tho` hoặc head mới hơn — mở file ra đọc, đừng suy từ tên). Cổng `tests/unit/test_alembic_mot_head.py` canh chuyện hai head.

### 4.2 Phép thoát sớm theo hash

Đây là hạng mục khó nhất và là chỗ dễ sai nhất của cả đợt.

**Hash phải tính trên đúng chuỗi đã sinh point** — tức nội dung chunk **sau khi** prepend breadcrumb (`"<tên dự án> — <section>"`), không phải trên cột thô. Hash cột thô thì đổi tên dự án sẽ không được nhận là thay đổi, dù breadcrumb trong mọi chunk của mọi phân khu và mọi tài liệu đều mang tên đó, và agent sẽ trả lời với tên dự án cũ mãi.

Cấu trúc lại `RagClient.index()`/`MediaClient.index()`: tách phần **dựng nội dung + tính hash** (thuần CPU, rẻ) khỏi phần **embed + ghi Qdrant** (tốn tiền, tốn mạng). `service.index_text`/`index_media` gọi phần một, so hash, rồi mới quyết định có gọi phần hai.

Thứ tự ở `service` (thứ tự này là hợp đồng, đảo lên là ghi "đã nạp" cho thứ chưa lên Qdrant):

```
đọc row → None thì trả None (caller chuyển sang xoá)
  → dựng directive → dựng nội dung chunk → hash
  → mode='delta' và hash == hash đã lưu và dòng sổ đang ở state 'indexed'
        → save_state(state='skipped', chạm indexed_at, GIỮ NGUYÊN content_hash và points)
        → trả IndexResult(points_upserted=0, skipped=True)
  → ngược lại: save_state('indexing') → embed → upsert → save_state('indexed')
```

Điều kiện `dòng sổ đang ở state 'indexed'` là bắt buộc: một record từng lỗi (`state='error'`) có hash trùng vẫn phải nạp lại — hash trùng chỉ nói nội dung không đổi, không nói point đã lên Qdrant.

`mode='full'` bỏ qua phép so hoàn toàn. "Nạp lại toàn bộ" phải thật là toàn bộ, vì đó là công cụ duy nhất người dùng có khi nghi Qdrant sai.

### 4.3 Trạng thái theo dự án

`repo.trang_thai_du_an(conn)` — một câu SQL trả trạng thái **mọi** dự án của tenant. Phải mang vị từ `tenant_id = portal.current_tenant()` tường minh: cổng `tests/isolation/test_loc_tenant_o_tang_app.py` quét tĩnh, nó không biết `$1` mang gì.

Ba nguồn ghép lại theo `project_code`:

| Nguồn | Cho ra |
|---|---|
`control.jobs` (`kind IN ('kb_index','kb_sync_project')`, `state IN ('queued','running')`, `payload->>'project_code'`) | `pending` — số job còn chờ |
`kb_index_state GROUP BY project_code` (D10) | `total`, `errorCount`, `lastSyncedAt` = `max(indexed_at)` |
4 bảng nguồn LEFT JOIN sổ theo `(entity, record_id)` | `staleCount` — record published có `updated_at > indexed_at` hoặc chưa có dòng sổ |

Cột `project_code` mới (D10) làm hai nguồn đầu thành câu một-bảng. Nguồn thứ ba **vẫn phải** đọc 4 bảng nguồn: `staleCount` cần `updated_at` của record, thứ chỉ bảng nguồn có. Nối theo **từng** bảng rồi mới gộp — nối thẳng bằng `record_id` là trộn id của 4 bảng có 4 sequence riêng.

`kb_index` payload thêm khoá `project_code` (chỉ là một khoá JSON) để đếm `pending` không phải JOIN ngược. `ops/sync.py` và `ops/backfill.py` cùng phải đặt khoá này, và `repo.save_state()` nhận thêm tham số `project_code` để ghi vào cột mới.

### 4.4 Endpoint

`GET /api/v1/projects/kb-status` — viết lại `kb-sync-status`. Giữ đường dẫn cũ? **Không**: đổi tên vì response đổi hình dạng hoàn toàn, và không có ai đang gọi đường cũ nên không phá gì. Route này phải đứng **trước** `GET /projects/{project_code}` trong router (Starlette khớp theo thứ tự đăng ký, `{project_code}` nhận mọi chuỗi).

```json
[{ "projectCode": "DPR-01",
   "state": "stale",
   "pending": 0, "total": 116, "staleCount": 8, "errorCount": 0,
   "lastSyncedAt": "2026-08-11T10:32:00Z" }]
```

| `state` | Điều kiện | Nhãn trên màn |
|---|---|---|
`running` | `pending > 0` | ◐ Đang nạp — 12/116 |
`error` | `errorCount > 0` | ✕ 3 mục lỗi |
`stale` | `staleCount > 0` | △ 8 mục chưa nạp |
`never` | `total = 0` | ○ Chưa nạp lần nào |
`synced` | còn lại | ● Agent đã có bản mới nhất |

Thứ tự ưu tiên đúng như bảng. `running` che `stale` vì đang chạy thì con số lệch đang giảm dần, hiện "chưa nạp" làm người dùng bấm lại. `error` che `stale` vì lỗi là thứ cần xử lý trước.

`POST /projects/{code}/sync-kb` nhận thêm `?mode=delta|full`, mặc định `delta`. Vẫn `202`, vẫn ghi nhật ký (BR13) — nạp lại toàn bộ là việc tốn tiền, phải lần được ai bấm.

### 4.5 Bảng thay đổi theo file

| File | Thay đổi |
|---|---|
`migrations/versions/<mới>` | `'skipped'` vào `CHECK` + cột `project_code` + index + backfill 4 câu (§4.1) |
`kb/contracts.py` | `IndexResult` thêm `skipped: bool`; `IndexState` thêm `'skipped'`; hằng `MODE_DELTA`/`MODE_FULL` |
`kb/clients/rag.py` · `media.py` | tách dựng-nội-dung-và-hash khỏi embed-và-ghi |
`kb/service.py` | `index_text`/`index_media` nhận `mode`, cài phép thoát sớm; `delete_cascade` đọc sổ theo `project_code` thay vì `fanout.children_of_anchor()` |
`kb/source/fanout.py` | **không còn ai gọi** `children_of_anchor()` ở đường cascade-khi-xoá (row nguồn đã bị CASCADE xoá). Giữ hàm cho reconcile đợt sau, thêm docstring nói rõ nó chỉ dùng được khi row còn |
`kb/jobs.py` | `handle_index` đọc `mode`; `handle_sync_project` chuyển `mode` xuống job con; `handle_delete` nhánh cascade đọc sổ |
`kb/ops/sync.py` | payload job con thêm `project_code` + `mode` |
`kb/ops/backfill.py` | payload thêm `project_code` |
`kb/state/repo.py` | `+ project_status()`; `+ indexed_of_project()` (cho cascade); `save_state` nhận `project_code`, và với `state='skipped'` giữ nguyên `content_hash`/`points` |
`realestate/router.py` | `sync-kb` nhận `mode`; `kb-status` viết lại; 6 route DELETE/PATCH thêm enqueue xoá; 2 route PATCH thêm enqueue enrich; `PATCH documents` bỏ nửa index lại |
`realestate/repo.py` | `+ media_ids_of_zone()` — đọc id media gắn một phân khu, gọi **trước** `DELETE`/unpublish (§3.1) |

`kb/router.py` (`reindex`, `index-status`) **không đổi** — nó là đường một-record, vẫn dùng được.

## 5. Frontend

### 5.1 Component

| File | Trách nhiệm |
|---|---|
`realestate/components/TheKienThuc.tsx` 🆕 | Badge 5 trạng thái. Nhận `TrangThaiKb`, trả một `<span>`. Không tự gọi API — dùng ở hai chỗ nên không được tự query |
`realestate/components/NutNapKienThuc.tsx` 🆕 | Nút + menu 2 lựa chọn + hộp xác nhận cho "nạp lại toàn bộ" (nêu rõ số mục sẽ nạp lại). Nhận `projectCode` + trạng thái |
`realestate/useTrangThaiKb.ts` 🆕 | react-query, **một** query cho cả trang (`GET /projects/kb-status`). `refetchInterval` bật chỉ khi có dự án `running`, tắt khi hết |
`realestate/useTrangThaiEnrich.ts` 🆕 | Poll `enrich-status` mỗi 3s, chỉ khi còn job `queued`/`running`. `invalidateQueries` danh sách media/tài liệu khi một job sang `success` để ô mô tả tự có chữ |
`realestate/api.ts` ✏️ | `+ trangThaiKb()` · `napKienThuc(code, mode)` · `taoLaiMoTa(mediaId)` |
`realestate/components/DuAnList.tsx` ✏️ | cột thứ 6 "Kiến thức agent": badge + nút menu mỗi dòng |
`realestate/components/KhungDuAn.tsx` ✏️ | badge + nút cạnh `<h2>` mã dự án, trên hàng tab (thấy từ cả 9 tab) |
`realestate/components/VungMedia.tsx` ✏️ | **caption hiện CHỈ ĐỌC** (`<p>{m.caption \|\| '(chưa có chú thích)'}</p>`) — đây là nơi ảnh trong kho hiện ra, nên phải thêm ô sửa được + "◐ Đang tạo mô tả…" + nút "↻ Tạo lại mô tả". Không có bước này thì mô tả tự động hiện lên mà người dùng **không sửa được**, tức nửa yêu cầu bị bỏ |
`realestate/components/OMedia.tsx` ✏️ | ô cover/map: caption đã sửa được, chỉ thêm trạng thái enrich + nút tạo lại. **Viết lại docstring** — tuyên bố `⚠ caption NHẬP TAY` hết đúng |
`realestate/components/TaiLieuTab.tsx` ✏️ | cùng cách cho `body`: "◐ Đang bóc nội dung tệp…". **Viết lại docstring** `⚠ body NHẬP TAY` |
`lib/msw/handlers.ts` ✏️ | 3 handler mới |

Badge trên danh sách hiện trong ô tên dự án (cạnh dòng `⚠ Thiếu: …` đã có) **hoặc** cột riêng — chọn cột riêng vì ô tên đã mang mã + tên + cảnh báo thiếu dữ liệu, thêm badge thứ tư vào đó là bốn thông tin trong một ô.

### 5.2 Nhãn tiếng Việt

```
Nút:    [Nạp kiến thức cho agent ▾]
          ├ Chỉ phần mới thay đổi (8 mục)
          └ Nạp lại toàn bộ dự án
Badge:  ● Agent đã có bản mới nhất
        ◐ Đang nạp — 12/116
        △ 8 mục chưa nạp
        ○ Chưa nạp lần nào
        ✕ 3 mục lỗi
Enrich: ◐ Đang tạo mô tả…      (ảnh)
        ◐ Đang bóc nội dung tệp…  (tài liệu)
        ↻ Tạo lại mô tả
```

Không dùng "index", "kho vector", "đồng bộ", "Qdrant", "embed" ở bất kỳ chuỗi nào người dùng đọc được (D7).

## 6. Bất đồng bộ

Ràng buộc tường minh của người yêu cầu, áp cho cả hai repo.

**Backend.** Không endpoint nào chờ Qdrant hay model. Cả ba đường ghi (`sync-kb`, `recaption`, mọi enqueue trong DELETE/PATCH) chỉ `INSERT` vào `control.jobs` rồi trả `202` — request kết thúc trong một chuyến DB. Trong worker: `AsyncQdrantClient` (bản đồng bộ nuốt event loop), `httpx.AsyncClient` cho embed/VLM, mọi thứ CPU nặng (Docling, render PDF, sha256 trên tệp) qua `asyncio.to_thread`. Phép hash mới tính trên chuỗi đã có trong bộ nhớ nên chạy thẳng, không cần thread.

**Frontend.** Không `await` chặn UI. Bấm nút → `useMutation` → badge sang "◐ Đang nạp" ngay bằng cập nhật lạc quan, rồi poll xác nhận. Upload ảnh xong là dùng được ô ngay, mô tả tự chảy vào sau. Hai hook poll đều có **điều kiện dừng tường minh** — không timer nào chạy nền vô hạn.

## 7. Xử lý lỗi

| Tình huống | Hành vi |
|---|---|
Một job con lỗi giữa 116 job | Job đó ghi `state='error'` + `error`; 115 job còn lại chạy tiếp. Badge chuyển `error`, panel hiện mục nào lỗi |
Embed service trả thiếu phần tử | `raise` **trước** khi ghi sổ `indexed` (hành vi hiện có, giữ nguyên) — point cũ đã xoá nên ghi "đã nạp" là mất dữ liệu im lặng |
Job enrich lỗi (CDN 404, Pillow không đọc được) | Caption không có; thumbnail lỗi chỉ ghi log, không làm đổ job (hành vi hiện có). FE hiện lại ô trống + nút "↻ Tạo lại mô tả" |
Worker chết giữa job | `control.jobs` có cơ chế thu hồi job `running` quá 15 phút (migration jobs). Badge vẫn `running` tới khi thu hồi — chấp nhận |
Người dùng bấm nạp khi đang nạp | Nút vô hiệu hoá khi `state='running'`. Bấm hai lần vẫn an toàn: `upsert` idempotent theo point-id, `save_state` là `ON CONFLICT DO UPDATE` |
Người dùng đang gõ caption thì job enrich ghi vào | Chỉ xảy ra khi họ vừa thay ảnh (D6). FE hiện "◐ Đang tạo mô tả…" và khoá ô **chỉ trong lúc đó**, mở lại khi xong |
Xoá dự án rồi worker mới chạy tới job cascade | Row con đã bị `ON DELETE CASCADE` xoá; job đọc sổ `kb_index_state` theo `project_code` (D10) nên vẫn xoá đủ point. Dòng sổ có `project_code = ''` (di sản trước migration) không dọn được đường này — xem §4.1 |
Xoá tenant | `kb_index_state.tenant_id` là FK `ON DELETE CASCADE` tới `control.tenants`, nên sổ biến mất cùng tenant. Collection Qdrant do `collections.drop()` lo, gọi sau khi `DELETE control.tenants` thành công (đường có sẵn, không đổi) |

## 8. Test

| Tầng | Đo gì |
|---|---|
`tests/unit/` | thoát sớm: hash giống → `state='skipped'`, **không** gọi embed lần nào (fake đếm lời gọi), `indexed_at` **có** được chạm, `content_hash`/`points` giữ nguyên |
`tests/unit/` | hash tính **sau** khi prepend breadcrumb: đổi `projects.name` → hash của mọi `zones`/`documents` con đổi theo |
`tests/unit/` | `state='error'` + hash trùng ⇒ **vẫn** nạp lại |
`tests/unit/` | SQL trạng thái dự án: 5 trạng thái + thứ tự ưu tiên `running > error > stale > never > synced` |
`tests/modules/kb/` | `mode='full'` bỏ qua phép so hash |
`tests/modules/realestate/` | 6 route DELETE/PATCH enqueue đúng `kind` + payload; `PATCH media` đổi `mediaUrl` → `kb_enrich force=true`, chỉ đổi `caption` → **không** job nào |
`tests/modules/realestate/` | `PATCH documents` đổi loại: có job xoá, **không** có job index (nửa auto đã bỏ) |
`tests/modules/kb/` | **cascade sau khi row nguồn đã biến mất**: xoá dự án ⇒ row con bị `ON DELETE CASCADE`, job cascade vẫn xoá đủ point vì nó đọc sổ. Đây là test quan trọng nhất của đợt — nó là chính cái lỗi mà D10 sửa |
`tests/modules/realestate/` | xoá phân khu (§3.1): enqueue đúng job cho chính phân khu **và** cho từng media gắn phân khu đó; `documents` cùng dự án **không** bị enqueue xoá (nó không thuộc phân khu) |
`tests/isolation/` | câu SQL mới ở `repo.project_status()` và `indexed_of_project()` mang vị từ tenant tường minh |
`tests/integration/` | migration: backfill điền đúng `project_code` cho 4 entity; dòng sổ có record nguồn đã xoá giữ `''` |
`tests/unit/test_alembic_mot_head.py` | (cổng có sẵn) migration mới không tạo head thứ hai |
FE `vitest` | `TheKienThuc` map 5 trạng thái đúng nhãn |
FE `vitest` | hook **ngừng** poll khi không còn job — test này bắt đúng lỗi timer chạy mãi |
FE `msw` | 3 handler mới |

## 9. Ngoài scope, cố ý

- **`handle_reconcile`** vẫn `NotImplementedError` (D9). Hàm so lệch `ops/reconcile.diff()` và `ops/fanout_tenant.py` đã có, chờ một đợt riêng.
- **Nạp nhiều dự án trong một cú bấm.** Nút nằm từng dòng nên bấm lần lượt được; một nút "nạp cả tenant" là đường dễ tốn tiền nhất và chưa ai cần.
- **`units`** vẫn không embed (`settings.ENTITIES` có nó nhưng `embed_sources` không) — agent lọc căn bằng SQL trên cột thật.
- **Chỉ báo tiến độ trong lúc chạy chi tiết hơn `N/M`.** Panel chi tiết từng mục là việc của một đợt sau nếu người dùng thấy cần.

## 10. Tài liệu liên quan

- Ingest hiện hành: `docs/superpowers/specs/2026-08-10-ingest-qdrant-design.md` (§6.2 là bước thoát sớm mà spec này cài)
- Plan ingest: `docs/superpowers/plans/2026-08-10-ingest-qdrant.md`
- Tab kiến thức BĐS: `docs/superpowers/specs/2026-08-10-tab-kien-thuc-bds-design.md`
- Hợp đồng đọc của agent: `docs/contracts/mat-bang-agent.md`
