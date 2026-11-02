# CLAUDE.md

Guidance for Claude Code sessions working in this repository.

## Project

**Noble Voice Agent** — real-time voice hotline for Noble Real Estate. WebRTC, telephony (Asterisk/AudioSocket), and LiveKit RTC transports, with pluggable STT / TTS / LLM, VAD-based interrupts, and RAG-powered Q&A. Python 3.11–3.13. Serves port **8766**.

Package: `noble-voice-agent` (installed as `noble_agent`, CLI entry `noble-agent`).

**Active codebase:** `src/noble_agent/` — single-agent unified architecture (persona: **Luna**), renamed from the former `noble_agent_unified`. The earlier multi-agent and `noble_agent_refactor` packages have been deleted. Always work in `src/noble_agent`.

Design spec: [docs/superpowers/specs/2026-06-03-noble-agent-unified-design.md](docs/superpowers/specs/2026-06-03-noble-agent-unified-design.md).

## Branch & Workflow Rules — DO NOT VIOLATE

- **Never touch `develop`.** Don't check out, merge into, push to, or fetch onto `develop`.
- **Default working branch is whatever the user is on** (e.g. `feat/unify-agent`). Run `git branch --show-current` to confirm. Don't create new branches without explicit approval.
- **No `git worktree add`, `git merge`, `git rebase --onto`, `git push`, `gh pr create`** without explicit instruction in the same session. Local commits on the user's feature branch are fine.
- **Cherry-picking between user-owned branches requires permission.**
- "Commit and continue" = commit on the current branch only.

## Self-Maintenance Rules for This File

CLAUDE.md must stay accurate or it actively misleads the next session. Update it (in the same commit as the code change) whenever any of these happen:

1. **Architecture / layering change** — files move between layers, a new layer is introduced, the audio pipeline order changes, the single-agent assumption is broken.
2. **Major bug fix that changes a workflow rule** — e.g. an invariant was added (history must stay consistent on mid-tool-loop failure), a new env var gates behavior, a tool was added/removed from the agent's catalog.
3. **New tool, new STT/TTS backend, new transport** — update the pluggable-backends list and the tool catalog summary.
4. **Storage schema change** — Redis key shape, Postgres `tenant_data` table/column change, new `State` / `Customer` field.
5. **Command surface change** — new Make target, renamed script, changed env var name.
6. **User explicitly says "remember this" or "this rule from now on"** — encode it here, not just in memory.

When you make such a change, edit the relevant section AND ghi changelog. If a section becomes stale, fix it; don't leave a stale paragraph next to a "see also" note.

**Changelog đi vào hai chỗ (2026-08-06 tách file):**

- [`docs/CHANGELOG-agent.md`](docs/CHANGELOG-agent.md) — bản đầy đủ, thêm entry mới lên ĐẦU bảng.
- Bảng `## Change Log` cuối file này — bản **1–2 câu**, giữ đúng **10 entry gần nhất**; thêm entry mới thì xoá entry thứ 11.

**Budget kích thước: giữ CLAUDE.md ≤ 45 KB.** File này nạp vào MỌI session — mỗi KB
thừa là context người sau mất trước khi gõ chữ nào. Trước 2026-08-06 nó phình tới
**271 KB (~85k token)** vì changelog viết dạng prose dài và mọi chi tiết đều nhét vào
đây; đã nén còn ~40 KB bằng cách đẩy chi tiết sang `docs/architecture/*`.

Khi cần thêm nội dung: hỏi "cái này phải biết NGAY ở mọi session, hay tra khi cần?"
Phải-biết-ngay (rule, lệnh, bẫy, bản đồ) → ở đây. Tra-khi-cần (pipeline chi tiết,
bảng env đầy đủ, lịch sử) → `docs/architecture/*`, `docs/superpowers/specs|plans/`,
rồi để lại một dòng trỏ tới. **Nếu chạm trần thì nén, đừng nới budget.**

What does NOT belong here: per-task progress, in-flight plans, todos, recent commit summaries, anything derivable from `git log`. Memory and conversation context cover those.

## Commands

```bash

# Setup (Python 3.11+)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                       # set ANTHROPIC/OPENAI/GEMINI + SONIOX keys

# Run dev server (hot-reload, port 8766). Needs USE_UNIFIED_AGENT=true in .env.
scripts/run.sh
scripts/run.sh --no-reload
noble-agent                                # via installed CLI

# Open http://localhost:8766/chat for the text chat tester (no audio).

# Drive the agent from the terminal — same NobleAgent.stream_response entrypoint as

# the transports, but prints every tool call + args + raw result + TTFT (what /chat

# hides). Needs Redis + an LLM key.
python scripts/chat_repl.py                       # REPL; /tools /customer /raw /last
python scripts/chat_repl.py --ask "câu hỏi"       # one-shot
python scripts/chat_repl.py -t <tenant_id>        # simulate a per-request tenant

# Live-check just the two retrieval tools against real embed+Qdrant. Needs NO config

# bundle / Redis / LLM — it calls the tool functions with an explicit tenant, so it works

# even when no tenant has a published config. Separates "infra unreachable" from "no

# matching data" (both degrade silently). Open the tunnel first if outside the VPC.
scripts/qdrant_tunnel.sh &                        # SSM port-forward → 127.0.0.1:16433
make test-search ARGS="-i"                        # interactive: type your own queries (/help)
make test-search                                  # ARGS="--list" | ARGS="-t <tenant>"

# Tests
make test                                  # all
make test-unit                             # tests/unit
make test-integration                      # tests/integration (some need Docker)
make test-unified                          # tests/unit/unified + tests/integration/unified
make e2e                                   # python -m tests.e2e_scenarios (ARGS="..." để truyền flag)
pytest tests/unit/unified/test_runner.py::test_x -v

# Markers: requires_docker, bench (opt-in via -m bench), needs_redis, needs_qdrant

# Lint / format
make lint                                  # ruff check src/ tests/
make format                                # ruff format

# Benchmarks
make bench-component                       # scripts/benchmark.py (STT/LLM/TTS, live)

# `make bench` + `make perf-report` đã XOÁ 2026-08-18: bench_latency.py gọi
# `agent.registry` (multi-agent, đã xoá) nên vốn đã hỏng; perf_report đọc
# Mongo `session_metrics` (đã xoá). Latency tổng hợp lịch sử hiện KHÔNG có.

# Estate eval (answer-quality, tests/bench_estate/)
make eval-estate                           # full run, LLM judge: gpt-5.4-nano-2026-03-17
make eval-estate-smoke                     # section A, 5 cases, --no-judge
make eval-estate-list
make eval-estate-test                      # pytest the harness itself

# Unified evals harness (evals/, replaces tests/eval — registry evals/registry.jsonl records every run)
make eval-quality ARGS="--case POL-001"    # tool_selection/trajectory/policy/run_integrity + latency (+ --judge = 3 rubric, --tag, --case list)
make eval-quality-smoke                    # POL-001,TOOL-001,QA-001 fixed smoke set (tenant du_test)
make eval-rag                              # retrieval metrics (context_recall/precision/mrr) vs golden v2 (+ --judge = generation stage)
make eval-bench                            # per-component bench: STT/TTS/speaker/VAD/LLM
make eval-load                             # CCU ramp: chat admission (4029/503) / voice / per-service
make eval-report                           # aggregate registry.jsonl into a trend report
make eval-periodic                         # cron/CI: smoke + bench + report, exit = OR of all
make eval-selftest                         # pytest tests/unit/evals/ (the harness's own tests)
make eval-labeller                         # python -m evals labeller — server (127.0.0.1:8765) + UI to approve cases/golden

# Docker stack (agent + Redis)
docker compose up -d
```

Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Pytest uses `asyncio_mode=auto`.

