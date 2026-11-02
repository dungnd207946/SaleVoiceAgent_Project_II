# Tích hợp HippoRAG — chuẩn bị sẵn, tắt mặc định

Ngày: 2026-09-09. Nhánh: `feat/hippo-rag` (cả ba repo, rẽ từ `origin/develop`).

## 1. Mục tiêu và phạm vi

Dựng đủ code để HippoRAG chạy được trên đường dữ liệu per-tenant đang sống, **tắt mặc định**, đổi qua lại bằng một biến môi trường. Pipeline RAG hiện tại không đổi một hành vi nào.

Trong phạm vi:

- Portal build được graph HippoRAG cho một tenant từ chính chunk mà nó đã ghi vào Qdrant.
- Agent đọc được graph đó và trả lời bằng đường HippoRAG khi được bật.
- Cả hai đường tắt mặc định; tắt thì đường nạp và đường đọc bit-identical với hôm nay.

Ngoài phạm vi (nợ, xem §8):

- Không migration, không đổi lược đồ DB.
- Không chạy build trên bất kỳ môi trường nào, không bật cờ ở đâu.
- Frontend không đụng tới.
- Ba khoảng hở so với HippoRAG 2 upstream (synonym edge, recognition memory, seeding kiểu upstream).

## 2. Hiện trạng đo được

### 2.1 HippoRAG đã có trong `odyssey-agent`, nhưng đang parked

`src/noble_agent/agent/rag/hipporag/` — 7 file (~1050 dòng), 11 file test, backend `NOBLE_RAG_BACKEND=hipporag`, ~20 env knob, cộng `docs/hipporag2-explainer.html` và hai spec/plan.

Nó không dùng được trên deployment hiện tại vì hai lý do:

1. Nó đọc collection clone legacy `noble_kb_hybrid` (`QDRANT_COLLECTION`), không phải `{tenant}_documents` của đường `kb_service` đang sống. Collection đó không tồn tại trên deployment per-tenant.
2. Embedder build-time là `flat_store._Embedder` qua `EMBED_REMOTE_*`, và hợp đồng wire đó đã chết — body cũ ăn `HTTP 422 Field required: side` từ embed service đang chạy (`docs/architecture/rag.md` ghi lại phép đo).

Hệ quả: đổi `NOBLE_RAG_BACKEND=hipporag` hôm nay thì code tự phát hiện thiếu graph và degrade về đúng kết quả hybrid cũ. An toàn, và vô tác dụng.

### 2.2 Package hipporag không biết tenant

`grep -i tenant` trong cả package trả về 0 kết quả. `HIPPORAG_GRAPH_PATH` là một file toàn cục, `expander.load()` là singleton không khoá. Agent lại là một tiến trình phục vụ nhiều workspace qua `current_tenant()`. Dùng lại nguyên trạng nghĩa là một graph dùng chung cho mọi tenant — rò dữ liệu xuyên tenant, chỉ được scope theo `project`, không theo tenant.

Đây là lý do đợt này thêm backend MỚI thay vì sửa backend cũ.

### 2.3 Lỗi ánh xạ `content_hash`

`clients/rag.py:132` tính `content_hash = _hash_of(chunks)` — hash của TOÀN BỘ chunk của một record, rồi gắn cùng một giá trị vào mọi point của record đó. Builder của agent lại dùng `content_hash` làm khoá bỏ-qua theo từng passage:

```python
if not renew and chash and graph.has_passage(chash):
    n_skip += 1
    continue
```

Nối thẳng hai cái này: chunk đầu của một record vào graph, mọi chunk còn lại bị skip vì hash đã có. Một tài liệu 30 chunk chỉ vào graph 1 chunk, im lặng, không lỗi nào.

Bản portal khoá incremental theo `point_id` (danh tính chunk), `content_hash` chỉ dùng để phát hiện "record này đã đổi". File legacy của agent không sửa — nó phải giữ byte-identical.

