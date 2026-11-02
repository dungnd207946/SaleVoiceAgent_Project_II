# Ingest lên Qdrant — làm giàu nội dung rồi đồng bộ tri thức

> Nối đường ghi Qdrant còn thiếu trong `modules/kb`, và thêm chặng làm giàu nội dung
> (caption ảnh · caption video · bóc chữ tệp) mà người dùng xem và sửa được trước khi
> nội dung đó tới tay agent.

---

## 1. Vấn đề

Đo trên Aurora dev ngày 2026-08-10: dữ liệu nghiệp vụ **đã lên Postgres AWS bình thường**
— 44 dự án · 58 phân khu · 604 căn · 269 media · 66 hội thoại trên 9 tenant. Nhưng
`tenant_data.kb_index_state` là **0 hàng ở mọi tenant**, và `control.jobs` chỉ có 3 job
`publish`; chưa từng có một job `kb_index` nào chạy.

Nguyên nhân nằm ở ba chỗ trong `modules/kb`:

| Chỗ | Trạng thái hôm nay |
|---|---|
`clients/base.py` | Cả 5 phương thức `raise NotImplementedError("cần dep httpx")` |
`jobs.py::dependencies()` | `raise NotImplementedError("chưa nối client thật")` |
`jobs.py::handle_reconcile()` | `raise NotImplementedError("thân reconcile để PR sau")` |

Thiết kế gốc (`docs/build_module_knowledgebase/02b-rag-service.md`) đặt phần chunk · embed ·
caption · ghi Qdrant ở một service `rag_service` bên repo `santa-models`. Service đó **chưa
tồn tại**, và chủ dự án đã chốt: Portal làm việc độc lập trên repo này.

Hệ quả người dùng thấy: `POST /kb/{entity}/{id}/reindex` trả 202 rồi im lặng vĩnh viễn. Và
ở màn tài liệu, ô nội dung phải **nhập tay** — `TaiLieuTab.tsx` đã ghi sẵn lời thú nhận đó
trong docstring của chính nó.

### 1.1 Điều đã có sẵn và phải tôn trọng

**8 collection Qdrant đang sống trên EC2** với 381 point, và **agent đang đọc chúng**:

```
_documents:  dense 1024 (Cosine) + sparse "bm25" (IDF)
_media:      text 1024 + visual 768
```

Point cũ mang payload `{project_id, content_type, category, caption, media_url,
content_hash, record_id, thumb_url}`, `id` là UUID5, và `record_id` **khớp đúng**
`tenant_data.media.id` trên Aurora (kiểm: id 960/964 nằm trong range 895–991 của tenant
`an-phu-land_q8w2_retail`). Chúng là bản copy từ Qdrant cũ `10.50.13.220`, không phải rác.

**Caption VLM chất lượng tốt đã tồn tại — nhưng nằm ở Qdrant, không ở Aurora:**

| | `media.caption` trên Aurora | payload point Qdrant |
|---|---|---|
`an-phu-land_q8w2_retail` | 2 / 96 | có caption |
`an-phu-land_z5r1_retail` | 1 / 90 | có caption |
`noble-homes_k3n7_retail` | 4 / 46 | có caption |
`noble-homes_k3n7_wholesale` | 1 / 37 | có caption |

`content_hash` thì đầy đủ 100%; `thumb_url` rỗng hoàn toàn trên Aurora, còn point cũ trỏ
`http://10.50.13.220:9000/…` — MinIO LAN mà EC2 không với tới được.

**Embed service dùng được ngay.** `EMBED_SERVICE_URL` (Cloudflare tunnel) phục vụ đủ bốn
kind mà hai collection cần:

```
POST /embed  {side, texts[], images[], kind}   Authorization: Bearer …
dense=intfloat/multilingual-e5-large (1024) · sparse=Qdrant/bm25
visual_text/visual_image=google/siglip2-base-patch16-256 (768)
```

Biến `KB_SANTA_MODELS_TOKEN` trong `kb/settings.py` đã dự trù đúng token này.

---

## 2. Ngoài phạm vi

- **Xây `rag_service` bên `santa-models`.** Repo đó chỉ còn là tài liệu tham khảo. Thứ duy
  nhất Portal gọi ra ngoài là embed service.
- **Đổi hình dạng collection.** Số chiều, tên vector, tên khoá payload giữ nguyên — agent
  đang đọc chúng và không có test nào hai bên bắt được một lần đổi tên.
