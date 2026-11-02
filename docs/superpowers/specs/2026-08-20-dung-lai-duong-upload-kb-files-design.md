# Dựng lại đường upload cho màn «Tài liệu tra cứu» (`/kb`) — kho `kb_files` trên pipeline kb hiện hành

Ngày: 2026-08-20 · Trạng thái: đã duyệt hướng A với người dùng, chờ duyệt spec

## 1. Bối cảnh — màn `/kb` hỏng từ 2026-08-04, và vì sao

FE gọi `GET/POST/DELETE /api/v1/kb/files` (hợp đồng ở
`odyssey-portal-frontend/src/features/kb/api.ts`). Backend **từng có** đủ ba route
(commit `0390d86`, M6 nạp tài liệu đầu-cuối, 31/07/2026), nhưng merge `66ff3e7`
"[Fix conflict]" ngày 04/08 chọn phương án A của `MERGE-REVIEW-kb.md` — lấy trọn
module kb của develop, **xoá bản M6 upload cũ**: cả ba route, pipeline
parse/chunk/embed riêng của nó, và test. Mục B2 của chính file đó đã cảnh báo
"FE sẽ 404" — không ai nối lại từ đó.

Hiện trạng đo được (2026-08-20, backend đang chạy + OpenAPI):

- `GET /api/v1/kb/files` → 404. Màn `/kb` không load được dưới `VITE_MSW=0`.
- Bảng `tenant_data.kb_files` (migration `0300`) còn nguyên, **có người đọc**
  (dashboard ops `kien_thuc()` đếm nó; enrollment đọc `chunk_count`) nhưng
  **không còn ai ghi** và không route nào phục vụ.
- Module kb ngày nay đã tự làm trọn pipeline trong portal (không còn chờ
  rag_service của santa-models): `clients/extract.py` (pdf/docx/xlsx → Markdown),
  `index/chunker.py`, `clients/embed.py` (dense+sparse), `index/store.py`
  (Qdrant), `storage/object_store.py` (S3/MinIO). Cái thiếu duy nhất là đường
  orchestration cho tệp cấp workspace.

## 2. Quyết định kiến trúc

**Chọn: dựng lại kho riêng `kb_files`, nối vào máy móc hiện hành của module kb.**
Không có đường ghi Qdrant thứ hai — mọi thứ đi qua chính `RagClient`/`QdrantStore`
đang phục vụ documents/zones/projects.

Hai hướng đã loại:

- **Trỏ `/kb` vào `tenant_data.documents` với `project_code='__ALL__'`** — ít
  code pipeline mới, nhưng (a) hồi sinh kho `__ALL__` mà quyết định sản phẩm
  2026-08-08 đã bỏ khỏi giao diện; (b) map `status` draft/published +
  `kb_index_state` về `dang_xu_ly/san_sang/loi` gượng; (c) chuỗi enqueue của
  documents nằm trong module realestate — kb import ruột nó là CI đỏ (Luật 3),
  tự chép lại thì thành hai bản.
- **Bỏ hẳn màn `/kb`** — người dùng đã yêu cầu dựng lại; kb_search mất nguồn
  tài liệu chung nếu bỏ.

Điểm tựa quan trọng nhất — **hợp đồng phía agent đã dự trù sẵn chỗ cho kho
này**: `kb_search` (repo `odyssey-agent`, `data/qdrant_search.py`) query
`<tenant>_documents` với filter bắt buộc `status == 'published'`, và khi lọc
theo dự án luôn union sentinel `SYSTEM_ANCHOR = "__ALL__"` — comment ghi rõ nó
tồn tại để "tenant-level content (a shared brochure, a tenant-wide policy doc)"
vẫn hiện. Point của kb_files chỉ cần mang `project_id='__ALL__'` +
`status='published'` là agent thấy, **không sửa một dòng nào bên agent**.

## 3. Hợp đồng HTTP — khôi phục ĐÚNG bản `0390d86`

