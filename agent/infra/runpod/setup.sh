#!/usr/bin/env bash
# setup.sh — Single-shot RunPod bootstrap (Noble Voice Agent).
#
# One command, full lifecycle: apt → uv → vLLM → model → patches → env →
# services → health → prints LiveKit URL + room token to copy-paste.
#
# Single canonical bootstrap script (replaces 3 legacy split scripts).
#
# Usage:
#   bash infra/runpod/setup.sh                 # full bootstrap (default)
#   bash infra/runpod/setup.sh --check         # dry-run, verify only
#   bash infra/runpod/setup.sh --only env      # run a single stage
#   bash infra/runpod/setup.sh --from model    # resume from stage onward
#   bash infra/runpod/setup.sh --skip model    # skip stage(s), CSV
#   bash infra/runpod/setup.sh --no-model      # use cloud LLM (skip vLLM)
#   bash infra/runpod/setup.sh --no-services   # provision only, don't start
#   bash infra/runpod/setup.sh --clean         # wipe /opt/vllm-venv + force rebuild
#                                                (auto-detect broken venv anyway,
#                                                 use --clean only to force)
#
# Env overrides:
#   HF_MODEL_REPO=Qwen/Qwen3.6-35B-A3B
#   MODEL_DIR=/workspace/$(basename HF_MODEL_REPO)
#   ROOM=smoke                                 # default LiveKit room name
#
# All output is teed to /workspace/logs/setup-YYYYMMDD-HHMMSS.log.
set -euo pipefail

# ── Paths ──────────────────────────────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
LOG_DIR="${LOG_DIR:-/workspace/logs}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/setup-$(date +%Y%m%d-%H%M%S).log"
STATE_FILE="$REPO_ROOT/.runpod-setup-state"

VLLM_VENV="${VLLM_VENV:-/opt/vllm-venv}"
VLLM_LOG="/workspace/vllm.log"
AGENT_LOG="/workspace/agent.log"

# Safe .env parser — bash `source` is fragile when values contain spaces
# (e.g. `KEY=hello world` would try to run `world` as a command). This loop
# strips comments, validates key syntax, and exports raw values verbatim.
load_dotenv() {
    local env_file="$1" line key val
    [[ -f "$env_file" ]] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        line="${line#"${line%%[![:space:]]*}"}"
        [[ -z "$line" || "$line" == \#* ]] && continue
        [[ "$line" != *"="* ]] && continue
        key="${line%%=*}"
        val="${line#*=}"
        key="${key//[[:space:]]/}"
        [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
        if [[ "$val" =~ ^\".*\"$ ]]; then val="${val:1:${#val}-2}"
        elif [[ "$val" =~ ^\'.*\'$ ]]; then val="${val:1:${#val}-2}"; fi
        export "$key=$val"
    done < "$env_file"
}
load_dotenv "$REPO_ROOT/.env"

# Defaults applied AFTER .env load so user can override via .env or env-inline.
HF_MODEL_REPO="${HF_MODEL_REPO:-Qwen/Qwen3.6-35B-A3B}"
MODEL_DIR="${MODEL_DIR:-/workspace/$(basename "$HF_MODEL_REPO")}"
NOBLE_DATA_HF_REPO="${NOBLE_DATA_HF_REPO:-NMCxyz/flat_store}"
ROOM="${ROOM:-smoke}"
export HF_MODEL_REPO MODEL_DIR NOBLE_DATA_HF_REPO

# Prepend vllm-venv bin to PATH so `hf` CLI + huggingface_hub Python are
# available to subsequent stages (model download, data sync) even when
# system Python doesn't have them.
[[ -d "$VLLM_VENV/bin" ]] && export PATH="$VLLM_VENV/bin:$PATH"

# ── Flags ──────────────────────────────────────────────────────────────────
ALL_STAGES=(preflight system uv vllm_pkg agent_venv data model embeddings patches paths env migrate services verify connect)
ONLY=""; FROM=""; SKIP=""; CHECK=0; NO_MODEL=0; NO_SERVICES=0; CLEAN=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check) CHECK=1; shift;;
        --only) ONLY="$2"; shift 2;;
        --from) FROM="$2"; shift 2;;
        --skip) SKIP="$2"; shift 2;;
        --no-model) NO_MODEL=1; shift;;
        --no-services) NO_SERVICES=1; shift;;
        --clean) CLEAN=1; shift;;   # wipe vllm-venv + state, force rebuild
        --help|-h) sed -n '2,28p' "$0" | sed 's|^# ||; s|^#$||'; exit 0;;
        *) echo "Unknown arg: $1 (use --help)" >&2; exit 1;;
    esac
done

# Tee all stdout + stderr from this point onward into LOG_FILE.
exec > >(tee -a "$LOG_FILE") 2>&1

# ── Output helpers (no color in log file via tput stripping when non-tty) ──
if [[ -t 1 ]]; then
    G='\033[32m'; Y='\033[33m'; R='\033[31m'; B='\033[34m'; C='\033[36m'; M='\033[35m'; D='\033[2m'; X='\033[0m'
