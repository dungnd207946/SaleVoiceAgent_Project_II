# Design — dựng Qdrant local từ PG dev `.208` (chỉ-đọc)

- **Ngày:** 2026-08-13
- **Nguồn:** `postgresql://portal_api:apidev@10.50.13.208:5442/portal` — **chỉ đọc**
- **Đích:** Qdrant local `http://localhost:6343` (`odyssey-portal-backend-qdrant-1`)
- **Phạm vi:** 2 tenant `eco_green`, `anphu` — cả đường text lẫn đường media

## 1. Bối cảnh

Agent local đang đọc Qdrant EC2 qua SSM tunnel (`QDRANT_URL=http://127.0.0.1:16433`) —
mỗi lần test phải mở tunnel, và tunnel chết là RAG câm. Mục tiêu: một Qdrant local có
collection giống prod để bỏ hẳn tunnel khỏi vòng lặp phát triển.

Đo trên `.208` ngày 2026-08-13:

| tenant | projects | zones | documents | media | media có caption |
|---|---|---|---|---|---|
| `anphu` | 17 | 23 | 6 | 97 | 2 |
| `sunrise` | 17 | 10 | 6 | 90 | 1 |
| `haven` | 10 | 24 | 11 | 46 | 4 |
| `eco_green` | 7 | 11 | 0 | 37 | 1 |

(số hàng `status='published'`)

Hai dữ kiện định hình thiết kế:

- **Qdrant tại `.208:6343` rỗng hoàn toàn** và `kb_index_state` = 0 hàng ở cả 11 tenant →
  không có vector nào để copy, muốn có point thì phải embed lại từ Postgres.
- **Qdrant local `:6343` đã có vết test cũ**: `anphu_documents` (13 point), `anphu_media`
  (1), `debug_documents` (1), `wsdbg_documents` (1). Schema đúng nhưng nội dung là rác →
  phải `--recreate`, không nạp chồng.

## 2. Ràng buộc

| # | Ràng buộc | Hệ quả |
|---|---|---|
| 1 | `.208` là DB dev **dùng chung** | Không được ghi: không `kb_index_state`, không cache caption/extracted_text, không `control.jobs` |
| 2 | RLS `FORCE` trên `tenant_data`, policy đọc GUC **`app.tenant_id`** qua `portal.current_tenant()` | Mỗi connection phải `set_config('app.tenant_id', <tenant>)`; quên → 0 hàng, im lặng |
| 3 | `service.index_text`/`index_media` ghi PG ở 4 chỗ (`save_state` ×2, `cache_*`, `save_thumb_and_hash`) | Không gọi được `service.*`; script chép lại luồng và bỏ đúng 4 lời gọi đó |
| 4 | `MediaClient.index` lấy caption từ cột PG, **không tự gọi VLM** | Không enrich = point vẫn có vector `visual`; chi phí VLM bằng 0 |
| 5 | Ràng buộc 1 loại bỏ cả job `kb_enrich` | 131/134 ảnh của 2 tenant index với `caption=""` |

## 3. Kiến trúc

`experiments/nap_qdrant_local.py` — một script, chạy lại được, ghi **chỉ** vào Qdrant local.

Thư mục `experiments/` **nằm trong `.gitignore`**: đây là đồ thử tay cho một máy, không
phải phần của service. Test đi kèm nằm cạnh nó (`experiments/test_nap_qdrant_local.py`)
chứ không ở `tests/` — `testpaths=["tests"]` mà module thì không có trong git, nên test
đặt ở đó sẽ đỏ trên mọi máy khác. Chạy: `PYTHONPATH=. uv run pytest experiments -q`.

```
--tenant eco_green,anphu [--recreate] [--chi-text|--chi-media] [--limit N]
  ↓
asyncpg.connect(SRC_DSN) → set_config('app.tenant_id', <t>, false)
  ↓
ops.collections.create(rag, media, workspace_slug=<t>)      # --recreate: drop trước
  ↓ text — mỗi spec trong REAL_ESTATE.embed_sources (projects · zones · documents)
reader.list_published → reader.read_record → resolve.resolve_text → rag.index()
  ↓ media
reader.list_published → reader.read_media → profiles.should_index_media
      → profiles.resolve_media → media.index()
```

Mọi chặng gọi đúng hàm mà service gọi; chỗ duy nhất tự viết là **thứ tự gọi**. Đó là rủi
ro lệch duy nhất — service đổi luồng thì script không tự đi theo (cùng loại nợ mà
`mockdb/ingest/README.md` đã ghi cho `steps.py`).

`workspace_slug` = `tenant_id` (`jobs.workspace_slug`, CHECK ở migration 0002) → collection
`eco_green_documents` / `eco_green_media` / `anphu_documents` / `anphu_media`.

