#!/usr/bin/env bash
# Usage: sampler.sh <out_dir> [interval_s]
# Run on the server; SIGINT/SIGTERM to stop. Samples GPU + container CPU/mem.
set -u
out="${1:?out_dir required}"
iv="${2:-2}"
mkdir -p "$out"
echo "ts,gpu_util,gpu_mem_used_mib,gpu_power_w" > "$out/gpu.csv"
: > "$out/containers.log"
trap 'exit 0' INT TERM
while true; do
  ts=$(date +%s)
  line=$(nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw \
         --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
  echo "${ts},${line}" >> "$out/gpu.csv"
  {
    echo "=== ${ts} ==="
    docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' 2>/dev/null \
      | grep -E 'hotline|models|infra' || true
  } >> "$out/containers.log"
  sleep "$iv"
done