else
    G=''; Y=''; R=''; B=''; C=''; M=''; D=''; X=''
fi
log()  { printf "${G}▶${X} %s\n" "$*"; }
warn() { printf "${Y}⚠${X} %s\n" "$*"; }
fail() { printf "${R}✗${X} %s\n" "$*" >&2; exit 1; }
ok()   { printf "${G}✓${X} %s\n" "$*"; }
skip() { printf "${D}—${X} ${D}%s${X}\n" "$*"; }
hdr()  { printf "\n${B}━━━ %s ━━━${X}\n" "$*"; }

state_set() {
    mkdir -p "$(dirname "$STATE_FILE")"; touch "$STATE_FILE"
    grep -v "^$1=" "$STATE_FILE" > "$STATE_FILE.tmp" || true
    echo "$1=done" >> "$STATE_FILE.tmp"
    mv "$STATE_FILE.tmp" "$STATE_FILE"
}

should_run() {
    local stage="$1"
    [[ ",$SKIP," == *",$stage,"* ]] && { skip "stage:$stage (--skip)"; return 1; }
    [[ -n "$ONLY" && "$ONLY" != "$stage" ]] && return 1
    if [[ -n "$FROM" ]]; then
        local found=0
        for s in "${ALL_STAGES[@]}"; do
            [[ "$s" == "$FROM" ]] && found=1
            [[ "$s" == "$stage" && $found -eq 1 ]] && return 0
        done
        return 1
    fi
    [[ "$NO_MODEL" -eq 1 && ( "$stage" == "vllm_pkg" || "$stage" == "model" ) ]] && { skip "stage:$stage (--no-model)"; return 1; }
    [[ "$NO_SERVICES" -eq 1 && ( "$stage" == "services" || "$stage" == "verify" || "$stage" == "connect" ) ]] && { skip "stage:$stage (--no-services)"; return 1; }
    return 0
}

# ═══════════════════════════════════════════════════════════════════════════
# 0. PREFLIGHT — GPU + disk + branch
# ═══════════════════════════════════════════════════════════════════════════
stage_preflight() {
    hdr "0. preflight"
    log "Repo: $REPO_ROOT"
    log "Branch: $(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || echo '(no git)')"
    log "Commit: $(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo '(no git)')"
    log "Log file: $LOG_FILE"

    if command -v nvidia-smi &>/dev/null; then
        ok "GPU detected:"
        nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader | sed 's/^/    /'
        local mem_total
        mem_total=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || true)
        if [[ "$mem_total" -lt 24000 ]]; then
            warn "GPU memory ${mem_total}MiB < 24GB — Qwen3.6-35B-A3B may not fit. Try: HF_MODEL_REPO=Qwen/Qwen2.5-14B-Instruct"
        fi
    else
        warn "No GPU — vLLM will be skipped (cloud LLM only)"
        NO_MODEL=1
    fi

    local disk_free
    disk_free=$(df -BG /workspace 2>/dev/null | awk 'NR==2 {print $4}' | tr -d 'G')
    [[ -n "$disk_free" && "$disk_free" -lt 100 ]] && warn "Disk free ${disk_free}GB < 100GB — model download may fail" || ok "Disk free: ${disk_free:-?}GB"

    [[ -f "$REPO_ROOT/pyproject.toml" ]] || fail "Not in repo root (no pyproject.toml)"
    state_set preflight
}

# ═══════════════════════════════════════════════════════════════════════════
# 1. SYSTEM — apt packages
# ═══════════════════════════════════════════════════════════════════════════
stage_system() {
    hdr "1. system packages"
    if command -v tmux &>/dev/null && command -v redis-server &>/dev/null && command -v ffmpeg &>/dev/null && command -v git-lfs &>/dev/null; then
        ok "system packages already installed"
        return 0
    fi
    [[ $CHECK -eq 1 ]] && { skip "(check mode)"; return 0; }
    log "Installing tmux + redis + ffmpeg + python3.11..."
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        tmux git git-lfs rsync curl jq bc \
        pciutils iproute2 net-tools iputils-ping dnsutils \
        python3.11 python3.11-venv python3-pip \
        redis-server ffmpeg libsndfile1 build-essential
    git lfs install --system 2>/dev/null || true
    state_set system
}

# ═══════════════════════════════════════════════════════════════════════════
# 2. UV — install uv (10× faster pip)
# ═══════════════════════════════════════════════════════════════════════════
stage_uv() {
    hdr "2. uv (fast Python package manager)"
    if command -v uv &>/dev/null; then
        ok "uv $(uv --version)"
    else
        [[ $CHECK -eq 1 ]] && { skip "(check)"; return 0; }
        log "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh -s -- --quiet
    fi
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    command -v uv &>/dev/null || fail "uv not on PATH after install — source ~/.bashrc and re-run"
    state_set uv
}

