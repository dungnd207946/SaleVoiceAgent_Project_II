# Handoff — Eval Harness P0 (`tests/eval/`)

> **SUPERSEDED 2026-08-24** bởi evals/ — xem docs/superpowers/specs/2026-08-24-unified-evals-harness-design.md

- **Ngày:** 2026-08-18
- **Branch:** `feat/share-agent` — HEAD `3240e7e`, **chưa merge, chưa push**
- **Trạng thái:** P0 xong, đã review đầy đủ. 106 test xanh. **0 dòng `src/` bị sửa.**
- **Spec:** [`docs/superpowers/specs/2026-08-17-agent-eval-pipeline-design.md`](../superpowers/specs/2026-08-17-agent-eval-pipeline-design.md)
- **Plan:** [`docs/superpowers/plans/2026-08-17-eval-harness-p0.md`](../superpowers/plans/2026-08-17-eval-harness-p0.md)
- **README của harness:** [`tests/eval/README.md`](../../tests/eval/README.md)

---

## 1. Đây là cái gì

Một **release gate** cho agent: chạy eval case qua **đúng entrypoint production**
`NobleAgent.stream_response`, ghi trace ra đĩa, rồi chấm offline và xuất scorecard
PASS/FAIL với exit code.

Nguyên tắc kiến trúc (đừng phá):

- **Tách RUN khỏi SCORE.** RUN đắt (cần Redis + LLM + RAG). SCORE rẻ, thuần, đọc trace.
  Đổi ngưỡng / sửa scorer → chỉ chạy lại SCORE, không tốn lượt LLM.
- **Chỉ `runner.py` và `__main__.py` được chạm hạ tầng.** Mọi module khác là hàm
  thuần — không import `noble_agent`, không I/O. Đó là lý do scorer test được mà
  không cần Redis/LLM/RAG.
- **Gate FAIL CLOSED.** Metric không scorer nào sinh ra ⇒ FAIL, không phải skip.
  Metric bị gate mà mẫu số rỗng ⇒ trả `None` ⇒ hiện `missing` ⇒ FAIL.
- **Chỉ case `reviewed: true` mới làm dịch chuyển số bị gate.**

### Bản đồ file

| File | Vai trò |
|---|---|
| `tests/eval/cases.py` | Schema case + loader JSONL strict (validate chặt, key lạ → lỗi lúc load) |
| `tests/eval/trace.py` | Trace JSONL. Dòng 1 = header tự mô tả (git sha, model, rag backend, temperature, config source…), mỗi dòng sau = 1 case |
| `tests/eval/runner.py` | **File DUY NHẤT** import `noble_agent`. Chạy case, bắt trace + timing + loop-exhaustion, dọn Redis khi xong |
| `tests/eval/scorers/policy.py` | Trục policy — bọc `tests/e2e_scenarios/assertions.py` (một bộ từ vựng assert duy nhất) |
| `tests/eval/scorers/tool_traj.py` | Trục tool — selection / arg / error / loop exhaustion |
| `tests/eval/scorers/run_integrity.py` | Trục `run` — case crash, thiếu trace, coverage thật (`cases_gated`) |
| `tests/eval/scorecard.py` | Ngưỡng + verdict + render Markdown. Thuần, không ghi file |
| `tests/eval/__main__.py` | CLI `list`/`run`/`score`. Chỗ duy nhất có side effect |
| `tests/eval/data/thresholds.toml` | **6 gate loại 1** (an toàn tuyệt đối). Ngưỡng chất lượng CỐ Ý chưa có |
| `tests/eval/data/cases/noble/*.jsonl` | **30 case** (14 policy + 16 tool), 0 unreviewed |
| `tests/eval/runs/` | Artifact mỗi lần chạy (gitignored) |

### 6 gate hiện tại

```
policy_violations      <= 0      arg_accuracy          >= 1
unnecessary_call_rate  <= 0      loop_exhaustion_rate  <= 0.02
cases_errored          <= 0      cases_missing_trace   <= 0
```

---

## 2. Cách chạy (đã test thật)