## Architecture — Unified Single Agent

**One agent (Luna) owns the entire conversation end-to-end.** No router, no consultant/support split, no `switch_agent` tool. Luna's scope is **pre-sale** (tư vấn dự án + đặt lịch tham quan); **post-sale** (khách đã mua: hợp đồng / thanh toán / sổ hồng / bảo hành) and **private pricing** are handed off to a human via the `escalate` tool — the only human handoff. State lives in 3 Redis keys per session: `meta` / `customer` / `state` (history + optional summary + scratchpad).

### Một agent dùng chung cho N tenant

**MỘT process agent phục vụ nhiều tenant — KHÔNG phải một worker/bundle mỗi tenant.**
Tenant resolve **per-request** qua `tenant/current.py::current_tenant()` (một `ContextVar`);
mọi cache mức-module đều keyed theo tenant nên dữ liệu tenant A không rỉ sang lượt của B.
Voice: một worker pool đăng ký `settings.livekit_agent_name` dùng chung, tenant đi trong
participant metadata. Chat: tenant đi trong header `X-Tenant-Id` — gateway tự resolve tenant
bằng Bearer API key qua runtime-credentials API (`GATEWAY_CREDENTIALS_API_URL`, không còn
subdomain/`control.*`), rồi forward PG role/password per-tenant (`X-PG-Role`/`X-PG-Password`/
`X-PG-Expires`) cho worker dựng pool riêng qua `pool_for_tenant`. (`X-PG-Deployment`/`X-PG-Kind`
đã BỎ 2026-08-19 — Portal `0941` xoá `control.deployments`, `0919` xoá `kind`.)
Voice không có hop trực tiếp gateway→worker (dispatch qua LiveKit Cloud) nên credential per-tenant
đi vòng qua Redis: gateway stash Fernet-encrypted vào `noble:pgcred:<tenant>` (TTL=expires_at)
trước khi dispatch, LiveKit job `fetch_and_register` lúc vào cuộc để đăng ký cùng cơ chế
`pool_for_tenant`. Không có credential (dev/REPL, hoặc stash/fetch fail) thì rơi về shared DSN
như cũ — best-effort, không chặn cuộc gọi.

Khác biệt DUY NHẤT giữa các tenant là **config có cấu trúc** (identity/scope/tools) — khung
prompt giống hệt nhau. Hai nguồn config, gate bằng `AGENT_CONFIG_SOURCE`: `legacy` (default,
bundle `tenants/<id>/`) hoặc `db` (persona skeleton dùng chung + config đọc từ VIEW Postgres
`agent_published_config`; ở mode này TOÀN BỘ control-plane đọc Postgres, MinIO không nằm trên
serving path).

→ Chi tiết: [`docs/architecture/multi-tenant.md`](docs/architecture/multi-tenant.md)

### One turn, end to end

```
user_text
  ↓
NobleAgent.stream_response (agent/facade.py — drop-in for transport)
  ↓
TurnRunner.handle_turn (agent/orchestrator.py)
  ├─ semcache.cancel_refresh   (kill stale prefetch from prior turn)
  ├─ repo.load(sid) → (meta, customer, state)
  ├─ append ThreadMessage(user, user_text)
  ├─ try semcache full-mode hit → replay chain → done
  └─ else run_turn (agent/runner.py):
        ├─ build_system_prompt(agent_def, customer, state.summary)   # jinja2
        ├─ messages = [system] + build_request_messages(history[covers_turns:])
        │     # tool result lượt cũ (ngoài 2 user-turn cuối) → digest; session_facts.render()
        │     # (hồ sơ MỚI NHẤT + căn/tài liệu/lịch đã đưa) chèn đầu user msg cuối — chỉ request
        └─ for _ in range(MAX_TOOL_ITERATIONS=7):   # chạm trần → 1 vòng chốt tools=[]
             content, tool_calls = llm.stream_completion(... on_token, interrupt_check)
             append assistant msg
             if no tool_calls → return
             for tc in tool_calls: dispatcher.dispatch(tc) → append tool msg
             # (không rebuild system prompt giữa lượt: customer block đóng băng cả phiên)
  ↓
  meta.last_active = now; repo.save_all
  if pending_turns > summary_threshold_K: asyncio.create_task(_run_summary_then_warm)
    # summary persists, then (if NOBLE_SUMMARY_WARM_CACHE) a throwaway warm call
    # replays the next turn's exact request so the provider prompt cache is warm.
    # Warm is a separate per-sid task (_warm_tasks), cancelled at the next turn's start.
  transcript_writer.write_session_async
  callbacks.on_done   (fired in finally — transport never wedges on exceptions)
  semcache.schedule_refresh   (predict + sandbox the next turn)
```

