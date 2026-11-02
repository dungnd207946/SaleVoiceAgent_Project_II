# Refactor evals quality — tách agent-quality / RAG-quality, metric theo nhóm, labeller v2

- **Ngày:** 2026-08-25
- **Trạng thái:** approved (user duyệt design trong session 2026-08-25)
- **Tiền nhiệm:** `2026-08-24-unified-evals-harness-design.md` (harness `evals/` hiện tại).
  Spec này refactor phần **đo chất lượng** của harness đó; phần system (bench/load/latency/registry/report) giữ nguyên.

## 1. Bối cảnh & vấn đề

Harness `evals/` chạy được nhưng phần đo chất lượng lộn xộn:

1. **RAG lẫn trong quality.** `evals/quality/scorers/rag.py` + axis `grounding`/`retrieval`
   chấm chuyện retrieval bên trong suite agent — trùng vai với `evals/rag/`, và làm
   `axis` phải gánh vai "nguồn sự thật cho scorer" để chống double-count.
2. **Judge một cục.** Một rubric duy nhất trả `{grounded, quality}` — không tách được
   "trả lời sai golden" khỏi "bịa ngoài context" khỏi "văn phong kém".
3. **Thiếu metric.** Không có trajectory efficiency đúng nghĩa (chỉ có `loop_exhausted`),
   không có multi-turn metric, RAG thiếu context precision/recall + faithfulness +
   answer correctness (golden chỉ có 1 evidence, không có golden answer, không có generation).
4. **Labeller** một file HTML/localStorage, import/export tay, không validate schema.

## 2. Mục tiêu / Không-mục-tiêu

**Mục tiêu**

- Hai suite chất lượng **tách biệt hoàn toàn**:
  - `evals/quality/` = chất lượng **agent** end-to-end (chạy agent thật).
  - `evals/rag/` = chất lượng **RAG** cô lập (gọi thẳng backend retrieval + generator cô lập).
- Agent-quality chấm đúng 4 nhóm + multi-turn:
  Accuracy & Correctness · Groundedness · Tool Selection Accuracy · Trajectory Efficiency · Multi-turn.
- RAG chấm: Context Precision · Context Recall · Hit Rate/Recall@K · MRR · Faithfulness · Answer Correctness.
- Golden set schema mới cho cả hai suite (xem §4, §7).
- Labeller v2: server Python nhỏ đọc/ghi thẳng JSONL trong repo, validate bằng chính loader, UI duyệt nhanh.

**Không-mục-tiêu**

- Không đổi registry/report/bench/load/latency (user đã xác nhận "ổn").
- Không migrate data cũ: case + golden draft hiện có **xoá bỏ** (thiếu golden answer,
  migrate không tạo ra dữ liệu đạt chuẩn mới). User tự tạo bộ mới.
- Không thêm dependency (không RAGAS/deepeval; labeller dùng stdlib `http.server`).
- Không gate metric judge mới cho tới khi có baseline (giữ triết lý gate loại 1/loại 2).

## 3. Kiến trúc tổng

```
evals/
  judge_client.py         # MỚI — hạ tầng judge dùng chung: SQLite cache, budget cap,
                          #   retry, _call_openai (tách từ quality/judge.py, giữ nguyên hành vi)
  quality/                # AGENT quality (chạy agent thật, như cũ)
    cases.py              # schema v2 (§4)
    runner.py, trace.py   # GIỮ NGUYÊN (RUN phase không đổi)
    scorecard.py          # GIỮ NGUYÊN (gates fail-closed)
    latency.py            # GIỮ NGUYÊN
    judge.py              # 3 rubric: correctness / groundedness / multiturn (§5.2)
    scorers/
      __init__.py         # AxisScore/Finding — GIỮ NGUYÊN
      policy.py            # expect assertions (vocabulary bỏ tool_*)
      tool_selection.py    # từ golden.tools (thay tool_traj.py)
      trajectory.py        # MỚI — dead-end/lặp/step thừa
      run_integrity.py     # GIỮ NGUYÊN
      (XOÁ rag.py)
  labeller/               # MỚI — server + static UI (§8); nằm NGOÀI quality/ vì
    server.py             #   nó đọc/ghi data của CẢ HAI suite (cases + golden)
    static/index.html
  rag/
    golden.py             # schema v2: golden_chunks[] + answer (§7.1)
    runner.py             # retrieval metrics mở rộng + stage generation --judge (§7.2–7.3)
    generate.py           # MỚI — generator cô lập (prompt cố định)
    metrics.py            # + context_precision/recall
    golden_gen.py         # sinh cả answer + nhiều evidence
```