```bash
make eval-test                                    # 106 test harness — không cần gì
make eval-list                                    # liệt kê 30 case
AGENT_CONFIG_SOURCE=legacy make eval-run          # ← lệnh go/no-go (xem §3a)
make eval-score RUN=<RUN_ID>                      # chấm lại từ trace, KHÔNG chạy agent
make eval-score RUN=<RUN_ID> ARGS="--case POL-001"  # nếu run đó chỉ chạy 1 case
```

Ba điều dễ hiểu sai:

1. **Exit code ≠ 0 nghĩa là scorecard FAIL, không phải lệnh lỗi.** `make` bọc thành exit 2.
2. **Chạy 1 case luôn FAIL các gate tool** (`arg_accuracy = missing`). Đó là fail-closed
   đúng: một case policy không thể chứng nhận gate tool.
3. `make eval-score` **không kèm `--case`** sẽ chấm cả 30 case với trace chỉ có 1 →
   29 `missing_trace`. Truyền lại đúng filter.

---

## 3. FACT MÔI TRƯỜNG — đọc trước khi tin bất kỳ con số nào

### 3a. Postgres không có dữ liệu cho tenant `noble`

`tenant_data.agent_config` = **0 row** → `make eval-run` mặc định (`AGENT_CONFIG_SOURCE=db`)
crash với `RuntimeError: no published config for tenant 'noble'`.
`tenant_data.projects` / `units` cũng **rỗng**.

Hệ quả: **baseline đầu tiên phải chạy `AGENT_CONFIG_SOURCE=legacy`**, tức đo **persona
legacy** (`src/noble_agent/tenants/noble/persona/`) chứ không phải persona `db` production.
Case được viết theo scope của persona `db`. **Một FAIL ở mode legacy KHÔNG chứng minh
agent production fail, và một PASS cũng không chứng minh gì.** Chi tiết đầy đủ đã ghi
trong `tests/eval/README.md`.

Muốn baseline thật: publish config cho tenant `noble` + seed `projects`/`units`, rồi bỏ
`AGENT_CONFIG_SOURCE=legacy`.

### 3b. `.env` có 17 dòng comment inline → `make test` (full suite) vỡ

```
SPEAKER_INTERRUPT_MIN_SEC=0.8          # (multi) audio gom trước khi ID speaker...
                          ^^^ pydantic đọc cả comment thành float → 11 validation error
```

`pytest tests/` cho **59 collection error**. **KHÔNG phải do harness** — đã chứng minh:
chạy `tests/` bỏ hẳn `tests/eval` vẫn ra đúng 59 error. Harness không bị vì `__main__.py`
nạp `.env` qua `python-dotenv` (thư viện này *có* strip comment).

Sửa: đưa comment lên dòng riêng trong `.env`.

### 3c. Harness ghi vào Redis dùng chung với production

`REDIS_URL` trong `.env` trỏ **`10.50.13.220:6379/0`** — Redis production. Mỗi case tạo
session thật ở đó.

- **Đã kiểm 4 store:** Redis 🔴 (từng còn 207 key `session:eval-*`, TTL ~22h);
  Postgres ✅ 0 row; Mongo `session_metrics` ✅ 0; `hotline_call_events` ✅ 0.
  (Mongo sạch vì runner cố ý **không** gọi `ensure_session_started()`.)
- **Đã sửa** (`f6c6cf3`, `3240e7e`): `run_case` xoá key của chính nó ở `finally`, chạy
  trên mọi đường thoát, và **không bao giờ đổi kết quả** case.
- **CHƯA xác minh live** — xem §4.
- **Khuyến nghị vẫn nên làm:** tách Redis khi chạy eval bằng DB index riêng
  `REDIS_URL="redis://...@10.50.13.220:6379/9" AGENT_CONFIG_SOURCE=legacy make eval-run`.
  Eval không nên ghi vào store production dù có dọn sau.

### 3d. Baseline đầu tiên: FAIL (đúng như phải vậy)

```
✗ policy_violations = 5    (need <= 0)
✗ arg_accuracy = 0.625     (need >= 1)
✓ 4 gate còn lại
```
`thresholds.toml` **không** bị sửa để làm nó xanh. Phân rã 11 case fail ban đầu:
3 do môi trường (`projects` rỗng → `find_project` not_found → dừng flow theo RULES.md),
5 do agent không escalate ca giá riêng/post-sale (**nhưng không rò rỉ gì**),
3 do agent hỏi lại thay vì gọi tool ngay. Sau khi đóng lỗ rò trục (I2),
`policy_violations` giảm 11 → 5.

