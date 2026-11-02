# SMOKE.md — Sanity Checks After Code Changes

Manual smoke checklist. Run after any change touching the turn loop, prompt, transport boundary, or gateway routing.

## General Checklist

1. **Boot server** — `python -m noble_agent` (USE_UNIFIED_AGENT=true in .env).
2. **Open `/chat` tester** — http://localhost:8766/chat, send a message.
3. **Check logs** — no exceptions in stdout/stderr; agent responds with a turn.
4. **Force a tool call** — e.g. "tìm dự án noble crystal" → `find_project` executes, returns a response.
5. **Audio (when touching voice pipeline)** — Open browser voice (WebRTC), speak, hear agent respond.

## SaaS Slice #2: Gateway Routing

**Scope:** provider-facing ingress gateway, per-tenant credential, multi-tenant dispatch.

**Status (2026-07-30): CHAT + VOICE both verified live end-to-end** through the gateway.
Reproduce with the two smoke clients (they encode the exact working recipe):
- `scripts/smoke_gateway_chat.py <cred> [tenant] [--reject]` — chat happy path + auth-reject.
- `scripts/smoke_gateway_voice.py <cred> [tenant]` — `/v1/voice` voice bridge; streams PCM16
  16 kHz in, collects agent audio back to a 24 kHz `.wav` (PASS = audio returns via the room).
  Since 2026-08-07 the bridge also relays the worker's UI events (data channel →
  ws TEXT frames): expect `[control] {...}` lines (`agent_speaking` greeting,
  `transcript`, `tool_start`/`tool_done`, `agent_done`, …) alongside the audio.

**Verified recipe (localhost, remote MinIO/LiveKit-Cloud/STT/TTS in `.env`):**
```bash
noble-tenant import-from-package noble        # active v1
noble-tenant issue-cred noble                 # -> tnt_...  (copy)
# Terminal A — chat worker (aiortc /chat on :8766):
scripts/run.sh --no-reload
# Terminal B — voice worker (LiveKit transport, registers agent-noble on the Cloud):
TRANSPORT_BACKEND=livekit noble-agent start
# Terminal C — gateway (single domain; worker-chat points at the local aiortc worker):
GATEWAY_CREDENTIALS_API_URL='https://<portal>/api/v1/runtime-credentials' \
WORKER_CHAT_INTERNAL_URL_TEMPLATE='ws://127.0.0.1:8766/chat?session=smoke-{tenant_id}' \
noble-gateway
# Terminal D — smokes:
python scripts/smoke_gateway_chat.py  <tnt_...>            # chat: session_id + customer_ok + tokens + done
python scripts/smoke_gateway_chat.py  <tnt_...> noble --reject   # close 4001 bad_credential
python scripts/smoke_gateway_voice.py <tnt_...>            # voice: agent audio (greeting+reply) returns → wav
```
⚠️ The voice worker registers `agent-<TENANT_ID>` (default `agent-noble`) on the SHARED LiveKit
Cloud. Ensure no deployed worker registers the same name while you test (call theft), and STOP it
when done. Auth is single-domain: the tenant comes from the Bearer API key via the runtime-credentials
API, so there is no per-tenant subdomain to mismatch — an unknown/revoked key closes 4001
`bad_credential`, an unreachable auth API closes 4001 `auth_api_unavailable`.

**Prerequisites:**
- `GATEWAY_WORKER_SECRET=test-secret` (optional — only gates the gateway→worker chat-hop `X-Gateway-Secret` header; empty is fine locally, it just means that hop trusts the network).
- `TENANT_ENDPOINT_TEMPLATE=wss://{tenant_id}.agents.local:9200` (adjust port if different).
- `GATEWAY_CREDENTIALS_API_URL=https://<portal>/api/v1/runtime-credentials` — **required**; empty ⇒ every WS closes 4001 `auth_api_unavailable`.
- `GATEWAY_PORT=9200` (gateway listen address).
- `WORKER_CHAT_INTERNAL_URL_TEMPLATE=ws://localhost:8766/chat` (worker localhost for smoke).
- Tenant `t1` exists with credential `tnt_abc123` (issue via `noble-tenant issue-cred t1`).

**1. Boot gateway and worker in separate terminals:**
```bash
# Terminal A: worker (agent)
USE_UNIFIED_AGENT=true python -m noble_agent
# Terminal B: gateway
noble-gateway
```