# ═══════════════════════════════════════════════════════════════════════════
# 3. VLLM_PKG — dedicated venv at $VLLM_VENV (inherits CUDA torch via
# --system-site-packages, avoids PEP 668 EXTERNALLY-MANAGED on Ubuntu 24.04)
# ═══════════════════════════════════════════════════════════════════════════
stage_vllm_pkg() {
    hdr "3. vLLM venv ($VLLM_VENV)"
    local VPY="$VLLM_VENV/bin/python"

    # Auto-heal: if existing venv exists, run a CUDA smoke test. This catches:
    #   - CUDA driver mismatch (cu13 wheels on cu12.8 driver → "driver too old")
    #   - Broken/partial installs from interrupted setups
    #   - Version constraint changes (e.g. requirements-pod.txt pinned vllm<0.20)
    # Failure → wipe venv + rebuild from requirements-pod.txt.
    if [[ "$CLEAN" -eq 1 ]] && [[ -d "$VLLM_VENV" ]]; then
        warn "--clean: removing $VLLM_VENV"
        rm -rf "$VLLM_VENV"
    elif [[ -x "$VPY" ]]; then
        if "$VPY" -c "
import sys
try:
    import vllm
    import torch
    # Trigger driver-level CUDA init (catches cu13/cu128 mismatch).
    if torch.cuda.is_available():
        torch.tensor([1.0]).cuda()
    # Validate vllm version meets requirements-pod.txt pin (>=0.17, <0.20).
    v = tuple(int(x) for x in vllm.__version__.split('.')[:2])
    assert v >= (0,17) and v < (0,20), f'vllm {vllm.__version__} outside pinned range'
    print(f'vLLM {vllm.__version__} · torch {torch.__version__} · CUDA {torch.version.cuda}')
    sys.exit(0)
except Exception as e:
    print(f'SMOKE_FAIL: {e}', file=sys.stderr)
    sys.exit(1)
" 2>/tmp/vllm-smoke.err; then
            ok "$(cat /tmp/vllm-smoke.err 2>/dev/null; "$VPY" -c "import vllm,torch; print(f'vLLM {vllm.__version__} · torch {torch.__version__} · CUDA {torch.version.cuda}')")"
            export PATH="$VLLM_VENV/bin:$PATH"
            state_set vllm_pkg; return 0
        else
            warn "Existing $VLLM_VENV broken: $(tr '\n' ' ' </tmp/vllm-smoke.err 2>/dev/null | head -c 200)"
            warn "Wiping + rebuilding..."
            rm -rf "$VLLM_VENV"
        fi
    fi
    [[ $CHECK -eq 1 ]] && { skip "(check)"; return 0; }

    if [[ ! -x "$VPY" ]]; then
        log "Creating $VLLM_VENV (inherits system CUDA torch)..."
        uv venv --system-site-packages --python python3 "$VLLM_VENV"
    fi
    # UV_TORCH_BACKEND tells uv to pick CUDA 12.8 torch wheels (matches RunPod
    # cu128 templates). Without this, vllm pulls cu13 + nvidia-cu13 → driver
    # mismatch ("driver too old (found version 12080)") on CUDA 12.8 pods.
    local TORCH_BACKEND="${UV_TORCH_BACKEND:-cu128}"
    log "Installing pod deps (UV_TORCH_BACKEND=$TORCH_BACKEND) from infra/runpod/requirements-pod.txt..."
    UV_TORCH_BACKEND="$TORCH_BACKEND" \
        uv pip install --python "$VPY" --reinstall \
            -r "$REPO_ROOT/infra/runpod/requirements-pod.txt"
    "$VPY" -c "import vllm, torch; print(f'  vLLM: {vllm.__version__} · torch: {torch.__version__} · CUDA: {torch.version.cuda}')"
    # Make hf CLI + huggingface_hub Python available to later stages
    export PATH="$VLLM_VENV/bin:$PATH"
    state_set vllm_pkg
}

# ═══════════════════════════════════════════════════════════════════════════
# 4. AGENT_VENV — uv sync (creates .venv from pyproject + lock)
# ═══════════════════════════════════════════════════════════════════════════
stage_agent_venv() {
    hdr "4. agent venv (uv sync)"
    if [[ -f "$REPO_ROOT/.venv/bin/noble-agent" ]]; then
        ok ".venv exists; refreshing in case code changed"
    fi
    [[ $CHECK -eq 1 ]] && { skip "(check)"; return 0; }

    # uv sync: respects uv.lock, idempotent, cleans removed deps.
    # CPU torch comes via lockfile; vLLM uses system torch (CUDA).
    log "Running uv sync --extra stt-soniox --extra tts-elevenlabs..."
    cd "$REPO_ROOT"
    uv sync --extra stt-soniox --extra tts-elevenlabs --no-progress

    # Sanity: smoke-test imports
    if ! "$REPO_ROOT/.venv/bin/python" -c "from noble_agent.config import settings; from noble_agent.agent.llm.streaming import StreamingLLM; from noble_agent.agent.rag.flat_store import FlatStore; print('  imports ok — rag=', settings.noble_rag_backend)" 2>&1 | tail -3; then
        fail "noble_agent imports failed after uv sync"
    fi
    ok "agent venv ready (.venv)"
    state_set agent_venv
}

