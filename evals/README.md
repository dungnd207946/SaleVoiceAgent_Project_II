# Evals harness

Bộ đánh giá go/no-go trước release, thay cho `tests/eval` (đã xoá — xem
`docs/superpowers/specs/2026-08-24-unified-evals-harness-design.md`). Chạy qua
một CLI duy nhất: `python -m evals <subcommand>`.

Refactor 2026-08-25 (`docs/superpowers/specs/2026-08-25-evals-quality-refactor-design.md`)
tách **quality** (chất lượng agent end-to-end) khỏi **rag** (chất lượng retrieval
+ generation cô lập) hoàn toàn — hai suite không còn scorer chung, không còn `axis`
làm trọng tài chống double-count.

## 4 suite

```
quality  (evals/quality/)  — chạy agent thật qua case (chat), score theo 4 nhóm
                              metric + multi-turn (§ dưới) → scorecard pass/fail.
rag      (evals/rag/)      — đo retrieval + (tuỳ chọn) generation trên golden set,
                              độc lập với agent — gọi trực tiếp backend RAG.
bench    (evals/bench/)    — micro-benchmark từng component (stt/tts/speaker/vad/llm), N lần lặp, p50/p95.
load     (evals/load/)     — CCU test qua transport thật (chat/voice/service), ramp tới ngưỡng vỡ.
```

Cả 4 ghi **một dòng registry** vào `evals/registry.jsonl` (tracked trong git — chi
tiết per-case nằm ở `evals/reports/<run_id>/`, **gitignored**, không commit). `report`
đọc registry, render `evals/reports/TREND.md`.

## Suite `quality` — chất lượng agent

**Hai env var quyết định run có ý nghĩa hay không** (runbook đầy đủ: `evals/readme.html`):

- `EVAL_TENANT_API_KEY` — API key gateway của tenant. Harness drive agent in-process nên
  không có hop gateway; thiếu key thì `pool_for_tenant` rơi về shared `POSTGRES_DSN`, RLS
  trả **0 row chứ không lỗi**, và mọi case chết bằng `no published config`. `evals/tenant_creds.py`
  đổi key → PG role per-tenant, gọi lại **mỗi case** nên tự gia hạn khi hết TTL (~1h).
  Không đặt → no-op (tenant chạy shared DSN không cần). Wrapper `scripts/eval_with_key.sh`
  làm cùng việc bằng `POSTGRES_DSN` nhưng fetch một lần, không gia hạn.
  Key thuộc tenant **khác** tenant ghi trong case (vd. key `aina_test` là bản sao dữ liệu của
  `aina_prod`) → `python -m evals run --tenant aina_prod --as-tenant aina_test`: bộ case của
  thư mục `--tenant` chạy dưới tenant override (trace/preflight đều dùng tenant mới).
- `SANTA_MODELS_TOKEN` — bearer của embed service. Sai token ⇒ 401 ⇒ `kb_search` degrade
  **im lặng** về rỗng, agent vẫn trả lời trơn và preflight KHÔNG bắt. Kiểm bằng
  `scripts/test_search_tools.py -t <tenant> --kb "…"`.

Case chưa duyệt (`reviewed: false`) vẫn chạy và vẫn ghi trace nhưng **không scorer nào chấm** —
duyệt thiếu một nhóm thì gate của nhóm đó hiện `missing` và FAIL (fail-closed).

Case (`evals/quality/data/cases/<tenant>/*.jsonl`) không còn `axis` — mỗi scorer đọc
một block riêng của `turns[].expect` / `turns[].golden`, nên không cần trọng tài
chống double-count nữa. Filter/group chỉ dùng `tags` (`--tag`), tag hợp lệ:
`policy` · `tool` · `qa` · `multiturn` · `smoke`. Case ≥2 turn tự động vào nhóm
metric multi-turn — không có schema riêng, `multiturn` chỉ là nhãn.