### 2.4 Dữ kiện hạ tầng

- Agent có quyền ghi object store dưới `tenants/<id>/*` — `GetObject` + `PutObject` + `DeleteObject`, `core/storage.py::chinh_sach_tien_to`.
- Agent chỉ ĐỌC Qdrant, JWT scope đúng một collection `{tenant}_documents` (`enrollment/qdrant_jwt.py`). Nên `HIPPORAG_TRIPLE_STORE=qdrant` không khả thi cho đường per-tenant — agent không ghi được collection triple, và cũng không đọc được collection thứ hai.
- Agent đã parse và giữ sẵn block `storage` từ `/runtime-credentials` (`gateway/credentials.py:39`), nhưng KHÔNG ai chuyển nó tới đường query được: registry `storage/tenant_credentials.py` chỉ giữ role/password Postgres, không có trường S3. Nên artefact đọc bằng một khối cấu hình TĨNH riêng của agent (`HIPPORAG_ARTEFACT_*`), và tenant vào bằng `current_tenant()` trong đường dẫn khoá.

  Đây KHÔNG phải nới lỏng mới: đường `kb_service` đang sống cũng dùng khoá Qdrant TOÀN CỤC (`settings.qdrant_api_key`, `kb_service_adapter.py`) chứ không dùng `cred.kb.api_key`, và cách ly của nó đã nằm ở `current_tenant()` qua tên collection. Artefact đi theo đúng mô hình đó. Rỗng cấu hình thì loader trả `None` và backend degrade về `kb_service` — cùng chiều fail-closed.
- Portal đã có client OpenAI-compatible `/chat/completions` (`kb/clients/vlm.py`, DashScope). OpenIE dùng lại đúng hình dạng đó, không cần dependency mới.
- `control.jobs.kind` là `text NOT NULL CHECK (kind <> '')` — không có CHECK enum, nên một job kind mới cần zero migration.

### 2.5 Đối chiếu với HippoRAG 2 upstream

Theo arxiv 2502.14802:

| Upstream | Repo |
|---|---|
| phrase node + passage node, edge "contains" | có |
| synonym edge giữa phrase (cosine >= 0.8) | không có |
| query-to-triple matching (embed cả câu hỏi, khớp triple) | có, nhưng default OFF |
| recognition memory: LLM lọc triple ở query-time | cố ý bỏ ("NO LLM at query time") |
| seed = mọi passage node theo cosine, nhân weight 0.05, rank thuần PPR | không: seed top-k hybrid rồi RRF-fuse PPR với hybrid |
| damping 0.5, <= 5 phrase seed | có |

Deviation cuối là chủ ý của bản hiện có: RRF làm cho "bật hippo không bao giờ tệ hơn qdrant", đổi lấy việc làm loãng chính cái lợi của graph. Đợt này giữ nguyên deviation đó — nó là thứ khiến việc bật cờ an toàn.

## 3. Quyết định

| # | Quyết định | Lý do |
|---|---|---|
| 1 | Switch là env cấp tiến trình `NOBLE_RAG_BACKEND` | Rẻ nhất, gọn trong repo agent, không đổi hợp đồng config với FE |
| 2 | Portal làm chủ việc build graph | Portal biết chính xác lúc chunk đổi (nó vừa ghi), đã có job queue + worker + client `/chat/completions`. Agent chỉ có JWT Qdrant read-only nên không tự dựng được collection triple |
| 3 | Build tự động cùng lượt nạp, qua một job RIÊNG, gate bằng cờ | HippoRAG dùng chính chunk của pipeline hiện tại, nên bước chunking chia sẻ nguyên vẹn. Job riêng để độ chậm và tỉ lệ lỗi của LLM không chạm `state` của record |
| 4 | Artefact ở object store `tenants/<id>/hipporag/` | Không migration, không đổi hợp đồng; agent đã có quyền và đã có creds. Qdrant triple collection là tối ưu về sau |
| 5 | Backend agent mang tên MỚI `hipporag_kb` | Legacy `hipporag` giữ byte-identical, 11 file test của nó tiếp tục xanh; cái mới thuần additive |
| 6 | Frontend không đụng | Cả switch lẫn cờ build đều là env |