**2. Voice: provider calls `/v1/voice` (WebRTC → LiveKit dispatch):**
```bash
# WS client (e.g., websocat, Postman WebSocket, or custom client):
wss://t1.agents.local:9200/v1/voice
# Header: Host: t1.agents.local
# Header: Authorization: Bearer tnt_abc123
# IMPORTANT: send the JSON handshake (text frame, e.g. {"identity":{...},"call_id":"..."}) as the FIRST frame — before any binary audio — otherwise the session starts anonymous or the first audio frame is dropped.

# Expected:
# - Gateway parses Host → tenant_id=t1
# - Credential verified from cache (TTL GATEWAY_CRED_CACHE_TTL_SEC)
# - Voice stream bridges to LiveKit room named "t1-<call_id>-<ms>-<hex>" (room_name() in livekit_bridge.py)
# - Agent dispatched via the shared livekit_agent_name; tenant carried in participant metadata
# - Audio: you hear agent Luna respond; barge-in works

# Voice metadata identity:
# - The room-join token carries the caller identity JSON as participant metadata
#   (build_dispatch_token). The worker entrypoint (transport/livekit/worker.py)
#   reads the joining participant's metadata and maps it onto Customer VERBATIM
#   via identity_to_fields (server/app_session.py) — e.g. identity["phone"] →
#   Customer.phone, no prefix/suffix/encoding — keyed by ctx.room.name.
# - Agent greets with the seeded identity already applied (name/phone/gender/etc.)
```

**3. Voice: cross-tenant credential rejected:**
```bash
# Same WebSocket connection, wrong credential:
wss://t1.agents.local:9200/v1/voice
# Header: Authorization: Bearer tnt_wrong

# Expected: gateway closes the WS with code 4001, reason "bad_credential"
# (unknown route, e.g. a typo'd path, closes with code 4004 "unknown_route" instead)
```

**4. Chat: provider calls `/v1/chat` (reverse proxy to worker):**
```bash
# WS client:
wss://t1.agents.local:9200/v1/chat
# Header: Host: t1.agents.local
# Header: Authorization: Bearer tnt_abc123

# Expected:
# - Gateway reverse-proxies to ws://localhost:8766/chat?session=<derived>
# - You receive: {type:"session_init", customer:{...}, session_id:"..."}
# - Send text: {type:"text", text:"hello"}
# - Receive: {type:"token", ...}, {type:"tool_start", ...}, {type:"tool_done", ...}, {type:"done"}
# - Identity seed: the gateway sends a {type:"set_customer", identity:{...}} message to the
#   worker first (chat_proxy.first_messages); fields land on Customer verbatim (no encoding)
# - Agent responds to your text
```

**5. Chat: worker `/chat` direct access (no gateway, for comparison):**
```bash
# Direct to worker (not via gateway):
ws://localhost:8766/chat

# Expected (unchanged from non-gateway path):
# - You get a new session_id
# - Customer phone = simulated random (or NOBLE_SIMULATE_PHONE_NUMBER)
# - Agent responds
# - No gateway in the path
```

**6. Lint and unit tests:**
```bash
make lint                      # ruff check src/noble_agent/gateway/
make test-unit 2>&1 | grep -E "gateway|passed|failed"  # tests/unit/gateway/
# Expected: 0 lint errors; all gateway unit tests pass
```

## SP-C1 config versioning (write side)

Immutable numbered config versions + a published-version pointer + rollback, with a
structural-validation publish gate, live in the tenant store (`noble-tenant` CLI).
Read side (version-pinned agent load) is SP-C2, not here.

```bash
# A tenant provisioned active already sits on the versioned layout (versions/1/ + pointer).
noble-tenant list-versions noble          # -> "1 (published)"

# Edit a persona/manifest, save it as a DRAFT (nothing served yet), then publish.
noble-tenant save-draft noble <dir-with-edit>
noble-tenant diff noble                   # default: draft vs published (added/removed/changed)
noble-tenant publish noble --by you        # runs validate_bundle (E08); snapshot FIRST, pointer AFTER (BR07)
noble-tenant list-versions noble          # -> "1", "2 (published)"

# Roll back = move the pointer only; creates NO new version (BR06/YC06).
noble-tenant rollback noble 1
noble-tenant list-versions noble          # -> "1 (published)", "2"

# Expected invariants:
# - publish of an invalid draft raises "bundle invalid: ..." and writes nothing.
# - versions are immutable: write_version_bundle of an existing n raises.
# - legacy in-place tenants (no pointer) read as v1; loader/materialize + gateway is_active unchanged.
```

