# odyssey-models: port from santa-models

## Goal

Create `odyssey-models` as a standalone, fully rebranded copy of the four
generic model-serving microservices currently living in `santa-models`
(`embed`, `stt`, `speaker`, `tts`), decoupled from the KB stack
(`ingest`/`query_rag`/`query_media`) that grew up around them in that repo.
odyssey-models ships nothing else — no Qdrant, no Mongo, no S3, no VLM API
keys, no CI/deploy config. This task builds the new repo only; wiring any
consumer (e.g. odyssey-agent) to it is explicit future work.

## Source snapshot

Ported from `santa-models` at `develop@b03e6eb` (2026-08-19, pulled fresh for
this port — the repo had moved 38 commits since the last time it was looked
at, including the removal of the old standalone `normalize/`/`media/`
services and their replacement by a KB stack built on a shared `common/`).

## Scope

### In (ported)

| Path | Notes |
|---|---|
| `common/auth.py` | Bearer-token dependency. Generic, no KB coupling. |
| `common/logging.py` | Shared logging setup. Generic. |
| `common/registry.py` | `kind → implementation` lookup table used by `embed/models/`. Generic. |
| `common/settings.py` | Env-var read helpers + `TOKEN`/`LOG_LEVEL`. Generic. |
| `embed/` | `server.py`, `settings.py`, `models/{__init__,e5,bm25,siglip2}.py`, `Dockerfile`, `README.md`. Unmodified internals — one service, 4 kinds (dense/sparse/visual_image/visual_text), all bundled. |
| `stt/` | `stt_server.py`, `Dockerfile`. Self-contained, unchanged. |
| `speaker/` | `speaker_server.py`, `Dockerfile`. Self-contained, unchanged. |
| `tts/` | `tts_server.py`, `requirements.txt`, `reference/presets.json`, `tools/ccu_loadtest.py`. No Dockerfile — stays native/GPU, run via `uv venv` + systemd as today. |
| `docs/remote_stt_tts_spect.md` | Wire-contract source of truth for STT/TTS `remote` backend. No santa references, ported as-is. |
| `docker-compose.yml` | Trimmed to `embed` + `stt` + `speaker` only (CPU services). `tts` stays native, not in compose — matches current santa-models pattern. |
| `pyproject.toml` | Trimmed: `name = "odyssey-models"`, `packages.find.include = ["common*", "embed*"]`, optional-dependencies trimmed to `embed` + `dev` only. |
| `.env.example` | Trimmed to vars these 4 services actually read (`ODYSSEY_MODELS_TOKEN`, `HF_TOKEN`, `ODYSSEY_LOG_LEVEL`, `EMBED_*`). |
| `.gitignore`, `.dockerignore` | Same shape as santa-models, egg-info name updated. |
| `tests/test_embed_api.py`, `tests/test_auth.py`, `tests/test_logging.py`, `tests/test_registry.py`, `tests/test_settings.py`, `tests/ws_protocol_test.py` | Ported. Each gets a quick pass during implementation to confirm no accidental KB-specific imports slipped in. |
| `tests/test_repo_hygiene.py` | Ported with `PACKAGES` trimmed to `("common", "embed")`. |

### Out (left behind in santa-models)

- `ingest/`, `query_rag/`, `query_media/` and the KB-specific parts of
  `common/` (`qdrant.py`, `payload.py`, `point_id.py`, `collections.py`,
  `content_hash.py`, `embed_client.py`).
- Cloudflare quick-tunnel compose blocks (KB-only, existed to expose
  `query-rag`/`query-media` to the agent over the internet).
- `.gitlab-ci.yml` — devops sets up CI/deploy separately, later.
- KB-specific tests (`test_chunking.py`, `test_caption.py`, `test_ocr.py`,
  `test_ingest_api.py`, `test_query_rag.py`, `test_query_media.py`,
  `test_media_indexer.py`, `test_thumbnail.py`, `test_video.py`,
  `test_profiles.py`, `test_prompts.py`, `test_incremental.py`,
  `test_normalize.py` — this last one tests `ingest.chunking.normalize`
  (HTML→text for chunking), unrelated to TTS despite the name — and the
  KB-specific `common/*` tests (`test_collections.py`, `test_content_hash.py`,
  `test_payload.py`, `test_point_id.py`, `test_qdrant.py`).
- Historical `docs/superpowers/{specs,plans}/*santa-tts*` design docs —
  project-history artifacts of past work on the old repo; still available
  there if ever needed.
- odyssey-agent — untouched. It keeps referencing `SANTA_MODELS_TOKEN` and
  `NobleX-AI/santa-stt`/`santa-tts` until a future task cuts it over, in
  coordination with whoever rotates the real secrets on the running box.

## Renaming (full rebrand)

| Old | New |
|---|---|
| `SANTA_MODELS_TOKEN` | `ODYSSEY_MODELS_TOKEN` |
| `SANTA_LOG_LEVEL` | `ODYSSEY_LOG_LEVEL` |
| `santa-embed:local` / `santa-stt:local` / `santa-speaker:local` (image names) | `odyssey-embed:local` / `odyssey-stt:local` / `odyssey-speaker:local` |
| `/models/santa-stt` (local bind-mount path in stt's Dockerfile/compose) | `/models/odyssey-stt` |
| `"Santa Embed Service"` / `"Santa Speaker Service"` (FastAPI titles) | `"Odyssey Embed Service"` / `"Odyssey Speaker Service"` |
| `santa_models.egg-info/`, `pyproject.toml` `name` | `odyssey_models.egg-info/`, `odyssey-models` |
| `"NobleX-AI santa reference"` (presets.json provenance string) | `"NobleX-AI odyssey reference"` |
| `/home/thebc/.config/santa/secrets.env` (fallback path in `ccu_loadtest.py`) | `/home/thebc/.config/odyssey/secrets.env` — cosmetic; the directory doesn't need to exist for the port itself to be correct. |

**Exceptions — these stay pointing at the old names, per earlier decision:**

- `SHERPA_HF_REPO` default (`NobleX-AI/santa-stt`) and `TTS_BACKBONE_REPO`
  default (`NobleX-AI/santa-tts`) are unchanged. Only the env var *names*
  rebrand elsewhere — these two are HF Hub repo identifiers, and the actual
  weights haven't moved.
- The two log lines in `tts_server.py` ("Loading VieNeu santa-tts...", "VieNeu
  santa-tts ready...") stay unchanged — they describe the actual HF artifact
  being loaded, which is still literally named `santa-tts`. Renaming the log
  text would misdescribe what's running.

## Process

Fresh copy, not a history-preserving migration: copy the current file
contents into the new repo and make one clean initial commit, rather than
rewriting santa-models' history with `git filter-repo` (its history is
dominated by KB-only commits and several rounds of restructuring — a rewrite
would be high-effort for little payoff). Blame history for these files
remains available in santa-models.

## Validation

- `pip install -e ".[dev,embed]"` in the new repo; `pytest -q` passes for all
  ported tests.
- `ruff check .` passes (same exclude list as santa-models, minus the
  KB-only `mockdb` entry which no longer applies).
- `docker compose up -d` brings up `embed` + `stt` + `speaker`; `curl
  localhost:8013/health` / `:8014/health` return `200`.
- `tts` still runs the existing native/`uv venv` path unchanged (no
  Dockerfile, no compose entry) — smoke-test via `ws_protocol_test.py`.
