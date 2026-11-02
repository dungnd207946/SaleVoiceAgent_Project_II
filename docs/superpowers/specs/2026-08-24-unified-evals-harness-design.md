# Unified Evals Harness (`evals/`) — Design

**Date:** 2026-08-24
**Branch:** feat/share-agent
**Status:** Approved (design review qua brainstorming session 2026-08-24)

## 1. Mục tiêu

Một harness đánh giá thống nhất, đứng NGOÀI `src/`, làm chuẩn cho:

1. **Đánh giá chất lượng full-pipeline agent** — per-turn và multi-turn (policy, tool
   trajectory, grounding, answer quality).
2. **Đánh giá RAG component tách riêng** — recall@k / MRR / latency retrieval trên
   golden set có kiểm soát.
3. **Latency per-component** — STT, TTS, VAD, speaker verification, LLM/agent,
   full pipeline — mỗi component một con số riêng (p50/p95/p99).
4. **Khả năng chịu tải (CCU)** — ramp concurrency cho chat WS, voice LiveKit, và
   từng service, kèm knee detection và assert hành vi admission.
5. **Registry bền vững** — một file `registry.jsonl` tracked trong git, mỗi run một
   dòng tổng hợp, làm cơ sở monitoring định kỳ và so sánh model/config.

## 2. Ràng buộc (non-negotiable)

- **Không sửa bất kỳ file nào trong `src/`.** Harness chỉ import các seam public:
  `NobleAgent` facade (`agent/facade.py`), `noble_kb.query_noble_kb`, class Silero VAD
  (`voice/vad/silero.py`), và gọi các service remote qua network.
- **Không ghi vào dữ liệu production một cách không phân biệt được.** PG vẫn bật
  (tools cần ĐỌC `tenant_data.projects`/`units`/KB); phần ghi core của agent
  (`conversation_messages`, `conversations`, Redis session keys) được **cách ly bằng
  namespace**: mọi `session_id` mang prefix `eval:<run_id>:<case_id>` trên tenant thật.
  Redis tự dọn qua TTL; dòng PG lọc/xoá được qua prefix. `BILLING_METERING_ENABLED=false`
  khi chạy eval (không ghi `billing.usage_events`).
- **Qdrant/PG chỉ đọc** ở mọi bước của `rag/` (kể cả bước sinh golden set).

## 3. Quyết định đã chốt

| Quyết định | Lựa chọn |
|---|---|
| Kiến trúc | Harness mới thống nhất `evals/` (top-level); **xoá `tests/eval` cũ sau khi port** |
| DB isolation | Namespace eval (session prefix) trên infra thật; KHÔNG tắt PG (tools cần đọc) |
| VAD bench | Import Silero đúng cách worker dùng (in-process, không có service remote) |
| Speaker bench | HTTP request tới speaker service `:9100` (`SPEAKER_REMOTE_URL`) |
| STT/TTS bench | WS request tới service remote `:8770` / `:8771` |
| Chấm chất lượng | Deterministic scorers (port từ `tests/eval`) + LLM judge (pattern `bench_estate`) |
| RAG golden set | Sinh từ corpus Qdrant/PG (read-only) → JSONL draft → **user duyệt tay** trước khi thành chuẩn |
| Registry | JSONL tracked trong git + report Markdown trend; chi tiết per-run gitignored |

## 4. Kiến trúc tổng thể

```
evals/
  __main__.py        # CLI: run | score | bench | load | gen-golden | report | list
  config.py          # EvalSettings (pydantic-settings, env prefix EVAL_)
  registry.py        # append + đọc evals/registry.jsonl
  common/            # run_id, git_sha, fixture loader, percentile helpers
  quality/           # ① full-pipeline agent eval
    cases.py         #   port tests/eval/cases.py (EvalCase.turns, Golden, JSONL loader)
    runner.py        #   port tests/eval/runner.py — NobleAgent.stream_response
    trace.py         #   port tests/eval/trace.py (JSONL, header tự mô tả)
    scorers/         #   policy.py, tool_traj.py, run_integrity.py (port) + rag.py (MỚI)
    judge.py         #   LLM judge (MỚI — pattern tests/bench_estate/judge.py)
    latency.py       #   aggregate ttft_ms/total_ms per-turn → p50/p95 (MỚI)
    scorecard.py     #   port tests/eval/scorecard.py + thêm nhóm latency + judge
    data/
      cases/noble/*.jsonl    # port 30 case p0_policy/p0_tool + case grounding mới
      thresholds.toml
  rag/               # ② RAG component eval (retrieval-only, không qua agent)
    golden_gen.py    #   đọc chunks (read-only) → LLM sinh query→chunk → JSONL draft
    runner.py        #   gọi noble_kb.query_noble_kb per case, đo hit/rank/latency
    metrics.py       #   recall@k, MRR, ndcg (tuỳ chọn), latency percentiles
    data/golden/<tenant>/*.jsonl
  bench/             # ③ component latency (single-request, N lần lặp)
    stt.py           #   WS :8770 — fixture PCM 16k → final; TTFB + total
    tts.py           #   WS :8771 — text → first-audio-chunk + total
    speaker.py       #   HTTP :9100 — embed request round-trip
    vad.py           #   import Silero như worker; per-chunk ms trên fixture
    llm.py           #   TTFT + total qua provider chain đang pin (NOBLE_AGENT_MODEL)
    fixtures/        #   PCM 16k mẫu (tiếng Việt thật, ~5–10s) + câu text chuẩn
  load/              # ④ CCU / chịu tải
    ramp.py          #   port scripts/load_test/v2/common.py (schedule, knee, report)
    chat_ccu.py      #   WS :8766/chat — multi-session, per-turn latency,
                     #   assert admission: WS close 4029 + /health/ready 503 khi vượt trần
    voice_ccu.py     #   port phase_c_livekit.py — synthetic audio, ttfr/total
    service_ccu.py   #   ramp cho STT/TTS/speaker service riêng lẻ
  reports/           # artifact chi tiết per-run — GITIGNORED
  registry.jsonl     # 1 dòng tổng hợp / run — TRACKED
  README.md
```