### 3e. Sản xuất không bị ảnh hưởng

- `src/` không import `tests/eval`; CI không có target eval; **Dockerfile không copy
  `tests/`** (chỉ `src/ data/ static/ assets/`).
- Không có gì tự chạy. API chỉ tốn khi gõ `make eval-run` bằng tay
  (~30 case × 1–2 lượt LLM trên `gemini-2.5-flash`).

---

## 4. Việc còn treo

| # | Việc | Ghi chú |
|---|---|---|
| 1 | **Xác minh cleanup Redis trên môi trường thật** | BLOCKED lúc bàn giao: host `10.50.13.220` mất route (Redis 6379, PG 5433, ping đều không tới). Khi VPN có lại: chạy `AGENT_CONFIG_SOURCE=legacy python -m tests.eval run --case POL-002` rồi đếm `session:eval-*` — kỳ vọng **không tăng** |
| 2 | **207 key `session:eval-*` cũ** | Tự hết hạn ~22h kể từ 2026-08-17 sáng. Muốn dọn sớm: xoá theo pattern `session:eval-*` (không thể trùng session thật — sid thật không có tiền tố `eval-`) |
| 3 | **Rotate password Redis** | Đã lộ vào transcript session cũ 2 lần (một lần do lệnh che không kín, một lần do thư viện `redis` in nguyên URL trong traceback). Cân nhắc tách credential ra biến riêng để traceback không in |
| 4 | **Seed Postgres cho tenant `noble`** | Điều kiện tiên quyết cho baseline thật và cho P1 |
| 5 | **Sửa 17 dòng comment inline trong `.env`** | Để `make test` chạy lại được |
| 6 | **Quyết định tích hợp** | 23 commit local. CLAUDE.md cấm chạm `develop` và cấm push/PR không có chỉ thị → cần chỉ thị rõ ràng |

### Minor đã ghi nhận, cố ý hoãn

- Trace chỉ ghi sau khi chạy xong cả vòng → Ctrl-C giữa chừng mất toàn bộ trace.
  Cân nhắc ghi tăng dần / `finally`.
- `make eval-gate` hiện **trùng hệt** `eval-run` (P0 chưa có trục judge để loại trừ).
  Sẽ khác nhau khi P1 thêm judge.
- Chưa có test CLI với selection **trộn** reviewed/unreviewed chứng minh
  `cases_scored != cases_gated`.
- `_reject_mixed_channels` cũng chặn cả `run --no-score`, nơi không sinh scorecard —
  hiện vô hại (0 case voice).

---

## 5. Quyết định đã chốt (đừng đảo ngược mà không đọc lý do)

| Quyết định | Vì sao |
|---|---|
| Test harness ở `tests/eval/tests/`, chạy bằng `make eval-test` — **không** thuộc `make test-unit` | Theo quy ước sẵn có của `tests/bench_estate/tests/` + `make eval-estate-test` |
| `checks`/`pass_rate` của trục tool **cố ý bi quan** | `pass_rate` chỉ để hiển thị; gate đọc `metrics`. Bi quan còn hơn hiện "99.2% pass" trên run vừa FAIL. Có test khoá invariant `findings ≠ ∅ ⇒ pass_rate < 1.0` |
| Metric bị gate trả `None` khi mẫu số rỗng (không phải "số + đếm kèm") | Tái dùng đúng đường fail-closed đã có; đồng thời đóng luôn lỗi `TypeError` khi metric là `None` |
| `run_integrity` là trục riêng, không phải gate per-axis | Nó là nơi duy nhất thấy mọi case bất kể axis; tránh gate `tool_selection_accuracy` (spec §8.2 cấm cho tới khi có baseline) |
| `cases_scored` (kích thước selection) tách khỏi `cases_gated` (chỉ reviewed) | Một PASS trên 1 case không được đọc thành PASS toàn suite |
| POL-005 regex số điện thoại **giữ nguyên** | Sample 5 reply thật: agent không bao giờ đọc ra số nào. Siết thêm sẽ là suy diễn. Lý do đã ghi trong `tests/eval/README.md` |
| POL-004 regex neo động từ cam kết vào đại từ (`em\|mình`) | Regex proximity cũ fire trên **cả** câu trả lời đúng lẫn sai (câu từ chối buộc chứa "không thể **cam kết** … **tăng**"). Đo bằng số: cũ fire 2/3 câu đúng và bỏ lọt 1/3 câu sai; mới 0/3 và 3/3 |
| TOOL-001/002 dùng `recommend_units` (không phải `search_units`) | Theo schema: `search_units` = tra căn trong **một** dự án khách đã nêu; `recommend_units` = lọc **xuyên nhiều** dự án theo ngân sách. Hai tool dùng tên tham số khác nhau: `max_price` vs `budget_max` |
| `tests/eval/__main__.py` tự nạp `.env` vào `os.environ` | `storage/redis_client.py` đọc `os.getenv("REDIS_URL")` **trực tiếp**; pydantic-settings không populate `os.environ`. Không có bước này thì mọi case nói chuyện với localhost:6379 không tồn tại |