- **Cải thiện chất lượng retrieval.** `chunk` strategy giữ đúng khai báo hiện hành.
- **`reconcile`.** Hàm `diff()` đã có ở `ops/reconcile.py`; thân job vẫn để PR sau, cùng lý
  do đã ghi ở spec `2026-08-10-tab-kien-thuc-bds-design.md` §7.
- **Đổi schema Postgres.** Thiết kế này **không cần migration nào** — xem §7 và §5.4.

---

## 3. Nguyên tắc: Aurora là nguồn sự thật, Qdrant là dẫn xuất

Mọi thứ do máy sinh ra — caption ảnh, mô tả video, chữ bóc từ tệp — **ghi vào đúng cột mà
người dùng vẫn sửa** (`tenant_data.media.caption`, `tenant_data.documents.body`). Không có
kho nháp riêng, không có bảng phụ.

Ba hệ quả kéo theo, và cả ba đều là lý do chọn nguyên tắc này:

1. Việc thu hồi 381 caption cũ từ Qdrant về (§9) chỉ là ghi vào cùng cột đó, không phải
   dựng một cơ chế thứ hai.
2. Người dùng sửa caption thì lần index sau tự lấy bản đã sửa — không cần đường đồng bộ
   ngược nào.
3. Xoá sạch Qdrant rồi dựng lại luôn được, vì mọi thứ cần thiết đều còn trong Aurora.

---

## 4. Kiến trúc — hai chặng, tách theo "ai chịu hậu quả nếu sai"

```
① UPLOAD                    ② ENRICH (tự động, bất đồng bộ)   ③ INDEX (người bấm)
POST /realestate/uploads    job kb_enrich                     nút "Đồng bộ tri thức"
   ↓ trả khoá S3               ↓ ảnh   → VLM caption             ↓ job kb_sync_project
POST /media | /documents      ↓ video → Gemini mô tả            ↓ cascade cả cây dự án
   ↓ ghi Aurora                ↓ tệp   → pypdf/docx/xlsx bóc     ↓ job kb_index mỗi record
   enqueue kb_enrich           ↓                                 ↓
                            UPDATE media.caption              chunk → embed → Qdrant
                            UPDATE documents.body                ↓
                               ↓                              UPDATE kb_index_state
                            user XEM và SỬA
```

| | ② Enrich | ③ Index |
|---|---|---|
Kết quả là gì | Bản nháp cho người đọc | Thứ agent trả lời khách hàng |
Sai thì sao | User sửa, chỉ nội bộ thấy | Khách nhận thông tin sai |
Nên | Chạy ngay, không hỏi | Người bấm, sau khi đã xem |

Đây là lý do ③ thủ công: caption do VLM sinh mà chưa ai đọc thì không được phép đã nằm
trong kho tri thức của agent.

---

## 5. Chặng ② — Enrich

### 5.1 Một job, ba nhánh

```python
# kb/contracts.py — cạnh KIND_INDEX/KIND_DELETE_INDEX đã có
KIND_ENRICH = "kb_enrich"      # payload: {entity, record_id, force?}

# kb/jobs.py
media, content_type='image' → clients/vlm.py      → caption  → media.caption
media, content_type='video' → clients/video.py    → mô tả    → media.caption
documents                   → clients/extract.py  → markdown → documents.body
```

Enqueue từ `POST /media` và `POST /documents` trong `modules/realestate`. Hằng số nằm ở
`kb/contracts.py` **chứ không ở `jobs.py`**, cùng lý lẽ đã ghi sẵn cho `KIND_INDEX` trong
file đó: luật 3 chỉ cho module khác import `contracts`, nên hằng phải đi kèm chỗ nó được
dùng qua ranh giới module. Ba job còn lại (`kb_sync_project` · `kb_provision` ·
`kb_reclaim_caption`) không bị module nào khác enqueue nên ở lại `jobs.py`.

### 5.2 Luật chỉ-ghi-khi-rỗng

Điều kiện nằm **trong câu lệnh SQL**, không ở tầng Python:

```sql
UPDATE tenant_data.media
   SET caption = $1
 WHERE id = $2 AND coalesce(caption, '') = ''
```

Job có thể chạy lại: worker restart, retry sau timeout, người dùng bấm lại. Một job retry
sau khi biên tập viên đã sửa caption sẽ **im lặng xoá công sức của họ** — không lỗi, không
log, và họ chỉ biết khi tình cờ đọc lại. Kiểm ở tầng Python không đủ: hai worker chạy song
song đều đọc thấy "đang rỗng" rồi cùng ghi.