**Deterministic (luôn chạy, không network):**

| Scorer | Metric | Gate? |
|---|---|---|
| `policy.py` | `policy_violations` | **gate 0.0** |
| `tool_selection.py` | `tool_selection_accuracy` | chưa (chờ baseline) |
| `tool_selection.py` | `arg_accuracy` | **gate 1.0** |
| `tool_selection.py` | `banned_call_rate` | **gate 0.0** |
| `tool_selection.py` | `irrelevant_call_rate` | **gate 0.60** (loại 2) |
| `tool_selection.py` | `tool_error_rate` | chưa |
| `trajectory.py` | `loop_exhaustion_rate` | **gate 0.02** |
| `trajectory.py` | `repeated_call_rate` | **gate 0.05** (loại 2) |
| `trajectory.py` | `steps_overhead` | **gate 1.8** (loại 2) |
| `run_integrity.py` | `cases_errored`, `cases_missing_trace` | **gate 0.0** |
| `latency.py` | p50/p95 | `turn_total_p95_ms` **gate 20000** (loại 2) |
| `style.py` | `style_violation_rate`, `style_da_opener_rate`, `style_a_overuse_rate`, `style_markdown_rate`, `style_multi_question_rate`, `style_cliche_rate` | `style_markdown_rate` **gate 0.0**; còn lại chưa (chờ baseline có scorer này) |

`tool_selection.py` đọc `golden.tools`/`golden.banned_tools` (thay `tool_traj.py` cũ).
Miễn trừ `irrelevant_call_rate`: `update_customer` (agent được khuyến khích gọi bất
cứ lúc nào khách nhả thông tin). `trajectory.py` là scorer mới — chấm mọi case,
không cần golden (`repeated_call_rate` = turn có ≥2 call trùng hệt `(name, args)`
sau `json.dumps(sort_keys=True)`; `steps_overhead` chỉ tính trên turn có `golden.tools`).

**LLM judge (gated `--judge`, pha SCORE, đọc trace — không đụng agent):** 3 rubric
độc lập, mỗi rubric có coverage riêng (turn lỗi/hết budget → *ungraded*, trừ vào
coverage, KHÔNG trừ điểm):

| Rubric | Chạy trên | Metric |
|---|---|---|
| `correctness` | turn có `golden.answer` | `answer_correctness_mean`, `intent_alignment_rate`, `hallucination_rate`, `correctness_coverage` |
| `groundedness` | turn có `golden.answer` **và** ≥1 tool call có kết quả trong trace | `grounded_rate`, `groundedness_coverage` |
| `multiturn` | case ≥2 turn (1 call/case, toàn hội thoại) | `context_retention_score`, `consistency_score`, `multiturn_coverage` |

Hạ tầng judge dùng chung (`evals/judge_client.py`): SQLite cache theo rubric-version,
budget cap USD, retry/backoff, env `EVAL_JUDGE_MODEL` / `_BASE_URL` / `_API_KEY`.

**Gate loại 1 (tuyệt đối, chốt ngay — `evals/quality/data/thresholds.toml`):**
`policy_violations <= 0`, `arg_accuracy >= 1.0`, `banned_call_rate <= 0.0`,
`loop_exhaustion_rate <= 0.02`, `cases_errored <= 0`, `cases_missing_trace <= 0`,
`style_markdown_rate <= 0`.
**Gate loại 2 (chặn tụt so với baseline 3 run 100 case ngày 2026-08-25, chốt 2026-08-27):**
`irrelevant_call_rate <= 0.60`, `repeated_call_rate <= 0.05`, `steps_overhead <= 1.8`,
`turn_total_p95_ms <= 20000`; với `--judge`: `answer_correctness_mean >= 0.45`,
`hallucination_rate <= 0.40`, `grounded_rate >= 0.65`, `context_retention_score >= 0.75`.
Gate khai `judge = true` trong run KHÔNG `--judge` hiện `skipped` (không FAIL) — cố ý
không đo khác với đo mà không ra số. Ngưỡng đặt ở kết quả xấu nhất đã quan sát + biên
nhỏ; siết theo model thì sửa file, đừng nới cho vừa kết quả.

