# odyssey-models Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up `odyssey-models` as a fully rebranded, standalone copy of santa-models' `embed`, `stt`, `speaker`, and `tts` model-serving microservices, decoupled from santa-models' KB stack.

**Architecture:** A flat multi-service repo — `common/` (4 generic helper modules), `embed/` (FastAPI, CPU, Docker), `stt/` (websockets, CPU, Docker), `speaker/` (FastAPI, CPU, Docker), `tts/` (websockets, GPU, native/systemd — no Docker). One `pyproject.toml` covers `common`+`embed`; `stt`/`speaker`/`tts` keep their own Dockerfile/requirements.txt deps, matching santa-models' existing pattern exactly.

**Tech Stack:** Python 3.11, FastAPI, sherpa-onnx, websockets, fastembed/sentence-transformers/transformers (embed only), pytest, Docker.

**Spec:** `docs/superpowers/specs/2026-08-19-odyssey-models-port-design.md`

## Global Constraints

- Source: `santa-models` at `develop@b03e6eb` (local checkout: `/Users/noblex-thebc-mac/Developer/noble-projects/santa/santa-models`). Every `cp` step below references this exact path.
- Full rebrand: `SANTA_MODELS_TOKEN`→`ODYSSEY_MODELS_TOKEN`, `SANTA_LOG_LEVEL`→`ODYSSEY_LOG_LEVEL`, image names `santa-*:local`→`odyssey-*:local`, `/models/santa-stt`→`/models/odyssey-stt`, FastAPI titles, `santa_models.egg-info/`→`odyssey_models.egg-info/`, presets.json provenance string, `ccu_loadtest.py`'s secrets-file fallback path and its own docstring's service-name mention (`santa-tts`→`odyssey-tts`, since that names the *service*).
- **Exception — do not rename:** `SHERPA_HF_REPO`/`TTS_BACKBONE_REPO` default values (`NobleX-AI/santa-stt`, `NobleX-AI/santa-tts` — HF Hub identifiers, weights haven't moved) and the two `tts_server.py` log lines plus its module docstring's first line that name the `santa-tts` backbone artifact — these describe the actual HF model being loaded, which is still literally named `santa-tts`.
- Fresh copy, no history rewrite: every ported file is `cp`'d then edited in the new repo; no `git filter-repo`.
- Out of scope, do not touch: `ingest/`, `query_rag/`, `query_media/`, KB-specific `common/*`, `.gitlab-ci.yml`, Cloudflare tunnel config, `odyssey-agent` (any repo other than `odyssey-models`).
- Repo root for every step below: `/Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models`. Source root: `/Users/noblex-thebc-mac/Developer/noble-projects/santa/santa-models` (referred to as `$SRC` in commands).

---

### Task 1: Project scaffolding + `common/` package

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.dockerignore`, `.env.example`
- Create: `common/__init__.py`, `common/auth.py`, `common/logging.py`, `common/registry.py`, `common/settings.py`
- Test: `tests/test_auth.py`, `tests/test_logging.py`, `tests/test_registry.py`, `tests/test_settings.py`, `tests/test_repo_hygiene.py`

**Interfaces:**
- Produces: a `.venv` with `common` installed editable (`pip install -e ".[dev]"`), reused by every later task. `common.auth.require_token(token: str) -> Callable`, `common.logging.setup(level: str) -> None`, `common.registry.Registry(what: str)` / `UnknownName`, `common.settings.env/env_int/env_float/env_bool/clean`, `common.settings.TOKEN: str`, `common.settings.LOG_LEVEL: str`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "odyssey-models"
version = "0.1.0"
description = "Model microservices: embed · stt · speaker · tts"
requires-python = ">=3.11"

# Chung cho embed. stt/tts/speaker KHÔNG dùng file này — chúng giữ requirements
# riêng trong Dockerfile/requirements.txt của mình.
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "httpx>=0.27",
    "numpy",
]

[project.optional-dependencies]
embed = [
    "sentence-transformers",
    "transformers",
    "torch",
    "fastembed",
    "huggingface_hub",
    "Pillow",
    "sentencepiece",
    "protobuf",
]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
    "ruff>=0.5",
    "httpx2",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["common*", "embed*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
# Chỉ `test_*.py`: `tests/ws_protocol_test.py` là test protocol của stt/tts, chạy
# bằng `python tests/ws_protocol_test.py`, không phải pytest.
python_files = ["test_*.py"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 110
target-version = "py311"
# Ngoài phạm vi lint: stt/tts/speaker giữ style riêng, không đụng.
exclude = ["stt", "tts", "speaker", "tests/ws_protocol_test.py"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 2: Write `.gitignore`**

```gitignore
# Model weights / data are provided at runtime (bind-mount or HF pull), never versioned.
# PHẢI có `/` đầu: pattern không neo thì git khớp mọi cấp, và `models/` đã từng nuốt
# `embed/models/` (registry 4 kind) — build trên box thiếu module, máy dev không thấy gì.
/models/
/model_cache/

# Secrets / local
.env
.env.*
# Mẫu (không chứa secret) — phải vào git, nếu không nó vô dụng.
# Git KHÔNG hiểu comment cùng dòng với pattern, nên dòng này phải đứng riêng.
!.env.example

# Python
__pycache__/
*.pyc
.venv/
odyssey_models.egg-info/
.pytest_cache/
.ruff_cache/

# kết quả loadtest sinh runtime
tts/tools/results/
```

- [ ] **Step 3: Write `.dockerignore`**

```dockerignore
.git
.gitlab-ci.yml
**/__pycache__
**/*.pyc
**/.venv
**/*.egg-info
models/
docs/
tests/
.env
*.service
```

- [ ] **Step 4: Write `.env.example`**

```dotenv
# odyssey-models — copy sang .env (gitignored) và điền.
# Giá trị bị cắt ở " #": compose không tự cắt inline comment.

ODYSSEY_MODELS_TOKEN=
HF_TOKEN=
ODYSSEY_LOG_LEVEL=INFO

# embed :8013 — tên theo vai trò, đổi model không phải đổi tên biến
EMBED_DENSE_MODEL=intfloat/multilingual-e5-large  # nhánh text (E5-large 1024d)
EMBED_SPARSE_MODEL=Qdrant/bm25
EMBED_VISUAL_MODEL=google/siglip2-base-patch16-256  # nhánh visual (SigLIP2 768d)
EMBED_VISUAL_MAXLEN=64
EMBED_DEVICE=cpu
EMBED_THREADS=4
EMBED_BATCH_SIZE=32
EMBED_WARMUP=dense,sparse,visual_image,visual_text  # nạp sẵn cả 4, đừng để agent chờ
```

- [ ] **Step 5: Create venv and install**

Run:
```bash
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -e ".[dev]" -q
```
Expected: no errors. `python -c "import fastapi, pytest, ruff"` (ruff has no importable API the same way, so instead run `ruff --version` and `pytest --version`) succeeds.

- [ ] **Step 6: Copy `common/` source files**

Run:
```bash
SRC=/Users/noblex-thebc-mac/Developer/noble-projects/santa/santa-models
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
mkdir -p common
cp "$SRC/common/__init__.py" common/__init__.py
cp "$SRC/common/auth.py" common/auth.py
cp "$SRC/common/logging.py" common/logging.py
cp "$SRC/common/registry.py" common/registry.py
cp "$SRC/common/settings.py" common/settings.py
```

- [ ] **Step 7: Rename in `common/auth.py`**

old_string:
```
"""Bearer SANTA_MODELS_TOKEN."""
```
new_string:
```
"""Bearer ODYSSEY_MODELS_TOKEN."""
```

- [ ] **Step 8: Rename in `common/settings.py`**

old_string:
```
TOKEN = env("SANTA_MODELS_TOKEN")
LOG_LEVEL = env("SANTA_LOG_LEVEL", "INFO")
```
new_string:
```
TOKEN = env("ODYSSEY_MODELS_TOKEN")
LOG_LEVEL = env("ODYSSEY_LOG_LEVEL", "INFO")
```

- [ ] **Step 9: Copy test files**

Run:
```bash
SRC=/Users/noblex-thebc-mac/Developer/noble-projects/santa/santa-models
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
mkdir -p tests
cp "$SRC/tests/test_auth.py" tests/test_auth.py
cp "$SRC/tests/test_logging.py" tests/test_logging.py
cp "$SRC/tests/test_registry.py" tests/test_registry.py
cp "$SRC/tests/test_settings.py" tests/test_settings.py
cp "$SRC/tests/test_repo_hygiene.py" tests/test_repo_hygiene.py
```

- [ ] **Step 10: Rename test-only env var prefix in `tests/test_settings.py`**

Use replace_all on `tests/test_settings.py`:
old_string: `SANTA_TEST_`
new_string: `ODYSSEY_TEST_`
(Replaces `SANTA_TEST_X`, `SANTA_TEST_Y`, `SANTA_TEST_N`, `SANTA_TEST_F`, `SANTA_TEST_B` — all arbitrary test-fixture var names, no functional effect.)

- [ ] **Step 11: Trim `PACKAGES` in `tests/test_repo_hygiene.py`**

old_string:
```
PACKAGES = ("common", "embed", "ingest", "query_rag", "query_media")
```
new_string:
```
PACKAGES = ("common", "embed")
```

- [ ] **Step 12: Run the common/ tests**

Run: `source .venv/bin/activate && pytest tests/test_auth.py tests/test_logging.py tests/test_registry.py tests/test_settings.py -v`
Expected: all PASS (30 tests total: 8 in test_auth, 3 in test_logging, 7 in test_registry, 12 in test_settings).

- [ ] **Step 13: Stage and run the repo-hygiene test**

Run:
```bash
git add pyproject.toml .gitignore .dockerignore .env.example common tests/test_auth.py tests/test_logging.py tests/test_registry.py tests/test_settings.py tests/test_repo_hygiene.py
source .venv/bin/activate && pytest tests/test_repo_hygiene.py -v
```
Expected: PASS (passes vacuously for `embed` since it doesn't exist yet — `Path.rglob` on a missing dir yields nothing).

- [ ] **Step 14: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat: add project scaffolding and common/ package

Trimmed port from santa-models develop@b03e6eb: only the 4 generic
common/ modules embed/ depends on (auth, logging, registry, settings) —
none of the KB-specific common/* (qdrant, payload, point_id, etc).
EOF
)"
```

---

### Task 2: `embed` service

**Files:**
- Create: `embed/__init__.py`, `embed/settings.py`, `embed/server.py`, `embed/models/__init__.py`, `embed/models/e5.py`, `embed/models/bm25.py`, `embed/models/siglip2.py`, `embed/Dockerfile`, `embed/README.md`
- Test: `tests/test_embed_api.py`

**Interfaces:**
- Consumes: `common.auth.require_token`, `common.logging.setup`, `common.registry.Registry`/`UnknownName` (Task 1). `.venv` from Task 1.
- Produces: `embed.server:build_app(*, token: str = "", hub: ModelHub | None = None) -> FastAPI`, `embed.server:app` (module-level instance), image `odyssey-embed:local` — consumed by Task 7's `docker-compose.yml`.

- [ ] **Step 1: Copy source files**

Run:
```bash
SRC=/Users/noblex-thebc-mac/Developer/noble-projects/santa/santa-models
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
mkdir -p embed/models
cp "$SRC/embed/__init__.py" embed/__init__.py
cp "$SRC/embed/settings.py" embed/settings.py
cp "$SRC/embed/server.py" embed/server.py
cp "$SRC/embed/models/__init__.py" embed/models/__init__.py
cp "$SRC/embed/models/e5.py" embed/models/e5.py
cp "$SRC/embed/models/bm25.py" embed/models/bm25.py
cp "$SRC/embed/models/siglip2.py" embed/models/siglip2.py
cp "$SRC/embed/Dockerfile" embed/Dockerfile
cp "$SRC/embed/README.md" embed/README.md
```

- [ ] **Step 2: Rename FastAPI title in `embed/server.py`**

old_string:
```
    app = FastAPI(title="Santa Embed Service", version="3.0.0", lifespan=lifespan)
```
new_string:
```
    app = FastAPI(title="Odyssey Embed Service", version="3.0.0", lifespan=lifespan)
```

- [ ] **Step 3: Rename in `embed/README.md`**

Use replace_all on `embed/README.md`:
old_string: `SANTA_MODELS_TOKEN`
new_string: `ODYSSEY_MODELS_TOKEN`
(2 occurrences: the `Authorization: Bearer` header example, and the env-var table row.)

- [ ] **Step 4: Copy the embed API test**

Run:
```bash
SRC=/Users/noblex-thebc-mac/Developer/noble-projects/santa/santa-models
cp "$SRC/tests/test_embed_api.py" /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models/tests/test_embed_api.py
```

- [ ] **Step 5: Run the embed test**

Run: `cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models && source .venv/bin/activate && pytest tests/test_embed_api.py -v`
Expected: all 20 tests PASS. (No `embed` extra / torch / transformers needed — the test injects fake models via `ModelHub`, and `embed/models/{e5,bm25,siglip2}.py` only import their heavy deps lazily inside `__init__`.)

- [ ] **Step 6: Docker build check (slow — allow up to 10 minutes, needs network)**

Run: `docker build -f embed/Dockerfile -t odyssey-embed:local .` from the repo root.
Expected: build succeeds (downloads torch-cpu + sentence-transformers + fastembed + transformers). If network/time doesn't allow this locally, note it as deferred — Step 5's pytest run is the required gate; this Docker build is a secondary confidence check.

- [ ] **Step 7: Stage and run repo-hygiene test**

Run:
```bash
git add embed tests/test_embed_api.py
source .venv/bin/activate && pytest tests/test_repo_hygiene.py -v
```
Expected: PASS — confirms every `.py` under `embed/` (including `embed/models/*.py`) is actually staged, not swallowed by `.gitignore`'s `/models/` pattern (that pattern is anchored to the repo root, so it does *not* match the nested `embed/models/` directory).

- [ ] **Step 8: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat: add embed service

Ported unmodified from santa-models develop@b03e6eb, minus the FastAPI
title rebrand and SANTA_MODELS_TOKEN->ODYSSEY_MODELS_TOKEN in the README.
One service, 4 kinds (dense/sparse/visual_image/visual_text), all bundled.
EOF
)"
```

---

### Task 3: `stt` service

**Files:**
- Create: `stt/stt_server.py`, `stt/Dockerfile`

**Interfaces:**
- Produces: image `odyssey-stt:local` (self-contained, no dependency on `common/`) — consumed by Task 6 (protocol check) and Task 7 (`docker-compose.yml`).

- [ ] **Step 1: Copy source files**

Run:
```bash
SRC=/Users/noblex-thebc-mac/Developer/noble-projects/santa/santa-models
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
mkdir -p stt
cp "$SRC/stt/stt_server.py" stt/stt_server.py
cp "$SRC/stt/Dockerfile" stt/Dockerfile
```

- [ ] **Step 2: Rename model dir default in `stt/stt_server.py`**

old_string:
```
MODEL_DIR = os.environ.get("STT_MODEL_DIR", "/models/santa-stt")
```
new_string:
```
MODEL_DIR = os.environ.get("STT_MODEL_DIR", "/models/odyssey-stt")
```

- [ ] **Step 3: Rename token env var in `stt/stt_server.py`**

old_string:
```
TOKEN = os.environ.get("SANTA_MODELS_TOKEN", "").strip()
```
new_string:
```
TOKEN = os.environ.get("ODYSSEY_MODELS_TOKEN", "").strip()
```

- [ ] **Step 4: Docker build + import check**

Run:
```bash
docker build -t odyssey-stt:local ./stt
docker run --rm odyssey-stt:local python -c "import stt_server; print('ok')"
```
Expected: build succeeds, prints `ok`. (This exercises the full dependency install — sherpa-onnx, numpy, websockets — and confirms the renamed module imports cleanly, without needing real model files: `stt_server.py`'s module-level code only defines constants/functions, the recognizer is built lazily.)

- [ ] **Step 5: Stage, verify, commit**

```bash
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
git add stt
source .venv/bin/activate && pytest tests/test_repo_hygiene.py -v
git commit -m "$(cat <<'EOF'
feat: add stt service

Ported unmodified from santa-models develop@b03e6eb, minus the model-dir
default path and SANTA_MODELS_TOKEN->ODYSSEY_MODELS_TOKEN rename.
EOF
)"
```

---

### Task 4: `speaker` service

**Files:**
- Create: `speaker/speaker_server.py`, `speaker/Dockerfile`

**Interfaces:**
- Produces: image `odyssey-speaker:local` (self-contained) — consumed by Task 7's `docker-compose.yml`.

- [ ] **Step 1: Copy source files**

Run:
```bash
SRC=/Users/noblex-thebc-mac/Developer/noble-projects/santa/santa-models
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
mkdir -p speaker
cp "$SRC/speaker/speaker_server.py" speaker/speaker_server.py
cp "$SRC/speaker/Dockerfile" speaker/Dockerfile
```

- [ ] **Step 2: Rename in docstring**

old_string:
```
  SANTA_MODELS_TOKEN   shared bearer token — enforced on /embed when set; /health open
```
new_string:
```
  ODYSSEY_MODELS_TOKEN shared bearer token — enforced on /embed when set; /health open
```

- [ ] **Step 3: Rename token env var**

old_string:
```
TOKEN = os.environ.get("SANTA_MODELS_TOKEN", "").strip()
```
new_string:
```
TOKEN = os.environ.get("ODYSSEY_MODELS_TOKEN", "").strip()
```

- [ ] **Step 4: Rename FastAPI title**

old_string:
```
app = FastAPI(title="Santa Speaker Service", version="1.0.0")
```
new_string:
```
app = FastAPI(title="Odyssey Speaker Service", version="1.0.0")
```

- [ ] **Step 5: Docker build + import check**

Run:
```bash
docker build -t odyssey-speaker:local ./speaker
docker run --rm odyssey-speaker:local python -c "import speaker_server; print('ok')"
```
Expected: build succeeds, prints `ok`. (`speaker_server.py`'s module-level code only builds the FastAPI `app` object; `_load()` — which needs a real model file or HF network access — only runs on the `startup` event, not on bare import.)

- [ ] **Step 6: Stage, verify, commit**

```bash
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
git add speaker
source .venv/bin/activate && pytest tests/test_repo_hygiene.py -v
git commit -m "$(cat <<'EOF'
feat: add speaker service

Ported unmodified from santa-models develop@b03e6eb, minus the
SANTA_MODELS_TOKEN->ODYSSEY_MODELS_TOKEN and FastAPI title rebrand.
EOF
)"
```

---

### Task 5: `tts` service

**Files:**
- Create: `tts/tts_server.py`, `tts/requirements.txt`, `tts/reference/presets.json`, `tts/tools/ccu_loadtest.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `tts_server.handler`, `tts_server.TOKEN`, `tts_server.TTS`/`DEFAULT_VOICE` (module globals stubbed by tests), `tts_server._process_request` — consumed by Task 6's protocol check. No Docker image (native/GPU, unchanged from santa-models).

- [ ] **Step 1: Copy source files**

Run:
```bash
SRC=/Users/noblex-thebc-mac/Developer/noble-projects/santa/santa-models
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
mkdir -p tts/reference tts/tools
cp "$SRC/tts/tts_server.py" tts/tts_server.py
cp "$SRC/tts/requirements.txt" tts/requirements.txt
cp "$SRC/tts/reference/presets.json" tts/reference/presets.json
cp "$SRC/tts/tools/ccu_loadtest.py" tts/tools/ccu_loadtest.py
```

- [ ] **Step 2: Rename token references in `tts/tts_server.py`**

First old_string/new_string (docstring):
old_string:
```
  SANTA_MODELS_TOKEN  shared bearer token; empty = auth off (loopback dev)
```
new_string:
```
  ODYSSEY_MODELS_TOKEN shared bearer token; empty = auth off (loopback dev)
```

Second old_string/new_string (code):
old_string:
```
TOKEN = os.environ.get("SANTA_MODELS_TOKEN", "").strip()
```
new_string:
```
TOKEN = os.environ.get("ODYSSEY_MODELS_TOKEN", "").strip()
```

Do **not** touch: `REPO = os.environ.get("TTS_BACKBONE_REPO", "NobleX-AI/santa-tts")`, the `TTS_BACKBONE_REPO ... (default NobleX-AI/santa-tts)` docstring line, the module docstring's first line (`"""Standalone streaming TTS microservice — VieNeu santa-tts (GPU, lmdeploy fast).`), or the two `log.info` lines mentioning `VieNeu santa-tts` — these describe the actual (unrenamed) HF backbone artifact.

- [ ] **Step 3: Rename in `tts/tools/ccu_loadtest.py`**

old_string 1 (module docstring, service name — not the backbone):
```
"""Ad-hoc CCU load-test cho TTS service (santa-tts, ws://localhost:8011/tts).
```
new_string 1:
```
"""Ad-hoc CCU load-test cho TTS service (odyssey-tts, ws://localhost:8011/tts).
```

old_string 2:
```
            if line.startswith("SANTA_MODELS_TOKEN="):
```
new_string 2:
```
            if line.startswith("ODYSSEY_MODELS_TOKEN="):
```

old_string 3:
```
    """Thứ tự: --token → env SANTA_MODELS_TOKEN → secrets.env → repo .env → ''."""
```
new_string 3:
```
    """Thứ tự: --token → env ODYSSEY_MODELS_TOKEN → secrets.env → repo .env → ''."""
```

old_string 4:
```
    if os.environ.get("SANTA_MODELS_TOKEN"):
        return os.environ["SANTA_MODELS_TOKEN"].strip()
```
new_string 4:
```
    if os.environ.get("ODYSSEY_MODELS_TOKEN"):
        return os.environ["ODYSSEY_MODELS_TOKEN"].strip()
```

old_string 5:
```
    for p in ("/home/thebc/.config/santa/secrets.env",
```
new_string 5:
```
    for p in ("/home/thebc/.config/odyssey/secrets.env",
```

- [ ] **Step 4: Rename provenance string in `tts/reference/presets.json`**

old_string:
```
    "source": "NobleX-AI santa reference"
```
new_string:
```
    "source": "NobleX-AI odyssey reference"
```

- [ ] **Step 5: Add `websockets` to dev extras in `pyproject.toml`**

old_string:
```
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
    "ruff>=0.5",
    "httpx2",
]
```
new_string:
```
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
    "ruff>=0.5",
    "httpx2",
    "websockets>=14",
]
```

- [ ] **Step 6: Reinstall and verify import**

Run:
```bash
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
source .venv/bin/activate
pip install -e ".[dev]" -q
python -c "import sys; sys.path.insert(0, 'tts'); import tts_server; print('ok')"
```
Expected: prints `ok`. (`tts_server.py`'s module-level imports are `numpy`, `websockets`, and a try/except-guarded `huggingface_hub` — `vieneu`/`lmdeploy` are only imported lazily inside `_load_tts()`, never at module scope.)

- [ ] **Step 7: Stage, verify, commit**

```bash
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
git add tts pyproject.toml
source .venv/bin/activate && pytest tests/test_repo_hygiene.py -v
git commit -m "$(cat <<'EOF'
feat: add tts service

Ported unmodified from santa-models develop@b03e6eb. SANTA_MODELS_TOKEN
renamed to ODYSSEY_MODELS_TOKEN; TTS_BACKBONE_REPO default and the two
log lines describing the santa-tts backbone artifact are intentionally
left unchanged (per design spec) since the HF weights haven't moved.
EOF
)"
```

---

### Task 6: stt + tts protocol conformance check

**Files:**
- Create: `tests/ws_protocol_test.py`

**Interfaces:**
- Consumes: `stt_server` module (Task 3), `tts_server` module (Task 5), image `odyssey-stt:local` (Task 3) as the run environment (already has `sherpa-onnx`+`websockets` installed).

- [ ] **Step 1: Copy the test file**

Run:
```bash
SRC=/Users/noblex-thebc-mac/Developer/noble-projects/santa/santa-models
cp "$SRC/tests/ws_protocol_test.py" /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models/tests/ws_protocol_test.py
```

- [ ] **Step 2: Rename image reference in its docstring**

old_string:
```
Runs the real handlers with STUBBED engines (no GPU / no model / no vieneu / no
sherpa model files) against a real websockets client, asserting the exact frames
in docs/remote_stt_tts_spect.md. Plain-asyncio (no pytest dep) so it runs inside
the santa-stt image.
```
new_string:
```
Runs the real handlers with STUBBED engines (no GPU / no model / no vieneu / no
sherpa model files) against a real websockets client, asserting the exact frames
in docs/remote_stt_tts_spect.md. Plain-asyncio (no pytest dep) so it runs inside
the odyssey-stt image.
```

- [ ] **Step 3: Ensure the stt image is built**

Run: `docker build -t odyssey-stt:local ./stt` (idempotent if Task 3 already built it).

- [ ] **Step 4: Run the combined protocol check inside the stt image**

Run:
```bash
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
CID=$(docker create odyssey-stt:local sleep infinity)
docker start "$CID"
docker cp tts/tts_server.py "$CID":/app/tts_server.py
docker cp tests/ws_protocol_test.py "$CID":/app/ws_protocol_test.py
docker exec "$CID" python /app/ws_protocol_test.py
docker rm -f "$CID"
```
Expected: every line prints `[PASS]`, final line reads `N passed, 0 failed` (9 checks across TTS + STT), exit code 0. This exercises the exact wire contract in `docs/remote_stt_tts_spect.md` — synth/end frames, empty-text short-circuit, default voice, barge-in abort, auth reject/accept, `/health`, STT partial/final frames, `eos` closing the session, bad-auth close 1008 — with stubbed engines (no GPU, no real sherpa model files needed).

- [ ] **Step 5: Stage, verify, commit**

```bash
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
git add tests/ws_protocol_test.py
source .venv/bin/activate && pytest tests/test_repo_hygiene.py -v
git commit -m "$(cat <<'EOF'
test: add stt/tts protocol conformance check

Ported unmodified from santa-models develop@b03e6eb except the image
name in its own docstring (santa-stt -> odyssey-stt).
EOF
)"
```

---

### Task 7: `docker-compose.yml`, docs, README — final integration

**Files:**
- Create: `docker-compose.yml`, `docs/remote_stt_tts_spect.md`, `README.md`

**Interfaces:**
- Consumes: images `odyssey-embed:local`, `odyssey-stt:local`, `odyssey-speaker:local` (Tasks 2-4).

- [ ] **Step 1: Copy the STT/TTS wire-contract spec (verbatim, no renames — verified zero santa references)**

Run:
```bash
SRC=/Users/noblex-thebc-mac/Developer/noble-projects/santa/santa-models
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
mkdir -p docs
cp "$SRC/docs/remote_stt_tts_spect.md" docs/remote_stt_tts_spect.md
```

- [ ] **Step 2: Write `docker-compose.yml`**

```yaml
# odyssey-models — shared model microservices (CPU), decoupled from the agents.
#
#   embed   :8013  e5-large fp32 (1024d) + BM25 sparse + SigLIP2 image/text tower
#   stt     :8012  sherpa Zipformer  — streaming STT over WebSocket
#   speaker :8014  sherpa CAM++      — speaker embedding over HTTP
#
# TTS (vieneu, GPU :8011) stays a NATIVE service (tts-odyssey) — GPU-in-Docker is
# avoided, so it is NOT in this compose.
# These CPU services are LAN-visible (0.0.0.0) so other devs can use them; access is
# gated by a shared bearer token (ODYSSEY_MODELS_TOKEN from .env — health endpoints
# stay open). Models cache to a named volume.

services:
  # Nhà máy vector: dense (e5) · sparse (BM25) · visual_image/visual_text (SigLIP2).
  # Build context là REPO ROOT vì image cần common/.
  embed:
    build:
      context: .
      dockerfile: embed/Dockerfile
    image: odyssey-embed:local
    ports:
      - "0.0.0.0:8013:8013"
    environment:
      # PHẢI có `:-default`. `${FOO}` với biến chưa đặt truyền vào container `FOO=` (rỗng,
      # KHÔNG phải unset) — `settings.env()` thấy chuỗi rỗng là "đã đặt" nên default trong
      # embed/settings.py bị đè mất, và model name rỗng thì service chết lúc nạp model.
      - EMBED_DENSE_MODEL=${EMBED_DENSE_MODEL:-intfloat/multilingual-e5-large}
      - EMBED_SPARSE_MODEL=${EMBED_SPARSE_MODEL:-Qdrant/bm25}
      - EMBED_VISUAL_MODEL=${EMBED_VISUAL_MODEL:-google/siglip2-base-patch16-256}
      - EMBED_DEVICE=${EMBED_DEVICE:-cpu}
      - EMBED_THREADS=4
      - EMBED_WARMUP=${EMBED_WARMUP:-dense}
      - HF_TOKEN=${HF_TOKEN:-}
      - ODYSSEY_MODELS_TOKEN=${ODYSSEY_MODELS_TOKEN}
    volumes:
      - model_cache:/root/.cache
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request,json,sys; d=json.load(urllib.request.urlopen('http://127.0.0.1:8013/health')); sys.exit(0 if d['status']=='ok' else 1)\""]
      interval: 15s
      timeout: 5s
      retries: 10
      start_period: 600s

  # Streaming STT — standalone sherpa-onnx Zipformer over WebSocket (CPU).
  # Self-contained (own sherpa-onnx, no agent image). Any service can use it by
  # streaming PCM16/16k and reading partial/final JSON. LAN-visible.
  stt:
    build:
      context: ./stt
    image: odyssey-stt:local
    ports:
      - "0.0.0.0:8012:8012"
    environment:
      - STT_MODEL_DIR=/models/odyssey-stt
      - STT_MODEL_QUANTIZE=false
      - STT_PRESERVE_CASE=false   # lowercase + sentence-case
      - STT_SAMPLE_RATE=16000
      - STT_WS_PORT=8012
      - ODYSSEY_MODELS_TOKEN=${ODYSSEY_MODELS_TOKEN}
    volumes:
      - ./models:/models:ro       # odyssey-models owns its model data (not the agent repo)
    restart: unless-stopped

  # Speaker embedding — standalone sherpa-onnx CAM++ over HTTP (CPU). Self-contained
  # (own sherpa-onnx, no agent image). Workers reach it via SPEAKER_REMOTE_URL:
  # POST /embed {"audio_b64": ...} → {"embedding": [...]}. The single CAM++ ONNX
  # auto-downloads from HF to the speaker_cache volume on first boot.
  speaker:
    build:
      context: ./speaker
    image: odyssey-speaker:local
    ports:
      - "0.0.0.0:8014:8014"
    environment:
      - SPEAKER_MODEL_DIR=/models/speaker
      - SPEAKER_MODEL_NAME=3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx
      - SPEAKER_HF_REPO=csukuangfj/speaker-embedding-models
      - SPEAKER_HF_REVISION=main
      - SPEAKER_NUM_THREADS=2
      - SPEAKER_SAMPLE_RATE=16000
      - SPEAKER_SERVICE_PORT=8014
      - HF_TOKEN=${HF_TOKEN:-}
      - ODYSSEY_MODELS_TOKEN=${ODYSSEY_MODELS_TOKEN}
    volumes:
      - speaker_cache:/models       # single CAM++ ONNX auto-pulled from HF on first boot
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request,json,sys; d=json.load(urllib.request.urlopen('http://127.0.0.1:8014/health')); sys.exit(0 if d['status']=='ok' else 1)\""]
      interval: 15s
      timeout: 5s
      retries: 10
      start_period: 60s

volumes:
  model_cache:
  speaker_cache:
```

- [ ] **Step 3: Write `README.md`**

```markdown
# odyssey-models

Standalone, reusable **model microservices** for the Odyssey platform —
decoupled from any agent. Any service consumes them over the network like a
cloud vendor (Soniox/ElevenLabs): just a URL + protocol, no shared code.

## Services

| Service | Port | What | Notes |
|---|---|---|---|
| `embed` | 8013 | Nhà máy vector: e5-large (dense, 1024d) + BM25 (sparse) + SigLIP2 (visual, 768d) | `POST /embed` với `side: index\|query` (bắt buộc — quên là 422, không lệch âm thầm). 4 `kind`: `dense` · `sparse` · `visual_image`/`visual_text`. Xem [embed/README.md](embed/README.md). |
| `stt`   | 8012 | Streaming STT — sherpa-onnx Zipformer (CPU), WebSocket | `ws://host:8012/stt` — client streams PCM16/16k binary frames → `{"type":"partial"\|"final","text"}`; ends the session with `{"type":"eos"}`. Server-side endpointing. |
| `speaker` | 8014 | Speaker embedding — sherpa-onnx CAM++ (CPU), HTTP | `POST http://host:8014/embed` `{audio_b64}` (base64 PCM16/16k) → `{"embedding": [...]}` (empty list = unusable audio). `GET /health` → 200. |
| `tts`   | 8011 | VieNeu santa-tts backbone (lmdeploy fast, **GPU**), streaming PCM over WebSocket | `ws://host:8011/tts` — one WS per clause: client sends `{"type":"synthesize","text",…}` → binary PCM16 @ 24k → `{"type":"end"}`. `GET /health` → 200. |

Both STT and TTS speak the **`remote` WebSocket contract** in
[docs/remote_stt_tts_spect.md](docs/remote_stt_tts_spect.md) (source of truth).

## Run

**embed + stt + speaker** (CPU) run as Docker containers:
```bash
docker compose up -d            # builds + starts embed + stt + speaker
curl localhost:8013/health      # embed   — {status, device, models, kinds, loaded}
curl localhost:8014/health      # speaker
```

Build context of `embed` is the **repo root** (not `embed/`), because the image
needs `common/`. Build by hand: `docker build -f embed/Dockerfile .`

**tts** (GPU) runs **native** (not Docker — avoids GPU-in-container issues), from
its own venv via a systemd service:
```bash
cd tts && uv venv -p 3.11 .venv && uv pip install --python .venv -r requirements.txt
# then run tts_server.py under systemd, with HF_TOKEN set
```

All CPU services bind **`0.0.0.0`** (LAN-visible, not loopback-only) — see
`docker-compose.yml`. Access is gated by a shared bearer token
(`ODYSSEY_MODELS_TOKEN` from `.env`); health endpoints stay open.

Test:
```bash
pip install -e ".[dev]"
pytest -q
ruff check .
```

## Models (not in git)

Model weights live under `models/` (gitignored) and are bind-mounted:
- `embed`: downloads e5-large + SigLIP2 to the `model_cache` volume on first boot.
- `stt`: expects the sherpa Zipformer at `models/odyssey-stt/`
  (`encoder/decoder/joiner-*.onnx` + `tokens.txt`).
- `speaker`: single CAM++ ONNX auto-pulled from HF to the `speaker_cache` volume.

## View logs

All services log with icon-prefixed lines for easy scanning (🚀 boot · 📦 load ·
✅ ready · 🔌/👋 session open/close · 🔒 auth reject · 📝 STT final · 🔊/🎵 TTS
synth+ttfb · 🧑 speaker embed · ⚠️/❌ warn/error).

**embed / stt / speaker** (Docker) — follow with `docker compose logs`:
```bash
docker compose logs -f embed      # e5-large + BM25 + SigLIP2 embeddings
docker compose logs -f stt        # 📝 finals (✏️ partials only at DEBUG level)
docker compose logs -f speaker    # 🧑 per-embed size + dim + latency
docker compose logs -f            # all services at once
docker compose logs --tail=100 stt   # last 100 lines, no follow
```

**tts** (native systemd, not Docker) — follow with `journalctl`:
```bash
journalctl --user -u tts-odyssey -f            # live (🔊 start / 🎵 done + ttfb)
journalctl --user -u tts-odyssey --since "10 min ago"
```
```

- [ ] **Step 4: Validate the compose file**

Run: `docker compose config -q`
Expected: exit code 0, no output (validates YAML structure and `${VAR}` interpolation without starting any container — booting `embed`/`stt` for real needs actual model files under `./models/`, which this dev environment doesn't have).

- [ ] **Step 5: Run the full test suite and linter**

Run:
```bash
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
source .venv/bin/activate
pytest -q
ruff check .
```
Expected: all tests pass (`test_auth`, `test_logging`, `test_registry`, `test_settings`, `test_embed_api`, `test_repo_hygiene`); `ruff check .` reports no errors.

- [ ] **Step 6: Stage, verify, commit**

```bash
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-models
git add docker-compose.yml docs/remote_stt_tts_spect.md README.md
source .venv/bin/activate && pytest tests/test_repo_hygiene.py -v
git commit -m "$(cat <<'EOF'
docs: add docker-compose, README, and stt/tts protocol spec

Completes the odyssey-models port from santa-models develop@b03e6eb:
embed + stt + speaker wired into docker-compose.yml (tts stays native/
GPU, unchanged); README trimmed to these 4 services, dropping the KB
stack, Cloudflare tunnel section, and hardcoded deploy-box IP.
EOF
)"
```