Invariants the runner / orchestrator enforce (don't break these):

- Every `assistant(tool_calls=[...])` must be followed by all matching `tool` messages before the turn persists. On mid-tool-loop crash, the orchestrator truncates `state.history` back to the pre-turn anchor.
- Tool calls with empty `id` or `name` (provider cut mid-stream) are dropped before persisting.
- On `interrupt_check()` true mid-tool-loop, placeholder `{"interrupted": true}` tool results are injected so the invariant holds.
- Khoá `instruction` trong tool result (directive một-lượt: upsell pitch…) bị gỡ khỏi history TRƯỚC `save_all` + warm (`_strip_tool_directives`) — directive chỉ sống một lượt; dữ liệu (`over_budget`/`highlights`…) giữ nguyên, prefix cache ổn định.
- `on_done` always fires — success, exception, or `CancelledError`.
- Background summary tasks are held in `_bg_tasks` strong-ref set (asyncio only keeps weakrefs).

### Transports

All converge on the same agent core via the `NobleAgent` facade:

- **Browser WebRTC** (`server/ws_handler.py` → `server/session.py`) — Opus 48 kHz → 16 kHz → VAD → STT → agent → TTS 24 kHz → 48 kHz → Opus.
  Barge-in (mọi transport voice): transport `agent.interrupt()` + cancel task `handle_utterance`; `VoiceAgent` bắt `CancelledError` và gọi `NobleAgent.note_interrupted(spoken_text)` cắt assistant cuối trong history về phần khách đã nghe (`agent/interrupt_trim.py`).
- **Text chat tester** (`server/text_chat.py`, path `/chat`) — same brain, no audio. Each tab = a `session_id` (resumable via `?session=`).
- **Telephony** (`telephony/`) — inbound PSTN via Asterisk ARI + AudioSocket TCP (G.711 8 kHz, resampled 8↔16 kHz).
- **LiveKit RTC** (`transport/livekit/`) — SIP/PSTN over LiveKit rooms (μ-law↔PCM16).

Audio pipeline (full-duplex streaming):

```
mic → resample 48→16 → Silero VAD → Streaming STT
    → Smart Turn (ONNX semantic endpoint, optional)
    → Streaming LLM (+ tools)
    → Sentence buffer (clause/sentence segmentation)
    → Streaming TTS → resample 24→48 → speaker
```

Barge-in: `VAD_INTERRUPT_CONFIRM_CHUNKS` (3) chunk 32 ms liên tiếp có tiếng; khi audio agent đang phát còn phải vượt sàn `BARGE_IN_RMS_THRESHOLD` (RMS int16, mặc định 1500, 0 = tắt) để lọc echo residual — `voice/vad/silero.py`.

### Layout — `src/noble_agent/`

| Path | Vai trò |
|---|---|
| `__main__.py` / `_runner.py` | CLI entry (route theo `TRANSPORT_BACKEND`) / compat shim |
| `config.py` | `UnifiedSettings` (pydantic-settings, ~370 field) — **mọi env var sống ở đây** |
| `agent/` | Bộ não: `facade.py` (`NobleAgent`, cache runner theo `(tenant, version)`), `orchestrator.py` (`TurnRunner`), `runner.py` (vòng LLM+tool), `context_compaction.py` (history → request: digest tool cũ + khối ngữ cảnh), `session_facts.py` (fact phiên do code ghi từ kết quả tool), `base.py` (`AgentDef`), `agent_config.py` (DB path), `persona_compose.py`, `prompts/`, `tools/`, `rag/`, `memory/`, `llm/`, `summary/`, `catalog.py` |
| `persona/` · `tenants/` | Skeleton dùng chung (DB path), **tách per-kênh: `persona/chat/` + `persona/voice/`** (transport khai báo `channel` bắt buộc ở `NobleAgent.create`) · bundle per-tenant (legacy path, phẳng — dùng chung cho cả 2 kênh qua fallback `resolve_persona_dir`) |
| `tenant/` | Resolve tenant per-request, load config bundle, versioning, heartbeat, provisioning PG |
| `server/` · `telephony/` · `transport/livekit/` | 4 transport, đều hội tụ về facade `NobleAgent` |
| `voice/` | VAD, turn detection, STT/TTS cắm-được, speaker policy, sentence buffer |
| `storage/` | Redis (3 key/session), Postgres (pool + `tenant_conn` RLS), DAO data-plane |
| `gateway/` | Ingress per-tenant cho client provider (voice WS → LiveKit, chat WS reverse-proxy) |
| `data/` | Provider `pg_kb`, embed client, qdrant search, media, project matching |
| `billing/` | Đo tiêu thụ để tính tiền (gated `BILLING_METERING_ENABLED`): `meter.py` (in-memory, lớp DUY NHẤT chạm đường nóng), `sink.py` (INSERT `billing.usage_events`), `capture.py` (chuẩn hoá usage provider → 4 cột token), `context.py` (ContextVar + registry theo phiên + high-water seq) |
| `semcache/` · `metrics/` · `observability/` | Cache ngữ nghĩa (off) · Latency collector trong-phiên · Phoenix OTEL |
| `SMOKE.md` | Checklist smoke thủ công — **chạy sau mọi thay đổi chạm turn loop / prompt / transport** |

→ Vai trò đầy đủ từng module: [`docs/architecture/layout.md`](docs/architecture/layout.md)

### Pluggable backends

Chọn bằng env, lazy-import. Thêm backend mới = implement interface + đăng ký vào builder map.

| Loại | Env | Lựa chọn | Fallback chain (init-time) |
|---|---|---|---|
| STT | `STT_BACKEND` | `soniox` · `sherpa` · `elevenlabs` · `qwen3asr` · `remote` | `remote → soniox → sherpa` |
| TTS | `TTS_BACKEND` | `vieneu` · `elevenlabs` · `remote` | `remote → elevenlabs → vieneu` |
| LLM | `NOBLE_AGENT_MODEL` | 5 slot: `anthropic` · `vllm` · `openai` · `dashscope` · `gemini` | theo thứ tự build, primary được pin lên đầu |
| Speaker | `SPEAKER_MODE` | `off` · `single` · `multi` | — |
| Transport | `TRANSPORT_BACKEND` | `aiortc` · `livekit` | — |

Ba điểm dễ sai nhất (chi tiết + phần còn lại ở doc):

- **Fallback chỉ chạy lúc init/start.** Backend lên khoẻ rồi chết giữa cuộc gọi KHÔNG kích hoạt fallback. Riêng STT (2026-08-07): `ReconnectingSTT` restart CHÍNH backend đang dùng khi stream chết giữa call — vẫn không đổi sang backend khác.
- **`<P>_MODEL` rỗng = bỏ qua hẳn provider đó.** `NOBLE_AGENT_MODEL` phải bằng đúng một `<P>_MODEL` đã cấu hình, nếu không chain rơi về thứ tự mặc định (chỉ log warning).
- **Ba slot OpenAI-compat là RIÊNG BIỆT** (`vllm` / `openai` / `dashscope`) — đừng dùng chung `OPENAI_*` cho cả ba.

→ Chi tiết: [`docs/architecture/backends.md`](docs/architecture/backends.md)

### Adding a new tool

**Standard (all-tenant) tool:**
1. New file `agent/tools/<name>.py` with an async executor.
2. Add the schema in `agent/tools/schemas.py`.
3. Register a `ToolSpec` in `agent/tools/builtins.py` (a thin adapter over the executor, taking the kwargs bag `args, *, state, customer, callbacks, session_id, provider, tenant, rag, dispatcher`). Set `dirties_customer=True` if it mutates `Customer` (only the semcache sandbox reads the flag today — the live runner keeps the customer block frozen per session) and `read_only` to match its semcache classification.
4. Offer it: **`legacy` path** — add the name to `tenants/noble/manifest.toml` `[tools].enabled`; **`db` path** — add it to `OPTIONAL_TOOLS` in `agent/agent_config.py` (or `CORE_TOOLS` if it must always be on), and Portal adds it to the tenant's published `config.tools.enabled`.
5. Document it. **Since 2026-08-27 the schema `description` is the ONE source of truth** for when to call a tool, its step order and how to read each result kind — write the protocol there, not in RULES. The skeleton `persona/chat/RULES.md` + `persona/voice/RULES.md` keeps only cross-tool rules (xưng hô, không bịa, escalate, rỗng→nới, style, guardrails) plus a one-line-per-tool index, under a locked budget (rendered chat ≤ 16k chars, voice ≤ 11k — `test_persona_skeleton.py`). A cross-tool sentence that must name the tool goes inside `<!-- TOOL:<name>:START/END -->` (both channels) so it is stripped for tenants without it; feng-shui text in `search_units` sits in `[FENG_SHUI]…[/FENG_SHUI]` and `build_schemas` cuts it when the ranker is off. Inside a schema description, a sentence that names ANOTHER tool goes in `[TOOL:<name>]…[/TOOL:<name>]` — `build_schemas` keeps it only when that tool is offered too (e.g. `kb_search` pointing price questions to `search_units`, 2026-08-27). The **`legacy`** bundle `tenants/noble/persona/RULES.md` is frozen — don't extend it.

Tool taxonomy (source of truth `agent/agent_config.py`): **4 core** (`update_customer`/`kb_search`/`find_project`/`escalate`) always on; van xả **`no_lookup_needed`** CHỈ được chào khi `LLM_FORCE_TOOL_FIRST_ROUND=true` (rời CORE_TOOLS 2026-09-03 — cờ tắt thì nó là tool chết chiếm chỗ prompt; facade tự thêm ở cả path db lẫn legacy); **6 optional** provider-tick (`discover_projects`/`get_document`/`search_units`/`booking`/`send_media`/`analyze_projects`). **Merge 2026-09-07 (6→3 tool dữ liệu cấu trúc):** `search_units` nuốt `recommend_units` (scope bắt buộc `in_project`|`all_projects` phân đôi nghĩa project_code rỗng; envelope 2 nhóm units/upsell_units; phong thủy + union filter ở cả hai scope), `discover_projects` nuốt `get_project_overview` (có project_code → overview đầy đủ), `analyze_projects` nuốt `check_inventory` (tồn kho = GROUP BY trên `agent_units_v`; SQL SELECT read-only dưới role `agent_sql_ro`, CLI `pg-ensure-sql-ro`). Tên cũ trong config đã publish / manifest được map qua `TOOL_ALIASES` (`agent_config.resolve_tool_aliases`, áp ở cả path db lẫn loader legacy, log warning) — Portal dọn config xong thì gỡ. Đó là TOÀN BỘ 11 built-in — không còn tool "reserved" nào.

**Tenant-specific custom tool** (SaaS Phase 3c): drop one file in `tenants/<id>/tools/<name>.py` with a `@tool(name=..., schema=..., tenant="<id>", read_only=..., dirties_customer=...)`-decorated executor `async def <name>(args, *, provider, tenant, **_) -> str`; add the name to that tenant's `manifest.enabled`. The loader imports `tenants/<id>/tools/` at boot so the decorator self-registers; it is invisible to other tenants and shadows a built-in of the same name for that tenant only. No core edit.

### Storage

- **Redis** — 3 keys per session: `session:{sid}:meta`, `session:{sid}:customer`, `session:{sid}:state`. TTL = `session_ttl_seconds`. Summary updates use WATCH for optimistic concurrency on the `state` key.
- **MongoDB — ĐÃ XOÁ HOÀN TOÀN (2026-08-18).** Không còn `motor`/`pymongo` trong deps, không còn `MONGODB_URI`/`MONGODB_DATABASE`, `storage/connection.py` giờ chỉ quản Redis. Mọi DAO Mongo (`mongo_client`/`agent_messages`/`bookings_flat`/`call_summaries`/`call_events`/`user_snapshots`/`noble_profiles`/`resilience`) đã xoá; transcript đọc từ PG `conversation_messages` qua `pg_data_plane.read_session_messages`. **Mất theo:** sink `session_metrics` + `/api/metrics/*` + `make perf-report` + `make bench` (chưa có nhà ở PG — xem changelog), và audit log `call_events` (write-only, không có reader nào).
- **FAISS** — SemanticCache hot layer for prefetch (only when semcache is enabled).
- **Postgres (SP-E1+E2, Odyssey only, `POSTGRES_ENABLED=true`)** — the Odyssey data plane (contract C4). Schema `tenant_data` with 4 agent-write tables `conversations` / `conversation_messages` / `appointments` / `contacts`. **`conversation_messages` (2026-08-06) = realtime per-message transcript:** one row per turn message `{seq, role, content, created_at, meta jsonb}` (meta = optional tool_calls/name/tool_call_id; system messages skipped), PK `(tenant_id, session_id, seq)` where `seq` = the message's absolute index in `state.history`; written as ONE INSERT batch per turn (`ON CONFLICT DO UPDATE` — retry rewrites, a reset session reusing its sid overwrites from seq 0) fired fire-and-forget from the orchestrator's existing `_persisted_msg_count` delta cursor AFTER a successful `save_all` — never awaited on the streaming path (`storage/pg_data_plane.py::persist_turn_messages`). `ThreadMessage.created_at` (default_factory, UTC) stamps append time; storage-only, never rendered into `to_openai()`. `conversation_messages` là transcript DUY NHẤT — cột `conversations.full_conversation` đã BỎ (2026-08-07): DDL không tạo nữa, `record_conversation`/`persist_conversation` không ghi nữa; row `conversations` chỉ còn call record phẳng (summary/handoff/version + `source` = transport `voice`\|`chat`, thêm 2026-08-07; + `agent_key_id` = API key Portal mà gateway đã auth ra connection, thêm 2026-08-19 — lan truyền per-connection qua contextvar `tenant/current.py::current_agent_key_id`, NULL khi không qua gateway). **`conversations` SEED realtime (2026-08-17):** orchestrator fire-and-forget `pg_data_plane.seed_conversation` sau MỖI lượt `save_all` thành công — upsert phần phẳng (phone/name/project/source/started_at/running_version), **không** ghi `summary`/`ended_at` (COALESCE merge sẽ giữ giá trị seed và che mất bản thật lúc close); `persist_conversation` lúc kết thúc phiên vẫn điền summary/ended_at như cũ. Trước đó row chỉ sinh ra lúc đóng phiên → tab `/chat` mở lâu không có row cho tới khi refresh, còn voice trông "realtime" chỉ vì cuộc gọi tự kết thúc. `TurnRunner` nhận thêm `channel`/`version` (runner vốn đã cache theo `(tenant, version, channel)` nên là hằng số mỗi lượt) để đóng dấu `source`/`running_version`; seed KHÔNG đòi phone (khác `persist_conversation`) nên phiên chat chưa có số vẫn hiện. **RLS ENABLE+FORCE with TWO PERMISSIVE policies (OR'd) on each table (Plan 2 — Option C pooling, 2026-07-31):** `tenant_isolation` (`USING/WITH CHECK (tenant_id = current_user)`) still serves the Portal/admin per-tenant LOGIN roles created by `pg-provision` (unchanged, O5); `agent_runtime` (`USING/WITH CHECK (tenant_id = current_setting('app.current_tenant', true))`) serves the agent's own runtime traffic, which now connects as **ONE SHARED app role** (`POSTGRES_APP_ROLE`, default `odyssey_agent` — LOGIN, non-owner, non-superuser, **NOT BYPASSRLS** so FORCE still binds it, CRUD-granted, provisioned once via `ensure_app_role`/`noble-tenant pg-ensure-app-role`, NOT per-tenant) instead of a per-tenant login. Each turn/call scopes its transaction to a tenant via `storage/postgres_client.py::tenant_conn(pool, tenant_id)` — `SELECT set_config('app.current_tenant', $1, true)` (`is_local=true`, so it resets when the txn ends and a REUSED pooled connection can never leak the prior tenant's scope — proven live under a size-1 pool). `assert_app_role_distinct` (`tenant/pg_provisioning.py`) guards the app-role name against colliding with any tenant_id (else it would accidentally match `tenant_isolation`'s `current_user` clause too). Fail-closed: an unset GUC → NULL → 0 rows. `pg_data_plane._tenant_id()` reads the Plan-1 per-request `current_tenant()` contextvar (not `settings.tenant_id`), so **one shared agent process serves N tenants** with per-transaction DB-enforced isolation (BR08/BR09) — a code bug cannot leak rows across tenants even under connection reuse. DDL `storage/sql/odyssey_data_plane.sql` (idempotent: `CREATE … IF NOT EXISTS` + `ALTER … ADD COLUMN/CONSTRAINT IF NOT EXISTS` for later-added `appointments.appointment_id`/UNIQUE + `contacts.profile` + the `agent_runtime` policy); async pool `storage/postgres_client.py` (asyncpg, lazy); write DAOs + best-effort call-site wrappers `storage/pg_data_plane.py`; agent-owned provisioning `tenant/pg_provisioning.py` + `noble-tenant pg-apply-schema`/`pg-provision`/`pg-deprovision`/`pg-ensure-app-role`. **SP-E2 CUTOVER DONE (PG-only writes):** the agent write+read paths for all 3 tables go to PG; the old Mongo DAOs were deleted outright on 2026-08-18. `appointments` keyed on the agent-minted `appointment_id` (APTxxxxx) so `modify` upserts the same row; `conversations` merge-upsert by (tenant,session) carrying `running_version` from `NobleAgent.pinned_version`; the old structured `customers` profile is folded into `contacts.profile` jsonb (independent of the free-text `snapshot` column on the same row). The CSKH dashboard (`http /api/v1/sales/*`) is **gone from the worker entirely** (2026-08-18 — it had been 410-gated, so every handler behind the gate was unreachable code; Portal owns this surface and reads PG directly). `POSTGRES_DSN` = runtime shared-app-role DSN; `POSTGRES_ADMIN_DSN` = provisioning superuser (off the turn path). Wrappers no-op when PG unconfigured (e.g. `noble` before its role is provisioned) → inert on Santa/Noble until a role + `POSTGRES_ENABLED=true` exist.
- **Postgres bề mặt ghi THỨ HAI: `billing.usage_events`** (gated `BILLING_METERING_ENABLED`, mặc định tắt). **Schema `billing` do Portal sở hữu; agent chỉ ghi thêm** — không `UPDATE`/`DELETE`/`TRUNCATE`, không cột tiền (quy đổi giá là việc của Portal). **Bảng + GRANT + RLS đã tạo thật trên DB `portal` (10.50.13.208:5442) ngày 2026-08-18** bằng `portal_migrator` — role duy nhất tạo được DDL ở đó; `portal_api` trong `POSTGRES_DSN` không có `CREATE` ở đâu cả. Idempotency nằm hoàn toàn ở `ON CONFLICT ON CONSTRAINT usage_events_idem DO NOTHING` với khoá 7 cột `(tenant_id, session_id, seq, component, purpose, provider, model)` — **đừng thêm cột nào vào khoá gộp của `meter._aggregate_events`**: một lô có hai dòng cùng 7 cột khoá thì dòng thứ hai bị `DO NOTHING` nuốt KHÔNG log (đúng lỗi đã sập với cột `exact`). **`SELECT` PHẢI được cấp** dù agent không đọc lại: Postgres đòi `SELECT` cho `ON CONFLICT` có nêu arbiter, thiếu nó thì 100% dòng billing mất im lặng — và đừng "sửa" bằng cách bỏ `ON CONSTRAINT` (dạng trần nuốt xung đột trên mọi unique ⇒ mất lưới chống nhân đôi hoá đơn). Policy `agent_read` vì thế là load-bearing, không phải dư. Ghi ngoài đường nóng: `fire_and_forget` sau mỗi `save_all`, cộng một lần `final=True` lúc đóng phiên (thất bại ở lần cuối thì dump payload JSON mức `error`). Contract đầy đủ (DDL/GRANT/RLS/VIEW rollup + checklist Portal): [`docs/handoff/agent-postgres-billing-write-contract.md`](docs/handoff/agent-postgres-billing-write-contract.md); design: [`docs/superpowers/specs/2026-08-18-billing-usage-metering-design.md`](docs/superpowers/specs/2026-08-18-billing-usage-metering-design.md).

### Data

`data/md_v2/ABOUT_<Name>.md` (**the RAG corpus source for all 15 projects** — sliced by `build_faq_flatstore.py` → `data/rag/lightrag_s02_*/`), `data/faq/` (`<CODE>.md` is the corpus for the `grep_faq` backend; the `*_faq.json` files are orphaned — the dynamic-FAQ searcher that read them was removed), `data/flat_store/` (FlatStore embeddings + BM25 indices, gitignored, ~30 MB), `data/faq_cache/` (per-project FAQ npz, gitignored), `data/hotwords.txt`, `data/tts_pronunciation.json`, `data/fake_customers.json`.

## RAG Stack

### Single source of project truth: `agent/catalog.py`

15 Noble projects (NCLB / NCTH / NCR / NPLB / NPTH / NTTL / SLC / SSC / SGR / SGI / SRP / SCHN / SBR / ALLUVIA / Alumi), longest-first alias resolution, ambiguous tokens reject (return `""`). With 15 projects many former-unique tokens are now ambiguous and are NOT aliases of anything (e.g. bare `sunshine`, `crystal`, `palace`, `noble crystal`, `noble palace`, `tây hồ`, `long biên`) — only multi-word discriminators map to a code. The static `data/project_registry.py` has been deleted — `discover_projects` (tên cũ `list_projects`, đổi 2026-07-22; từ 2026-09-07 kiêm overview) / `search_units` nay đọc **Postgres** qua provider `pg_kb` (`tenant_data.projects`/`units`), KHÔNG phải Mongo `project_du_an` nữa (SP1, 2026-08-03).

**Project codes are resolved on demand, not enumerated.** As of 2026-07-22, project-code tool params (`kb_search.project_filter` — tên cũ `noble_search`, `send_media.project_code`, and the string `project_code` on `booking`/`discover_projects`/`get_document`/`search_units`; `get_project_financial` đã XOÁ ở SP1) are plain free-text strings — there is no per-session code ENUM injected into their schemas, and the system prompt no longer carries a full-roster project table (`{{ project_table }}` + `builder._project_table()` were removed, along with the tool-schema enum plumbing `_with_project_enum`/`_ENUM_TOOLS`/`_PROJECT_CODE_TOOLS` and the `state.scratchpad["project_codes"]` snapshot). Instead Luna calls the **`find_project`** tool with the customer's spoken project name; it resolves via `data/project_matching.ProjectNameIndex` (VN phonetic fold + trigram/token-set/phonetic channels, weighted fusion + region/brand boosts + confidence gate) built at bootstrap from `db_project_registry.registry_rows()`, returning `resolved` (code sticks into `customer.project_interest`), `ambiguous` (candidate list), or `not_found`. `catalog.normalize()` is now purely a **validation gate**: it still canonicalizes/validates a code before it's trusted (Redis only ever holds canonical codes — DB-aligned `NCR`/`SLC`/`ALLUVIA`/`Alumi`; others 4-char) and still accepts any live DB code as a fallback (lazy `db_project_registry.cached_codes()` consult after its hardcoded alias map), but it is no longer the thing that supplies choices to the LLM — `find_project` does that job at retrieval time instead of upfront enumeration. Every consumer of `customer.project_interest` MUST still go through `catalog.normalize()`.

### Foreground retrieval (per turn, blocks TTFA)

```
LLM tool kb_search(query, project_filter)   # renamed from noble_search (Phase 3d)
  ↓ dispatcher writes customer.project_interest if a new project_filter shows up
agent/rag/noble_kb.query_noble_kb → dispatch on settings.noble_rag_backend:
  ├─ "flat_store" (default) → FlatStore.search_hybrid (e5-large + BM25 RRF, <50ms warm)
  ├─ "qdrant" → qdrant_adapter: ONE Qdrant Query-API call (dense + BM25 sparse prefetch → server-side RRF); local disk BM25 fallback on error
  ├─ "hipporag" → hipporag/adapter: qdrant hybrid seed → Personalized PageRank on the KG (numpy, NO LLM) → RRF fuse; degrades to qdrant on missing graph
  ├─ "grep_faq" → substring grep over data/faq/<CODE>.md (A/B vs flat_store)
  ├─ "kb_service" → kb_service_adapter: IN-PROCESS embed (embed svc) + ONE Qdrant hybrid over <tenant>_documents; degrades to "" on any error
  └─ "empty" → "" (degraded mode for missing artifacts)
```

### Chi tiết từng backend

Pipeline đầy đủ của `kb_service` / `send_media` / `qdrant` hybrid / HippoRAG 2 — kèm shape
payload, thứ tự fuse, điều kiện degrade — nằm ở [`docs/architecture/rag.md`](docs/architecture/rag.md).

Ba điều phải nhớ trước khi đụng vào:

- **Tenant isolation là TÊN COLLECTION** (`<tenant>_documents`), không phải filter → một bug không thể lộ chunk của tenant khác. Collection thiếu ⇒ trả rỗng **trước khi** tốn lượt embed.
- **`score_threshold` trên thang RRF** (`Σ 1/(2+rank)`: rank0=0.5, rank1=0.333…), không so sánh được giữa các query, và **đổi theo số nhánh fuse**.
- **Mọi backend degrade IM LẶNG về rỗng** (`noble_kb` có catch-all). Pipeline hỏng trông y hệt pipeline không tìm thấy gì — luôn xác minh bằng `make test-search`.

### Per-turn FAQ inject — REMOVED

There is no FAQ-inject path anymore. The legacy per-turn FAQ semantic searcher
(`agent/rag/faq_searcher.py`, the `*_faq.json` corpus, and the `faq_*` settings)
was dead code — never wired into `builder.py` or the turn loop — and was deleted.
Answer quality comes solely from `kb_search` → `noble_kb.query_noble_kb`.
Note: `data/faq/<CODE>.md` is unrelated — it is still the corpus for the
`grep_faq` RAG backend.

### Background prefetch / semcache (off by default)

When `NOBLE_SEMCACHE_ENABLED=true`: predictor LLM generates N likely next-turns; each runs in a sandbox copy of state; result chains are stored. Next user turn: embed → similarity-search → if a `full` hit clears the threshold, replay the chain (token / tool_start / tool_done events) instead of running the LLM. `partial` hits currently fall back to live run.

### Key configuration

Nguồn sự thật là `src/noble_agent/config.py` (~370 field). Dưới đây chỉ là nhóm hay chạm nhất.

| Setting (env) | Default | Purpose |
|---|---|---|
| `USE_UNIFIED_AGENT` | `false` | Master flag. Phải `true` mới chạy được unified server. |
| `AGENT_CONFIG_SOURCE` | `legacy` | `legacy` (bundle) \| `db` (Postgres + persona skeleton dùng chung). `db` ⇒ toàn bộ control-plane đọc Postgres. |
| `TENANT_ID` | `noble` | Tenant mặc định khi request không mang tenant. |
| `NOBLE_DATA_SOURCE` | `pg_kb` | **Provider DUY NHẤT** (`postgres_kb.py`). 3 provider cũ (`sales_api`/`nbx_mongo`/`mongo`) đã XOÁ ở SP1 — không còn rollback qua env. |
| `POSTGRES_ENABLED` / `_DSN` / `_SERVER_DSN` / `_ADMIN_DSN` / `_APP_ROLE` | `false` / — / — / — / `odyssey_agent` | Data plane + VIEW config. `_DSN` = pool shared app-role (fallback cho dev/REPL/heartbeat khi KHÔNG có credential per-tenant); `_SERVER_DSN` = DSN không userinfo, `pool_for_tenant` lắp role+password per-tenant vào; `_ADMIN_DSN`/`_APP_ROLE` chỉ dùng provisioning (`noble-tenant pg-*`), ngoài đường nóng. |
| `NOBLE_RAG_BACKEND` | `flat_store` | `flat_store` \| `qdrant` \| `hipporag` \| `grep_faq` \| `kb_service` \| `empty` |
| `EMBED_BACKEND` / `EMBED_SPARSE_MODEL` | `gemini` / `Qdrant/bm25` | **Phải khớp thứ ingest đã index** — sai model là sai không gian vector, Qdrant trả nhiễu mà KHÔNG báo lỗi. |
| `QDRANT_URL` | empty | Chứa `<tenant>_documents` / `<tenant>_media`. Deployment-local (SSM tunnel) → **không portable giữa máy**. |
| `EMBED_SERVICE_URL` | empty | Chỉ còn cần cho nhánh **visual** của `send_media`. Rỗng ⇒ media search text-only, `kb_search` không ảnh hưởng. |
| `KB_SEARCH_MIN_SCORE` / `MEDIA_SEARCH_THRESHOLD` | `0.0` / `0.0` | **Thang RRF, KHÔNG phải cosine** và đổi theo số nhánh fuse → dùng `TOP_K` để chặn, đừng đặt ngưỡng cứng. |
| `NOBLE_AGENT_MODEL` / `_SUMMARY_` / `_SEMCACHE_` | empty | Pin primary provider cho từng đường. Phải bằng một `<P>_MODEL`. |
| `NOBLE_LLM_ENABLE_THINKING` / `_SHOW_THINKING` | `false` / `false` | Sinh thinking hay không / có hiện ở chat UI không. TTS + eval LUÔN strip. |
| `LLM_FORCE_TOOL_FIRST_ROUND` | `false` | Ép vòng LLM đầu mỗi turn gọi tool (`tool_choice=required`, chỉ provider OpenAI-compat, cần thinking off với dashscope); lượt xã giao thoát qua `no_lookup_needed` — van xả đó chỉ được chào khi cờ này bật. |
| `TRANSPORT_BACKEND` | `aiortc` | `aiortc` \| `livekit` |
| `STT_BACKEND` / `TTS_BACKEND` / `SPEAKER_MODE` | `soniox` / `vieneu` / `off` | Xem bảng Pluggable backends. |
| `CHAT_MAX_CONCURRENT_SESSIONS` | `200` | Cap admission `/chat` in-process; đạt trần → WS close 4029 + `/health/ready` 503. |
| `NOBLE_HEARTBEAT_ENABLED` / `_SEC` | `true` / `20` | Nhịp tim agent tự đẩy (Backend không gọi xuống agent). |
| `BILLING_METERING_ENABLED` | `false` | Bật đo tiêu thụ để tính tiền → ghi `billing.usage_events` (Portal sở hữu, agent chỉ `INSERT`). Tắt = không đo và **không** gửi `stream_options` cho LLM. |

→ Bảng đầy đủ: [`docs/architecture/configuration.md`](docs/architecture/configuration.md)

### Migration artifacts (gitignored, regen via scripts)

- `data/flat_store/embeddings_intfloat__multilingual-e5-large{,_nofaq}.npy`
- `data/flat_store/bm25_index{,_nofaq}/`
- `data/flat_store/meta_*.json`
- `data/faq_cache/{CODE}_e5large_{hash}.npz`

Build: `python -c "from noble_agent.agent.rag.flat_store import FlatStore; s=FlatStore(); s.load(); s.build_bm25()"` (separate runs for `skip_faq=True/False`).

## Gotchas — bẫy đã sập ít nhất một lần

Những cái này tốn một lần debug thật mới tìm ra. Chi tiết ở doc tương ứng, nhưng phải
biết TRƯỚC khi đụng vào vùng liên quan.

- **Đừng để lại pool asyncpg bị buộc vào loop đã đóng.** Code prewarm/startup chạy dưới
  `asyncio.run()` tạo rồi ĐÓNG một loop tạm; pool dựng trong đó gắn vào loop chết → query
  sau đó trên loop thật crash `RuntimeError: Event loop is closed`. Phải `await close_pool()`
  trong `finally` (xem `transport/livekit/worker.py::_warm_registry`). `get_pool`/`pool_for_tenant`
  cũng tự rebuild khi loop đang chạy khác loop đã tạo pool (LiveKit chạy mỗi job một loop).
- **Task nền phải giữ strong ref.** `asyncio` chỉ giữ weakref — task summary/warm không
  nằm trong `_bg_tasks` sẽ bị GC nuốt giữa chừng, im lặng.
- **`send_media` cache kết quả in-process 300s và KHÔNG bị invalidate khi ingest.** Media
  vừa upload chỉ xuất hiện sau tối đa TTL. Test **bắt buộc** gọi
  `media_data.reset_result_cache_for_tests()` giữa các case, không thì kết quả rò qua nhau.
- **RLS fail-closed, không fail-loud.** `tenant_conn` set `app.current_tenant` ở phạm vi
  transaction (`is_local=true`). GUC chưa set → NULL → **0 row**, không phải lỗi. Query
  trả rỗng có thể là "không có dữ liệu" HOẶC "quên scope tenant".
- **`embed_client` bắt buộc truyền `side=`, không có default.** E5 prefix passage/query
  khác nhau; truyền sai side là truy vấn sai không gian vector mà không có cảnh báo.
- **`feng_shui` chỉ có tác dụng khi `search_units` được bật.** Bật riêng nó là no-op.
- **`escalate` không bao giờ disable được** — nó là van an toàn, luôn nằm trong `CORE_TOOLS`.
- **Thêm provider LLM vào chain thì PHẢI probe usage-trong-stream, không thì billing về 0 im
  lặng.** Endpoint OpenAI-compat chỉ trả `usage` giữa stream khi được gửi
  `stream_options={"include_usage": True}`, mà cờ đó chỉ gửi cho tên nằm trong
  `_STREAM_USAGE_PROVIDERS` (`client.py`). Provider ngoài allowlist ⇒ mọi dòng
  `purpose='conversation'` ra token 0 + `exact=False`, trong khi `summary` vẫn đúng (nó không
  streaming, đọc `resp.usage` trực tiếp) — đúng triệu chứng đã sập với `gemini` 2026-08-18.
  Đừng thêm tên theo phỏng đoán: provider không nhận field lạ trả **400**, mà 400 là
  non-transient nên nó bị loại khỏi chain và có thể rớt cuộc gọi. Gọi thật một lần rồi mới thêm.
- **`total_tokens` có thể lớn hơn `prompt + completion` — phần chênh là thinking token vẫn bị
  tính tiền.** Gemini không kể thinking vào `completion_tokens` (đo thật: `completion=12` mà
  `total=332`). `capture.normalize_usage` dồn phần chênh vào `output_tokens` để bốn cột luôn
  cộng lại bằng `total`; đừng "đơn giản hoá" mất đoạn đó, bật `NOBLE_LLM_ENABLE_THINKING` là
  đếm thiếu output ~95%.
- **Tool trả `ESCALATE_SIGNAL` thì dispatcher TỰ gọi escalate.** Prompt không được bảo LLM
  gọi lại lần nữa.
- **`fire_and_forget` chỉ LÊN LỊCH, nên "đặt dòng này sau dòng kia" không đủ để sắp thứ tự.**
  Mọi giá trị mutable mà coroutine sẽ đọc phải được **chụp đồng bộ** rồi truyền vào làm tham số.
  Đã sập thật: `fire_and_forget(sink.flush(meter))` rồi `meter.turn_idx += 1` — comment ghi rõ
  "flush TRƯỚC, tăng SAU" nhưng `drain()` chạy trong task hoãn nên đọc `turn_idx` đã tăng, cùng
  một lô ra `llm turn=0` và `stt turn=1`. Test cũ không bắt được vì nó chỉ đọc `meter.turn_idx`
  tại thời điểm **gọi** (luôn đúng), không đọc dấu trên **dòng**.
- **Ngưỡng GHI centroid phải chặt hơn ngưỡng ĐỌC (`SPV_ADAPT_MARGIN`).** `CentroidSet.match()`
  lấy MAX cosine trên toàn tập, nên nếu hai ngưỡng bằng nhau thì mỗi mẫu vùng biên lại nới
  rộng biên và biên mới làm bàn đạp cho lần nới kế — danh tính trôi dạt tới mức ai nói cũng
  khớp. Đặt `SPV_ADAPT_MARGIN=0` là quay về đúng hành vi đó.
- **Speaker fail-OPEN, không fail-closed.** Không nhận diện được ⇒ tập rỗng ⇒ floor mở ⇒ ai
  cũng ngắt được (như `SPEAKER_MODE=off`). Đừng "sửa" thành chặn hết: bản 2026-08-28 enroll
  mù rồi khoá cứng, và triệu chứng là khách thật không ngắt được suốt turn.

## Behavioral Guidelines

**Tradeoff:** these bias toward caution over speed. For trivial tasks, use judgment.

1. **Think before coding.** State assumptions explicitly. If multiple interpretations exist, present them — don't pick silently. If unclear, stop and ask.
2. **Simplicity first.** Minimum code that solves the problem. No speculative features, no abstractions for single-use code, no error handling for impossible scenarios.
3. **Surgical changes.** Touch only what you must. Don't "improve" adjacent code or refactor things that aren't broken. Match existing style. Remove imports/vars your change orphaned; don't delete pre-existing dead code without asking.
4. **Goal-driven execution.** Transform tasks into verifiable goals ("fix the bug" → "write a test that reproduces it, then make it pass"). For multi-step work, state a brief plan with a verify check per step.
5. **Run the smoke checklist** (`src/noble_agent/SMOKE.md`) after any change that touches the turn loop, prompt, or transport boundary.

## Harness: Voice-Agent Development Lifecycle

**Trigger:** Non-trivial changes (feature / latency / RAG / new tool / transport / storage) → use the `noble-feature-flow` skill (plan → TDD → review + verify, user-gated checkpoints, branch-safe). **Fast-path:** Trivial tasks (≤1–2 files, a text/config/prompt-markdown tweak, a pure question, a one-spot bug fix) → handle directly, **don't call the orchestrator**.

Agents live in `.claude/agents/`, skills in `.claude/skills/` — both **tracked in git** (commit harness changes on a feature branch, never `develop`). Harness design docs are also checked in under `docs/harness/` (`architecture.md` = the agent/skill map + orchestration flow; `project-baseline.md` = the drift anchor). To reshape the harness itself, use the `harness` skill.

**Harness change log:** [`docs/harness/CHANGELOG.md`](docs/harness/CHANGELOG.md) (thay đổi harness ghi ở đó, không ghi vào file này).

## Change Log

**Lịch sử đầy đủ (100 entry, từ 2026-06-03): [`docs/CHANGELOG-agent.md`](docs/CHANGELOG-agent.md).**
Chỉ 10 entry gần nhất giữ ở đây; entry mới thêm vào CẢ HAI (bản đầy đủ ở file kia,
bản 1–2 câu ở đây), rồi xoá entry thứ 11 khỏi bảng dưới.

| Date | Change | Why |
|------|--------|-----|
| 2026-09-07 | Merge tool dữ liệu cấu trúc 6→3: `search_units` nuốt `recommend_units` (param `scope` bắt buộc `in_project`\|`all_projects`, envelope 2 nhóm + phong thủy + union filter cả hai scope; provider còn MỘT method `search_units(UnitQuery)` thêm bedrooms/region, cap 200), `discover_projects` nuốt `get_project_overview` (có `project_code` → overview), `analyze_projects` nuốt `check_inventory` (tồn kho qua SQL); alias tên cũ ở `agent_config.TOOL_ALIASES` cho config/manifest chưa migrate; golden evals đã rename (33 entry). | 6 tool chồng lấn cùng đọc `tenant_data.projects/units`, ranh giới search-vs-recommend là luật routing model phải học thuộc và từng chọn nhầm; mỗi tool thừa chiếm chỗ prompt mọi lượt. |
| 2026-09-04 | `search_units`/`recommend_units` trả theo TRANG 6 căn kiểu discover (`index`/`has_more`/`next_index`, sort thêm tiebreak `unit_code` vì SQL không ORDER BY), `counts.total` = tổng khớp thật + `shown`, instruction chở lệnh lật trang / báo "đã hết"; guard pitch-một-lần bỏ ở 2 tool căn — `upsell_instruction` sống ở MỌI lần gọi (discover giữ guard). | Khách chê 6 căn rồi hỏi "có căn khác không" → gọi lại cùng tham số nhận y hệt 6 căn cũ, model dễ bịa "hết căn" theo total=6, và lượt gọi lại mất luôn lời chèo kéo. |
| 2026-09-03 | Fix idle-timer ma: `_trigger_agent_for_text` reset idle SAU khối cancel (finally của turn bị cancel luôn re-arm timer 25s) + guard `_on_idle_timeout` bỏ qua khi agent đang nói. | Timer ma sống xuyên turn dài >25s: idle prompt đè lên answer đang phát — hai producer một AudioSource → `capture_frame InvalidState`, prompt câm — rồi goodbye cắt máy giữa cuộc gọi. |
| 2026-09-03 | SpeakerRegistry: danh tính sống cả phiên (bỏ `reset()` mỗi turn), enroll chỉ nhận cụm cửa sổ nhất quán (không cụm → không enroll, fail-open), probe đổi sang cửa sổ tích luỹ từ mốc 0.25s, drop rule dùng bằng chứng dương + van thoát mismatch-streak. | Enroll mù từ câu ngắt lời tạo centroid rác khoá cứng cả turn (khách thật không ngắt được, final còn bị drop); span rời 0.8s khiến verdict không thể về sớm và độ tin cậy không tăng theo thời gian. |
| 2026-09-03 | Chèo kéo data-driven (`agent/tools/upsell.py`): căn/dự án vượt-ngân-sách-trong-biên mang `over_budget`/`price_delta_pct`/`highlights` (từ `amenities`) + directive "GIỚI THIỆU LUÔN, không hỏi xin phép" (pitch 1 lần/dự án/phiên), headroom `max(500tr, 12%)`, payload `recommend_units` tách 2 nhóm `units`/`upsell_units` với directive riêng (`upsell_instruction` = "nâng ngân sách thêm ~X% lấy căn Z") + phân bổ slot theo độ liên quan giá (within xa tầm <75% ngân sách chỉ giữ 2 căn), directive strip khỏi history lúc persist; RULES chat+voice bỏ mẫu chốt câu hỏi-xin-phép; `no_lookup_needed` rời CORE_TOOLS — chỉ chào khi `LLM_FORCE_TOOL_FIRST_ROUND=true`. | Instruction cũ trong tool result tự dạy model hỏi "có muốn tư vấn không ạ?" — model nghe chỉ đạo gần hành động hơn persona; bảo "giới thiệu tính ưu việt" mà không cấp highlights là ép model bịa. |
| 2026-08-28 | Parallel SPV: SpeakerTracker thay SpeakerFloor/SpeakerVerifier — chunk song song STT (0.8s → SPV_CHUNK_SEC=2s sau khi chốt speaker), multi-centroid (cap SPV_MAX_CENTROIDS=10, enroll-on-match), interrupt tức thì tại chunk speaker, final kèm chuỗi nhãn + majority-drop. | Người lạ chen trước làm khách phải đợi hết turn mới ngắt được; 1 embedding/danh tính nhạy biến thiên giọng. |
| 2026-08-27 | Escalate theo chủ đề GIAO DỊCH của khách (điều khoản HĐMB / chuyển nhượng-bán lại-sang tên + phí / cam kết ghi trong hợp đồng / sau mua / "người hay máy?") → escalate ngay kể cả khách CHƯA mua; pháp lý DỰ ÁN + chiết khấu theo CSBH vẫn kb_search — `escalate` description + RULES chat/voice quy tắc 2/7. Cùng config + judge, 100 case gemini-2.5: escalate đúng 12/15 → 15/15, cấm-mà-gọi 2 → 0, tool_selection 0.856 → 0.880 (review doc §14; config dev đổi v4 → v8 giữa chừng — so sánh phải cùng `pinned_version`). | Sau 4 bước escalate miss 0 → 3: RULES định nghĩa ngoài phạm vi bằng "khách đã mua" nên khách chưa mua hỏi điều khoản / bán lại bị trả lời từ KB. |
| 2026-08-27 | Routing giá căn → `search_units`: mô tả `kb_search` bỏ "giá", chỉ sang `search_units` qua span mới `[TOOL:x]…[/TOOL:x]` (`build_schemas` chỉ giữ khi x được offer); RULES chat/voice bỏ "Giá" khỏi dòng kb_search. Đo gemini-2.5 100 case: tool_selection 0.840 → 0.872, policy 22 → 18, 2 case giá trả đúng khoảng giá; cùng chiều: hỏi/xin BẢN CSBH (đang áp dụng / mới nhất) → `get_document` qua `[TOOL:get_document]`, kb_search chỉ còn nội dung điều khoản — tool_selection 2.5: 0.872 → 0.904, 3.7 irrelevant 0.31 → 0.26 (review doc §13, có đính chính baseline 25/08). | Eval 27/08: "căn 2PN giá khoảng bao nhiêu" → kb_search rồi "chưa có thông tin giá" dù kho căn có giá — mô tả kb_search cũ (`e21c2d9`) ép giá vào tài liệu. |
| 2026-08-27 | Evals: cờ `--as-tenant` (case `aina_prod` chạy dưới bản sao `aina_test`); A/B `agent_temperature` 0.7 vs 0.4 đã đo trên 46 case tool gemini-2.5-flash — chênh trong nhiễu, giữ 0.7 (review doc §9); golden POL-507 `"AI"` substring → regex `\bAI\b` (bắt nhầm brand AINA). | Key eval thuộc `aina_test`, case chỉ có cho `aina_prod`; runner lấy tenant từ case. |
| 2026-08-27 | Bước 4 review — voice barge-in: `agent/interrupt_trim.py` + `NobleAgent.note_interrupted(spoken_text)` cắt assistant cuối trong history về phần khách ĐÃ NGHE (dấu "(bị khách ngắt lời ở đây)"), ghi đè cùng seq vào `conversation_messages`; `VoiceAgent.handle_utterance` gọi trên cả đường cancel task lẫn đường cờ. Spec `docs/superpowers/specs/2026-08-27-voice-barge-in-history-trim-design.md`. | LLM persist xong trước khi TTS phát; khách ngắt giữa chừng thì lượt sau model tin mình đã nói cả phần khách chưa nghe. |