# ═══════════════════════════════════════════════════════════════════════════
# 4.5 DATA — RAG/flat_store/faq_cache (gitignored, must come from somewhere)
# ═══════════════════════════════════════════════════════════════════════════
stage_data() {
    hdr "4.5 data sync (rag + flat_store + faq_cache)"
    local missing=()
    for d in rag flat_store faq_cache; do
        [[ -d "$REPO_ROOT/data/$d" ]] && [[ -n "$(ls -A "$REPO_ROOT/data/$d" 2>/dev/null)" ]] || missing+=("$d")
    done
    if [[ ${#missing[@]} -eq 0 ]]; then
        ok "data dirs present: rag, flat_store, faq_cache"
        bash "$REPO_ROOT/scripts/data_sync.sh" check >/dev/null && ok "data integrity OK"
        state_set data; return 0
    fi
    [[ $CHECK -eq 1 ]] && { warn "missing: ${missing[*]} — would attempt hf-download"; return 0; }

    if [[ -n "${NOBLE_DATA_HF_REPO:-}" ]]; then
        if [[ -z "${HF_TOKEN:-}" ]]; then
            warn "data missing AND HF_TOKEN empty in .env"
            warn "Edit: nano .env → set HF_TOKEN=hf_xxx (https://huggingface.co/settings/tokens)"
            warn "Then re-run: bash infra/runpod/setup.sh --from data"
            return 0
        fi
        log "missing ${missing[*]} — pulling from HF Dataset $NOBLE_DATA_HF_REPO"
        bash "$REPO_ROOT/scripts/data_sync.sh" hf-download "$NOBLE_DATA_HF_REPO" || \
            fail "hf-download failed — see stderr above. Common: HF_TOKEN expired/revoked."
    else
        warn "data missing: ${missing[*]}"
        warn "Pick ONE:"
        warn "  (A) Mac: bash scripts/data_sync.sh push <pod_ip> <ssh_port>"
        warn "  (B) NOBLE_DATA_HF_REPO=NMCxyz/flat_store HF_TOKEN=<token> bash infra/runpod/setup.sh --from data"
        warn "  (C) bash scripts/data_sync.sh rebuild   # ~30 phút CPU encode"
        warn "Continuing — agent sẽ chạy nhưng noble_search trả empty"
    fi
    state_set data
}

# ═══════════════════════════════════════════════════════════════════════════
# 5. MODEL — hf download
# ═══════════════════════════════════════════════════════════════════════════
stage_model() {
    hdr "5. model ($HF_MODEL_REPO → $MODEL_DIR)"
    if [[ -d "$MODEL_DIR" && -f "$MODEL_DIR/config.json" ]]; then
        local first_st
        first_st=$(ls "$MODEL_DIR"/*.safetensors 2>/dev/null | head -1 || true)
        if [[ -n "$first_st" ]]; then
            local sz
            sz=$(stat -c%s "$first_st" 2>/dev/null || stat -f%z "$first_st" 2>/dev/null || echo 0)
            if [[ "$sz" -gt 1000000 ]]; then
                ok "model present ($(du -sh "$MODEL_DIR" | cut -f1))"
                state_set model; return 0
            fi
            warn "safetensors look like LFS pointers (${sz}b) — re-downloading"
        fi
    fi
    [[ $CHECK -eq 1 ]] && { warn "would download ~70GB"; return 0; }

    log "Downloading $HF_MODEL_REPO (10-15min)..."
    export HF_HUB_ENABLE_HF_TRANSFER=1
    # Resolve a Python that has huggingface_hub (vllm-venv has it from requirements-pod.txt)
    local HFCLI="$VLLM_VENV/bin/hf"
    local HFPY="$VLLM_VENV/bin/python"
    [[ -x "$HFCLI" ]] || HFCLI="$(command -v hf 2>/dev/null || true)"
    [[ -x "$HFPY"  ]] || HFPY="$REPO_ROOT/.venv/bin/python"
    if [[ -n "$HFCLI" && -x "$HFCLI" ]]; then
        "$HFCLI" download "$HF_MODEL_REPO" --local-dir "$MODEL_DIR" || fail "hf download failed (HF_TOKEN missing/invalid?)"
    else
        "$HFPY" -c "from huggingface_hub import snapshot_download; snapshot_download('$HF_MODEL_REPO', local_dir='$MODEL_DIR')"
    fi
    [[ -f "$MODEL_DIR/config.json" ]] || fail "model download incomplete"
    ok "model: $MODEL_DIR ($(du -sh "$MODEL_DIR" | cut -f1))"
    state_set model
}

# ═══════════════════════════════════════════════════════════════════════════
# 6. EMBEDDINGS — pre-cache fastembed e5-large ONNX (~500MB)
# ═══════════════════════════════════════════════════════════════════════════
stage_embeddings() {
    hdr "6. e5-large ONNX cache"
    local cache="$HOME/.cache/fastembed/models--qdrant--multilingual-e5-large-onnx"
    if find "$cache" -name "model.onnx" -size +100M 2>/dev/null | grep -q .; then
        ok "e5-large ONNX cached"
        state_set embeddings; return 0
    fi
    [[ $CHECK -eq 1 ]] && { warn "would download ~500MB"; return 0; }
    rm -rf "$cache" 2>/dev/null || true
    log "Caching e5-large ONNX (~500MB)..."
    "$REPO_ROOT/.venv/bin/python" -c "from fastembed import TextEmbedding; m=TextEmbedding('intfloat/multilingual-e5-large'); list(m.embed(['test'])); print('  ✓ cached')" \
        || fail "e5-large download failed (no internet? HF rate-limit?)"
    state_set embeddings
}

# ═══════════════════════════════════════════════════════════════════════════
# 7. PATCHES — vLLM compat fixes (idempotent)
# ═══════════════════════════════════════════════════════════════════════════
stage_patches() {
    hdr "7. code patches (vLLM compat)"

    # Patch A: streaming.py — sanitize mid-conv system msgs for vLLM
    local sp="$REPO_ROOT/src/noble_agent/agent/llm/streaming.py"
    if grep -q "Strict-server sanitization" "$sp" 2>/dev/null; then
        ok "streaming.py: sanitizer applied"
    else
        log "Patching streaming.py..."
        [[ $CHECK -eq 1 ]] || REPO_ROOT="$REPO_ROOT" python3 <<'PYEOF'
import os
p = os.environ['REPO_ROOT'] + '/src/noble_agent/agent/llm/streaming.py'
s = open(p).read()
OLD = '        # Gemini-specific sanitization (known OpenAI-compat quirks)\n        if provider_name == "gemini":\n            messages = self._sanitize_messages_for_gemini(messages)\n            tools = self._sanitize_tools_for_gemini(tools)'
NEW = '        # Strict-server sanitization: Gemini + vLLM (Qwen3-coder) reject mid-conv system msgs\n        _b = str(settings.openai_base_url or "")\n        _vllm_local = provider_name == "openai" and ("localhost" in _b or "127.0.0.1" in _b)\n        if provider_name == "gemini" or _vllm_local:\n            messages = self._sanitize_messages_for_gemini(messages)\n            tools = self._sanitize_tools_for_gemini(tools)'
if OLD in s: open(p,'w').write(s.replace(OLD,NEW)); print("  patched")
else: print("  WARN: marker not found (already patched or branch differs)")
PYEOF
    fi

    # Patch B: tool_hint.py — separate embedding endpoint
    local th="$REPO_ROOT/src/noble_agent/agent/llm/tool_hint.py"
    if grep -q "OPENAI_EMBEDDING_API_KEY" "$th" 2>/dev/null; then
        ok "tool_hint.py: embedding endpoint applied"
    else
        log "Patching tool_hint.py..."
        [[ $CHECK -eq 1 ]] || REPO_ROOT="$REPO_ROOT" python3 <<'PYEOF'
import os
p = os.environ['REPO_ROOT'] + '/src/noble_agent/agent/llm/tool_hint.py'
s = open(p).read()
OLD = '''            if not settings.openai_api_key:
                logger.info("[ToolHint] OpenAI API key not set — hints disabled")
                return None
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                timeout=8,
            )'''
NEW = '''            import os as _os
            emb_key = _os.getenv("OPENAI_EMBEDDING_API_KEY") or settings.openai_api_key
            emb_base = _os.getenv("OPENAI_EMBEDDING_BASE_URL") or "https://api.openai.com/v1"
            if not emb_key or emb_key == "dummy":
                logger.info("[ToolHint] No embedding API key — hints disabled")
                return None
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=emb_key, base_url=emb_base, timeout=8)'''
if OLD in s: open(p,'w').write(s.replace(OLD,NEW)); print("  patched")
else: print("  WARN: marker not found")
PYEOF
    fi
    state_set patches
}

# ═══════════════════════════════════════════════════════════════════════════
# 8. PATHS — FAQ source symlinks
# ═══════════════════════════════════════════════════════════════════════════
stage_paths() {
    hdr "8. data paths (FAQ symlinks)"
    local src="$REPO_ROOT/data/faq/source"
    if [[ -d "$src" ]] && find "$src" -name "*_faq.json" -type l 2>/dev/null | grep -q .; then
        ok "FAQ source symlinks present"
        state_set paths; return 0
    fi
    if [[ ! -d "$REPO_ROOT/data/faq" ]]; then
        warn "data/faq/ missing — git clone chưa complete? Hoặc xem 'bash scripts/data_sync.sh help'"
        return 0
    fi
    [[ $CHECK -eq 1 ]] && { warn "would create symlinks"; return 0; }
    mkdir -p "$src"
    (cd "$REPO_ROOT/data/faq" && for f in *_faq.json; do [[ -f "$f" ]] && ln -sf "../$f" "source/$f"; done)
    ok "FAQ symlinks: $(ls "$src" 2>/dev/null | wc -l) files"
    state_set paths
}

# ═══════════════════════════════════════════════════════════════════════════
# 9. ENV — .env from template + pod overrides
# ═══════════════════════════════════════════════════════════════════════════
stage_env() {
    hdr "9. .env config"
    local env_file="$REPO_ROOT/.env"
    if [[ ! -f "$env_file" ]]; then
        warn ".env missing — copying from template"
        [[ -f "$REPO_ROOT/infra/runpod/env.runpod.example" ]] && \
            cp "$REPO_ROOT/infra/runpod/env.runpod.example" "$env_file" || \
            cp "$REPO_ROOT/.env.example" "$env_file"
        warn "Edit .env with REAL keys before next run!"
    fi

    # Required keys check
    local missing=()
    for k in LIVEKIT_URL LIVEKIT_API_KEY LIVEKIT_API_SECRET; do
        grep -q "^${k}=." "$env_file" || missing+=("$k")
    done
    [[ ${#missing[@]} -gt 0 ]] && warn "missing keys: ${missing[*]}" || ok "required keys present"

    # Pod-mode overrides (idempotent)
    if ! grep -q "^TELEPHONY_ENABLED=false" "$env_file"; then
        log "applying pod overrides"
        [[ $CHECK -eq 1 ]] || sed -i \
            -e 's|^SHERPA_MODEL_DIR=.*|#SHERPA_MODEL_DIR=mac-only|' \
            -e 's|^VIENEU_BACKBONE_REPO=.*|#VIENEU_BACKBONE_REPO=mac-only|' \
            -e 's|^GENDER_MODEL_DIR=.*|#GENDER_MODEL_DIR=mac-only|' \
            -e "s|^SANTA_CHAT_DATA_DIR=.*|SANTA_CHAT_DATA_DIR=$REPO_ROOT/data/rag|" \
            -e 's|^FASTEMBED_CACHE_PATH=.*|FASTEMBED_CACHE_PATH=/root/.cache/fastembed|' \
            -e 's|^TELEPHONY_ENABLED=.*|TELEPHONY_ENABLED=false|' \
            -e 's|^REDIS_URL=.*|REDIS_URL=redis://localhost:6379/0|' \
            "$env_file"
        grep -q "^NOBLE_RAG_BACKEND=" "$env_file" || echo "NOBLE_RAG_BACKEND=flat_store" >> "$env_file"
        grep -q "^FLAT_STORE_SKIP_FAQ=" "$env_file" || echo "FLAT_STORE_SKIP_FAQ=true" >> "$env_file"
        grep -q "^LIVEKIT_WORKER_PORT=" "$env_file" || echo "LIVEKIT_WORKER_PORT=8082" >> "$env_file"
    fi

    # Wire vLLM endpoint when model exists
    if [[ "$NO_MODEL" -eq 0 && -d "$MODEL_DIR" ]]; then
        if ! grep -q "^OPENAI_BASE_URL=http://localhost:8000" "$env_file"; then
            log "wiring OPENAI_BASE_URL → vLLM local"
            [[ $CHECK -eq 1 ]] || sed -i \
                -e 's|^OPENAI_BASE_URL=.*|OPENAI_BASE_URL=http://localhost:8000/v1|' \
                -e "s|^OPENAI_MODEL=.*|OPENAI_MODEL=$HF_MODEL_REPO|" \
                -e 's|^OPENAI_API_KEY=.*|OPENAI_API_KEY=dummy|' \
                "$env_file"
            # Embedding endpoint = real OpenAI (vLLM has no /v1/embeddings).
            # User must set these manually if they want ToolHint hints; otherwise
            # the patched tool_hint.py disables hints when key=="dummy".
            grep -q "^OPENAI_EMBEDDING_BASE_URL=" "$env_file" || echo "OPENAI_EMBEDDING_BASE_URL=https://api.openai.com/v1" >> "$env_file"
            grep -q "^OPENAI_EMBEDDING_API_KEY=" "$env_file" || echo "# OPENAI_EMBEDDING_API_KEY=sk-...    # set to enable ToolHint hints" >> "$env_file"
        fi
    fi
    state_set env
}

# ═══════════════════════════════════════════════════════════════════════════
# 9.5 MIGRATE — ensure MongoDB indexes/TTL (idempotent — safe re-run)
# Runs after env stage so MONGODB_URI is in place.
# ═══════════════════════════════════════════════════════════════════════════
stage_migrate() {
    hdr "9.5 mongo migrate (indexes + TTL — idempotent)"
    [[ $CHECK -eq 1 ]] && return 0
    [[ -f "$REPO_ROOT/.env" ]] || { warn ".env missing — skip migrate"; return 0; }

    local PY="$REPO_ROOT/.venv/bin/python"
    [[ -x "$PY" ]] || { warn ".venv missing — skip migrate (run agent_venv first)"; return 0; }

    # Re-source .env to pick up any updates from stage env
    load_dotenv "$REPO_ROOT/.env"
    [[ -z "${MONGODB_URI:-}" ]] && { warn "MONGODB_URI empty — skip migrate"; return 0; }

    log "1/2 noble_profiles + customers + bookings_flat indexes..."
    "$PY" "$REPO_ROOT/scripts/mongo_migrate_noble_profile.py" 2>&1 | tail -5 | sed 's/^/   /' || warn "noble_profile migrate failed (non-fatal)"

    log "2/2 outbound_briefs + outbound_calls indexes..."
    "$PY" "$REPO_ROOT/scripts/mongo_migrate_outbound.py" 2>&1 | tail -5 | sed 's/^/   /' || warn "outbound migrate failed (non-fatal)"

    state_set migrate
}

# ═══════════════════════════════════════════════════════════════════════════
# 10. SERVICES — redis + vllm + agent in tmux
# ═══════════════════════════════════════════════════════════════════════════
stage_services() {
    hdr "10. services (redis + vllm + agent)"

    if ! redis-cli ping >/dev/null 2>&1; then
        log "starting redis"
        [[ $CHECK -eq 1 ]] || redis-server --daemonize yes --bind 127.0.0.1 --port 6379
    fi
    ok "redis: $(redis-cli ping 2>/dev/null || echo 'FAIL')"

    if [[ "$NO_MODEL" -eq 0 && -d "$MODEL_DIR" ]]; then
        if curl -sf http://localhost:8000/v1/models >/dev/null 2>&1; then
            ok "vLLM already on :8000"
        else
            # Auto-detect GPU count for tensor parallelism — Qwen3.6-35B-A3B BF16
            # needs ~70GB which doesn't fit on one A40 (46GB). Multi-GPU pods MUST
            # use TP=N or load fails with "Engine core initialization failed".
            local GPU_COUNT
            GPU_COUNT=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l)
            GPU_COUNT="${GPU_COUNT//[^0-9]/}"
            [[ -z "$GPU_COUNT" || "$GPU_COUNT" == "0" ]] && GPU_COUNT=1
            local TP="${TENSOR_PARALLEL:-$GPU_COUNT}"
            log "starting vLLM in tmux:vllm — TENSOR_PARALLEL=$TP (detected $GPU_COUNT GPUs), logs → $VLLM_LOG"
            [[ $CHECK -eq 1 ]] || {
                tmux kill-session -t vllm 2>/dev/null || true
                pkill -9 -f "vllm.entrypoints" 2>/dev/null || true
                sleep 2
                tmux new -d -s vllm "cd $REPO_ROOT && MODEL='$MODEL_DIR' SERVED_NAME='$HF_MODEL_REPO' VLLM_VENV='$VLLM_VENV' TENSOR_PARALLEL='$TP' bash infra/runpod/start_vllm.sh 2>&1 | tee $VLLM_LOG"
            }
        fi
    else
        warn "vLLM skipped (no model) — using cloud LLM"
    fi

    if pgrep -f "noble-agent.*livekit" >/dev/null; then
        log "agent running — restarting cleanly"
        [[ $CHECK -eq 1 ]] || {
            tmux kill-session -t agent 2>/dev/null || true
            pkill -9 -f "noble-agent" 2>/dev/null || true
            pkill -9 -f "livekit.agents" 2>/dev/null || true
            sleep 3
        }
    fi
    log "starting agent in tmux:agent (logs → $AGENT_LOG)"
    # noble-agent uses pydantic-settings which auto-loads .env — no manual export needed
    [[ $CHECK -eq 1 ]] || tmux new -d -s agent \
        "cd $REPO_ROOT && source .venv/bin/activate && noble-agent --transport livekit start 2>&1 | tee $AGENT_LOG"
    state_set services
}

# ═══════════════════════════════════════════════════════════════════════════
# 11. VERIFY — wait for ready + log signals
# ═══════════════════════════════════════════════════════════════════════════
stage_verify() {
    hdr "11. verify"
    [[ $CHECK -eq 1 ]] && return 0

    # Helper: tail file in background, prefix lines, kill on demand.
    local TAIL_PID=""
    _tail_signals() {
        local file="$1" prefix="$2" pattern="$3"
        ( tail -n0 -F "$file" 2>/dev/null \
            | grep --line-buffered -E "$pattern" \
            | sed -u "s|^|   ${prefix} |" ) &
        TAIL_PID=$!
    }
    _kill_tail() { [[ -n "$TAIL_PID" ]] && kill "$TAIL_PID" 2>/dev/null; wait "$TAIL_PID" 2>/dev/null || true; TAIL_PID=""; }

    if [[ "$NO_MODEL" -eq 0 && -d "$MODEL_DIR" ]]; then
        log "waiting for vLLM (up to 15min) — streaming key signals from $VLLM_LOG"
        _tail_signals "$VLLM_LOG" "[vllm]" "Loading|Loaded|ERROR|CUDA|Uvicorn|Starting|Init|engine|warm|profil|capacity|allocate|gpu memory|Model loaded|application startup"
        local i
        for i in $(seq 1 90); do
            curl -sf http://localhost:8000/v1/models >/dev/null 2>&1 && { _kill_tail; ok "vLLM ready"; break; }
            sleep 10
        done
        _kill_tail
        if ! curl -sf http://localhost:8000/v1/models >/dev/null 2>&1; then
            warn "vLLM not ready after 15min — last 40 lines of $VLLM_LOG:"
            tail -n 40 "$VLLM_LOG" 2>/dev/null | sed 's/^/   /'
            warn "Common causes:"
            warn "  • OOM (model > GPU mem). Smaller: HF_MODEL_REPO=Qwen/Qwen2.5-14B-Instruct bash infra/runpod/setup.sh --from model"
            warn "  • Single GPU when need TP. Override: TENSOR_PARALLEL=2 bash infra/runpod/setup.sh --from services"
            warn "  • flashinfer crash on Ampere. Override: ATTN_BACKEND=FLASH_ATTN bash infra/runpod/setup.sh --from services"
        fi
    fi

    log "waiting for agent worker (60s) — streaming key signals from $AGENT_LOG"
    _tail_signals "$AGENT_LOG" "[agent]" "Loading|Loaded|FlatStore|BM25|registered worker|ERROR|prewarm|VAD|fastembed|FAQ|connecting|Connected"
    local i
    for i in $(seq 1 12); do
        grep -q "registered worker" "$AGENT_LOG" 2>/dev/null && { _kill_tail; ok "agent registered"; break; }
        sleep 5
    done
    _kill_tail

    log "health summary:"
    grep -q "registered worker"        "$AGENT_LOG" 2>/dev/null && ok  "  worker registered"     || warn "  worker NOT registered"
    grep -q "FlatStore loaded"         "$AGENT_LOG" 2>/dev/null && ok  "  RAG loaded"            || warn "  RAG not detected (may be lazy)"
    grep -q "FAQ semantic inject error" "$AGENT_LOG" 2>/dev/null && warn "  FAQ ONNX error"       || ok  "  FAQ inject OK"
    grep -q "Falling back from openai" "$AGENT_LOG" 2>/dev/null && warn "  Cloud fallback events" || ok  "  no cloud fallback"
    state_set verify
}

# ═══════════════════════════════════════════════════════════════════════════
# 12. CONNECT — print LiveKit URL + room + token (the user's "just paste" goal)
# ═══════════════════════════════════════════════════════════════════════════
stage_connect() {
    hdr "12. LiveKit connection (paste into Playground)"
    [[ $CHECK -eq 1 ]] && return 0

    local env_file="$REPO_ROOT/.env"
    [[ -f "$env_file" ]] || { warn "no .env — skipping token gen"; return 0; }

    # Generate JWT via .venv python (livekit-api already installed via uv sync)
    "$REPO_ROOT/.venv/bin/python" - <<PYEOF
import os, time
from dotenv import load_dotenv
load_dotenv("$env_file")
url    = os.getenv("LIVEKIT_URL", "")
key    = os.getenv("LIVEKIT_API_KEY", "")
secret = os.getenv("LIVEKIT_API_SECRET", "")
if not (url and key and secret):
    print("\n  ⚠ LIVEKIT_* keys missing in .env — fill them and re-run --only connect")
    raise SystemExit(0)
from livekit.api import AccessToken, VideoGrants
identity = f"user-{int(time.time())}"
tok = AccessToken(key, secret) \
    .with_identity(identity) \
    .with_grants(VideoGrants(room_join=True, room="$ROOM",
                              can_publish=True, can_subscribe=True, can_publish_data=True)) \
    .to_jwt()
print()
print(f"  ${C}URL:${X}  ", url)
print(f"  ${C}ROOM:${X} ", "$ROOM")
print(f"  ${C}TOKEN:${X} ", tok)
print()
print("  ▶ https://agents-playground.livekit.io/")
print("    Settings → Manual → paste URL + Token → Connect")
PYEOF
    state_set connect
}

# ═══════════════════════════════════════════════════════════════════════════
# Final summary
# ═══════════════════════════════════════════════════════════════════════════
print_summary() {
    hdr "DONE"
    cat <<EOF

  ${G}LOG FILES${X}
    setup       $LOG_FILE
    vLLM        $VLLM_LOG
    agent       $AGENT_LOG

  ${G}NEXT${X}
    bash scripts/noble-pod doctor          # health check
    bash scripts/noble-pod logs --watch    # live tail (ttft/fallback)
    bash scripts/noble-pod connect         # re-print LiveKit token any time

  ${G}TROUBLESHOOT${X}
    re-run a stage:                        bash infra/runpod/setup.sh --only env
    resume from a stage:                   bash infra/runpod/setup.sh --from services
    skip vLLM (cloud LLM):                 bash infra/runpod/setup.sh --no-model
    use smaller model:                     HF_MODEL_REPO=Qwen/Qwen2.5-14B-Instruct bash infra/runpod/setup.sh --from model

EOF
}

# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════
main() {
    [[ $CHECK -eq 1 ]] && hdr "DRY-RUN (--check)"
    log "Stages: ${ALL_STAGES[*]}"

    for stage in "${ALL_STAGES[@]}"; do
        if should_run "$stage"; then
            "stage_$stage"
        else
            skip "stage:$stage (filtered)"
        fi
    done
    print_summary
}

main "$@"