---

## 6. Bước tiếp theo — P1

Spec §13 định nghĩa 3 phase. P0 xong. **P1** = golden set sinh từ **dữ liệu tenant trong
Postgres** (không phải `data/md_v2/*.md` — đó là corpus `flat_store` legacy agent không
đọc ở mode `db`), + scorer grounding/retrieval/helpfulness, + judge, + **hiệu chuẩn judge**
(chấm tay ~50 lượt, báo cáo Cohen's κ).

**P1 chỉ có nghĩa sau khi Postgres có dữ liệu thật** (việc #4 ở §4). Trước đó không thể
sinh golden set từ `projects`/`units` rỗng, và không thể đo recall khi Qdrant/PG chưa có
nội dung của tenant.

Ba generator dự kiến (spec §5): structured từ `projects`/`units` (đáp án do **SQL tính**,
không cần review tay), KB từ chunk Qdrant `<tenant>_documents` (cần review tay),
`unanswerable` suy ra từ DB (`price_vnd = 0`, cột NULL, không có chunk). Kèm **data
fingerprint** chống golden set lỗi thời khi DB đổi.

---

## 7. Lịch sử commit (P0)

`c9a810c` spec → `3240e7e` HEAD. Các commit chính:

```
51ad2a0 case schema + JSONL loader          e61ed53 scorecard + fail-closed gates
607b884 trace JSONL + header tự mô tả       479f12b runner qua NobleAgent.stream_response
ea89b45 fix customer_after round-trip       9aebdae 10 seed case
8ddd0a4 policy scorer                       3d860d5 fix POL-004 regex
c8f19f1 tool-trajectory scorer              5215253 CLI + make targets
6c2c647 fix per-turn rate + doc asymmetry   88dd0cd cases_scored/case_filter
313acfa nạp .env trước khi dispatch         c8033a2 test case_filter
60eefd8 README + hiệu chỉnh case sau smoke  2fad9bb công bố giới hạn mode legacy
cdbd2bb GATE KHÔNG CÒN PASS TRÊN RỖNG (C1,C2,I2,I3,I4)
c97785b eval-gate phủ trục tool + self-describe (I1,I5)
8ed3528 siết guard case-file + tài liệu fail-closed
f6c6cf3 dọn Redis key mỗi lần run_case thoát
3240e7e siết test cleanup + phủ cancellation + log
```

Lưu ý: `f314ec2 "fix conversation save"` (tác giả: chủ dự án, vào qua merge `develop`)
có chứa **một phần các sửa plan/spec của phiên làm P0** — chúng bị `git commit -a` quét
vào chung. Nội dung đúng, chỉ nằm rải ở hai commit (`f314ec2` và `50a2429`).

Trong lúc làm P0, một merge `origin/develop` (`4d18761`) đã đáp xuống nhánh này từ
bên ngoài session. Đã xác minh: cả 7 commit đầu vẫn là ancestor của HEAD, mọi file
`tests/eval/` còn nguyên, suite vẫn xanh, `NobleAgent.create` signature không đổi.
Merge đó có sửa tool schema/persona RULES — đã kiểm lại và seed case vẫn hợp lệ.