## 4. Kiến trúc

Hai nửa. Cái switch chỉ đổi nửa ĐỌC; nửa GHI là thứ đợt này thêm.

```
NỬA GHI (portal, worker)
  khách nạp -> handle_index / handle_kb_file_index   [Y NGUYÊN]
                 |
                 |-> chunk -> embed -> Qdrant {tenant}_documents      (đang chạy)
                 |
                 '-> if KB_HIPPO_ENABLED: enqueue(kb_hippo_build)      (THÊM, dòng CUỐI)
                        |
                        '-> handle_hippo_build:
                              scroll chunk từ Qdrant
                              -> OpenIE (LLM) chỉ chunk MỚI -> triple
                              -> merge vào graph (phrase + passage node)
                              -> embed từng triple
                              -> ghi tenants/<id>/hipporag/{graph.json, triple_emb.npz}

NỬA ĐỌC (agent, theo NOBLE_RAG_BACKEND)
  kb_service   (mặc định, đang chạy)
      kb_search -> embed query -> Qdrant hybrid -> RRF -> context

  hipporag_kb  (MỚI, opt-in)
      kb_search -> Qdrant hybrid (seed passage) ---+
                -> embed query -> khớp triple  ----+-> PPR trên graph
                                                    -> RRF-fuse với hybrid -> context
      thiếu artefact / lỗi bất kỳ -> trả đúng kết quả kb_service

  hipporag     (legacy, parked, KHÔNG ĐỤNG)
```

## 5. Repo 1 — `odyssey-portal-backend`

### 5.1 Package mới `src/portal/modules/kb/hippo/`

| File | Nội dung |
|---|---|
`contracts.py` | `KIND_HIPPO_BUILD = "kb_hippo_build"`, dataclass `Triple`, `Passage`, hình dạng artefact, tiền tố object store |
`openie.py` | Client `/chat/completions` theo đúng hình dạng `VlmClient`; parse triple; 429/5xx/timeout bọc `TemporaryError` sẵn có để job retry |
`graph.py` | Dựng và merge graph. Hàm THUẦN over injected `chunks` + `extract_fn` — test không cần Docker/LLM/Qdrant. Khoá incremental theo `point_id` |
`artefact.py` | Serialize `graph.json` + `triple_emb.npz`; ghi và đọc lại qua `ObjectStore` sẵn có |

Profile prompt `openie_triple` thêm vào `kb/prompts.yaml`, cùng khuôn `caption`/`ocr_markdown` (model, prompt, max_tokens, temperature 0).

### 5.2 Nối dây