Ba route thêm vào `ROUTER` sẵn có của `modules/kb/router.py` (registry tự quét,
không đụng `api/app.py`). Đường tương đối viết THẲNG `/kb/files` (router kb
không có prefix, các route hiện hành tự mang `/kb/...`). Không xung đột với
`/kb/{entity}/{record_id}/index-status` — khác số segment.

| Route | Quyền | Trả về |
|---|---|---|
| `GET /kb/files` | `catalog.read` | `list[TaiLieuOut]`, kho rỗng trả `[]` |
| `POST /kb/files` (multipart, field `file`) | `catalog.write` | **202** + `TaiLieuOut` (`state='dang_xu_ly'`) |
| `DELETE /kb/files/{id}` | `catalog.delete` | 204 |

`TaiLieuOut` khôi phục nguyên văn từ `0390d86` — camelCase, khớp từng field với
`features/kb/api.ts` của FE (FE **không sửa gì**):
`id · tenFile · loai · kichThuoc · state · chunkCount · loiMessage · uploadedAt · uploadedBy`.

Mã lỗi giữ nguyên bản cũ (hợp đồng liên tục): `UNSUPPORTED_TYPE` (422, đuôi
ngoài pdf/docx/xlsx — khớp CHECK `kb_files_loai_check`) · `FILE_TOO_LARGE`
(422, quá `GIOI_HAN_BYTE = 25 MB` — con số tạm của KB_01 BR12, giữ nguyên) ·
`NO_DOCUMENT` (404). Hằng `GIOI_HAN_BYTE` đặt ở `router.py` như bản cũ.

### POST — thứ tự là hợp đồng

1. Validate đuôi + dung lượng (đọc trọn bytes — trần 25 MB nên không cần stream).
2. **Ghi S3 TRƯỚC**: key `tenants/<tenant>/kb/<sha256>/<tên-tệp-đã-làm-lành>`
   qua `S3Store.put` (bài học `0390d86`: hàng trỏ tới key không tồn tại là một
   tài liệu đứng mãi ở «Đang xử lý»). Tên tệp trong key rút về ASCII lành; tên
   GỐC giữ nguyên ở cột `ten_file`.
3. INSERT `kb_files` (`state='dang_xu_ly'`, `uploaded_by = p.user_id`).
4. `enqueue(kind='kb_file_index', payload={'record_id': id})` — cùng giao dịch.
5. Nhật ký `kb.upload` qua `core/nhat_ky.ghi` (kèm `file_id` + `ten_file`).

### DELETE — BR07, gỡ khỏi kho tri thức NGAY, không thùng rác

1. Đọc hàng, không có → 404.
2. **Xoá hàng DB** (trong giao dịch CHƯA commit).
3. Gỡ point Qdrant: `QdrantStore.delete_by_record(collection, record_id=id,
   doc_type='kb_file')`. Dùng `QdrantStore` trần chứ không qua
   `open_dependencies()` — bộ đó dựng cả `EmbedClient` (raise khi thiếu
   `KB_SANTA_MODELS_TOKEN`), mà xoá point không cần embed; cùng lý lẽ
   `collections.xoa_kho_cua_workspace` đã ghi. Qdrant hỏng → 500 → rollback
   trả hàng lại, người dùng bấm lại.
4. Commit.
5. Xoá tệp S3 **best-effort** (hỏng chỉ `log.warning` — object
   content-addressed nằm lại vô hại; làm chặt hơn không mua được gì).
6. Nhật ký `kb.delete`.