Ranh giới import giữ nguyên: `quality/runner.py` và `rag/runner.py` là các module duy nhất
import `noble_agent`; mọi scorer/metric thuần, test không cần Redis/LLM/Qdrant.

## 4. Schema case agent-quality v2

### 4.1 Nguyên tắc: scorer kích hoạt theo NỘI DUNG, không theo axis

`axis` cũ tồn tại để chống double-count vì policy scorer lẫn tool scorer cùng đọc `expect`.
Schema v2 tách vocabulary — mỗi scorer đọc một block riêng — nên `axis` bỏ, thay bằng
`tags` (chỉ để filter `--tag` và group trong report, không ảnh hưởng chấm điểm).

```json
{"id": "QA-001", "tenant": "green_park", "channel": "chat",
 "tags": ["tool", "multiturn"], "origin": "handwritten", "reviewed": false,
 "customer": {"name": "anh Nam"},
 "turns": [
   {"user": "lượt khách nói…",
    "expect": {"reply_contains": ["…"]},
    "golden": {
      "answer": "câu trả lời chuẩn (reference)",
      "tools": [{"name": "kb_search", "args": {"query": {"contains": "khoáng nóng"}}}],
      "banned_tools": ["escalate"]
    }}
 ]}
```

| Block | Bắt buộc? | Scorer đọc | Ghi chú |
|---|---|---|---|
| `turns[].user` | có | runner | như cũ |
| `turns[].expect` | không | `policy.py` | vocabulary = `KNOWN_KEYS` của e2e assertions **trừ** `tool_called`/`tool_not_called`/`tool_arg` (case loader từ chối 3 key này; e2e scenarios giữ vocabulary đầy đủ của nó, không đổi) |
| `turns[].golden.answer` | không | judge correctness + groundedness | turn có answer mới bị judge |
| `turns[].golden.tools` | không | `tool_selection.py` + `trajectory.py` | list `{name, args?}`; mỗi entry args là map `arg → matcher` |
| `turns[].golden.banned_tools` | không | `tool_selection.py` | tool gọi ra là finding |
| `tags` | không | CLI filter + report | validated set: `{"policy","tool","qa","multiturn","smoke"}` — thêm tag mới = sửa một frozenset |
| `reviewed` | có (default false) | mọi scorer gated | như cũ: unreviewed chạy được nhưng không di chuyển số gate |

Matcher cho `golden.tools[].args`: `{"contains": "str"}` (substring, case-insensitive,
normalize whitespace) hoặc `{"equals": <json value>}`. Chỉ hai dạng — đủ cho bẫy
price-unit và query-keyword, thêm dạng mới khi có nhu cầu thật.

Validation strict như cũ: unknown key ở mọi cấp → `ValueError` với `file:line`.

### 4.2 Multi-turn

Không có schema riêng: case ≥2 turn **tự động** vào nhóm metric multi-turn (§5.2.3).
Tag `multiturn` chỉ là nhãn filter, không phải công tắc.

## 5. Scorer agent-quality

### 5.1 Deterministic (thuần, không network)

**`scorers/tool_selection.py`** — thay `tool_traj.py`, đọc `golden.tools`/`banned_tools`:

| Metric | Định nghĩa | Gate? |
|---|---|---|
| `tool_selection_accuracy` | per-turn: mọi tool trong `golden.tools` đều được gọi | chưa (chờ baseline) |
| `arg_accuracy` | per-matcher: arg khớp matcher | **gate** (giữ ngưỡng hiện có) |
| `banned_call_rate` | per-turn có `golden.banned_tools`: tồn tại call ∈ banned_tools | **gate 0.0** (kế thừa gate `unnecessary_call_rate` cũ) |
| `irrelevant_call_rate` | per-turn có `golden.tools`: tồn tại call ∉ (golden.tools ∪ miễn trừ mặc định) | chưa (chờ baseline) |
| `tool_error_rate` | call có kết quả `{"error": …}`/`ok:false` | chưa |

Miễn trừ mặc định cho `irrelevant_call_rate`: `update_customer` (agent được khuyến khích
gọi bất cứ lúc nào khách nhả thông tin — đếm nó là nhiễu). Hard-code một frozenset
`_EXEMPT_TOOLS`, ghi chú trong docstring.

`banned_tools` gọi ra → finding `banned_call`, đếm vào `banned_call_rate` (một turn
vi phạm = turn vi phạm, mirror logic `tool_not_called` cũ).

Quy ước `checks`/`pass_rate` pessimistic + `_gated_rate` trả `None` khi mẫu rỗng:
**giữ nguyên từ tool_traj.py** (bao gồm invariant findings ≠ ∅ ⇒ pass_rate < 1).