`style.py` là linter văn phong xác định cho mục Style của persona (mở "Dạ", >1 "ạ"/tin,
markdown, ≥2 dấu hỏi, câu sáo tổng đài khi khách chưa chào kết) — chấm mọi reply không
rỗng của case reviewed, không LLM.

`--judge` thay cho trục cũ; **`--tag` thay `--axis`** ở `evals run`/`evals score`
(axis không còn ý nghĩa "nguồn sự thật chống double-count" — vocabulary `expect`
và `golden` đã disjoint theo scorer).

## Suite `rag` — chất lượng retrieval + generation

Golden set v2 (`evals/rag/golden.py`, một dòng JSONL):

```json
{"id": "gg-001", "tenant": "green_park", "query": "tiện ích nội khu Alumi",
 "project_code": "ALM",
 "golden_chunks": [{"chunk_id": "…", "evidence": "câu trích NGUYÊN VĂN"}],
 "answer": "câu trả lời chuẩn tổng hợp từ các chunk",
 "status": "draft|approved"}
```

- `query` viết theo **văn phong truy vấn kb_search** (như agent formulate), không
  phải nguyên văn lời khách.
- `golden_chunks` ≥1 phần tử, mỗi phần tử cần `chunk_id` và/hoặc `evidence`
  (evidence phải NGUYÊN VĂN từ chunk/corpus — matcher là normalized-substring,
  paraphrase sẽ luôn miss).
- `answer` bắt buộc để chạy `--judge` (generation stage); rỗng thì case đó bị
  runner `--judge` skip (đếm số case skip). Loader vẫn chỉ nạp dòng `status: approved`.

**Retrieval metrics (deterministic, luôn chạy) — `evals/rag/metrics.py`:**

