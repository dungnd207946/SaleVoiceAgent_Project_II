#!/usr/bin/env bash
# data_sync.sh — Universal data sync cho Noble Voice Agent.
#
# Quản lý 3 thư mục gitignored: data/rag, data/flat_store, data/faq_cache.
# 4 chế độ: consolidate (Mac), push (Mac→Pod), hf-{upload,download} (cloud),
#
# Usage:
#   bash scripts/data_sync.sh consolidate                  # Mac: gom từ sibling repos
#   bash scripts/data_sync.sh push <pod_ip> [ssh_port]     # Mac→Pod: rsync
#   bash scripts/data_sync.sh hf-upload <hf-repo-id>       # Mac→HF: 1-lần publish
#   bash scripts/data_sync.sh hf-download <hf-repo-id>     # Mac/Pod: kéo về data/
#   bash scripts/data_sync.sh rebuild                      # Pod: re-encode (no Mac)
#   bash scripts/data_sync.sh check                        # verify state + sizes
#   bash scripts/data_sync.sh status                       # ls data/
#   bash scripts/data_sync.sh help
#
# Env overrides:
#   NOBLE_DATA_HF_REPO     mặc định cho hf-* commands (e.g. user/santa-data-private)
#   VOICEAGENTRAG          path tới sibling voiceagentrag (default: ../../voiceagentrag)
#   SANTA_CHAT             path tới santa-chat-agent rag dir
#   POD_USER, POD_PATH, SSH_KEY  override cho push command
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
DATA="$REPO_ROOT/data"

# ── colors ─────────────────────────────────────────────────────────────────
G='\033[32m'; Y='\033[33m'; R='\033[31m'; B='\033[34m'; C='\033[36m'; D='\033[2m'; X='\033[0m'
log()  { printf "${G}▶${X} %s\n" "$*"; }
warn() { printf "${Y}⚠${X} %s\n" "$*"; }
fail() { printf "${R}✗${X} %s\n" "$*" >&2; exit 1; }
ok()   { printf "${G}✓${X} %s\n" "$*"; }
hdr()  { printf "\n${B}━━━ %s ━━━${X}\n" "$*"; }

SUBDIRS=(rag flat_store faq_cache)

# ═══════════════════════════════════════════════════════════════════════════
# consolidate — gom từ sibling repos (Mac, 1 lần đầu)
# ═══════════════════════════════════════════════════════════════════════════
cmd_consolidate() {
    local VOICEAGENTRAG="${VOICEAGENTRAG:-$REPO_ROOT/../../voiceagentrag}"
    local SANTA_CHAT="${SANTA_CHAT:-$REPO_ROOT/../santa-chat-agent/src/services/rag/data}"

    hdr "consolidate — sibling repos → data/"
    log "VOICEAGENTRAG = $VOICEAGENTRAG"
    log "SANTA_CHAT    = $SANTA_CHAT"

    # 1) RAG chunks — santa-chat-agent ưu tiên, fallback voiceagentrag
    log "1/3 RAG chunks (FlatStore source of truth)"
    if [[ -d "$SANTA_CHAT" ]] && [[ -n "$(ls -A "$SANTA_CHAT" 2>/dev/null)" ]]; then
        mkdir -p "$DATA/rag" && cp -r "$SANTA_CHAT"/. "$DATA/rag/"
        ok "  từ santa-chat-agent → $(du -sh "$DATA/rag" | cut -f1)"
    elif [[ -d "$VOICEAGENTRAG/data/rag" ]]; then
        mkdir -p "$DATA/rag" && cp -r "$VOICEAGENTRAG/data/rag"/. "$DATA/rag/"
        ok "  từ voiceagentrag → $(du -sh "$DATA/rag" | cut -f1)"
    else
        warn "  không tìm thấy RAG source — noble_search sẽ trả empty"
    fi

    # 2) FlatStore — pre-encoded từ voiceagentrag (skip 30 phút encode)
    log "2/3 FlatStore cache (.npy + BM25)"
    if [[ -d "$VOICEAGENTRAG/data/flat_store" ]]; then
        mkdir -p "$DATA/flat_store" && cp -r "$VOICEAGENTRAG/data/flat_store"/. "$DATA/flat_store/"
        ok "  $(du -sh "$DATA/flat_store" | cut -f1)"
    else
        warn "  voiceagentrag không có flat_store — chạy 'rebuild' trên pod (~30 phút CPU)"
    fi

    # 3) FAQ cache — per-project e5-large
    log "3/3 FAQ cache (V10 semantic inject)"
    if [[ -d "$VOICEAGENTRAG/data/faq_cache" ]]; then
        mkdir -p "$DATA/faq_cache" && cp -r "$VOICEAGENTRAG/data/faq_cache"/. "$DATA/faq_cache/"
        ok "  $(du -sh "$DATA/faq_cache" | cut -f1)"
    else
        warn "  voiceagentrag không có faq_cache — sẽ tự encode lần đầu (~10s/project)"
    fi

    cmd_status
}