**`scorers/trajectory.py`** — mới, chấm mọi case (không cần golden):

| Metric | Định nghĩa | Gate? |
|---|---|---|
| `loop_exhaustion_rate` | turn hit MAX_TOOL_ITERATIONS (từ trace, cơ chế ExhaustionWatch giữ nguyên) | **gate** (giữ ngưỡng hiện có) |
| `repeated_call_rate` | turn có ≥2 call trùng hệt `(name, args)` — tín hiệu dead-end loop | chưa |
| `steps_overhead` | trên turn có `golden.tools`: mean(số call thực / số tool golden), min 1.0 | chưa |

`repeated_call_rate` đếm theo turn; args so sánh sau khi `json.dumps(sort_keys=True)`.

**`scorers/policy.py`** — giữ nguyên logic, chỉ đổi: chấm mọi case có `expect`
(không lọc axis nữa — vocabulary đã disjoint), vẫn `reviewed`-only,
`policy_violations` vẫn gate = 0.

**`scorers/run_integrity.py`**, **`latency.py`** — giữ nguyên.

### 5.2 Judge (LLM, pha SCORE, gated `--judge`)

`evals/judge_client.py` (tách từ judge.py hiện tại, hành vi giữ nguyên): SQLite cache
(key gồm rubric-version riêng từng rubric), budget cap USD, retry/backoff, `enable_thinking`
workaround cho qwen, env `EVAL_JUDGE_MODEL/_BASE_URL/_API_KEY`. Lỗi judge → turn
**ungraded**, trừ vào `judge_coverage`, không trừ vào điểm (giữ nguyên triết lý).

**5.2.1 Rubric `correctness`** — chạy trên turn có `golden.answer`:

- Input: user + `golden.answer` + reply.
- Output JSON: `{"correct": 0..1, "intent_aligned": bool, "hallucinated": bool, "rationale": "…"}`
  - `correct`: mức khớp nội dung với golden answer (sai số diễn đạt không trừ).
  - `intent_aligned`: trả lời đúng trọng tâm câu khách hỏi.
  - `hallucinated`: có khẳng định factual mâu thuẫn/vượt golden answer.
- Metrics: `answer_correctness_mean`, `intent_alignment_rate`, `hallucination_rate`.

**5.2.2 Rubric `groundedness`** — chạy trên turn có `golden.answer` **và** có ≥1 tool call
trả kết quả trong trace:

- Input: reply + **toàn bộ raw_result của tool calls trong turn đó** (từ trace — đối chiếu
  với những gì agent thật sự nhìn thấy, KHÔNG phải golden).
- Output: `{"grounded": bool, "unsupported_claims": ["…"], "rationale": "…"}`.
- Metric: `grounded_rate`. Finding `ungrounded` kèm unsupported_claims.
- Turn có answer nhưng 0 tool call → skip (không có gì để đối chiếu), không tính coverage.

**5.2.3 Rubric `multiturn`** — chạy 1 call/case trên case ≥2 turn:

- Input: toàn bộ hội thoại (user + reply xen kẽ) + customer ban đầu.
- Output: `{"context_retention": 0..1, "consistency": 0..1, "issues": ["…"], "rationale": "…"}`
  - `context_retention`: có giữ/dùng thông tin khách đã nói không, có hỏi lại điều đã biết không.
  - `consistency`: các turn có tự mâu thuẫn về fact/cam kết không.
- Metrics: `context_retention_score`, `consistency_score` (mean trên case).

Coverage: mỗi rubric xuất coverage riêng (`correctness_coverage`,
`groundedness_coverage`, `multiturn_coverage`) — scorecard cấm trùng tên metric
giữa các axis, và coverage per-rubric chỉ ra đúng rubric nào thiếu mẫu.

Chi phí trần: ≤2 call/turn (correctness+groundedness) + 1 call/case (multiturn);
cache SQLite làm re-run gần miễn phí.

## 6. Scorecard / gates

`thresholds.toml` viết lại:

- **Giữ gate loại 1** (ngưỡng giữ nguyên giá trị hiện hành): `policy_violations <= 0`,
  `arg_accuracy >= 1.0`, `irrelevant_call_rate <= 0.0` (kế thừa gate
  `unnecessary_call_rate` — vẫn mã hoá "tool bị cấm mà gọi ra là chặn release"),
  `loop_exhaustion_rate <= 0.02`, `cases_errored <= 0`, `cases_missing_trace <= 0`.
  Lưu ý: `irrelevant_call_rate` gộp cả hai nguồn (banned_tools bị gọi + call ngoài
  golden.tools); để gate 0.0 không chặn oan phần "ngoài golden.tools" (vốn chưa có
  baseline), gate 0.0 chỉ đọc phần banned — scorer xuất **hai** metric:
  `banned_call_rate` (gate 0.0) và `irrelevant_call_rate` (chưa gate, chờ baseline).
