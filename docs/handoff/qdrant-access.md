# Qdrant access (`QDRANT_URL`)

`kb_search` (`NOBLE_RAG_BACKEND=kb_service`) and `send_media` read the per-tenant
collections `<tenant_id>_documents` / `<tenant_id>_media` from the Qdrant that the
Portal owns on EC2.

## The deployment (verified 2026-08-06)

| | |
|---|---|
| Instance | `i-095b82ffdd7d6c630` (`ap-southeast-1`, account `071732232185`) |
| VPC / subnet | `vpc-013da868d7f8a4c24` (`10.110.0.0/16`) / `subnet-0756256f7c4fb8c34` (`10.110.32.0/19`, private) |
| Instance private IP | `10.110.43.147` — **no public IP** |
| Qdrant container | `odyssey-portal-backend-qdrant-1` on docker network `odyssey-network` |
| Host port | **none** — `6333` is container-only; nothing listens on the host |
| Security group | `sg-06b48c4a10a5fe442`, inbound only `5274` + `9200` (both from `sg-0e5f3c1cd563bc02b`) — **no 6333 rule** |

## Target: agent inside the VPC — no tunnel, no AWS key

This is the intended production shape. Two variants, differing only in what infra has
to change:

**A. Agent on the SAME EC2, joined to `odyssey-network`**
```
QDRANT_URL=http://odyssey-portal-backend-qdrant-1:6333
```
Nothing else to change — docker DNS resolves it, no host port, no SG rule. Cheapest to
get running; the cost is that agent and Qdrant share one box.

**B. Agent on a different EC2/ECS in the VPC**
```
QDRANT_URL=http://10.110.43.147:6333
```
Needs two changes first, or it silently fails to connect:
1. Publish the port on the Qdrant host — `ports: ["10.110.43.147:6333:6333"]` in the
   **Portal's** compose (binding the private IP, not `0.0.0.0`). That file is in the
   `odyssey-portal-backend` repo, so this needs the Portal side.
2. `sg-06b48c4a10a5fe442`: allow inbound tcp `6333` **from the agent's security group**
   (SG-to-SG, not a CIDR).

Caveat for B: `10.110.43.147` is an instance IP. If that instance is ever replaced the
IP changes — put a private Route53 record or an internal NLB in front if the instance is
not treated as permanent.

Either way the agent needs **no AWS credentials at runtime**: it is a plain HTTP call
inside the VPC. If the agent runs on EC2 and needs AWS for anything else, use the
instance role, not an access key.

## Dev fallback: SSM port-forward

Only for working from a machine outside the VPC (e.g. a laptop). The instance is in a
private subnet, so SSM is the only way in: the SSM Agent dials out to AWS, the client
dials out to AWS, they meet in the middle. This does **not** go through `10.50.13.220`.

```bash
scripts/qdrant_tunnel.sh        # foreground; Ctrl-C closes it
```

It re-discovers the container IP each run (Qdrant publishes no host port there, so the
forward targets the container, and that IP changes on every redeploy), then forwards to
`127.0.0.1:16433` → set `QDRANT_URL=http://127.0.0.1:16433`. Override with
`LOCAL_PORT=`/`TARGET=`/`CONTAINER=`.

Verify: `curl -s http://127.0.0.1:16433/collections` should list the
`<tenant>_documents` / `<tenant>_media` pairs.

IAM: the user `dot220-qdrant-tunnel` (policy `qdrant-tunnel-ssm`) is already scoped to
exactly this instance plus the two SSM documents. Use that, not a broad key.

**`session-manager-plugin` binds `127.0.0.1` only** — measured, not assumed: with a
forward on `:16999`, `ss` shows `127.0.0.1:16999`, and `curl 172.17.0.1:16999` returns
nothing while `curl 127.0.0.1:16999` returns 200. So a container cannot reach the
forward directly; bridging it needs a second hop (`socat` bound to the bridge IP), which
is what the `.220` box does in its `qdrant-tunnel` systemd unit. Anything of the form
`172.17.0.1:<port>` is therefore **local to whichever host reads it** — copying such a
value to another machine points at that machine's own docker bridge and finds nothing.

## Failure mode to know

With no reachable Qdrant, both tools degrade **silently**: `kb_search` returns empty
context and `send_media` returns its `no_media` payload. Nothing crashes, so a dead
tunnel or a missing SG rule reads in the logs like "the KB has no data".

## Checking it

`scripts/test_search_tools.py` calls the real tool functions (no mocks) and separates
"infra unreachable" from "no matching data" — which is the whole point, given the silent
degrade above.

```bash
make test-search ARGS="-i"                  # interactive — type your own queries, /help for commands
make test-search ARGS="-t <tenant> -i"      # …on a specific tenant
make test-search                            # probe + run the smoke set on the first tenant
make test-search ARGS="--list"              # just list tenants/collections
make test-search ARGS='--kb "giá bao nhiêu" --project VRI'
make test-search ARGS='--media "hồ bơi" --category tien_ich'
```

Interactive mode reuses one Qdrant connection, so each query is just an embed + a
search. Inside it: `/kb` · `/media [category]` · `/cat <category>` · `/project [CODE]` ·
`/tenant [id]` · `/topk <n>` · `/both <query>` · `/help` · `/quit`.

Exit codes: `0` ok · `1` reachable but every query came back empty / isolation broke ·
`2` not configured or not reachable. It bypasses the media cache so every run really
hits the backends, and it always checks that an unknown tenant returns nothing.

Note the tool's own tenant matters: `TENANT_ID` in `.env` is `noble`, but the live
collections are named after real tenants (`noble-homes_k3n7_retail`, …). A tenant with no
collection is fail-closed by design, so pointing the agent at `noble` yields empty
results — that is correct behaviour, not a bug.
