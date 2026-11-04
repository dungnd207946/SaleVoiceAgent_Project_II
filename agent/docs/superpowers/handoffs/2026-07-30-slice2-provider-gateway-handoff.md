# Handoff — SaaS Slice #2: Provider-facing per-tenant gateway

**Date:** 2026-07-30 · **Branch:** `feat/agent` (repo `odyssey-agent`) · **HEAD:** `cd23adf` · **NOT merged / NOT pushed.**

This session designed, planned, implemented (subagent-driven TDD, 12 tasks + review loops), and **live-smoke-tested the chat path** of SaaS slice #2. This doc is the full context for the next session — you should not need the prior conversation.

---

## 1. What slice #2 is (the goal)

Odyssey SaaS pivot (source of truth: Notion **HT_01 "Quan hệ Dashboard · Backend · Agent"**): the **control plane only provisions** tenants; the **provider's backend connects DIRECTLY to the tenant's worker** — the control plane is NOT on the conversation data path (preserves HT_01 **E01**: backend down ⇒ end customers unaffected).

Slice #2 = **SP-A + SP-B**: issue a per-tenant credential at provisioning, and stand up a **tenant-aware ingress gateway** in front of LiveKit so a provider streams **voice** (bridged into an internal LiveKit room) or **chat** (reverse-proxied to the worker's `/chat`) to its own tenant, authenticated by a per-tenant Bearer credential.

- Spec: [docs/superpowers/specs/2026-07-29-saas-slice2-provider-direct-worker-design.md](../specs/2026-07-29-saas-slice2-provider-direct-worker-design.md)
- Plan: [docs/superpowers/plans/2026-07-29-saas-slice2-provider-direct-worker.md](../plans/2026-07-29-saas-slice2-provider-direct-worker.md)
- SDD ledger (per-task history, decisions, deferred minors): `.superpowers/sdd/2026-07-29-saas-slice2-provider-direct-worker/progress.md` (gitignored)

---

## 2. Architecture (as built)

```
Provider backend  (holds per-tenant credential  tnt_...)
   │  VOICE: wss://<tenant>.<base>/v1/stream  + Authorization: Bearer <cred>
   │  CHAT : wss://<tenant>.<base>/v1/chat    + Authorization: Bearer <cred>
   ▼
DNS/ingress → Ingress Gateway  (noble-gateway, stateless, shared)
   1. tenant ← Host subdomain          (gateway/auth.py: tenant_from_host)
   2. verify Bearer ← store-backed CACHE (gateway/registry.py) — NEVER a live Portal API (E01)
   3a VOICE: mint LiveKit token (dispatch agent-<tenant>) + join room + relay audio  ⚠️ skeleton, unverified
   3b CHAT : reverse-proxy WS → worker /chat, sending set_customer first (identity seed)
   ▼
LiveKit room (voice)  /  worker :8766 /chat (chat)  →  Worker pod (TENANT_ID=<tenant>)
```

**Key invariants — DO NOT BREAK:**
- Gateway verifies creds from a **cache over the tenant store** (MinIO), never a live control-plane call → E01 holds (Portal down ⇒ new calls still start).
- Plaintext credential **never persisted** — only a salted SHA-256 hash in `<tenant>/_creds.json`. Plaintext returned once at issue.
- Cross-tenant isolation: verify runs only against the **Host-resolved** tenant's creds; the token carries no tenant id. `tenant_from_host` dot-boundary suffix match rejects lookalikes.
- Gateway is **serving-plane infra** (peer of the LiveKit server), NOT control plane — never imports/executes tenant code; only auth + relay.
- Offline-safe: `gateway/` modules have **no top-level** `websockets`/`livekit` import (those live inside `# pragma: no cover` integration fns) so `make test-unit` collects.
- **Single source of truth for the LiveKit dispatch name:** `tenant/naming.py::agent_dispatch_name(tenant_id) → "agent-<tenant>"`. Used by worker registration (`transport/livekit/worker.py`), the app mint (`server/app_session.py::_mint_livekit_token`), AND the gateway (`gateway/livekit_bridge.py`). A regression test locks these three in agreement — keep it green.
- Worker media path + turn loop are **byte-identical** to before; worker touch was only agent_name + a voice identity seed from participant metadata.

---

## 3. Files shipped (18 commits `ef38281`..`cd23adf`)