Đường tạo lại có chủ đích: nút **"Tạo lại mô tả"** trên từng ảnh/tệp → `force: true` → bỏ
mệnh đề `AND coalesce(...)`. Có hộp xác nhận vì nó đè lên bản người dùng đã sửa.

Hệ quả: ảnh nào đã có caption — kể cả caption thu hồi từ Qdrant ở §9 — **không bao giờ bị
VLM chạy lại tự động**.

### 5.3 Ba client

**`clients/vlm.py` — caption ảnh.** DashScope `qwen-vl-max`, cùng nhà cung cấp mà agent đã
dùng (`DASHSCOPE_BASE_URL`). Nhận thẳng URL ảnh: 100% media hiện tại là CloudFront công
khai (`https://nbx-sales-dev.noble.vn/...` → `dfdzs7tailafe.cloudfront.net`), nên không cần
presign. Ảnh nào là khoá S3 nội bộ thì đi qua `ObjectStore.presign_get` — nhánh đó
`service.py` đã viết sẵn và không phải sửa.

Prompt chọn theo `caption_profiles` đã khai trong `verticals/real_estate.py`:

```
caption_full     mặc định — tong_quan · ngoai_that · noi_that · tien_ich
caption_subject  vi_tri · tien_do · mat_bang
```

**`clients/video.py` — mô tả video.** Gemini `gemini-2.5-flash`. Hai nhánh nguồn:

- YouTube → `file_data.file_uri`, Gemini tự tải, Portal không tốn băng thông.
- MP4 trong S3 → Files API upload. Hôm nay chưa có bản ghi nào dùng nhánh này, nhưng
  `POST /realestate/uploads` đã cho phép tệp lên kho nên nhánh phải có sẵn.

**Chuẩn hoá URL là bắt buộc.** Dữ liệu lưu dạng nhúng, Gemini nhận dạng xem:

```
https://www.youtube.com/embed/fSVkxmsjAEw?si=Wq2tvB-rwoAx77PG   ← trong DB
https://www.youtube.com/watch?v=fSVkxmsjAEw                      ← gửi cho Gemini
```

Hàm chuẩn hoá chỉ đổi thứ gửi đi; **cột `media_url` giữ nguyên dạng nhúng** vì frontend
dùng chính nó để nhúng iframe.

**`clients/extract.py` — bóc chữ tệp.** Bốn đường, chọn theo đuôi tệp và theo việc PDF có
lớp chữ hay không:

| Nguồn | Cách bóc | Ra |
|---|---|---|
PDF **có** lớp chữ | `pypdf` | text thuần, ghép theo trang |
PDF **không** có lớp chữ (scan) | `pypdfium2` render trang → `clients/vlm.py` profile `ocr_markdown` | Markdown do VLM đọc |
DOCX | `python-docx` | Markdown — style `Heading N` → `#`×N, bảng → bảng Markdown |
XLSX | `openpyxl` | Markdown — mỗi sheet một `##`, nội dung thành bảng Markdown |

Bảng ra **đúng hình dạng `| … |`** là có chủ đích: `chunker` strategy `structured_md` nhận
diện khối bảng bằng chính hình dạng đó để không cắt đôi nó. Một bảng giá bị xé làm hai
chunk thì nửa dưới mất hàng tiêu đề, và agent trả lời bằng những con số không còn tên cột.

**Ngưỡng "có lớp chữ" là `NGUONG_CO_CHU = 40` ký tự, không phải phép kiểm rỗng.** PDF scan
thường vẫn trả vài ký tự — watermark, số trang, chữ ký số nhúng. Kiểm `if not text` sẽ cho
ra "có chữ" rồi bỏ qua nhánh VLM, và người dùng nhận một ô nội dung gần trống mà không có
lỗi nào. Test đo **cả hai phía** ngưỡng; thiếu phía đối chứng thì ngưỡng nào cũng "đúng".

`OCR_MAX_PAGES = 20` trong `settings.py` — một PDF 300 trang không được thành 300 lời gọi
API. Chạm trần thì bóc 20 trang đầu và báo cho người dùng biết tài liệu đã bị cắt, không
im lặng trả về một phần.

### 5.3.1 Đã thử Docling rồi bỏ — ghi lại để không ai đề xuất lại mà không biết giá

Docling xuất Markdown có cấu trúc **và** có layout model thật (phân tích bảng, PDF nhiều
cột) — nó là lựa chọn hiển nhiên cho bài toán này, và bản thi công đầu đã dùng nó.

Hai điều đo được trong lúc thi công lật ngược quyết định:

1. **Không tổ hợp extras nào tránh được torch.** `docling.document_converter` import cứng
   `StandardPdfPipeline` ở top-level bất kể định dạng đang bóc; pipeline đó import cứng
   `docling_ibm_models`; gói ấy khai `torch`/`torchvision`/`accelerate` là dependency
   thẳng, không phải extra. Chỉ riêng `import DocumentConverter` đã đòi torch — chưa tới
   lượt `.convert()`. Đã thử mọi tổ hợp trên `docling-slim` 2.119.0.
2. **Giá thật: ruột 9 MB, phụ thuộc 1.35 GB.** torch 734M · scipy 86M · opencv 81M ·
   transformers 58M · pandas 50M · numpy 34M · docling_parse 33M. `.venv` đo được
   **335 MB → 1.7 GB**. `Dockerfile` copy nguyên `.venv` sang runtime image, và API với
   worker **dùng chung một image** (`docker-compose.dev.yml`, "một image, hai vai") — nên
   bản API cũng mang 1.35 GB nó không bao giờ chạm tới.

Pin `[[tool.uv.index]] pytorch-cpu` tránh được chuỗi `nvidia-*` (~2.5 GB) nhưng không tránh
được torch. Chủ dự án chốt: không đáng. `.venv` sau khi gỡ: **360 MB**.

**Cái mất:** phân tích layout cho PDF nhiều cột và bảng phức tạp. Bù lại một phần bằng
đường VLM — tài liệu nào bóc ra kém có thể xoá `body` rồi bấm tạo lại để đi nhánh
`ocr_markdown`, nơi Qwen-VL đọc bảng khá tốt. Đây là giải pháp thủ công, không tự động.

**Cổng canh:** `tests/unit/test_khong_keo_torch.py` bắt việc bất kỳ gói ML nặng nào quay
lại môi trường. Cách hỏng là âm thầm — ai đó thêm một thư viện tiện tay, image phình
1.4 GB, và không lệnh nào báo.

### 5.4 Trạng thái cho giao diện — không cột mới

```
GET /projects/{code}/enrich-status
→ [{entity, recordId, state}]        state ∈ queued | running | done | error
```

Suy thẳng từ `control.jobs`: `kind = 'kb_enrich'`, lọc theo `payload->>'record_id'`. Frontend
poll 3 giây khi còn `queued|running`, ô hiện *"Đang tạo mô tả…"*; hết thì dừng poll. Người
dùng sửa được ô ngay cả khi job chưa xong — nếu họ sửa trước, §5.2 giữ nguyên bản của họ.

---

## 6. Chặng ③ — Index

### 6.1 Nút "Đồng bộ tri thức" → một job mở màn, không phải N job

```
POST /projects/{code}/sync-kb   → 202 {jobId}
```

Enqueue **một** job `kb_sync_project`. Chính worker của job đó mới liệt kê record
`published` trong cây dự án rồi enqueue từng `kb_index` — đúng việc `ops/backfill.py` đang
làm, chỉ thu hẹp phạm vi từ cả tenant xuống một `project_code` (`ops/sync.py`).

Vì sao không để router enqueue thẳng: một dự án có 20 phân khu + 96 media thì router giữ
giao dịch mở suốt 116 lần `INSERT` trong khi người dùng ngồi chờ.

### 6.2 Đường ống một record

```
kb_index(entity, record_id)
   ↓ reader.read_record()                       ← đã có
   ↓ resolve.resolve_text() / resolve_media()   ← đã có
   ↓ chunker.split()        facts · markdown · structured_md · atomic
   ↓ content_hash = sha256(text)
   ↓ ── trùng hash trong sổ? → THOÁT, không embed
   ↓ embed  POST /embed   dense + sparse   (media: visual_image + text)
   ↓ qdrant.upsert  point_id = uuid5(doc_type:record_id:idx)
   ↓ repo.save_state(indexed, content_hash)     ← đã có
```

Ba dòng ở giữa là toàn bộ phần mới. **`service.py` không đổi một dòng** — nó vốn gọi
`IndexClient.index(directive)`; thay đổi nằm ở cài đặt đứng sau interface đó.

Bước thoát-sớm-theo-hash là lưới chặn tiền: nó biến "bấm Lưu rồi bấm Đồng bộ mà không đổi
gì" thành một truy vấn DB thay vì một lần embed.

### 6.3 Payload point giữ nguyên hình dạng cũ

Ghi đúng bộ khoá point cũ đang có (`project_id`, `content_type`, `category`, `caption`,
`media_url`, `content_hash`, `record_id`, `thumb_url`), cộng `doc_type` và `anchor_code`.