| Metric | Định nghĩa |
|---|---|
| `recall_at_k` (k=1,3,5) | ≥1 golden chunk trong top-k (hit rate) |
| `context_recall_at_k` | mean(&#124;golden ∩ top-k&#124; / &#124;golden&#124;) |
| `context_precision_at_k` | mean(&#124;golden ∩ top-k&#124; / k) — **LOWER BOUND**: mẫu số là k, không phải số chunk thật-sự-liên-quan trong top-k (golden set không phủ hết chunk liên quan). Đọc như "ít nhất bao nhiêu phần top-k chắc chắn liên quan", không phải precision thật. |
| `mrr` | 1/(rank+1) của golden chunk đầu tiên tìm thấy |
| `empty_rate`, `retrieval_p50/p95_ms` | như cũ |

Match golden chunk theo `chunk_id` trước, evidence-substring sau; greedy theo rank
(một hit chỉ khớp tối đa một golden chunk) để không double-count.

**Generation stage (gated `--judge`) — `evals/rag/generate.py`:** generator **cô
lập** (không qua agent) — prompt cố định tiếng Việt "chỉ dùng các đoạn sau, thiếu
thì trả lời 'Tôi không tìm thấy thông tin này'" — input = query + top-k chunk thực
tế retrieve được, model qua env `EVAL_RAG_GEN_MODEL` (fallback `EVAL_JUDGE_MODEL`).
Hai rubric:

| Rubric | Metric |
|---|---|
| `rag_faithfulness` (answer sinh ra vs chunks) | `faithfulness_rate` |
| `rag_answer_correctness` (answer sinh ra vs `golden.answer`) | `rag_answer_correctness_mean` |
| deterministic (marker câu từ chối) | `rag_refusal_rate` = generator từ chối trong khi context_recall của case > 0 |

`generation_coverage` = tỉ lệ case chấm được / case đủ điều kiện (có answer + có
retrieved).

## Labeller v2 — duyệt case & golden

`make eval-labeller` (`python -m evals labeller [--port 8765]`) — server Python
stdlib (`http.server`, không dependency), bind `127.0.0.1`, phục vụ UI 1 file
(`evals/labeller/static/index.html`) để duyệt cả hai schema (agent case / RAG
golden) trong cùng chỗ. Nguồn sự thật là file JSONL trong repo — save = `PUT`,
server **validate từng dòng bằng chính loader** (`cases.parse_case` /
`golden.parse_golden`) trước khi ghi (sai schema → 422, không ghi gì), ghi atomic
(tmp + rename). localStorage chỉ autosave draft chưa lưu để chống mất tay.

Quy trình:

1. Tạo case/golden mới bằng `evals gen-golden` (RAG) hoặc viết tay JSONL
   (`reviewed`/`status` mặc định `false`/`draft`).
2. Mở `make eval-labeller`, chọn tenant/file, duyệt từng case: sửa nội dung, gán
   `golden`/`golden_chunks`, phím tắt `j`/`k` chuyển case, `a` toggle
   reviewed/approved, `e` focus editor, `/` focus ô lọc case, `Ctrl+S` save.
   Ô lọc dưới tên file thu hẹp danh sách theo id **và** nội dung (câu khách,
   golden answer, tên/args tool; golden thì `query`/`answer`/`evidence`) —
   bỏ dấu tiếng Việt (`du an` khớp `dự án`), nhiều từ là AND. `Enter` mở case
   khớp đầu tiên, `Esc` xoá lọc; `j`/`k` chỉ đi trong tập đang hiện.
   `expect` là builder dropdown (một dòng / một key, giá trị theo đúng kiểu của
   key đó — field khách lấy từ `/api/customer-fields` = model `Customer` thật);
   nút `{ } JSON thô` mở lại ô JSON để dán nguyên khối. Lúc lưu, chuỗi rỗng và
   dòng `customer_field` thiếu `field` bị bỏ (`""` nằm trong MỌI reply nên là
   assertion hỏng, không phải assertion rỗng); key ngoài vocabulary v2 vẫn giữ
   nguyên và để server từ chối 422 thay vì bị UI nuốt mất.
3. Chỉ case `reviewed:true` (agent) / golden `status:approved` (RAG) mới được
   scorer/loader tính vào scorecard — case draft chạy được nhưng không di chuyển
   số gate.

Guide đầy đủ để sinh case quality mới cho tenant bất kỳ (thu thập dữ kiện tenant
từ Qdrant, văn phong, validator, bẫy đã biết):
[`docs/handoff/2026-08-24-synthetic-eval-cases-guide.md`](../docs/handoff/2026-08-24-synthetic-eval-cases-guide.md) —
**format case trong guide đó là schema CŨ**, đọc banner đầu file trước khi dùng.

## Bảng lệnh make

| Target | Gọi | Cần gì |
|---|---|---|
| `make eval-list` | `evals list` | không |
| `make eval-quality` | `evals run` (toàn bộ case, không judge) | Redis + LLM key + RAG backend |
| `make eval-quality-smoke` | `evals run --case POL-001,TOOL-001,QA-001 --tenant du_test` | như trên, rẻ — chạy mọi commit |
| `make eval-quality-full` | `evals run --judge` (+ 3 rubric judge) | như trên + judge model |
| `make eval-score RUN=<run_id>` | `evals score --run-dir evals/reports/<run_id>` | không (chỉ đọc trace) |
| `make eval-rag` | `evals rag --golden <path>` | RAG backend sống (+ judge model nếu `ARGS="--judge"`) |
| `make eval-bench` | `evals bench` | component sống (stt/tts/speaker/vad/llm) |
| `make eval-load` | `evals load --target chat` | service/transport sống |
| `make eval-report` | `evals report` | không (đọc registry) |
| `make eval-periodic` | smoke + bench + report, suite lỗi không chặn suite sau | như eval-quality-smoke + bench |
| `make eval-selftest` | `pytest tests/unit/evals/` | không |
| `make eval-labeller` | `evals labeller` | không |

`ARGS="..."` truyền thẳng flag xuống CLI, ví dụ
`make eval-quality ARGS="--tag tool"` hay `make eval-score RUN=20260824-...`
hay `make eval-rag ARGS="--golden evals/rag/data/golden/du_test/xxx.jsonl --judge"`.

## Quy trình golden set (RAG)

1. **`evals gen-golden`** — LLM sinh `{query, evidence}` **+ `answer`** (tổng hợp từ
   chunk, vẫn lọc evidence-nguyên-văn) từ corpus, `status: draft`, 1 `golden_chunks`
   phần tử/case (case nhiều chunk gộp tay qua labeller).
2. **Duyệt qua labeller** (`make eval-labeller`, mode "RAG golden") — sửa/xoá case
   bịa, gộp thêm golden_chunks nếu cần, bấm `a` chuyển `status` thành `approved`.
   `evals rag` (loader `evals/rag/golden.py`) **từ chối nạp bất kỳ dòng nào không
   phải `approved`** — golden chưa duyệt không lọt được vào gate.
3. **`evals rag --golden <file đã approved>`** — chạy đo retrieval (luôn); thêm
   `--judge` để chạy stage generation (cần `answer` không rỗng).

Quy ước bắt buộc: **`golden_chunks[].evidence` phải là câu trích NGUYÊN VĂN (copy
đúng từng ký tự) từ chunk/corpus**, không diễn giải. Matcher là normalized-substring
(lowercase + gộp khoảng trắng) — evidence paraphrase sẽ luôn miss dù retrieval đúng,
làm sai số liệu recall.

## Cảnh báo: load test

**Chỉ chạy `eval-load` trên staging/dev, KHÔNG chạy trên production.** Nhánh
`--target voice` đi qua **LiveKit Cloud dùng chung** với traffic thật — ramp CCU ở
đây có thể giật/nghẽn cuộc gọi thật đang diễn ra trên cùng project LiveKit. Luôn xác
nhận `--host`/room project trước khi chạy, và ưu tiên `--target chat`/`service` khi
chỉ cần đo transport không đụng LiveKit.

## Registry schema

`evals/registry.jsonl` — **một dòng JSON append-only mỗi run** (schema
`evals/registry.py::RegistryEntry`): `run_id`, `ts`, `kind`
(`quality`|`rag`|`bench`|`load`), `git_sha`, `config`, `metrics`, `gates`, `verdict`
(`pass`|`fail`|`error`), `report_dir`. File này tracked trong git để diff/trend qua
thời gian; chi tiết trace/scorecard đầy đủ nằm trong `report_dir` (dưới
`evals/reports/`), gitignored.

## Cron định kỳ

Đặt `make eval-periodic` chạy theo lịch (ví dụ cron hàng ngày) để có tín hiệu drift
liên tục mà không tốn judge/LLM cho toàn bộ case:

```cron
0 3 * * * cd /path/to/santa-hotline-agent && make eval-periodic >> /var/log/noble-eval-periodic.log 2>&1
```

`eval-periodic` chạy đủ cả 3 bước (một suite fail không chặn suite sau — `eval-report`
luôn chạy để `TREND.md` phản ánh đúng), nhưng exit code cuối là **OR** của các suite: bất
kỳ suite nào fail thì target cũng exit non-zero, để cron/CI thấy đỏ (spec §10). Nếu
preflight của `evals run` fail (ví dụ Redis down), vẫn có một dòng registry
`kind="quality" verdict="error"` được ghi (`config.preflight_error` mang lý do) — một
lần chạy cron không còn có thể "biến mất" hoàn toàn (exit 0 + không dòng registry).