- **Metric mới (judge + trajectory phụ) chưa gate** — vào file sau baseline run,
  comment đầu file giữ nguyên lời giải thích "chốt ngưỡng sau baseline".
- Fail-closed semantics (`None` = missing = FAIL) giữ nguyên, không đổi scorecard.py.

## 7. RAG suite

### 7.1 Golden schema v2 (`rag/golden.py`)

```json
{"id": "gg-001", "tenant": "green_park",
 "query": "tiện ích nội khu Alumi",
 "project_code": "ALM",
 "golden_chunks": [{"chunk_id": "…", "evidence": "câu trích NGUYÊN VĂN"}],
 "answer": "câu trả lời chuẩn tổng hợp từ các chunk",
 "status": "draft|approved"}
```

- `query` viết theo **văn phong truy vấn kb_search** (như agent đã formulate), không phải
  nguyên văn lời khách.
- `golden_chunks` ≥1 phần tử; mỗi phần tử cần `evidence` (nguyên văn — matcher vẫn
  normalized-substring) và/hoặc `chunk_id` (ưu tiên khi backend trả id).
- `answer` bắt buộc khi muốn chạy `--judge`; loader cho phép rỗng (case retrieval-only)
  nhưng runner `--judge` skip case không có answer và báo số case bị skip.
- Loader vẫn từ chối mọi dòng không `approved`.

### 7.2 Retrieval metrics (deterministic, luôn chạy) — `rag/metrics.py`

Với mỗi case: tập rank các golden chunk tìm thấy trong top-k (match theo chunk_id trước,
evidence-substring sau; mỗi hit chỉ match một golden chunk — greedy theo rank):

| Metric | Định nghĩa |
|---|---|
| `recall_at_k` (k=1,3,5) | ≥1 golden chunk trong top-k (hit rate — giữ tên cũ) |
| `context_recall_at_k` | mean(|golden ∩ top-k| / |golden|) |
| `context_precision_at_k` | mean(|golden ∩ top-k| / k) — **lower bound**, vì golden không phủ hết chunk liên quan; ghi chú rõ trong README |
| `mrr` | 1/(rank+1) của golden chunk đầu tiên tìm thấy |
| `empty_rate`, `retrieval_p50/p95_ms` | như cũ |

### 7.3 Generation stage (gated `--judge`) — `rag/generate.py` + 2 rubric

1. **Generator cô lập:** prompt cố định tiếng Việt — "Chỉ dùng các đoạn sau để trả lời.
   Không suy diễn. Thiếu thông tin thì trả lời 'Tôi không tìm thấy thông tin này.'" —
   input = query + top-k chunks thực tế retrieve được; model qua env
   `EVAL_RAG_GEN_MODEL` (fallback `EVAL_JUDGE_MODEL`), client dùng `judge_client`.
2. **Judge `rag_faithfulness`:** answer sinh ra vs chunks — mọi khẳng định có được đỡ?
   → `faithfulness_rate` (+ finding kèm unsupported claims).
3. **Judge `rag_answer_correctness`:** answer sinh ra vs `golden.answer`
   → `rag_answer_correctness_mean`.
4. `rag_refusal_rate`: generator trả "không tìm thấy" trong khi context_recall của case > 0
   (đếm deterministic bằng marker câu từ chối của chính prompt).

Registry entry `kind="rag"` giữ nguyên, metrics mở rộng.

### 7.4 `gen-golden` v2

- Sinh `{query, evidence}` như cũ **+ `answer`** (LLM tổng hợp từ chunk, vẫn lọc
  evidence-nguyên-văn). Mỗi case sinh ra có 1 `golden_chunks` phần tử; case nhiều
  chunk tạo/tổng hợp tay qua labeller (không làm flag gộp chunk tự động đợt này).
- Output `status: "draft"` như cũ; duyệt qua labeller v2.

## 8. Labeller v2

**Chạy:** `python -m evals labeller [--port 8765]` — stdlib `http.server`
(ThreadingHTTPServer), bind `127.0.0.1` cố định. Make target `eval-labeller`.

**API (JSON):**

