# Cây thư mục — module ingest KB

> Bản chốt, gom mọi quyết định của brainstorm 2026-08-03. Hợp đồng DB ở
> `02c-kb-ingest-module.md`; ranh giới với santa-models ở `2026-08-03-be-only-architecture-design.md`.

## 1. Code

### 1.0 Khai báo lĩnh vực — nằm TRONG module, chỉ phần ingest cần

Ingest đọc đúng **4 khoá** của template: `anchor` · `embed_sources` · `media.visual` ·
`caption_profiles`. Ba thứ còn lại của template (`fields` cho `/form-schema`, `enums`,
`completeness`) là đồ của **M4** — ingest không đọc, nên **không mang sang**.

Vì vậy tầng khai báo đặt ở `modules/kb/directive/verticals/` (xem §1.1), **không** ở `core/`:

- giữ mọi thứ trong một thư mục → isolate tuyệt đối, không tạo file ngoài module;
- không đảo chiều phụ thuộc — M4 không phải import qua `kb.contracts` để lấy `FieldSpec`;
- `fields`/`completeness` phụ thuộc bộ ~40 cột M4 chưa `ALTER` → khai bây giờ là khai trong hư không.
  `rag_config` thì đã có **nguyên văn, đã chạy** ở repo cms → là copy, không phải thiết kế.

**Nợ đã biết:** trong lúc chuyển tiếp có **hai chỗ khai lĩnh vực** (`rag_config` ở đây, `fields` ở
M4) → M4 thêm cột mà quên thêm vào `embed_sources` thì không ai biết. Chống bằng
`test_schema_hop_dong.py`: mọi field trong `embed_sources` phải tồn tại trong `information_schema`.
Khi M4 dựng template đầy đủ → hợp nhất về `portal/verticals/`, thư mục này teo thành một import.
Ghi lại nợ này ở header `directive/verticals/registry.py`.

### 1.1 Module

```
src/portal/modules/kb/
├── __init__.py
├── contracts.py          MẶT TIỀN CÔNG KHAI — Protocol + DTO (IndexDirective ·
│                         IndexResult · IndexState). File DUY NHẤT module khác đọc.
├── router.py             ⚠ TÊN BẮT BUỘC (api/registry.py quét đúng tên này, cần biến ROUTER)
│                         GET /kb/{entity}/{id}/index-status · POST /kb/{entity}/{id}/reindex
├── jobs.py               ⚠ TÊN BẮT BUỘC (worker import portal.modules.kb.jobs)
│                         register("kb_index" · "kb_delete" · "kb_reconcile")
│                         payload = {vertical, entity, record_id, op} — CÓ `vertical`,
│                         nếu thiếu thì worker không biết tra template nào (vertical #2 vỡ)
├── service.py            ĐIỀU PHỐI 1 job: source → directive → storage → clients → state
├── fake.py               FakeRagClient · FakeMediaClient · FakeObjectStore
│                         → 80% module test được không cần GPU/Qdrant/S3
│
├── source/               ĐỌC Postgres (chỉ đọc, trong tenant_conn → RLS)
│   ├── query.py           SINH SQL từ EntitySpec (bảng · cột anchor · fields · JOIN anchor)
│   │                      — vertical-agnostic. KHÔNG viết tay 5 câu cho real_estate.
│   ├── reader.py          chạy câu sinh ra + kèm anchor name/status
│   └── fanout.py          cascade anchor: anchor rời published → cả cây con (từ EntitySpec)
│
├── directive/            template → chỉ thị đã resolve (KHÔNG gửi config thô — §4.2c)
│   ├── resolve.py         đọc rag_config của vertical: ghép fields · strategy · doc_type · section
│   ├── profiles.py        category → caption_profile · pdf → extract_profile
│   └── verticals/         KHAI BÁO LĨNH VỰC — chỉ phần ingest cần (§1.0)
│       ├── base.py        EntitySpec: table · anchor_col · fields · join · doc_type
│       ├── registry.py    {"real_estate": …} + get(vertical)   ← header ghi nợ hợp nhất
│       └── real_estate.py RAG_CONFIG nguyên văn (§15.1) + media.visual 7 giá trị
│
├── storage/              S3/MinIO — portal là nơi DUY NHẤT có quyền ghi (§4.2a)
│   ├── object_store.py    prefix tenants/<slug>/ · presign GET TTL ngắn · delete
│   └── thumbnail.py       WebP thumb (chốt §14.3a: portal làm, không cấp quyền ghi cho service)
│
├── clients/              HTTP → santa-models (bearer SANTA_MODELS_TOKEN)
│   ├── base.py            IndexClient chung: /index · /admin/* · auth · retry
│   ├── rag.py             :8016  chỉ khác base_url + cách dựng body
│   ├── media.py           :8015  idem  → collection thứ 3 sau này = 1 file mỏng
│   └── retry.py           timeout · backoff · 429 backpressure (§10)
│
├── state/                GHI Postgres
│   └── repo.py            kb_index_state upsert · write-back caption/extracted_text/thumb_url
│
└── ops/                  đường CLI/cron, không nằm trên request người dùng
    ├── collections.py     provision/teardown <slug>_documents & <slug>_media (idempotent)
    ├── reconcile.py       published@Postgres vs /admin/scroll → bù thiếu, xoá thừa
    ├── backfill.py        re-index toàn bộ từ Postgres (đổi model/schema · migrate media_v3)
    └── fanout_tenant.py   ⚠ cron KHÔNG có JWT: lặp tenants → enqueue MỘT job/tenant,
                           mỗi job chạy trong tenant_conn() bằng role portal_api.
                           Tuyệt đối không quét thẳng bằng connection admin — đó là
                           đường duy nhất trong module này lách được RLS.
```