Không đổi tên khoá nào, kể cả `project_id` — tên đó thực chất mang `anchor_code` và đặt
chưa hay, nhưng agent đang đọc nó và **không có test nào ở hai repo bắt được một lần đổi
tên**. Đổi tên là việc của một đợt có kiểm chứng hai đầu.

Một sửa lỗi kèm theo: `thumb_url` mới ghi **khoá S3** hiện hành, không ghi URL của MinIO
`10.50.13.220` đã chết — đúng quy ước "lưu khoá, không lưu presigned URL" mà
`realestate/router.py` đã chốt.

### 6.4 Vòng đời collection

`ops/collections.py` hiện được gọi thẳng lúc cấp workspace. Chuyển thành job
`kb_provision`, đúng điều docstring của chính file đó đề nghị: tạo 2 collection trên Qdrant
từ xa là I/O có thể hỏng giữa chừng, và qua `control.jobs` thì có dấu vết và retry.

---

## 7. Chỉ báo lệch — thứ đóng lỗ hổng "quên bấm"

Nút thủ công mà không có chỉ báo thì dữ liệu cũ nằm im không dấu hiệu. Một endpoint, không
cột mới:

```
GET /projects/kb-sync-status
→ [{projectCode, inSync, lastSyncedAt}]
```

So `updated_at` của record trong cây dự án với `max(indexed_at)` của chính dự án đó trong
`kb_index_state`. Rẻ — một truy vấn, không phải dựng text.

Hiện ở **mức dự án**, hai chỗ: danh sách dự án (chấm cạnh tên) và đầu form dự án
(*"Đã đồng bộ 14:32"* / *"Có thay đổi chưa đồng bộ"* + nút). Không đi sâu xuống tab hay
từng hàng.

**Chỉ báo này báo thừa, có chủ đích.** Bấm Lưu mà không đổi gì cũng đẩy `updated_at` và làm
dự án hiện "chưa đồng bộ". Bù lại là §6.2: worker thoát sớm khi `content_hash` trùng. Chỉ
báo sai lệch về phía an toàn; tiền embed thì không tiêu thừa. Chỉ báo chính xác tuyệt đối
đòi dựng text và tính hash mỗi lần mở màn — đắt hơn nhiều so với thứ nó mua được.

---

## 8. Cấu hình và prompt

### 8.1 `prompts.yaml` — prompt về Portal sở hữu

```
src/portal/modules/kb/prompts.yaml
```

```yaml
caption_full:
  model: qwen-vl-max
  max_tokens: 300
  temperature: 0.2
  prompt: |
    …

caption_subject: { model: qwen-vl-max, … }
video_describe:  { model: gemini-2.5-flash, … }
ocr_markdown:    { model: qwen-vl-max, … }
```

**Đây là một thay đổi hợp đồng, không phải chi tiết thi công.** Hôm nay
`directive/verticals/profiles.py` ghi *"Portal chỉ giữ TÊN, prompt do service own (§4.2c)"*
và `PROFILE_NAMES` là "bốn profile santa-models cài". Cả hai câu đó hết đúng: `PROFILE_NAMES`
trở thành **khoá trong `prompts.yaml` của chính Portal**, và `validate()` đối chiếu vertical
với khoá có thật trong file đó. Docstring phải viết lại, không chỉ sửa một từ.

`pdf2text` biến mất khỏi danh sách profile — nó không còn là một profile của service nào,
mà là đường Docling chạy cục bộ. `document_extract` trong `verticals/real_estate.py` sửa
theo.

### 8.2 Ba điểm kèm theo

**`pyyaml` phải khai tường minh** trong `[project].dependencies`. Nó đang có trong
`uv.lock` nhưng chỉ là dep bắc cầu của nhóm dev; `uv sync --no-dev` cho image production sẽ
thiếu, và vì loader chạy lúc import module thì **app không khởi động được** — không phải
hỏng một endpoint. Đây đúng là cách `minio` từng hỏng, đã ghi trong comment ở `pyproject.toml`.

**Đọc bằng `importlib.resources.files()`**, không phải `Path(__file__).parent` — đường thứ
hai gãy khi chạy từ wheel, tức là ở production chứ không phải ở máy người viết.

**Một test cổng:** mọi profile được `verticals/*.py` tham chiếu phải có trong `prompts.yaml`,
và mọi khoá trong YAML phải parse được. Gõ sai tên profile phải đỏ ở CI, không phải lúc
worker chạy job đầu tiên trên production.

### 8.3 Quyền của bốn endpoint mới