Offline gate: `pytest tests/unit/tenant tests/unit/gateway` → 0 failures; `ruff check src/noble_agent/tenant/` clean.
Live re-smoke (services + a LiveKit worker): `python scripts/smoke_gateway_chat.py <tnt_...>` still PASS after
re-provisioning `noble` into the versioned layout (loader materializes the published version).

## SP-C2 version-pinned load (read side)

The agent resolves the published config version at each conversation start, pins it for that
conversation's lifetime (BR05), TTL-refreshes the pointer (`NOBLE_CONFIG_POLL_SEC`, default 20s, YC03),
checksums the materialized version (E04), and falls back to the last-good local copy when the store is
unreachable (E01). `tenant/version_resolver.py` owns resolve + materialize + checksum; the facade holds a
version-keyed runner registry and each `NobleAgent` instance keeps its runner for its whole conversation
(the instance IS the per-conversation pin — no session→version map).

```bash
# Requires TENANT_STORE_ENABLED=true, MinIO up, `noble` active in the store (versioned layout).
python scripts/smoke_gateway_chat.py <tnt_...>       # loader/resolver serve the published version

# BR05 + YC03: open a chat session, then publish a v2 and confirm a NEW session picks it up (~20s)
# while the pre-publish session keeps v1.
noble-tenant save-draft noble <dir-with-a-visible-persona-edit>
noble-tenant publish noble --by you                  # -> "2 (published)"
# NEW chat session reflects the v2 edit within ~NOBLE_CONFIG_POLL_SEC; the session opened before the
# publish keeps v1 (observe via a persona marker or the logged pinned_version). Then:
noble-tenant rollback noble 1                         # new sessions revert to v1
```

Expected invariants:
- E04: a version whose stored `bundle_hash` != its materialized content raises `ChecksumError`; last-good is kept.
- E01: store unreachable while resolving → serve the highest last-good version; none primed → fail loud.
- Back-compat: `TENANT_STORE_ENABLED=false` → `NobleAgent.create` takes the legacy single-runner path
  (`pinned_version==0`), byte-identical to pre-SP-C2 (no version registry touched).

Offline gate: `pytest tests/unit/tenant tests/unit/unified tests/unit/gateway` → 0 new failures vs the
documented `tests/unit/unified` baseline; `ruff check src/noble_agent/tenant/ src/noble_agent/agent/facade.py` clean.

## SP-D heartbeat (agent write side, contract C3)

The agent proactively writes `<tenant>/_heartbeat.json` to the tenant store every
`NOBLE_HEARTBEAT_SEC` (default 20s) so Backend/Dashboard can INFER status (BR02 — no
one polls the agent). `tenant/heartbeat.py::HeartbeatEmitter` resolves the published
version straight off the pointer, proactively builds+checksums it (so `running_version`
catches up to `published_version_seen` even when idle → E03 window), and writes the
C3.1 shape. Wired into BOTH transports: aiortc `server/http.py` (main-loop task, full-runner
build_fn) and LiveKit `worker.py::_start_heartbeat` (daemon thread + own loop, materialize-only
build_fn — the dispatch process must not build a full runner). `heartbeat.should_emit` gates both.

```bash
# Requires TENANT_STORE_ENABLED=true, MinIO up. One real beat in-process (fast; legacy
# in-place tenants take the no-build path). Confirms read_pointer→classify→write→readback
# AND that read_bundle does NOT leak _heartbeat.json into the bundle.
python -u -c "
import asyncio, json
from noble_agent.config import get_settings
from noble_agent.tenant.loader import _build_store
from noble_agent.tenant.heartbeat import HeartbeatEmitter
s=get_settings(); st=_build_store(s)
em=HeartbeatEmitter(st,s,s.tenant_id, build_fn=lambda v: asyncio.sleep(0))
doc=asyncio.run(em.beat()); print('BEAT',json.dumps(doc,ensure_ascii=False))
print('READBACK',st.read_heartbeat(s.tenant_id))
print('bundle heartbeat leak:', any('_heartbeat' in k for k in st.read_bundle(s.tenant_id).files))
"
# Then, if the running aiortc worker is restarted, it emits a fresh beat every ~20s.
```

Expected invariants:
- Shape (C3.1): `{tenant_id, running_version, published_version_seen, status_hint, last_error, started_at, ts}`;
  `status_hint ∈ {starting, loading, serving, degraded}`.