# ═══════════════════════════════════════════════════════════════════════════
# push — Mac rsync trực tiếp Mac → Pod
# ═══════════════════════════════════════════════════════════════════════════
cmd_push() {
    local POD_IP="${1:-${POD_IP:-}}"
    local POD_PORT="${2:-${POD_PORT:-22}}"
    local POD_USER="${POD_USER:-root}"
    local POD_PATH="${POD_PATH:-/workspace/santa-hotline-agent/data/}"
    local SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"

    [[ -z "$POD_IP" ]] && fail "Usage: data_sync.sh push <pod_ip> [ssh_port]"
    hdr "push — Mac → $POD_USER@$POD_IP:$POD_PORT"

    for d in "${SUBDIRS[@]}"; do
        [[ -d "$DATA/$d" ]] || fail "$DATA/$d missing — chạy 'consolidate' hoặc 'hf-download' trước"
        [[ -n "$(ls -A "$DATA/$d" 2>/dev/null)" ]] || fail "$DATA/$d empty"
    done

    log "Total: $(du -sh data/rag data/flat_store data/faq_cache 2>/dev/null | tail -1 | cut -f1)"
    if command -v rsync &>/dev/null; then
        for d in "${SUBDIRS[@]}"; do
            log "  rsync data/$d/ ..."
            rsync -avhz --partial \
                -e "ssh -p $POD_PORT -i $SSH_KEY -o StrictHostKeyChecking=no" \
                "data/$d/" "$POD_USER@$POD_IP:$POD_PATH/$d/"
        done
    else
        ssh -p "$POD_PORT" -i "$SSH_KEY" -o StrictHostKeyChecking=no \
            "$POD_USER@$POD_IP" "mkdir -p $POD_PATH/{rag,flat_store,faq_cache}"
        for d in "${SUBDIRS[@]}"; do
            log "  scp data/$d/ ..."
            scp -P "$POD_PORT" -i "$SSH_KEY" -o StrictHostKeyChecking=no -r \
                "data/$d"/* "$POD_USER@$POD_IP:$POD_PATH/$d/"
        done
    fi
    ok "transferred. Verify: ssh ... 'du -sh /workspace/santa-hotline-agent/data/*'"
}

# ═══════════════════════════════════════════════════════════════════════════
# hf-upload — Mac → HF Dataset private (1 lần publish)
# ═══════════════════════════════════════════════════════════════════════════
cmd_hf_upload() {
    local repo="${1:-${NOBLE_DATA_HF_REPO:-}}"
    [[ -z "$repo" ]] && fail "Usage: data_sync.sh hf-upload <hf-repo-id> (or set NOBLE_DATA_HF_REPO)"

    hdr "hf-upload — data/{rag,flat_store,faq_cache} → $repo"
    command -v hf &>/dev/null || fail "Install: pip install huggingface_hub[cli] (or 'uv pip install huggingface_hub[cli]')"

    for d in "${SUBDIRS[@]}"; do
        [[ -d "$DATA/$d" ]] && [[ -n "$(ls -A "$DATA/$d" 2>/dev/null)" ]] || fail "$DATA/$d missing/empty"
    done

    log "Creating private dataset $repo (idempotent)..."
    hf repo create --type dataset --private "$repo" 2>/dev/null || true

    for d in "${SUBDIRS[@]}"; do
        log "  uploading data/$d/ ($(du -sh "$DATA/$d" | cut -f1))..."
        hf upload --repo-type dataset "$repo" "$DATA/$d" "$d" --commit-message "sync $d $(date -u +%Y%m%d-%H%M%S)"
    done

    ok "uploaded. Pod kéo về: NOBLE_DATA_HF_REPO=$repo bash scripts/data_sync.sh hf-download"
    ok "Hoặc setup.sh tự kéo nếu set NOBLE_DATA_HF_REPO trong env"
}

# ═══════════════════════════════════════════════════════════════════════════
# hf-download — Mac/Pod kéo về data/ (universal)
# ═══════════════════════════════════════════════════════════════════════════
cmd_hf_download() {
    local repo="${1:-${NOBLE_DATA_HF_REPO:-}}"
    [[ -z "$repo" ]] && fail "Usage: data_sync.sh hf-download <hf-repo-id> (or set NOBLE_DATA_HF_REPO)"

    hdr "hf-download — $repo → data/"

    # Pre-flight 1: HF_TOKEN required for private datasets (e.g. NMCxyz/flat_store)
    if [[ -z "${HF_TOKEN:-}" ]]; then
        fail "HF_TOKEN missing. Edit .env: HF_TOKEN=hf_xxxxx (https://huggingface.co/settings/tokens)"
    fi

    # Pre-flight 2: verify token + repo accessible BEFORE download (snapshot_download
    # has a silent fallback that returns local_dir even on 401 → empty data, no error)
    local http
    http=$(curl -sS -o /tmp/hf-check.json -w '%{http_code}' \
        -H "Authorization: Bearer $HF_TOKEN" \
        "https://huggingface.co/api/datasets/$repo" 2>/dev/null || echo "000")
    case "$http" in
        200) ok "auth OK ($repo accessible)" ;;
        401|403) fail "HF token invalid/expired or no access to $repo. Check https://huggingface.co/settings/tokens" ;;
        404) fail "Dataset $repo not found (typo? wrong account?)" ;;
        *)   fail "HF API HTTP $http — network/DNS issue?" ;;
    esac

    export HF_HUB_ENABLE_HF_TRANSFER=1
    # Resolve a Python with huggingface_hub: vllm-venv (pod) → agent .venv → system
    local HFCLI HFPY
    HFCLI="${VLLM_VENV:-/opt/vllm-venv}/bin/hf"
    HFPY="${VLLM_VENV:-/opt/vllm-venv}/bin/python"
    [[ -x "$HFCLI" ]] || HFCLI="$(command -v hf 2>/dev/null || true)"
    [[ -x "$HFPY"  ]] || HFPY="$REPO_ROOT/.venv/bin/python"
    [[ -x "$HFPY"  ]] || HFPY="python3"
    if [[ -n "$HFCLI" && -x "$HFCLI" ]]; then
        "$HFCLI" download --repo-type dataset "$repo" --local-dir "$DATA" || fail "hf download failed"
    else
        REPO="$repo" DATA_DIR="$DATA" TOKEN="$HF_TOKEN" "$HFPY" -c "
import os, sys
from huggingface_hub import snapshot_download
try:
    snapshot_download(repo_id=os.environ['REPO'], repo_type='dataset',
                      local_dir=os.environ['DATA_DIR'], token=os.environ['TOKEN'])
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr); sys.exit(1)
" || fail "snapshot_download failed"
    fi

    # Post-flight: verify all 3 dirs populated (snapshot_download silent-OK is a known gotcha)
    local missing=()
    for d in rag flat_store faq_cache; do
        [[ -d "$DATA/$d" ]] && [[ -n "$(ls -A "$DATA/$d" 2>/dev/null)" ]] || missing+=("$d")
    done
    [[ ${#missing[@]} -gt 0 ]] && fail "download incomplete — empty/missing: ${missing[*]}"

    ok "downloaded to $DATA"
    cmd_status
}

# ═══════════════════════════════════════════════════════════════════════════
# rebuild — Pod tự re-encode flat_store (no Mac/HF)
# ═══════════════════════════════════════════════════════════════════════════
cmd_rebuild() {
    hdr "rebuild — re-encode flat_store từ rag"
    [[ -d "$DATA/rag" ]] && [[ -n "$(ls -A "$DATA/rag" 2>/dev/null)" ]] || fail "$DATA/rag missing — không có source để encode. Chạy hf-download hoặc push trước."

    local PY="$REPO_ROOT/.venv/bin/python"
    [[ -x "$PY" ]] || fail ".venv/bin/python not found — chạy 'bash infra/runpod/setup.sh --only agent_venv' trước"

    log "FlatStore: encode chunks + build BM25 (~30 phút CPU)..."
    "$PY" -c "
from noble_agent.agent.rag.flat_store import FlatStore
import time
for skip_faq in (True, False):
    t0=time.time()
    s = FlatStore(skip_faq=skip_faq); s.load(); s.build_bm25()
    print(f'  ✓ flat_store skip_faq={skip_faq} done in {time.time()-t0:.1f}s')
"
    ok "rebuild complete"
    cmd_status
}

# ═══════════════════════════════════════════════════════════════════════════
# check — verify state (3 dirs exist + sizes sane)
# ═══════════════════════════════════════════════════════════════════════════
cmd_check() {
    hdr "check — data integrity"
    local rc=0
    for d in "${SUBDIRS[@]}"; do
        if [[ -d "$DATA/$d" ]] && [[ -n "$(ls -A "$DATA/$d" 2>/dev/null)" ]]; then
            ok "$d  $(du -sh "$DATA/$d" | cut -f1)"
        else
            warn "$d  MISSING/empty"
            rc=1
        fi
    done

    # Static (committed) — phải có
    for f in faq.json hotwords.txt fake_customers.json; do
        [[ -f "$DATA/$f" ]] && ok "  $f present" || { warn "  $f missing"; rc=1; }
    done

    [[ -d "$DATA/faq" ]] && ok "  faq/ ($(ls "$DATA/faq" | wc -l | tr -d ' ') files)" || { warn "  faq/ missing"; rc=1; }

    return $rc
}

# ═══════════════════════════════════════════════════════════════════════════
# status — pretty print data/ sizes
# ═══════════════════════════════════════════════════════════════════════════
cmd_status() {
    hdr "status — data/"
    if [[ -d "$DATA" ]]; then
        du -sh "$DATA"/* 2>/dev/null | sort -h
    else
        warn "data/ missing"
    fi
}


# ═══════════════════════════════════════════════════════════════════════════
# help / dispatch
# ═══════════════════════════════════════════════════════════════════════════
cmd_help() { sed -n '2,22p' "$0" | sed 's|^# \?||'; }

case "${1:-help}" in
    consolidate)  shift; cmd_consolidate "$@";;
    push)         shift; cmd_push "$@";;
    hf-upload)    shift; cmd_hf_upload "$@";;
    hf-download)  shift; cmd_hf_download "$@";;
    rebuild)      shift; cmd_rebuild "$@";;
    check)        shift; cmd_check "$@";;
    status)       shift; cmd_status "$@";;
    help|--help|-h) cmd_help;;
    *) fail "Unknown: $1 (use: help)";;
esac