Luật 4 buộc mọi endpoint khai `action` của nó. Dùng lại `catalog.*`, **không tạo action
mới** — cùng lý lẽ `kb/router.py` đã ghi: PQ_01 nhóm 7–8 đã gộp Dự án · Quỹ căn · Tài liệu ·
Media vào một quyền, và "đồng bộ tri thức" không phải một quyền người dùng nghĩ tới tách rời.

| Endpoint | Action |
|---|---|
`POST /projects/{code}/sync-kb` | `CATALOG_WRITE` |
`GET /projects/{code}/enrich-status` | `CATALOG_READ` |
`GET /projects/kb-sync-status` | `CATALOG_READ` |
`POST /media/{id}/recaption` (nút "Tạo lại mô tả", `force`) | `CATALOG_WRITE` |

Không đổi `actions.py` nghĩa là không phải chạy lại `make contracts`, và
`tests/actions-parity.test.ts` bên frontend không đỏ.

### 8.4 Biến môi trường mới

| Biến | Dùng cho | Rỗng thì |
|---|---|---|
`KB_SANTA_MODELS_TOKEN` | Bearer của embed service | Đã có sẵn; client raise, không gửi request không auth |
`KB_VLM_API_KEY` | DashScope qwen-vl-max | Client raise lúc dựng |
`KB_GEMINI_API_KEY` | Gemini mô tả video | Client raise lúc dựng |
`QDRANT_URL` · `QDRANT_API_KEY` | Đã có trong `core/config.py` | — |

Fail-closed lúc dựng client, cùng nếp `HttpIndexClient.__init__` đang làm.

---

## 9. Thu hồi 381 caption cũ

Job `kb_reclaim_caption`, chạy một lần mỗi tenant. Không phải script chạy tay: nó ghi vào
Aurora nên phải đi qua `tenant_conn()`, và cần dấu vết ai chạy lúc nào.

```
scroll collection _media  →  với mỗi point có caption:
    UPDATE media SET caption = … WHERE id = record_id AND coalesce(caption,'') = ''
```

Idempotent nhờ chính luật §5.2. Sau bước này, `kb_enrich` sẽ **không** gọi VLM lại cho 269
ảnh đã có caption — tiết kiệm đúng phần tiền đó.

`thumb_url` của point cũ (`10.50.13.220:9000`) **không thu hồi**: nó trỏ một MinIO mà cả EC2
lẫn máy dev đều không với tới, mang về Aurora chỉ là chép một liên kết chết.

---

## 10. Bất đồng bộ xuyên suốt

Không chỉ ở tầng job. Ba loại việc, ba cách chạy:

| Loại | Ví dụ | Cách chạy |
|---|---|---|
I/O mạng | `/embed`, DashScope, Gemini, Qdrant | `httpx.AsyncClient` dùng chung, `await` thẳng |
I/O kho | S3 presign/get | `aioboto3` (đã có trong deps) |
**CPU-bound** | Docling · pypdfium2 render · sha256 | **`asyncio.to_thread(...)`** |

Dòng thứ ba là chỗ dễ sai nhất và hỏng nặng nhất. Docling đồng bộ và một PDF 25 MB ngốn vài
giây CPU; gọi thẳng trong coroutine sẽ **đóng băng event loop của worker** — mọi job khác
đứng im, và triệu chứng nhìn giống "Qdrant chậm" chứ không giống "Docling đang chạy". Bọc
`to_thread` là bắt buộc, không phải tối ưu hoá.

Cùng lý lẽ: dùng `AsyncQdrantClient`, **không** `QdrantClient`. Bản đồng bộ nuốt event loop
y hệt, và nó là thứ mặc định khi chép code mẫu.

**Backpressure:** `WORKER_CONCURRENCY = 4` đã khai trong `settings.py` — dùng
`asyncio.Semaphore(4)` quanh lời gọi model. Embed service chạy trên `device: cpu` (endpoint
`/health` xác nhận), nên đẩy 100 request song song chỉ làm nó xếp hàng, không nhanh hơn.

---

## 11. Bề mặt thay đổi