⚠️ **Đổi từ bản đầu (Qdrant trước, hàng sau)** — thứ tự đó để lại một race với
worker `kb_file_index`: xoá-trong-lúc-nạp khiến route gỡ point TRƯỚC khi worker
kịp upsert, rồi worker `danh_dau_san_sang` thành công trên hàng đã biến mất
⇒ point `published` mồ côi vĩnh viễn (reconcile của kb_files chưa có thân —
xem §5). Xoá hàng trước (dù chưa commit) đóng race này: `DELETE` của route và
`UPDATE` của worker cùng khoá một hàng, Postgres serialize hai giao dịch nên
mọi interleaving rơi vào một trong hai nhánh sạch — worker khoá trước thì
route đợi rồi gỡ point sau khi worker upsert xong; route khoá trước thì
`danh_dau_san_sang` (nay trả `bool`) UPDATE trúng 0 hàng và worker tự gỡ
point nó vừa ghi. Đánh đổi: rollback trả hàng lại nếu Qdrant hỏng, nhưng nếu
crash đúng giữa bước 3 và bước 4 thì hàng còn `san_sang` mà mất point — hiếm,
tự chữa bằng bấm Xoá lại.

## 4. Job `kb_file_index` — một handler mới trong `jobs.py`

Orchestration đặt ở `service.index_kb_file()` (đúng vai file: "chỗ duy nhất
biết thứ tự các bước"), SQL của kb_files ở file mới `files_repo.py` (khuôn
`them/liet_ke/doc/xoa/cap_nhat_trang_thai`, tái dùng được từ `0390d86`).

Các bước, theo thứ tự (thứ tự là lời hứa — đánh dấu `san_sang` SAU CÙNG,
đúng bốn-bước của `0390d86`):

1. Đọc hàng `kb_files` theo `record_id`. Không còn → `JobResult` bỏ qua
   (người dùng xoá trước khi worker nhặt).
2. `collections.create(rag, media, slug)` — idempotent. Upload có thể là hành
   động KB đầu tiên của workspace; thiếu bước này job nổ 404 (bài học đã ghi
   trong docstring `handle_sync_project`).
3. Đọc byte từ S3 (`store.doc`). `build_key` idempotent nên `s3_key` đầy đủ
   trong cột đi thẳng được.
