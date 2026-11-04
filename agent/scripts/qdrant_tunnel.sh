#!/usr/bin/env bash
# SSM port-forward to the Qdrant on EC2 (private subnet — no other way in).
#
# Qdrant publishes no host port there, so the forward has to target the CONTAINER
# ip, and that ip changes on every `docker compose up` → it is re-discovered each
# run. Stays in the foreground; Ctrl-C closes the tunnel.
#
# Usage:
#   scripts/qdrant_tunnel.sh            # → QDRANT_URL=http://127.0.0.1:16433
#   LOCAL_PORT=6333 scripts/qdrant_tunnel.sh
#
# Then, in another terminal:  make test-search
#
# Details + the in-VPC alternative (no tunnel at all): docs/handoff/qdrant-access.md
set -euo pipefail

: "${AWS_PROFILE:=odyssey}"
: "${AWS_DEFAULT_REGION:=ap-southeast-1}"
export AWS_PROFILE AWS_DEFAULT_REGION

TARGET="${TARGET:-i-095b82ffdd7d6c630}"
CONTAINER="${CONTAINER:-odyssey-portal-backend-qdrant-1}"
LOCAL_PORT="${LOCAL_PORT:-16433}"

command -v aws >/dev/null || { echo "cần aws cli v2" >&2; exit 1; }
command -v session-manager-plugin >/dev/null || {
  echo "cần session-manager-plugin (aws ssm start-session không chạy được nếu thiếu)" >&2; exit 1; }

echo "→ dò ip container $CONTAINER trên $TARGET ..."
cid=$(aws ssm send-command --instance-ids "$TARGET" \
  --document-name AWS-RunShellScript \
  --parameters "commands=[\"docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $CONTAINER\"]" \
  --query Command.CommandId --output text)

ip=""
for _ in $(seq 1 15); do
  st=$(aws ssm get-command-invocation --command-id "$cid" --instance-id "$TARGET" \
       --query Status --output text 2>/dev/null || echo Pending)
  case "$st" in
    Success) ip=$(aws ssm get-command-invocation --command-id "$cid" --instance-id "$TARGET" \
                  --query StandardOutputContent --output text | tr -d '[:space:]'); break ;;
    Failed|Cancelled|TimedOut) echo "send-command $st" >&2; exit 1 ;;
  esac
  sleep 2
done
[ -n "$ip" ] || { echo "không dò được ip (status=$st) — container còn chạy không?" >&2; exit 1; }

echo "→ ip = $ip   forward 127.0.0.1:$LOCAL_PORT → $ip:6333"
echo "→ QDRANT_URL=http://127.0.0.1:$LOCAL_PORT   (Ctrl-C để đóng)"
exec aws ssm start-session --target "$TARGET" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"$ip\"],\"portNumber\":[\"6333\"],\"localPortNumber\":[\"$LOCAL_PORT\"]}"