## 4. Hai chỗ cắt bỏ, có kiểm chứng

**`store=None` (không MinIO).**

- Text: `profiles.extract_profile` chỉ trả profile khi `body` rỗng **và** có `file_url`.
  Đo trên `.208`: `anphu` 6/6 documents có body, `eco_green` không có documents nào →
  nhánh presign/OCR không chạm. Script **nổ ngay** nếu gặp record cần presign, thay vì
  âm thầm index một directive thiếu nội dung.
- Media: `media_url` trỏ `https://nbx-sales-dev.noble.vn/...` → `presigned_if_internal`
  nhận URL ngoài và trả `None` trước khi chạm store.

**Không enrich.** Point media vẫn mang vector `visual` (SigLIP2 đọc thẳng `media_url`) và
vector `text` từ `f"{category} {caption}"`. Với caption rỗng, nhánh text yếu hơn prod —
đánh đổi đã chấp nhận để giữ ràng buộc chỉ-đọc và chi phí VLM bằng 0.

## 4b. Gỡ HTML — chỗ script CỐ Ý lệch pipeline

`projects.overview` mang HTML thô của editor WYSIWYG: 12/17 dự án `anphu`, 6/7 `eco_green`,
12/17 `sunrise`, 5/10 `haven`. `zones.overview` và `documents.body` sạch.

Pipeline Portal **không có bước nào gỡ nó** — không `bleach`/`lxml`/`html2text` trong
`pyproject.toml`, không chỗ nào `html.unescape` trong `modules/kb`, và `resolve.build_text`
ghép field nguyên văn. Nên `<p>Vị tr&iacute;: Tọa lạc…` đi thẳng vào vector lẫn vào đoạn
LLM đọc; nặng hơn tag là entity Latin-1 làm mất dấu tiếng Việt ngay trong không gian embed.

Script gọi đúng `RagClient.index` mà worker prod gọi, nên **Qdrant EC2 gần như chắc chắn
chứa HTML y hệt** — bản mirror trung thực sẽ mirror cả khuyết tật này.

Quyết định: gỡ HTML **chỉ ở script**, bằng `chuan_hoa_html` của `scripts/chuan_hoa_overview.py`
(đã có test riêng, idempotent, `unescape` chạy sau khi gỡ tag). `lam_sach_row` áp nó lên các
giá trị chuỗi của row trước `resolve_text`, và chỉ khi phát hiện markup thật — guard đòi tên
thẻ bắt đầu bằng chữ cái, để `Giá từ <2 tỷ > 1 tỷ` không bị ăn mất khúc giữa.

**Hệ quả:** `content_hash` và nội dung point ở Qdrant local khác Qdrant EC2 đúng ở những dự
án có HTML. Muốn hết lệch thì sửa `resolve.build_text` rồi backfill prod — việc của một đợt
riêng, không thuộc spec này.

## 5. Cấu hình

```bash
SRC_DSN=postgresql://portal_api:apidev@10.50.13.208:5442/portal
QDRANT_URL=http://localhost:6343          # + QDRANT_API_KEY từ .env local
KB_EMBED_URL=https://hence-platform-pull-charity.trycloudflare.com
KB_SANTA_MODELS_TOKEN=<từ .env local>
```

Sau khi nạp xong, đổi `.env` của repo agent: `QDRANT_URL` từ `http://127.0.0.1:16433`
(tunnel EC2) sang `http://localhost:6343`. `NOBLE_RAG_BACKEND=kb_service` giữ nguyên.

## 6. Verify

1. `GET /collections` → có 4 collection; `_documents` mang `dense`+sparse `bm25`,
   `_media` mang `text`+`visual`.
2. `points_count`: text ≥ số record published (chia chunk nên ≥); media = số record
   published trừ những category ngoài `media_visual`.
3. Một point mẫu: payload đủ `project_id` · `anchor_code` · `entity` · `record_id` ·
   `content_hash`.
4. Repo agent: `make test-search ARGS="-t eco_green"` với `QDRANT_URL` local → query
   thật trả kết quả.
5. `python scripts/chat_repl.py -t eco_green --ask "..."` → agent trả lời có dẫn nguồn.

## 7. Ngoài phạm vi

- Enrich VLM (caption) và sinh thumb — `thumb_url` lấy nguyên từ PG, thiếu thì rỗng.
- `kb_index_state` — badge «Kiến thức agent» của Portal vẫn hiện "chưa nạp lần nào".
  Muốn dựng sổ thì chạy `dung_lai_so_kb.py`, **nhưng nó ghi PG** nên nằm ngoài spec này.
- Qdrant EC2 và mockdb — không đụng.
- `sunrise` / `haven` — chạy sau bằng cùng script, không cần sửa gì.