- `kb/jobs.py`: `register(KIND_HIPPO_BUILD, handle_hippo_build)`. Handler đọc chunk bằng `store.scroll` (đường reconcile đã dùng), OpenIE chunk mới, merge vào graph đọc lại từ artefact, ghi lại.
- Nối vào đường nạp bằng một WRAPPER ở chỗ `register()`, KHÔNG sửa thân handler:
  ```python
  def _kem_hippo(handler: JobHandler) -> JobHandler:
      async def _bao(conn, payload):
          ra = await handler(conn, payload)
          if get_env().hippo_enabled:
              await hippo_jobs.xep_build(conn, payload)
          return ra
      return _bao

  register(KIND_KB_FILE_INDEX, _kem_hippo(handle_kb_file_index), retries=0)
  register(KIND_INDEX, _kem_hippo(handle_index), retries=RETRY_VIEC_KB, max_concurrency=LANE_INDEX)
  ```
  Lý do không phải "một dòng ở cuối handler" như bản đầu của spec này viết: `handle_index` có BỐN điểm `return` và `handle_kb_file_index` có HAI (một trong khối `except`). Một dòng ở cuối thân hàm chỉ phủ một trong sáu đường ra, và sáu bản sao của cùng một dòng là sáu chỗ để quên. Wrapper phủ mọi đường ra, chỉ đụng đúng hai dòng `register(...)`, và với cờ tắt thì nó thêm đúng một lời gọi hàm cộng một phép so bool.

  `xep_build` gọi `enqueue`, hàm này đòi cả `tenant_id` và `actor` (`core/jobs.py:151`) và suy chuỗi tin cậy từ CHÍNH kết nối — nên nó phải chạy trong `tenant_conn()` của lượt nạp đó, đúng như handler đang chạy. Handler ném thì wrapper không xếp gì (ngoại lệ đi xuyên qua) — trừ `handle_kb_file_index`, hàm này bắt rộng và tự trả `JobResult`, nên ở đó `xep_build` phải tự bỏ qua khi message báo lỗi.
- `KbEnv.hippo_enabled: bool = False` (env `KB_HIPPO_ENABLED`), khai vào `.env.example` ở dạng comment.
- `src/portal/cli/hippo_build.py` — `python -m portal.cli.hippo_build --tenant <id> [--renew]`, cho dữ liệu đã nạp trước khi bật cờ. Không chạy trong đợt này.

### 5.3 Ràng buộc phải ghi tường minh

Triple embedding dùng `side="index"` lúc build, và agent embed câu hỏi bằng `side="query"` — cùng lệ với tài liệu. Quan trọng hơn: phải là CÙNG embed service. Khác model là khác vector space, và Qdrant/cosine trả nhiễu KHÔNG lỗi nào — cùng lớp lỗi `docs/architecture/rag.md` của repo agent đã đo (E5 query trên collection E5 ~0.82, Gemini query trên cùng collection ~0.03). Portal index tài liệu bằng chính service đó nên hôm nay nhất quán; ràng buộc này viết ra để nó không trở thành giả định ngầm.

## 6. Repo 2 — `odyssey-agent`

Backend mới `NOBLE_RAG_BACKEND=hipporag_kb`, đứng cạnh `hipporag`.

| File | Nội dung |
|---|---|
`agent/rag/hipporag/kb_adapter.py` | Entrypoint backend mới. Seed từ `kb_service_adapter` hybrid (collection per-tenant) thay vì clone legacy; embed câu hỏi bằng `data/embed_client.embed_dense(side="query")` thay vì `flat_store._Embedder` |
`agent/rag/hipporag/artefact_store.py` | Tải `graph.json` + `triple_emb.npz` từ object store; cache trên disk theo tenant |

Sửa:

- `agent/rag/noble_kb.py`: thêm một nhánh `if backend == "hipporag_kb"`.
- Cache graph khoá theo `current_tenant()`. `expander.load()` hiện là singleton toàn cục — giữ nguyên hàm đó cho legacy, thêm hàm mới có khoá tenant. Đây là chỗ rò dữ liệu nếu làm sai, nên nó có bài test riêng.
- `config.py`: knob mới cho backend `hipporag_kb`; các `HIPPORAG_*` sẵn có dùng lại nguyên nghĩa.

Không đụng: `adapter.py`, `builder.py`, `expander.py`, `graph.py`, `openie.py`, `triple_index.py` của package legacy.

Giữ nguyên tính chất degrade: thiếu artefact hoặc lỗi bất kỳ trong đường graph thì trả đúng kết quả `kb_service` hôm nay. Bật cờ không bao giờ tệ hơn không bật.

## 7. Hợp đồng artefact