Nguyên tắc module: `quality/runner.py` là file DUY NHẤT import `NobleAgent`;
`rag/runner.py` là file duy nhất import `noble_kb`; `bench/vad.py` là file duy nhất
import Silero. Scorers/metrics/registry thuần (pure), không I/O ngoài file — test được
không cần infra.

## 5. Sub-harness ①: `quality/` — full-pipeline agent eval

### 5.1 Kế thừa từ `tests/eval` (port nguyên, đã proven)

- **Case schema JSONL**: `EvalCase.turns` (tuple → multi-turn native), assertion
  vocabulary dùng chung với `tests/e2e_scenarios/assertions.py` (import từ đó,
  không copy), field `Golden` (evidence, golden_chunk_id, source, project_code).
- **Kiến trúc RUN / SCORE tách đôi**: `run` sinh `traces.jsonl` (đắt — gọi LLM);
  `score` chấm lại từ trace (rẻ — đổi threshold/scorer không tốn lượt LLM).
- **3 scorer deterministic**: `policy` (violations), `tool_traj` (selection/arg
  accuracy, unnecessary calls), `run_integrity` (errored/loop exhaustion).
- **Gates tuyệt đối** từ `thresholds.toml` (6 gate hiện có giữ nguyên ngưỡng).
- **30 case hiện có** (`p0_policy.jsonl` 14 + `p0_tool.jsonl` 16) port nguyên.

### 5.2 Bổ sung mới

**(a) Latency aggregation** (`latency.py`): trace đã capture `ttft_ms`/`total_ms`
per-turn từ trước — thêm bước aggregate p50/p95 vào scorecard + registry. KHÔNG đặt
gate latency ở phase đầu (giữ quyết định cũ của thresholds.toml) — chỉ báo cáo để
theo dõi trend; gate thêm sau khi có baseline ổn định.

**(b) LLM judge** (`judge.py`): tái dùng pattern `tests/bench_estate/judge.py` —
rubric JSON structured output, temperature 0, retry 2, **sqlite cache** theo
(transcript-hash, rubric-version), **budget cap USD** (`--judge-budget-usd`). Hai
rubric: `grounding` (câu trả lời có bịa ngoài evidence không — đọc `Golden.evidence`)
và `answer_quality` (đúng trọng tâm, đúng persona). Judge chỉ chạy ở mode `--full`;
mode smoke skip judge → deterministic gates vẫn đủ làm release gate nhanh. Judge model
qua env `EVAL_JUDGE_MODEL` (default kế thừa `ESTATE_JUDGE_MODEL`).

**(c) Scorer `rag.py`** (grounding trong ngữ cảnh full-pipeline): với case có
`Golden.golden_chunk_id`, đọc trace tool `kb_search` — kiểm chunk vàng có nằm trong
kết quả retrieval agent thực sự nhìn thấy không (`retrieval_hit_rate`), và câu trả
lời cuối có chứa evidence bắt buộc không (substring/normalized match, deterministic).

### 5.3 Cách ly & môi trường chạy

- `session_id = f"eval:{run_id}:{case_id}"`; tenant lấy từ `EVAL_TENANT_ID`
  (default `noble`).
- Runner ép `BILLING_METERING_ENABLED=false` (env của process eval, không sửa src) và
  từ chối chạy nếu phát hiện billing đang bật.