```
modules/kb/
├─ clients/
│  ├─ base.py         ✏️ thay 5 NotImplementedError bằng cài đặt thật
│  ├─ embed.py        🆕 EMBED_SERVICE_URL · dense/sparse/visual_image · Semaphore
│  ├─ vlm.py          🆕 DashScope qwen-vl-max → caption ảnh · OCR trang PDF scan
│  ├─ video.py        🆕 Gemini → mô tả video (YouTube file_uri · mp4 Files API)
│  ├─ extract.py      🆕 Docling → Markdown, trong to_thread
│  ├─ rag.py media.py ✏️ ráp các mảnh trên thành IndexClient
│  └─ retry.py           dùng lại nguyên
├─ index/
│  ├─ chunker.py      🆕 facts · markdown · structured_md · atomic
│  └─ store.py        🆕 AsyncQdrantClient: upsert · delete · scroll · collection
├─ prompts.yaml       🆕
├─ prompts.py         🆕 loader importlib.resources + validate
├─ jobs.py            ✏️ + kb_enrich · kb_sync_project · kb_provision · kb_reclaim_caption
│                        + dependencies() nối dây thật
├─ ops/sync.py        🆕 cascade theo project_code
├─ settings.py        ✏️ trần số trang PDF gửi VLM · endpoint DashScope/Gemini
├─ directive/verticals/profiles.py  ✏️ PROFILE_NAMES đọc từ prompts.yaml, viết lại docstring
├─ __init__.py        ✏️ tuyên bố "không chunk, không embed, không qdrant-client" hết đúng
└─ service.py · directive/resolve.py · source/ · state/ · contracts.py · fake.py   KHÔNG ĐỔI

modules/realestate/router.py  ✏️ enqueue kb_enrich sau POST /media · POST /documents
                                 + POST /projects/{code}/sync-kb
                                 + POST /media/{id}/recaption          (force: đè caption)
                                 + GET  /projects/{code}/enrich-status
                                 + GET  /projects/kb-sync-status
pyproject.toml                ✏️ + docling-slim[…,models-local] · torch-cpu (pin qua
                                   [tool.uv.sources]) · opencv-python-headless · pyyaml ·
                                   httpx (production)
                                 − pypdf
```

Frontend (repo `odyssey-portal-frontend`): ô caption/body hiện trạng thái *"Đang tạo mô
tả…"* + nút "Tạo lại mô tả"; đầu form dự án và danh sách dự án hiện chỉ báo đồng bộ + nút
"Đồng bộ tri thức".

---

## 12. Lỗi

Ba nhóm, ba cách:

- **Tạm thời** (5xx, timeout, 429): `retry.py` đã có — 5 lần, backoff 1→60s. Hết thì
  `state='error'`, job `failed`, hàng ở lại để `reconcile` bù về sau.
- **Vĩnh viễn** (PDF không bóc được kể cả qua VLM, video bị gỡ hoặc private, ảnh 404):
  **không retry**. Ghi `state='error'` kèm thông điệp tiếng Việt đọc được, hiện lên giao
  diện để người dùng tự nhập. Retry 5 lần một video đã bị gỡ chỉ tốn 5 lần chờ.
- **Sai cấu hình** (thiếu token, thiếu key): raise ngay lúc dựng client, fail-closed.

---

## 13. Test

| Tầng | Cách |
|---|---|
`chunker.py` | unit thuần — 4 strategy × biên (rỗng, 1 ký tự, vượt `max_chars`, `overlap > max_chars`) |
`extract.py` | unit với fixture PDF/DOCX/XLSX (`scripts/gen_fixtures.py` đã có), gồm **PDF không lớp chữ → rơi sang nhánh VLM** |
`vlm.py` `video.py` `embed.py` | `httpx.MockTransport` — không gọi mạng thật trong CI |
`store.py` | testcontainers Qdrant (`testcontainers[qdrant]` đã có trong nhóm dev) |
`prompts.py` | cổng: mọi profile vertical tham chiếu đều có trong `prompts.yaml`, và ngược lại |
Luật §5.2 | integration: enrich → user sửa caption → enrich lại → **bản của user còn nguyên** |
Chuẩn hoá URL video | unit: `/embed/…?si=…` → `watch?v=…`, và `media_url` trong DB không đổi |
Chỉ báo lệch | integration: index → sửa record → `inSync = false` |
Payload point | integration: bộ khoá payload ghi ra **khớp đúng** bộ khoá point cũ |

`fake.py` giữ nguyên và vẫn là thứ mọi test của `service.py` dùng — đó là lý do interface
`IndexClient` không bị đụng.

---

## 14. Ràng buộc vận hành

**Chạy MỘT worker.** Spec `2026-08-10-tab-kien-thuc-bds-design.md` §7 đã chỉ ra: `run_once`
claim job theo `ORDER BY id` nhưng **chạy handler ngoài giao dịch claim**, nên với từ hai
worker trở lên, một job `kb_delete` có thể hoàn tất sau `kb_index` và xoá đúng point vừa
tạo — không lỗi, không log.