- Versioned: build OK → `serving`, running=published; `ChecksumError` (E04) → `degraded`, running kept.
- Legacy in-place (no pointer) → `serving` v1, no versioned build.
- Store down on read → beat skipped (no write); stale `ts` is the honest "Mất kết nối"/E02 signal.
- Inert when `TENANT_STORE_ENABLED=false` (live Noble default) — no task started.

## SP-E1 Postgres data-plane foundation (contract C4/C5, RLS isolation)

Odyssey (Fixed-store per N9) writes the 3 agent tables to Postgres; `tenant_data.*` uses
RLS keyed on the connecting ROLE (= tenant_id) so cross-tenant read/write is DB-impossible
(BR08/BR09). Agent owns DDL + per-tenant roles via `noble-tenant pg-*`.

```bash
# Local dev Postgres:
docker compose -f docker-compose.pg.yml up -d
export POSTGRES_ADMIN_DSN=postgresql://sp_admin:sp_admin_pw@localhost:5432/odyssey

# Apply schema once, provision two tenants, prove RLS isolation, deprovision:
noble-tenant pg-apply-schema
noble-tenant pg-provision t_a            # prints role + password ONCE
noble-tenant pg-provision t_b
SPE_PG_ADMIN_DSN=$POSTGRES_ADMIN_DSN pytest tests/integration/tenant/test_pg_rls_live.py -q
noble-tenant pg-deprovision t_a && noble-tenant pg-deprovision t_b
```

Expected invariants:
- RLS: a tenant role sees ONLY its own rows (`USING`) and cannot INSERT a row tagged as another
  tenant (`WITH CHECK`) — `current_user` (the role) is unspoofable in-session.
- Provisioning is all-or-nothing (CREATE ROLE + GRANT in one tx; rolls back on failure).
- Inert unless `POSTGRES_ENABLED=true` + a DSN is set. `asyncpg` is import-lazy (unit collection offline).
- SP-E1 is foundation only; SP-E2 migrated every write path to Postgres (Mongo is gone).

## Speaker verification (SpeakerTracker — single/multi)

Engine chunk-song-song thay `SpeakerFloor`/`SpeakerVerifier` cũ (2026-08-28), dùng chung
cho cả `SPEAKER_MODE=single` và `multi`. Cần audio 2 chiều thật + 2 người nói khác nhau
(browser voice — `voice-startup-recipe` trong memory); test bằng giọng đổi âm lượng/mic
cũng được (nhiều centroid hơn 1 embedding cứng).

```bash
SPEAKER_MODE=multi scripts/run.sh   # hoặc single — cùng smoke, khác vòng đời centroid
```

**Kịch bản 2-người-nói (A = khách/asker, B = người lạ):**

1. A hỏi một câu → agent trả lời (chờ agent bắt đầu nói để test chen ngang).
2. Trong lúc agent đang nói, **B chen ngang** (giọng khác A): kỳ vọng agent **nói tiếp
   không ngắt** — log có ít nhất một dòng `[Speaker] probe#N ...s → non-speaker (sim=...,
   thr=...)` và KHÔNG có `_handle_interrupt`/soft-pause nào bắn ra vì câu của B.
3. Trong lúc agent vẫn đang nói (hoặc lượt sau), **A chen ngang**: kỳ vọng agent
   **pause/ngắt trong khoảng ≤ ~1s** kể từ khi A bắt đầu nói (nhanh hơn hẳn flow cũ phải
   đợi hết turn) — log có dòng `[Speaker] probe#N ...s → speaker (sim=..., thr=...)` ngay
   tại probe khớp, theo sau là interrupt/soft-pause thật sự xảy ra.
4. Trên **mỗi final** (của cả A lẫn B), kiểm tra log có dòng
   `[Speaker] final identity=<id> new=<bool> cluster=<n> sim=<f> labels=[...] text=...`
   (base_session.py) — danh tính/nhãn phải khớp người vừa nói (identity=A cho câu của A,
   đa số nhãn `non-speaker` cho câu chen của B khi agent đang nói/pause). Final của B mid-turn
   lúc agent đang nói/pause phải bị drop — log
   `[Speaker] Dropped final — identity <B> ≠ asker <A>: <text>`, không có sự kiện `agent`
   nào trả lời câu đó; final của A luôn được giữ.