**Vì sao đúng 6 subfolder** — mỗi cái cô lập một trục thay đổi:

| | Cô lập cái gì |
|---|---|
| `source/` | M4 đổi cột → chỉ đập vào 2 file |
| `directive/` | tri thức vertical — sửa `rag_config` không lan sang HTTP |
| `storage/` | quyền ghi S3 · biên cách ly prefix — cần review riêng |
| `clients/` | biên contract 2 repo — chỗ duy nhất biết santa-models tồn tại |
| `state/` | bảng của chính module |
| `ops/` | không nằm trên đường người dùng chờ |

## 2. Test — mirror 6 subfolder

```
tests/modules/kb/
├── conftest.py           SEED 8 HÀNG phủ mọi nhánh: project published · __ALL__ ·
│                         project draft · zone dưới project draft · documents có body ·
│                         documents body rỗng+file_url · media MinIO · media URL ngoài ·
│                         media category ngoài 7 giá trị
├── test_schema_hop_dong.py   đọc information_schema → M4 đổi cột là CI ĐỎ NGAY
├── test_source_reader.py     · test_source_fanout.py    (cascade)
├── test_directive.py         (ghép fields · chọn strategy/profile)
├── test_storage.py           (prefix · presign · thumbnail)
├── test_clients.py           (retry · 429 · nhánh file_url=null)
├── test_state.py             (upsert · write-back "user thắng")
└── test_ops.py               (reconcile diff · provision idempotent)

tests/integration/test_kb_round_trip.py   ❌ CHƯA VIẾT — chờ /index ở santa-models
                                          round-trip index→search · golden vector · incremental
```

Ba test đó không viết được hôm nay: chúng cần `/index` thật, và một file test chỉ toàn
`skip` là tiếng ồn chứ không phải cổng. Viết cùng lúc với Phase 4/5 của santa-models.

`make test-module M=kb`

## 3. Migration & docs

```
migrations/versions/
├── 0500_kb_documents.py       bảng documents (M6 sở hữu)  + enforce_tenant_isolation()
└── 0501_kb_index_state.py     bảng kb_index_state          + enforce_tenant_isolation()
                               ⚠ down_revision trỏ head hiện tại — DÒNG DUY NHẤT xung đột

docs/db-design/02c-kb-ingest-module.md      hợp đồng đọc/ghi Postgres
docs/superpowers/specs/…-m6-kb-ingest.md    spec module (mở đầu bằng bảng đối chiếu §2)
```

**Cần từ M4 trước khi chạy:** migration DDL-only cho `zones` + `media` theo `02a`.

## 4. Không sửa file nào khác

`api/registry.py` tự quét `router.py` · `worker/__main__.py` tự import `jobs.py` ·
`contracts/actions.json` dùng `catalog.read|write` đã có · `core/*` không đụng.