Thiết kế này không mở rộng bề mặt đó, nhưng cascade ở §6.1 đẩy hàng trăm job vào hàng đợi
cùng lúc, tức là đúng lúc người vận hành muốn tăng worker. Giữ một worker (mặc định của
`make worker`) cho tới khi `IndexPoint` mang `doc_type` và `reconcile` so theo
`(record_id, doc_type)`.

**`EMBED_SERVICE_URL` là Cloudflare quick tunnel** (`*.trycloudflare.com`) — URL đổi mỗi
lần service bên kia restart. Nó nằm trong secret backend-env nên đổi được không cần build
lại, nhưng đây là điểm hỏng nằm ngoài tầm kiểm soát của repo này. Khi nó chết, `kb_enrich`
vẫn chạy (VLM/Gemini/Docling không phụ thuộc nó) còn `kb_index` fail toàn bộ.

---

## 15. Hạn chế đã biết

**Aurora dev vẫn còn RLS, ngược với `develop`.** Đo 2026-08-10: `relrowsecurity = true` trên
cả 11 bảng `tenant_data`, tức Aurora **chưa apply `0909_bo_rls_toan_bo`** dù `CLAUDE.md` mô
tả develop là "0/10 bảng còn RLS". Mọi truy vấn kiểm chứng thủ công phải
`set_config('app.tenant_id', …)` trước, nếu không `count(*)` trả 0 và trông y hệt DB rỗng.

**Chỉ báo lệch báo thừa.** Đã nêu ở §7 — có chủ đích, đổi lấy một truy vấn rẻ.

**Bước thoát-sớm-theo-`content_hash` CHƯA CÀI.** §6.2 quy định worker so hash rồi thoát
trước khi embed, và §7 dựa vào đúng bước đó để biện minh cho việc chỉ báo lệch báo thừa
("báo sai lệch về phía an toàn, tiền embed không tiêu thừa"). Đo 2026-08-10: hash chỉ
được **tính** trong `RagClient.index`/`MediaClient.index` và **ghi** vào
`kb_index_state.content_hash`; không nơi nào trong `src/portal` đọc nó ra để so. Hệ quả:
mỗi lần bấm "Đồng bộ tri thức" là re-embed **toàn bộ** dự án, kể cả record không đổi một
ký tự — đúng chi phí mà §6.2 tồn tại để tránh. Chưa cài ở đợt này (đợt nối đường ghi
Qdrant); cần một bước đọc `kb_index_state` trong `service.index_text`/`index_media` trước
khi gọi `rag.index`.

**`enrich-status` đọc `control.jobs`, nên lịch sử trôi theo chính sách dọn job.** Nếu về sau
có job dọn hàng cũ, trạng thái enrich của record cũ biến mất — không sai, vì lúc đó
`caption` đã có hoặc đã `error`, nhưng giao diện sẽ không phân biệt được "chưa từng chạy" và
"đã chạy xong từ lâu".

**`OCR_MAX_PAGES = 20` là con số tạm.** Nó chặn chi phí nhưng cắt cụt tài liệu dài. Người
dùng có được báo (§5.3), nhưng con số này chưa dựa trên một phân bố số trang thật nào —
chưa có tài liệu scan nào trong dữ liệu hiện tại để đo. Xem lại khi có mẫu thật.

**Mất phân tích layout khi bỏ Docling.** §5.3.1 ghi đầy đủ lý do. Hệ quả thực tế: PDF nhiều
cột hoặc bảng phức tạp bóc bằng `pypdf` ra text theo thứ tự dòng của tệp, không theo thứ tự
đọc của con người — hai cột cạnh nhau có thể xen kẽ nhau trong kết quả. Chưa đo được mức độ
vì dữ liệu thật hiện chỉ có 5 tài liệu. Đường bù thủ công: xoá `body` rồi bấm "Tạo lại mô
tả" để tài liệu đi nhánh `ocr_markdown` (VLM đọc cả layout). Xem lại khi có mẫu thật đủ.

**`pypdf` không bóc được bảng thành bảng.** Với PDF, bảng ra text phẳng — `chunker` strategy
`structured_md` sẽ không nhận ra khối bảng nào để bảo vệ, nên một bảng giá dài có thể bị
cắt giữa chừng. DOCX/XLSX **không** bị: `python-docx`/`openpyxl` đọc được cấu trúc bảng
thật và `extract.py` xuất ra đúng hình dạng `| … |`. Chênh lệch này giữa các định dạng chưa
được phản ánh ở đâu trong giao diện.