| Area | Files | What |
|---|---|---|
| Config | `config.py` (+7 gateway settings), `.env.example`, `tenant/naming.py` | `TENANT_ENDPOINT_TEMPLATE`, `GATEWAY_BASE_DOMAIN`, `GATEWAY_HOST/PORT`, `GATEWAY_CRED_CACHE_TTL_SEC`, `GATEWAY_WORKER_SECRET`, `WORKER_CHAT_INTERNAL_URL_TEMPLATE`; `agent_dispatch_name()` |
| Credential | `tenant/credentials.py` | `CredentialEntry`, `generate_credential`/`verify`/`serialize_creds`/`parse_creds`; salted SHA-256, `hmac.compare_digest`, `tnt_`+token_urlsafe(32) |
| Store | `tenant/store.py` | `read_creds_raw`/`write_creds_raw` (`_creds.json`), excluded from `read_bundle`/bundle_hash |
| Provisioning | `tenant/provisioning.py`, `tenant/cli.py` | `issue_credential`/`revoke_credential`/`list_credentials`/`endpoint_url`; CLI `noble-tenant issue-cred/revoke-cred/list-creds` |
| Gateway | `gateway/registry.py` | `CredentialRegistry` — TTL cache of creds + `is_active` (store-backed, offline verify) |
| Gateway | `gateway/auth.py` | `tenant_from_host`, `authorize` → `AuthResult` (order: bad_host → tenant_inactive → no_bearer → bad_credential → ok) |
| Gateway | `gateway/livekit_bridge.py` | `room_name` (`tenant-callid-ms-hex`), `build_dispatch_token` (dispatch `agent-<tenant>` + identity as participant metadata) |
| Gateway | `gateway/server.py`, `pyproject.toml` | `route`/`parse_handshake` (pure, tested) + `_extract_request` + `_serve`/`_handle`/`_bridge_voice` (pragma) + console `noble-gateway` |
| Gateway | `gateway/chat_proxy.py` | `worker_chat_url`, `first_messages` (set_customer JSON), `proxy_chat` (pragma: WS reverse-proxy + relay) |
| Worker | `transport/livekit/worker.py`, `server/app_session.py` | agent_name = `agent_dispatch_name(tenant_id)`; voice identity seed from `caller.metadata`; extracted `identity_to_fields()` (behavior-preserving, shared) |
| Docs | `CLAUDE.md` (changelog row), `src/noble_agent/SMOKE.md` (new) | |

**Tests:** all new logic unit-tested under `tests/unit/gateway/` + `tests/unit/tenant/`. Full `tests/unit` diffed vs pre-branch baseline → **zero new failures**. (28 pre-existing env-baseline failures need live MinIO / are the documented unified baseline — NOT from this branch.)

---

## 4. What's VERIFIED vs NOT

- ✅ **Unit tests** — green (zero new failures).
- ✅ **CHAT smoke, live, end-to-end through the gateway** (2026-07-30): provision → issue-cred → provider WS `/v1/chat` → `session_id` + `customer_ok` (identity seeded) + streamed Luna tokens + `done`. Reproduce with `scripts/smoke_gateway_chat.py` (see §5).
- ⚠️ **NOT verified — cross-tenant reject:** run `scripts/smoke_gateway_chat.py <cred> noble --reject` (expects WS close 4001). Quick; do it first.
- ⚠️ **NOT verified — VOICE path.** `gateway/server.py::_bridge_voice` + the LiveKit-client audio relay are a `# pragma: no cover` **skeleton that has never actually run**. The final review flagged (and this session fixed) a websockets-API bug and an unreferenced-audio-pump-task bug in that area — but the relay itself is unproven. **Expect to finish/debug `_bridge_voice` when doing voice smoke.** This is real remaining implementation, not just "run the checklist."

---

## 5. How to run the chat smoke (the recipe that worked)

All in the repo venv (`source .venv/bin/activate`), MinIO/LiveKit/Redis/Mongo already in `.env` (remote `10.50.13.220`). Gotchas below were hit-and-fixed this session.