- Channel mặc định `chat` (persona chat); có cờ `--channel voice` để chấm persona voice
  qua cùng facade (không audio — chỉ khác skeleton prompt).

## 6. Sub-harness ②: `rag/` — retrieval component eval

Đánh giá retrieval TÁCH KHỎI agent để phân biệt "agent hỏi sai" với "retrieval trả sai".

- **`gen-golden`**: đọc chunk từ Qdrant collection `<tenant>_documents` (read-only,
  qua tunnel nếu ngoài VPC) hoặc PG KB; LLM sinh mỗi chunk 1–3 câu hỏi tự nhiên tiếng
  Việt mà chunk đó là câu trả lời đúng; xuất
  `evals/rag/data/golden/<tenant>/draft-<ts>.jsonl` với `status: "draft"`.
  **User duyệt tay** (sửa/xoá câu kém, đổi `status: "approved"`) rồi mới được runner
  nhận. Runner từ chối file còn dòng draft.
- **Runner**: mỗi golden case → `noble_kb.query_noble_kb(query, project_filter)` với
  backend đang cấu hình (`NOBLE_RAG_BACKEND`) → so `golden_chunk_id` (và fallback
  match theo `content_hash`/substring evidence khi backend không trả id) với top-k.
- **Metrics**: `recall@1/3/5`, `MRR`, latency retrieval p50/p95, tỉ lệ trả rỗng
  (bắt được degrade-im-lặng — gotcha đã biết của mọi backend RAG).
- Chạy được cho từng backend (`--backend qdrant|flat_store|kb_service`) để A/B.

## 7. Sub-harness ③: `bench/` — component latency

Mỗi component: `--runs N` (default 10, bỏ run đầu warm-up) → p50/p95/p99 + error rate,
output JSON vào `evals/reports/<run_id>/bench.json` + dòng registry.

| Component | Cách đo | Số liệu |
|---|---|---|
| STT | WS `:8770`, stream fixture PCM 16k theo realtime-pace, đo audio-end → final | TTFB (first partial), final latency |
| TTS | WS `:8771`, gửi câu chuẩn | TTFB (first audio chunk), total, RTF |
| Speaker | HTTP `:9100`, embed request với fixture | round-trip ms |
| VAD | Import Silero y hệt worker (cùng threshold/chunk 32ms từ settings), feed fixture | per-chunk ms (p50/p95), throughput chunks/s |
| LLM | Provider chain đang pin, prompt chuẩn ~1 turn thật | TTFT, total, tokens/s |
| Full pipeline (chat) | 1 session `/chat` WS, 1 turn chuẩn | user_text → first token → done |
| Full pipeline (voice) | 1 phòng LiveKit, synthetic audio (tái dùng code phase_c) | ttfr (audio-end → agent nói), total |

Endpoint đọc từ env đang có (`STT_SERVICE_URL`, `TTS_SERVICE_URL`, `SPEAKER_REMOTE_URL`)
— không hardcode; override được bằng `EVAL_*`.

## 8. Sub-harness ④: `load/` — CCU / khả năng chịu tải

Port ramp engine từ `scripts/load_test/v2/common.py` vào `evals/load/ramp.py`
(schedule `1,2,4,8,…,max`, hold ~60s/bậc, knee = bậc cao nhất throughput còn scale
≥15% và error <1%). `scripts/load_test/v2` GIỮ NGUYÊN (không xoá — kết quả cũ trong
`out/` là lịch sử); evals là bản kế nhiệm.

- **`chat_ccu`**: multi-session WS `:8766/chat`, mỗi session 4 turn kịch bản; đo
  per-turn latency theo bậc concurrency; **đẩy vượt `CHAT_MAX_CONCURRENT_SESSIONS`
  và assert**: session thừa bị close code 4029, `/health/ready` trả 503 khi bão hoà,
  hồi phục sau khi drain. Đây là kiểm chứng admission chưa từng có test.
- **`voice_ccu`**: port `phase_c_livekit.py` — N phòng đồng thời, synthetic audio,
  ttfr/total theo bậc.
- **`service_ccu`**: ramp riêng cho STT/TTS/speaker service (port phase_a) để tìm
  knee từng service — trả lời "component nào nghẽn trước".

Cảnh báo vận hành ghi trong README: load test chạy trên môi trường staging/dev —
KHÔNG nhắm vào production đang phục vụ khách (LiveKit Cloud dùng chung dễ giật cuộc
gọi thật — gotcha đã biết).

## 9. Registry & report định kỳ

### 9.1 `evals/registry.jsonl` (tracked)

Mỗi run một dòng, append-only, schema:

```json
{
  "run_id": "20260824-103000-quality-a1b2c3",
  "ts": "2026-08-24T10:30:00+07:00",
  "kind": "quality | rag | bench | load",
  "git_sha": "f251aa2",
  "config": {
    "model": "<NOBLE_AGENT_MODEL>", "rag_backend": "<NOBLE_RAG_BACKEND>",
    "tenant": "noble", "channel": "chat", "config_source": "db|legacy",
    "judge_model": "...", "cases": 30
  },
  "metrics": {"policy_pass_rate": 1.0, "arg_accuracy": 1.0,
               "ttft_p50_ms": 410, "ttft_p95_ms": 820, "recall_at_5": 0.92,
               "knee_ccu": 64, "...": "chỉ số tổng hợp, KHÔNG per-case"},
  "gates": {"policy_violations": "pass", "arg_accuracy": "pass"},
  "verdict": "pass | fail | error",
  "report_dir": "evals/reports/20260824-103000-quality-a1b2c3/"
}
```

- Dòng registry là TỔNG HỢP; chi tiết per-case/per-turn nằm `evals/reports/<run_id>/`
  (traces.jsonl, scorecard.md, scores.json, transcript, bench.json) — gitignored.
- `verdict: error` khi hạ tầng lỗi (service unreachable, LLM key hỏng) — phân biệt
  với `fail` (chạy được nhưng rớt gate).

### 9.2 `python -m evals report`

Đọc registry.jsonl → sinh `evals/reports/TREND.md`: bảng run gần nhất theo kind,
sparkline/bảng metric chính theo thời gian, so sánh run mới nhất vs run pass gần nhất
(delta từng metric). Đây là bề mặt monitoring định kỳ.

### 9.3 Make targets

```make
eval-quality        # python -m evals run --suite quality [ARGS=]
eval-quality-smoke  # subset nhanh, skip judge
eval-rag            # python -m evals run --suite rag
eval-bench          # python -m evals bench --all
eval-load           # python -m evals load --target chat  (ARGS=)
eval-report         # python -m evals report
eval-periodic       # quality-smoke + bench + report — dành cho cron/CI
eval-selftest       # pytest tests/unit/evals
```

Các target `eval-run/eval-gate/eval-score/eval-list/eval-test` cũ (trỏ tests/eval)
bị thay thế.

## 10. Error handling

- Mỗi sub-harness fail độc lập: `eval-periodic` chạy tuần tự, một suite lỗi vẫn ghi
  dòng `verdict: error` và chạy tiếp suite sau; exit code cuối = OR của các suite.
- Preflight mỗi suite: check Redis ping / PG SELECT 1 / service reachable TRƯỚC khi
  chạy case — fail sớm với thông báo rõ thay vì 30 case timeout.
- Judge: hết budget/lỗi → case đánh `ungraded`, metrics judge báo `coverage` (tỉ lệ
  case được chấm); gate deterministic không phụ thuộc judge.
- RAG trả rỗng hàng loạt (>50% case) → cảnh báo "backend degrade im lặng?" trong
  scorecard (đối chiếu gotcha đã biết).

## 11. Testing harness

`tests/unit/evals/` (port + mở rộng test cũ của tests/eval): scorers thuần với trace
giả, registry append/đọc/idempotent, latency percentiles, golden-gen parser từ chối
draft, thresholds gate logic, ramp knee detection với số liệu giả. Không test nào
cần infra sống — infra-dependent chạy qua chính CLI (smoke).

## 12. Migration & dọn dẹp

1. Dựng `evals/` hoàn chỉnh + port 30 case + port unit tests → xanh.
2. Chạy song song 1 lần: `evals quality` vs `tests/eval` cũ trên cùng case set —
   đối chiếu metric khớp (sai số 0 cho deterministic) trước khi xoá.
3. Xoá `tests/eval/` + các Make target cũ; cập nhật `.gitignore`
   (bỏ `tests/eval/runs`, thêm `evals/reports/`), CLAUDE.md (mục Commands +
   changelog), handoff doc cũ đánh dấu superseded.
4. GIỮ: `tests/e2e_scenarios` (assertions.py là dependency dùng chung),
   `tests/bench_estate`, `scripts/load_test/v2` (lịch sử), `scripts/benchmark.py`
   (đánh dấu deprecated trong docstring, xoá ở đợt sau).

## 13. Ngoài phạm vi (YAGNI)

- Gate latency cứng (chờ baseline ổn định vài tuần registry).
- HTML dashboard (TREND.md đủ; nâng cấp sau nếu cần).
- Eval voice full-duplex với audio thật per-case (voice_ccu đo pipeline tổng là đủ
  cho phase này; WER/chất lượng TTS đã có `scripts/tts_bench`).
- Chaos/degrade injection, tenant-isolation eval (spec §7b/§7c của thiết kế eval cũ)
  — để phase sau.
- Tự động cron trong repo — user tự đặt cron/CI gọi `make eval-periodic`.
