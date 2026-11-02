# Configuration — bảng env đầy đủ

Bảng env chi tiết. Nguồn sự thật vẫn là `src/noble_agent/config.py` (~370 field); bảng này là phần hay dùng.

Ngược lại: [`../../CLAUDE.md`](../../CLAUDE.md)

### Key configuration

| Setting (env) | Default | Purpose |
|---|---|---|
| `USE_UNIFIED_AGENT` | `false` | Master flag. Must be `true` to run the unified server. |
| `AGENT_CONFIG_SOURCE` | `legacy` | Where the agent's identity/scope/tools config comes from: `legacy` (`config.json` + `manifest.toml`, current behavior) \| `db` (Portal Postgres published config + shared on-disk `persona/` skeleton). `db` ⇒ the ENTIRE control-plane (gateway credentials / worker version+ctx / heartbeat) reads Postgres — MinIO is not on the serving path. See Architecture + `docs/handoff/agent-postgres-read-contract.md`. |
| `NOBLE_AGENT_NAME` | `Luna` | Agent display name in prompt/greeting (legacy path; DB path uses `config.identity.agent_name`). |
| `AGENT_TEMPERATURE` / `AGENT_MAX_TOKENS` | `0.7` / `800` | **DB path only** — replace `persona/config.json`'s temperature/max_tokens (ops knob, not provider-chosen). |
| `TENANT_ID` | `noble` | Process-default tenant when a request carries none (`current_tenant()` fallback). Single-tenant deploys pin this. |
| `TENANT_STORE_ENABLED` | `false` | Load tenant bundles from the MinIO store (org-nested `<org>/<tenant>/`) instead of the in-wheel package. |
| `POSTGRES_ENABLED` / `POSTGRES_DSN` / `POSTGRES_SERVER_DSN` / `POSTGRES_ADMIN_DSN` / `POSTGRES_APP_ROLE` | `false` / — / — / — / `odyssey_agent` | Odyssey PG data plane + (DB config path) the `agent_published_config` VIEW. `POSTGRES_DSN` = shared app-role pool, the fallback whenever the worker holds NO per-tenant runtime credential (dev / `chat_repl` / heartbeat / voice when the Redis credential stash misses) — it is NOT dead, don't remove it. `POSTGRES_SERVER_DSN` = host:port/db with NO userinfo; `pool_for_tenant` splices the per-tenant role+password into it. `POSTGRES_ADMIN_DSN` + `POSTGRES_APP_ROLE` are provisioning-only (`noble-tenant pg-apply-schema` / `pg-provision` / `pg-ensure-app-role`), never on the turn path. |
| `NOBLE_DATA_SOURCE` | `pg_kb` | Project/unit data provider (see `data/providers/`). **`pg_kb` là provider DUY NHẤT** (`postgres_kb.py`, đọc `tenant_data.projects/zones/units/documents/media` qua `tenant_conn` + RLS). 3 provider cũ (`sales_api`/`nbx_mongo`/`mongo`) đã XOÁ ở SP1 (2026-08-03) — không còn đường rollback qua env. Cần `POSTGRES_ENABLED=true` + role đã provision, nếu không tool degrade sang escalate. |
| `NOBLE_RAG_BACKEND` | `flat_store` | `flat_store` \| `qdrant` \| `hipporag` \| `grep_faq` \| `kb_service` \| `empty` |
| `EMBED_BACKEND` | `gemini` | Embedder for `kb_search` + `send_media`: `gemini` \| `service` \| `hf`. Governs **dense AND sparse** — `service` ⇒ both over HTTP and **no model loaded in-process**, no local fallback on error. **Must match what ingest indexed with** — same dimension is not enough, a different model is a different vector space and Qdrant returns noise with no error. |
| `EMBED_MODEL` / `EMBED_DIM` | empty / `1024` | Empty model = backend default (`gemini-embedding-001`, `intfloat/multilingual-e5-large`). `EMBED_DIM` must equal the collection's dense vector size. |
| `EMBED_SPARSE_MODEL` | `Qdrant/bm25` | In-process fastembed BM25 model for `kb_search`'s sparse branch. Applies **only when `EMBED_BACKEND != service`** — the service owns its own model name. **Must equal the model ingest used** — a different one is a different term vocabulary, so the branch silently contributes nothing. |
| `EMBED_SERVICE_URL` / `EMBED_TIMEOUT` | empty / `30.0` | Embed service endpoint (`…/embed`). Required for **visual** (SigLIP2 — no API equivalent) and for **dense + sparse** when `EMBED_BACKEND=service`. Empty + `EMBED_BACKEND=service` ⇒ `kb_search` raises → empty context, so pair them. Empty on another backend ⇒ `kb_search` unaffected, `send_media` searches text-only. |
| `QDRANT_URL` / `QDRANT_API_KEY` | empty / empty | Qdrant holding the per-tenant `<tenant>_documents` / `<tenant>_media` collections. **NOT `QDRANT_URL`** — that is the unrelated clone-from-root deployment used by `qdrant`/`hipporag`; both can be set at once. Deployment-local (SSM tunnel to a private-subnet EC2), so the value is not portable across hosts. |
| `QDRANT_TIMEOUT` | `10.0` | Qdrant query timeout (seconds). |
| `KB_SEARCH_TOP_K` / `KB_SEARCH_MIN_SCORE` | `5` / `0.0` | Hits returned by the `kb_service` backend / min fused score. `MIN_SCORE` is **RRF-scaled, not cosine**; `0.0` = no filter. |
| `MEDIA_SEARCH_TOP_K` / `MEDIA_SEARCH_THRESHOLD` | `10` / `0.0` | `send_media` hits / min fused score. Threshold is **RRF-scaled** and shifts with the number of branches fused, so `0` (no filter) is the default — cap with `TOP_K`. |
| `MEDIA_SEARCH_CACHE_TTL` | `300.0` | In-process `send_media` result cache TTL (seconds). NOT invalidated by an ingest; `0` disables. |
| `MEDIA_SEND_THUMB` | `false` | Include `thumb` (ingest's `thumb_url`) on image items. Off = clients render `media_url` for both grid and lightbox. Off by default because `thumb_url` points at a private-subnet MinIO; turn on when it resolves publicly. Deliberately absent from `.env.example`. |
| `HIPPORAG_GRAPH_PATH` | `data/hipporag/graph.json` | Persisted KG artifact (built by `noble-rag-sync`). |
| `HIPPORAG_PPR_ALPHA` / `HIPPORAG_PPR_ITERS` | `0.5` / `30` | PPR damping + power-iteration steps. |
| `HIPPORAG_SEED_K` / `HIPPORAG_TOP_K` | `8` / `5` | Hybrid hits that seed PPR / passages returned after fuse. |
| `HIPPORAG_OPENIE_MAX_TOKENS` | `1024` | Build-time OpenIE completion cap. |
| `HIPPORAG_OPENIE_MODEL` | empty | Primary-provider pin for build-time OpenIE, independent of the main agent (must equal a `<P>_MODEL` value). Empty → `NOBLE_AGENT_MODEL` pin. |
| `HIPPORAG_SPARSE_SEED_ENABLED` | `false` | Opt-in HippoRAG 2 sparse triple-seed: also seed PPR at query-nearest phrase nodes (embedding cosine, NO LLM), run in parallel with hybrid. Needs the `.phrase_emb.npz` sidecar (built by `noble-rag-sync`). |
| `HIPPORAG_SPARSE_SEED_TOP_M` / `HIPPORAG_SPARSE_SEED_WEIGHT` | `5` / `0.3` | Triples matched (each seeds ≤2 entities) / PPR restart mass share for the sparse seeds (0..1). |
| `HIPPORAG_PASSAGE_SEED_THRESHOLD` / `HIPPORAG_PHRASE_SEED_THRESHOLD` | `0.0` / `0.0` | Min score a top-K seed must clear to be used (applied after top-K, before the mix): passage = qdrant hybrid score, phrase = triple cosine. `0.0` = keep all. |
| `HIPPORAG_TRIPLE_STORE` | `local` | Where the sparse triple-seed reads its embeddings from: `local` (numpy `.triple_emb.npz` sidecar) \| `qdrant` (dedicated collection, cascade `qdrant → local → sparse-seed off`). Both stores are built by every `noble-rag-sync` regardless of this flag. |
| `QDRANT_TRIPLE_COLLECTION` | `noble_kb_hipporag_triples` | Qdrant collection holding triple embeddings, used when `HIPPORAG_TRIPLE_STORE=qdrant`. |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant endpoint. Used when `NOBLE_RAG_BACKEND=qdrant`. |
| `QDRANT_API_KEY` | empty | Qdrant API key. |
| `QDRANT_COLLECTION_ROOT` | empty | Read-only source collection (other team writes dense). Cloned into the app collection at startup. |
| `QDRANT_COLLECTION` | `noble_kb_hybrid` | **App-owned clone** (dense + BM25 sparse). All searches run here. |
| `QDRANT_DENSE_VECTOR_NAME` / `QDRANT_SPARSE_VECTOR_NAME` | `dense` / `bm25` | Named vectors on the clone (IDF modifier on the sparse). |
| `QDRANT_FALLBACK_DIR` | `data/flat_store/bm25_qdrant_fallback` | On-disk BM25 fallback (built by reconcile from the same root snapshot). |
| `QDRANT_RECONCILE_TIMEOUT_SEC` | `120` | Wall-clock bound on the startup reconcile so an unreachable Qdrant can't wedge boot. |
| `NOBLE_SUMMARY_K` | `8` | User-turn threshold that triggers async summary (counts role=user messages past the summarised boundary) |
| `NOBLE_SUMMARY_KEEP_TAIL` | `4` | Number of latest user-turns kept verbatim after summary covers older history |
| `NOBLE_SUMMARY_WARM_CACHE` | `true` | After summary persists, fire a background throwaway LLM call replaying the next turn's exact request (same model map / primary / tools) so the provider prompt cache is warm before the next live turn. Provider-agnostic; best-effort. Cancelled at the next turn's start. |
| `NOBLE_PROJECT_REGISTRY_REFRESH_SEC` | `120` | TTL debounce for re-warming the DB project registry (tool-schema code enums + prompt project table) at the start of each new call, so `ma_du_an` changes land without a restart. `0` disables the per-call refresh (boot cache only). |
| `NOBLE_SEMCACHE_*` | (disabled) | Predictor cache config |
| `NOBLE_HEARTBEAT_ENABLED` | `true` | SP-D heartbeat (contract C3). A `HeartbeatSupervisor` (both transports) writes `<tenant>/_heartbeat.json` for EVERY active tenant in the store (`list_ids()` + `read_meta().status=="active"`), one `HeartbeatEmitter` each (materialize-only build), every `NOBLE_HEARTBEAT_SEC`. Effective only when `TENANT_STORE_ENABLED=true` (else no store → inert). |
| `NOBLE_HEARTBEAT_SEC` | `20` | Heartbeat cadence (= config-poll cycle; N7 chốt: Dashboard infers fresh ≤60s, applying >2min→E03). |
| `TRANSPORT_BACKEND` | `aiortc` | `aiortc` \| `livekit` |
| `LIVEKIT_TOKEN_PUBLIC` | `false` | Public `GET /livekit/token` (dev tester); prod mints via `POST /api/v1/app/session channel=voice`. |
| `STT_BACKEND`, `TTS_BACKEND` | `soniox`, `vieneu` | See backends section |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` | empty | At least one required |
| `ANTHROPIC_MODEL` / `OPENAI_MODEL` / `GEMINI_MODEL` | per-provider defaults | Model name used **when that provider is called** (primary or fallback). Empty = skip that provider entirely. |
| `NOBLE_AGENT_MODEL` | empty | Primary-provider pin for the **main agent**. Must equal one of `<P>_MODEL` above; that match identifies the primary provider. Empty / unknown → default chain order (warning). |
| `NOBLE_SUMMARY_MODEL` | empty | Same scheme — pins primary provider for async summary. |
| `NOBLE_SEMCACHE_MODEL` | empty | Same scheme — pins primary provider for semcache predictor + sandbox. |
| `NOBLE_LLM_ENABLE_THINKING` | `false` | Does the model generate thinking. Off → disable kwarg + strip `<think>` everywhere (incl. history). On → thinking kept in history. See LLM backends section. |
| `NOBLE_LLM_SHOW_THINKING` | `false` | Display-channel debug. On → chat UI shows `<think>`. TTS + eval always strip. Only meaningful when `ENABLE_THINKING=true`. |
| `STT_INPUT_GATE_MODE` | `off` | `off` \| `rms` \| `vad`. Gates PCM frames reaching STT. `rms` replaces removed `AUDIO_GUARD_FRAMES_GATE_ENABLED`. `vad` reuses Silero VAD. |
| `AUDIO_GATE_PREROLL_CHUNKS` | `3` | K-chunk lookback so speech onset is not clipped (all gate modes). |
| `AUDIO_GATE_MIN_RMS` | `160.0` | (rms) per-frame RMS threshold to count as speech. |
| `AUDIO_GATE_REQUIRED_CONSECUTIVE` | `3` | (rms) consecutive above-threshold frames required to open gate. |
| `AUDIO_GATE_BARGE_IN_RMS` | `2400.0` | (rms) high-energy instant-open threshold. |
| `STT_VAD_GATE_HANGOVER_MS` | `300` | (vad) keep gate open this many ms after VAD speech ends. |
| `STT_GATE_KEEPALIVE_MAX_SEC` | `2.0` | (rms/vad) max synthetic silence fed to STT after a pending utterance so the endpoint fires; `0` = off. |
| `SPEAKER_MODE` | `off` | `off` \| `single` \| `multi`. `single` = one enrolled primary (drop others). `multi` = turn-taking floor; only the current asker may interrupt agent TTS; floor reopens on agent-done. **Floor-open (no asker enrolled yet, e.g. the agent-initiated auto-greeting) → the first speaker may barge in and claims the floor** — the "only asker" restriction applies only once someone owns the turn. |
| `SPEAKER_INTERRUPT_MIN_SEC` | `0.8` | (`multi`) seconds of interrupter audio collected before speaker ID; trades interrupt latency for confident ID before cutting the agent. |
| `SPEAKER_VERIFICATION_ENABLED` | — | **Deprecated.** Legacy `true` resolved to `single` via `config.resolve_speaker_mode()` + deprecation warning. Use `SPEAKER_MODE` instead. |
| `SPEAKER_REMOTE_URL` | empty | URL of resident `noble-speaker-service` HTTP `/embed`. Empty → local sherpa model. |
| `SPEAKER_REMOTE_TOKEN` | empty | Bearer token for the remote embed service (empty = no auth). |
| `SPEAKER_MATCH_THRESHOLD` | `0.5` | Cosine similarity threshold to accept a speaker match. |
| `SPEAKER_ADAPT_ENABLED` | `false` | Online adaptation: blend each verified embedding into the enroll vector. |
| `SPEAKER_ADAPT_WEIGHT` | `0.1` | Blend weight for online adaptation. |
| `SPEAKER_MODEL_DIR` | `models/speaker` | Local sherpa model dir (auto-provisioned from `SPEAKER_HF_REPO`). |
| `SPEAKER_HF_REPO` | `csukuangfj/speaker-embedding-models` | HF repo for the local CAM++ ONNX model. |
| `SPEAKER_HF_REVISION` | `main` | HF revision to pull (etag-cached). Public `csukuangfj` repo has only `main`. |
| `SPEAKER_SERVICE_HOST/PORT` | `0.0.0.0` / `9100` | Bind address for `noble-speaker-service`. |
| `CHAT_MAX_CONCURRENT_SESSIONS` | `200` | In-process /chat admission cap (`server/admission.py`); ≤0 = unbounded. At the ceiling `handle_text_session` rejects (WS close 4029) and `/health/ready` returns 503 with `chat_admission` stats. Voice unaffected (LiveKit forks per job). |
| `ANALYZE_SQL_ROLE` | `agent_sql_ro` | Role the `analyze_projects` tool runs the LLM's SQL under (`SET LOCAL ROLE`). Only `GRANT SELECT` on `agent_projects_v`/`agent_units_v` — provisioned via `noble-tenant pg-ensure-sql-ro`. |
| `ANALYZE_SQL_TIMEOUT_MS` | `2000` | `SET LOCAL statement_timeout` for the `analyze_projects` query. |
| `ANALYZE_SQL_MAX_ROWS` | `50` | Row cap on `analyze_projects` results; also the `LIMIT` auto-appended when the LLM's SQL omits one. |
| `ANALYZE_VOCAB_TTL_SEC` | `600` | TTL for the per-tenant in-process cache of real column values (`agent/tools/analytics_vocab.py`) injected into the `analyze_projects` tool description each turn. |