4. `TextExtractor(vlm=None).extract(data, filename=ten_file)`:
   - pdf có lớp chữ → pypdf; docx/xlsx → Markdown giữ heading + bảng.
   - **PDF scan (không lớp chữ) → `text=''`** → hàng thành `loi` với message
     chỉ đường: *"PDF này là bản scan, chưa đọc được chữ — tải bản có lớp chữ,
     hoặc nạp vào tài liệu của một dự án để đi qua luồng duyệt OCR."*
     Đây là quyết định KB_01 §I.2 sẵn có ("Không hỗ trợ: ảnh scan không lớp
     chữ") cộng nguyên tắc *model sinh ⇒ người xem* — màn `/kb` không có UI
     duyệt nên không auto-nạp chữ OCR. KHÔNG truyền VLM client.
5. Dựng `TextDirective` tay (không đi qua directive/source — kb_files không
   phải một entity của vertical):
   - `doc_type='kb_file'` (mới, rời khỏi mọi doc_type hiện có — vị từ xoá và
     `point_id_of` dựa vào nó)
   - `anchor_code=settings.SYSTEM_ANCHOR` (`'__ALL__'`)
   - `anchor_name=ten_file` — tiền tố chunk mang danh tính tài liệu
   - `status='published'`, `anchor_status='published'` → `status_hieu_luc` ra
     `'published'` (kho này không có khái niệm nháp — BR06 gắn vào `state`
     của chính kb_files, và chỉ hàng `san_sang` là hàng ĐÃ lên Qdrant)
   - `updated_at=uploaded_at`, `file_url=s3_key`, `file_name=ten_file`,
     `chunk=ChunkSpec()` mặc định, `section=''`, `chunk_root=()`
6. `rag.index(directive)` — chunk → embed (dense+sparse) → upsert vào
   `<tenant>_documents`. `RagClient.index` tự xoá point cũ của
   `(doc_type, record_id)` trước khi ghi nên job chạy lại an toàn.
7. UPDATE hàng: `state='san_sang'`, `chunk_count=points_upserted`,
   `loi_message=''`. `danh_dau_san_sang` trả `bool` (`RETURNING id`) — `False`
   nghĩa là hàng đã biến mất giữa lúc nạp (race với DELETE, xem §3); khi đó
   service GỠ NGAY point vừa ghi ở bước 6 thay vì để nó mồ côi.

**Chính sách lỗi: handler bắt RỘNG, mọi thất bại → hàng thành `loi` + message
nói lý-do-và-cách-sửa, KHÔNG re-raise, đăng ký `retries=0`.** Lý do từng vế:

- Hàng treo `dang_xu_ly` vĩnh viễn là chế độ hỏng tệ nhất (spinner quay mãi —
  bài học ghi trong commit `0390d86`); bắt rộng + ghi `loi` là cách duy nhất
  loại nó.
- Không re-raise vì handler chạy trong giao dịch của worker — raise là rollback
  luôn cả cú UPDATE `loi` vừa ghi.
- Retry transient đã có ở đúng tầng: `EmbedClient` tự retry (docstring của nó
  ghi rõ vì sao ở đó). Hết lượt mà vẫn hỏng thì `loi` + "thử tải lại tệp" là
  câu trả lời trung thực; đường tự chữa là tải lại.

`register(KIND_KB_FILE_INDEX, handle_kb_file_index, retries=0)` — retries > 0
vô nghĩa khi handler không bao giờ raise.

## 5. Sổ sách: `kb_files` là sổ DUY NHẤT — không ghi `kb_index_state`

Điều chỉnh so với phác thảo miệng ban đầu (đã nói "ghi sổ kb_index_state"),
phát hiện khi xác minh:

- `kb_index_state.entity` có CHECK cứng `IN ('projects','zones','documents','media')`
  (migration `0501`) — ghi thêm entity `kb_files` đòi một migration.
- Người tiêu thụ sổ đó không cần nó cho kho này: `handle_reconcile` là
  `NotImplementedError` (chưa ai chạy); `delete` không cần tra sổ vì
  `doc_type='kb_file'` là hằng (sổ tồn tại vì documents ĐỔI doc_type — kb_files
  thì không).
- `kb_files` đã mang đủ `state/chunk_count/loi_message` — ghi cùng sự thật vào
  hai bảng là hai chỗ để lệch, đúng lớp bug repo này ghi lại nhiều lần.

Hệ quả chấp nhận được, ghi để khỏi ngạc nhiên: `/kb/kb_files/{id}/index-status`
không tồn tại (FE không dùng), và ngày `handle_reconcile` có thân thì nguồn
expected của kho này là `kb_files WHERE state='san_sang'` chứ không phải
`kb_index_state` — một câu SELECT khác, không phải rào cản.

**Không migration nào trong đợt này.** Bảng `0300` dùng nguyên trạng.

## 6. Hợp đồng hai đầu với agent — cập nhật `docs/contracts/payload-qdrant.md`

Thêm mục cho `doc_type='kb_file'`: point nằm trong `<tenant>_documents`, payload
đủ bộ khoá như mọi point khác (`project_id='__ALL__'` · `project_name=tên tệp` ·
`record_id=kb_files.id` · `status='published'` · `file_public_url`/`file_name`
để agent gửi được link tệp). Ghi rõ một wart có chủ ý: khoá `project_name`
mang **tên tệp** (không có dự án nào để gọi tên) — chỗ render của agent dùng nó
làm nhãn ngữ cảnh, tên tệp là nhãn đúng nhất hiện có.

## 7. Những thứ CỐ Ý không làm

- **OCR cho PDF scan** — theo KB_01 §I.2 (xem §4 bước 4). Ngày muốn mở: đường
  đúng là thêm luồng duyệt như documents (`cho_duyet`), không phải auto-nạp.
- **Thumbnail / caption** cho kb_files — màn FE không hiện, agent không cần.
- **Sửa `ten_collection()` (`kb_<tenant>`) và JWT Qdrant đang scope theo tên
  đó** — lệch với collection thật `<tenant>_documents` là nợ CÓ SẴN (từ
  MERGE-REVIEW-kb.md §B1), Qdrant auth chưa bật ở môi trường nào nên chưa hại;
  sửa nó là đổi hợp đồng `manifest.toml`/enrollment với agent — việc riêng,
  spec riêng. Đợt này KHÔNG chạm.
- **FE** — không đổi một dòng. MSW fake + test FE sẵn có giữ nguyên giá trị.
- **Phân trang `GET /kb/files`** — hợp đồng cũ trả trọn danh sách; kho tài liệu
  workspace cỡ chục-trăm hàng, phân trang là YAGNI.

## 8. Kiểm chứng

Test module (khuôn `tests/modules/kb/` hiện có — `FakeIndexClient`/
`FakeObjectStore` từ `fake.py`, không mạng):

1. `test_kb_files_router.py`: GET rỗng trả `[]` · POST hợp lệ ra 202 + hàng
   `dang_xu_ly` + tệp nằm trong FakeObjectStore + job `kb_file_index` được xếp
   đúng tenant · đuôi lạ 422 `UNSUPPORTED_TYPE` · quá trần 422 `FILE_TOO_LARGE`
   · DELETE gỡ point trước xoá hàng · DELETE id lạ 404 · quyền: thiếu action
   đúng mã lỗi · hai dòng nhật ký `kb.upload`/`kb.delete`.
2. `test_kb_file_index_job.py` (gọi thẳng `service.index_kb_file` +
   handler): pdf có chữ → `san_sang` + `chunk_count` khớp points_upserted +
   directive mang đúng `anchor='__ALL__'`/`doc_type='kb_file'`/`status='published'`
   · PDF scan → `loi` + message chỉ đường · embed nổ → `loi`, hàng KHÔNG treo
   `dang_xu_ly` · hàng bị xoá trước khi worker nhặt → bỏ qua êm · chạy lại
   job → không nhân đôi point (delete-trước-ghi của RagClient).
3. Cách ly tenant: kb_files đã có RLS từ `0300`; SQL mới trong `files_repo.py`
   mang vị từ `tenant_id = portal.current_tenant()` như mọi repo khác — cổng
   `make test-isolation` phải giữ nguyên baseline.

E2E trên stack local (api 8100 + worker + qdrant 6343 + minio 9002, DB seed
sẵn): login `dang@anphuland.vn` → POST một PDF thật → chờ worker → GET thấy
`san_sang` + `chunk_count > 0` → đếm point `doc_type='kb_file'` trong
`anphu_documents` → mở màn `/kb` trên :5273 thấy danh sách → DELETE → point về
0. Dashboard ô ⑤ hàng «Tài liệu tra cứu» nhảy số theo.

## 9. Phạm vi file

| File | Việc |
|---|---|
| `modules/kb/contracts.py` | + `TaiLieuOut`, `LOAI_HO_TRO`, `TRANG_THAI_KB_FILE`, `KIND_KB_FILE_INDEX`, `DOC_TYPE_KB_FILE` |
| `modules/kb/files_repo.py` (mới) | SQL kb_files: them · liet_ke · doc · xoa · cap_nhat_trang_thai |
| `modules/kb/service.py` | + `index_kb_file()` |
| `modules/kb/router.py` | + 3 route + `GIOI_HAN_BYTE` + helper lỗi |
| `modules/kb/jobs.py` | + `handle_kb_file_index` + `register` |
| `docs/contracts/payload-qdrant.md` | + mục `doc_type='kb_file'` |
| `tests/modules/kb/test_kb_files_router.py` (mới) | test router |
| `tests/modules/kb/test_kb_file_index_job.py` (mới) | test job/service |
| `CLAUDE.md` (repo backend) | một dòng Change Log |

KHÔNG chạm: `settings.py` của module kb (đang có sửa đổi chưa commit của phiên
khác — `GIOI_HAN_BYTE` vì thế đặt ở `router.py`, cũng là chỗ bản `0390d86` đặt),
migrations, FE, repo agent.