`tenants/<tenant_id>/hipporag/graph.json` và `.../triple_emb.npz` là hợp đồng giữa portal (người ghi) và agent (người đọc). Theo lệ `contracts/` của repo này: chép tay, không job CI nào so hai bên. Tài liệu bàn giao `docs/contracts/hipporag-graph.md` viết cùng lúc thi công, mô tả:

- Hình dạng `graph.json`: danh sách phrase node, passage node (khoá theo Qdrant `point.id`), edge có trọng số, `triples`.
- Hình dạng `.npz`: ma trận embedding triple, hai mảng khoá phrase song song.
- Tên embed model đã dùng, để bên đọc phát hiện được lệch vector space thay vì nhận nhiễu im lặng.
- Mốc build và số chunk, để chẩn đoán stale.

## 8. Nợ để lại

| Nợ | Vì sao hoãn |
|---|---|
Synonym edge (cosine >= 0.8 giữa phrase) | Cần một lượt embed toàn bộ phrase + ngưỡng phải đo trên dữ liệu thật, không đoán được trước |
Recognition memory (LLM lọc triple query-time) | Thêm một lượt gọi LLM vào đường nói của agent; phải đo độ trễ trên đường voice trước khi cân nhắc |
Seeding kiểu upstream (mọi passage, weight 0.05, rank thuần PPR) | Bỏ RRF là bỏ chính thứ bảo đảm "không tệ hơn"; chỉ đổi khi đã đo được graph có ích |
Qdrant triple collection per-tenant | Cần mở rộng scope JWT ở `enrollment/qdrant_jwt.py`, tức đổi hợp đồng với agent |
Graph stale khi cờ đang tắt | Nạp trong lúc cờ tắt thì chunk mới không vào graph. Bật cờ phải kèm một lượt `--renew` |
`content_hash` per-record ở builder legacy | Sửa ở bản portal; file legacy giữ byte-identical có chủ ý |
Đoạn code này chưa từng chạy trên dữ liệu thật | Yêu cầu của đợt: chỉ chuẩn bị. Phải chạy thử có kiểm soát trên một tenant trước khi bật ở bất kỳ môi trường nào |

## 9. Test

Thuần, không Docker, không Postgres, không Qdrant, không gọi LLM, không ghi object store.

Portal:

- `graph.py` build trên chunk giả + `extract_fn` giả: ba chunk cùng một record ra ba passage node. Bài này đỏ ngay nếu ai đổi khoá incremental về lại `content_hash` (§2.3).
- Cờ tắt thì `handle_index`/`handle_kb_file_index` không enqueue gì. Đây là cổng của câu hứa "không phá workflow hiện tại".
- OpenIE ném thì job về `failed` mà `state` của record không đổi.
- Merge incremental: chunk đã có trong graph không gọi `extract_fn` lần nữa.
- Round-trip artefact: serialize rồi deserialize ra graph tương đương.

Agent:

- `noble_kb` với `hipporag_kb` vào đúng nhánh; các backend khác không đổi đường.
- Thiếu artefact thì output bằng đúng `kb_service`.
- Cache graph không lẫn giữa hai tenant — hai `current_tenant()` khác nhau nhận hai graph khác nhau.
- Legacy `hipporag` không đổi hành vi.

## 10. Thứ tự triển khai

1. Portal: `hippo/contracts.py` + `hippo/graph.py` + test thuần (phần lõi, không phụ thuộc gì).
2. Portal: `hippo/openie.py` + profile prompt + test với client giả.
3. Portal: `hippo/artefact.py` + test round-trip.
4. Portal: handler + nối dây + cờ + test cờ-tắt-không-enqueue.
5. Portal: CLI backfill.
6. Portal: `docs/contracts/hipporag-graph.md`.
7. Agent: `artefact_store.py` + test.
8. Agent: `kb_adapter.py` + cache theo tenant + test cách ly.
9. Agent: nhánh dispatch + knob + `.env.example`.

Bước 1-6 và 7-9 độc lập nhau ngoài hợp đồng artefact ở bước 6.