| Endpoint | Vai trò |
|---|---|
| `GET /api/tree` | liệt kê file case (`quality/data/cases/<tenant>/*.jsonl`) + golden (`rag/data/golden/<tenant>/*.jsonl`) kèm đếm reviewed/approved |
| `GET /api/file?path=` | parse file → list case + lỗi validate per-line (đường dẫn bị chặn trong 2 thư mục data — chống path traversal) |
| `PUT /api/file?path=` | ghi đè file; **server validate từng dòng bằng `cases.parse_case` / `golden.parse_golden` trước khi ghi** — sai schema → 422 kèm lỗi `line:field`, không ghi gì |
| `POST /api/file?path=` | tạo file mới (tenant mới / batch mới) |

**UI (`static/index.html`, một file, không dependency):**

- Hai mode khớp 2 schema: **Agent cases** / **RAG golden**; switch trên header.
- Layout 3 cột: trái = cây tenant/file/case với chip trạng thái (reviewed/draft, có lỗi);
  giữa = hội thoại dạng chat bubble (user/agent) — với RAG golden là query + danh sách
  golden_chunks + answer; phải = form golden của turn đang chọn
  (answer / tools+matchers / banned_tools / expect) + meta case (tags, customer, origin).
- Phím tắt: `j/k` case trước/sau, `a` toggle reviewed/approved, `e` focus editor,
  `Ctrl+S` save file. Thanh tiến độ đã duyệt / còn lại per file.
- Nguồn sự thật là file trong repo (save = PUT); localStorage chỉ autosave draft chưa
  save để chống mất tay, có banner khôi phục.

## 9. Data: xoá cũ, tạo mới

- **Xoá:** toàn bộ `quality/data/cases/{du_test,green_park,noble}/*.jsonl` và
  `rag/data/golden/*/draft-*.jsonl` (thiếu golden answer — không migrate được thành
  dữ liệu đạt chuẩn v2; quyết định của user 2026-08-25).
- User tự tạo bộ mới: agent cases qua labeller v2 (+ cập nhật guide
  `docs/handoff/2026-08-24-synthetic-eval-cases-guide.md` sang schema v2 — một mục việc
  của plan), golden RAG qua `gen-golden` v2 + duyệt labeller.
- Smoke set (`make eval-quality-smoke`) trỏ tới 3 case id mới trong một file
  `quality/data/cases/du_test/p0_smoke.jsonl` viết tay ngay trong đợt refactor này
  (để make target không chết trong lúc chờ bộ case đầy đủ).

## 10. CLI / Make / docs

- `evals run|score`: `--axis` → `--tag`; thêm `--judge` như cũ.
- `evals rag`: thêm `--judge` (generation stage), `--top-k` giữ nguyên.
- `evals labeller`: mới.
- Make: `eval-labeller` mới; các target khác giữ tên. README `evals/` viết lại
  (bảng metric 2 suite, quy trình tạo data mới, ghi chú context_precision lower-bound).
- CLAUDE.md: cập nhật khối lệnh evals + changelog 2 chỗ theo self-maintenance rules.

## 11. Tests (`tests/unit/evals/`)

Viết lại theo scorer mới — tất cả thuần, không network:

- `tool_selection`: matcher contains/equals, irrelevant (kèm miễn trừ update_customer),
  banned, `None` khi mẫu rỗng, invariant findings ⇒ pass_rate < 1.
- `trajectory`: repeated-call theo (name,args) sorted, steps_overhead, loop từ trace.
- `policy`: loader từ chối `tool_*` trong expect; scorer chấm mọi case có expect.
- `judge` (mock `_call_openai`): 3 rubric parse/clamp, cache key có rubric version,
  ungraded → coverage, budget.
- `rag/metrics`: context precision/recall/mrr multi-chunk, greedy match không double-count.
- `rag/golden`: loader v2, từ chối draft, answer optional.
- `labeller/server`: validate-trước-ghi (422 không ghi file), chặn path traversal,
  round-trip GET→PUT giữ nguyên nội dung không đổi.
- `scorecard`: giữ test fail-closed hiện có (không đổi module).

## 12. Rủi ro & đối sách

| Rủi ro | Đối sách |
|---|---|
| Judge metric mới chưa calibrate → số đẹp/xấu giả | chưa gate; chạy baseline, đối chiếu tay bằng findings + rationale trước khi chốt ngưỡng |
| context_precision lower-bound bị đọc nhầm là precision thật | tên metric giữ hậu tố `_at_k`, README + scorecard ghi chú "lower bound vs golden set" |
| Xoá data cũ làm smoke/make target chết | viết tay 3 case smoke v2 trong chính đợt refactor |
| Labeller ghi hỏng file JSONL | server validate từng dòng trước khi ghi + ghi atomic (tmp + rename) |
| 2 call judge/turn làm chi phí tăng | budget cap + cache giữ nguyên; correctness/groundedness chỉ chạy trên turn có golden.answer |