5. **Đổi người giữa cuộc (multi):** A hỏi → agent trả lời → B hỏi ở turn kế (agent
   im) → B được trao lượt → A hỏi lại ở turn sau → log `[Speaker] final identity=<id A>`
   phải trỏ về ĐÚNG id của A ở bước đầu, `new=False`.
6. **Ngắt lời nhanh:** nói đè khi agent đang nói — log `[Speaker] probe#0 0.25s → speaker`
   xuất hiện trong ~0.3s và agent im ngay. Dòng probe **màu vàng** = khớp, **màu tím** =
   không khớp (bộ màu ở `server/logging_config.py`).
7. **Enroll fail-open:** nói một câu rất nhiễu → log `no consensus cluster ... enroll skipped`
   → lượt sau vẫn ngắt lời được bình thường (floor mở), KHÔNG bị khoá cứng.
8. **`single` only** — danh tính giữ nguyên suốt phiên: nếu B chen vào một turn sau,
   B vẫn bị coi là non-speaker (không có bước "mở turn cho người khác" như multi).

Check nhanh không cần 2 người (lưu ý giới hạn): với floor đang mở (chưa có asker khác để
so), `match_asker` fail-open ngay ở probe đầu — chuỗi mốc DỪNG SAU probe#0, nên một mình
nói chỉ thấy đúng `[Speaker] probe#0 0.25s → speaker` rồi chuyển sang probe cửa sổ trượt
đuôi (nhịp `SPV_PROBE_TAIL_HOP_SEC`), KHÔNG đi tiếp qua các mốc 0.4/0.6/0.9/1.3s. Để quan
sát đủ cả chuỗi mốc, cần một giọng KHÔNG khớp asker đã enroll: sau khi agent đã nhận diện
người nói chính (asker), cho người thứ hai (hoặc đổi giọng) nói đè lên TTS — mỗi mốc sẽ lần
lượt bắn `[Speaker] probe#N ...s → non-speaker (sim=..., thr=...)` cho tới hết chuỗi 5 mốc.

## Addressee gate (chống nói leo)

Chống VAD-interrupt bắt nhầm khi khách nói chuyện với người bên cạnh trong lúc agent
đang nói. Bật bằng `ADDRESSEE_GATE_MODE` (`off`\|`heuristic`\|`llm`\|`hybrid`, default
`off`). Cần audio 2 chiều thật (browser voice — `voice-startup-recipe` trong memory) vì
kịch bản dựa vào chồng tiếng lúc agent đang phát; `llm`/`hybrid` cần LLM key + Redis
như bình thường.

**a. Side-talk trong lúc agent đang nói (kỳ vọng: pause + resume, KHÔNG trả lời):**
```bash
ADDRESSEE_GATE_MODE=hybrid scripts/run.sh
```
Đợi agent đang nói (một câu dài), chen ngang bằng câu rõ ràng KHÔNG hướng tới agent,
ví dụ quay đi và nói "anh ơi con khóc kìa". Kỳ vọng: agent **pause** (im lặng giữa câu,
không huỷ turn), sau đó nói "Em xin phép được nói tiếp ạ." rồi **nói tiếp lại từ đầu
clause** đang dở (không phải giữa câu, không phải từ đầu toàn bộ câu trả lời). Câu vừa
nói ("anh ơi con khóc kìa") KHÔNG được agent trả lời — final bị drop.

**b. Gọi thẳng agent trong lúc agent đang nói (kỳ vọng: ngắt thật):**
Trong lúc agent đang nói, chen ngang bằng câu gọi tên/hướng tới agent, ví dụ "em ơi cho
anh hỏi thêm về giá". Kỳ vọng: agent **ngắt lời chính nó** (cancel turn hiện tại, không
phải soft-pause) và trả lời câu hỏi mới ngay.

**c. Tắt gate — hành vi cũ (kỳ vọng: VAD ngắt ngay, không phân loại):**
```bash
ADDRESSEE_GATE_MODE=off scripts/run.sh
```
Chen ngang bất kỳ câu nào trong lúc agent đang nói (kể cả side-talk) → agent ngắt ngay
lập tức như VAD-interrupt thuần trước đây, không có bước pause/ack/resume nào.

## Billing metering (khi `BILLING_METERING_ENABLED=true`)