```bash
# 0. one-time: create the MinIO bucket (default name hotline-tenants) if missing
python - <<'PY'
from noble_agent.config import get_settings
from noble_agent.tenant.store import MinioTenantStore
s = get_settings(); c = MinioTenantStore.from_settings(s)._c
try: c.create_bucket(Bucket=s.tenant_bucket); print("created", s.tenant_bucket)
except Exception as e: print("bucket note:", type(e).__name__)
PY

# 1. provision tenant noble into MinIO + issue a credential
noble-tenant import-from-package noble      # NOTE: no --status flag; it defaults to active
noble-tenant list                           # expect: noble  active  v1
noble-tenant issue-cred noble               # -> tnt_...  (copy it)

# 2. Terminal A — worker (aiortc, serves /chat on :8766). MUST override the
#    materialize dir: default /var/lib/noble is not writable (perm denied).
mkdir -p "$HOME/.cache/noble/tenants"
TENANT_MATERIALIZE_DIR="$HOME/.cache/noble/tenants" scripts/run.sh --no-reload

# 3. Terminal B — gateway. base_domain=localhost so *.localhost -> 127.0.0.1;
#    worker-chat template overridden to the local worker (default agent-<tenant> won't resolve).
GATEWAY_BASE_DOMAIN=localhost \
WORKER_CHAT_INTERNAL_URL_TEMPLATE='ws://127.0.0.1:8766/chat?session=smoke-{tenant_id}' \
noble-gateway

# 4. Terminal C — client (happy path)
python scripts/smoke_gateway_chat.py <tnt_...>
# 5. cross-tenant reject
python scripts/smoke_gateway_chat.py <tnt_...> noble --reject   # expect close 4001
```

Gotchas resolved this session: MinIO bucket didn't exist (create it); `import-from-package` has no `--status`; `TENANT_MATERIALIZE_DIR` default `/var/lib/noble` is not writable → point at `$HOME/.cache/noble/tenants`. If `noble.localhost` doesn't resolve: `echo "127.0.0.1 noble.localhost" | sudo tee -a /etc/hosts`.

---

## 6. Next tasks for the next session (prioritized)

1. **Cross-tenant reject smoke** (5 min) — run the `--reject` client, confirm WS close 4001. Also try a valid cred on the WRONG tenant subdomain.
2. **VOICE path — finish + smoke** (the big one). `_bridge_voice`/`proxy_chat`-equivalent audio relay in `gateway/server.py` is an unproven skeleton. Needs:
   - a LiveKit worker running as the voice transport (`TRANSPORT_BACKEND=livekit` → `run_worker`), registered as `agent-noble` (it now derives this from `agent_dispatch_name(settings.tenant_id)`).
   - implement/validate the provider-audio ⇄ LiveKit-room relay (frame format per `voice/service/protocol.py`: binary PCM16 + JSON control). Write a voice smoke client (mirror `scripts/smoke_gateway_chat.py`).
   - ⚠️ **OPS PREREQ:** slice #2 changed the LiveKit dispatch name to `agent-<tenant>`. Any LiveKit **dispatch rule / SIP trunk / deploy config** naming the old `noble-hotline-agent` must be updated, and the deployed worker must register the new name — otherwise BOTH the existing NobleX-app voice and the gateway voice get no agent in the room. (`livekit_agent_name` config field is now dead-for-dispatch, kept only for `.env` back-compat.)
3. **Decide branch disposition** — currently unmerged/unpushed on `feat/agent` (only branch; remote `odyssey-agent`). Per the user's branch rules, push/PR needs explicit go-ahead.
4. **(Optional) harden deferred minors before merge** — from the SDD ledger: T2 key_id entropy (fine), T3 `_FakeS3` dedupe, T4 endpoint_url trailing-slash test + revoke/list read_meta gate, T6 is_active non-active-status + cross-tenant-cache tests, T7 lookalike-host + bearer-edge asserts, T8 assert RoomAgentDispatch name, T10 chat_proxy error logging (done in fix wave). Opus triaged ALL as non-blocking.
5. **Future slices (independent of this pivot, per HT_01):**
   - **SP-C** — config publish/versioning (immutable versions + pointer + rollback); worker loads published version at new-conversation start.
   - **SP-D** — heartbeat up-channel + dashboard status derivation.
   - **SP-E** — data plane → Postgres + RLS + per-tenant role + per-tenant Qdrant collection (largest; independent of the gateway).

---

## 7. Environment notes for the next session
- **RTK hook mangles Bash text output** (git/grep/pytest/ls print filtered "ok" summaries). For ground truth: use the Read tool on files, or redirect command output to a file and Read it, or prefix `rtk proxy`.
- Repo is `odyssey-agent` (remote GitLab) despite the `santa-hotline-agent` directory name; branch `feat/agent` has a single prior commit `03ed43e "upcode"` (the imported santa codebase) — slice #2 sits on top.
- `.superpowers/` is gitignored (SDD ledger + per-task reports live there, uncommitted).
- Exported shell env overrides `.env` (pydantic-settings). That's how the smoke overrides `TENANT_MATERIALIZE_DIR`/`GATEWAY_BASE_DOMAIN`/`WORKER_CHAT_INTERNAL_URL_TEMPLATE` per-process.
