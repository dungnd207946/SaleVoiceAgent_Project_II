#!/usr/bin/env bash
# Container-start hook: pull RAG artifacts from the HF dataset before
# launching the agent. Pulls only when the resolved commit SHA differs
# from the cached marker — same pattern as santa-llm-serving's
# pull-adapters.sh, so promotion is `promote prod` on the dataset side.
set -euo pipefail

: "${HF_TOKEN:?HF_TOKEN required to pull RAG dataset from HF}"

REPO="${RAG_HF_REPO:-NobleX-AI/santa-hotline-rag}"
REVISION="${RAG_HF_REVISION:-prod}"
DATA_DIR="${DATA_DIR:-/app/data}"

REPO="$REPO" REVISION="$REVISION" DATA_DIR="$DATA_DIR" python3 - <<'PY'
import os
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download

repo = os.environ["REPO"]
revision = os.environ["REVISION"]
data_dir = Path(os.environ["DATA_DIR"])
marker = data_dir / ".rag_revision"

api = HfApi(token=os.environ["HF_TOKEN"])
sha = api.repo_info(repo, repo_type="dataset", revision=revision).sha

if marker.exists() and marker.read_text().strip() == sha:
    print(f"[pull-rag] skip — already at {revision}@{sha[:8]}", flush=True)
else:
    print(f"[pull-rag] {repo}@{revision} (sha {sha[:8]}) -> {data_dir}", flush=True)
    snapshot_download(
        repo_id=repo,
        repo_type="dataset",
        revision=sha,
        local_dir=str(data_dir),
    )
    marker.write_text(sha)
    print(f"[pull-rag] ok — RAG data ready at {data_dir}", flush=True)
PY

# Hand off to the actual agent command (CMD or compose override)
exec "$@"