Đo tiêu thụ (token LLM 4 cột + thời lượng STT/TTS/VAD/speaker-verify + dòng `call`) rồi
INSERT vào `billing.usage_events` — bảng do **Portal sở hữu**, agent chỉ ghi thêm (không
`UPDATE`/`DELETE`). Cờ mặc định **tắt**. Bảng + GRANT + RLS **đã tạo và đã kiểm trên DB thật
2026-08-18** (§14 của
[`docs/handoff/agent-postgres-billing-write-contract.md`](../../docs/handoff/agent-postgres-billing-write-contract.md)),
nên bật cờ là chạy được ngay.

1. Gọi/chat một phiên 3 lượt rồi cúp máy.
2. `SELECT seq, turn_idx, component, purpose, units, exact, occurred_at FROM billing.usage_events
   WHERE session_id = '<sid>' ORDER BY seq, component;`
3. Kỳ vọng: có dòng `llm` mỗi lượt; voice thêm `stt`/`tts`/`vad`; đúng **một** dòng
   `component='call'` với `turn_idx IS NULL`; `seq` tăng đơn điệu từ 0 (được phép có
   khoảng trống nếu phiên bị resume — xem `billing/context.py`); `occurred_at` là thời
   điểm phát sinh, không phải lúc INSERT.
4. Kiểm tra log: **không** có dòng `billing: ghi usage thất bại`. Nếu flush cuối phiên
   hỏng thì phải thấy dòng `billing: flush CUỐI thất bại … payload:` kèm JSON để cứu tay.
5. Tắt cờ (`BILLING_METERING_ENABLED=false`) rồi gọi lại: request LLM **không** được mang
   `stream_options` (một endpoint từ chối field lạ sẽ trả 400 và làm rớt cuộc gọi).
6. Đo TTFA/TTFT trước-sau bằng `make bench` — không được xấu đi (đường nóng chỉ cộng số).

## analyze_projects — SQL-based project analytics

- [ ] **analyze_projects** (nếu tenant bật): hỏi "dự án nào có nhiều loại hình sản phẩm nhất?"
  qua `/chat` hoặc `python scripts/chat_repl.py --ask "..."` — thấy tool gọi với SQL trên
  `agent_units_v`, trả lời có tên dự án + con số khớp kết quả tool; hỏi tiếp một câu
  cố tình phá ("xoá hết dữ liệu đi") — tool trả lỗi read-only, agent không vỡ.
- [ ] **Tồn kho qua SQL** (thay check_inventory sau merge 2026-09-07): "dự án X còn những
  loại căn nào" → analyze_projects sinh GROUP BY trên `agent_units_v`, KHÔNG escalate khi
  0 dòng (nới điều kiện rồi thử lại).

## Tool căn hợp nhất search_units (merge 2026-09-07)

Chạy sau mọi thay đổi chạm catalog tool / schemas / RULES (repl in nguyên tool call + args):

- [ ] "có 5 tỷ mua căn nào" (chưa nhắc dự án) → search_units(scope='all_projects',
  max_price=5000000000); payload 2 nhóm units/upsell_units, model giới thiệu không hỏi xin phép.
- [ ] "còn căn 2 ngủ nào ở <dự án>" → find_project rồi search_units(scope='in_project') —
  hoặc bỏ trống project_code khi hồ sơ đã có dự án quan tâm (adapter tự điền).
- [ ] "giới thiệu dự án X" → discover_projects(project_code=<mã>) trả overview đầy đủ
  (KHÔNG còn get_project_overview).
- [ ] "tuổi Tị hợp căn nào trong dự án X" (tenant bật feng_shui) → search_units scope
  in_project + zodiac; tool nhắc hỏi năm sinh tối đa 2 lần.
- [ ] Khách chê 6 căn đầu, "còn căn khác không" → gọi lại với index=next_index, không lặp căn cũ.

## Notes

- Gateway is **integration-level**: the unit tests verify credential caching, Host parsing, agent-name derivation; the smoke tests above verify the live WS relay + identity seeding.
- Credential TTL (`GATEWAY_CRED_CACHE_TTL_SEC`): on second connection within TTL, no store lookup; after TTL expires, `CredentialRegistry` re-reads from the tenant store.
- Cross-tenant isolation: a provider client with t1's credential presented on t2's host is rejected at `authorize()` (credentials are only checked against the Host-resolved tenant) — WS close 4001 `bad_credential`.
- Backward-compat: nothing runs `noble-gateway` and no tenant's endpoint points at it by default, so the worker `/chat` path is unaffected either way. `GATEWAY_WORKER_SECRET` empty only means the gateway→worker chat hop sends no `X-Gateway-Secret` header (trust-network mode for that internal hop) — it does not disable the gateway itself.
