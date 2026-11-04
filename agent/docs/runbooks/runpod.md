# RunPod — Strategy, Scale & Limits

Companion to **[infra/runpod/SETUP.md](../../infra/runpod/SETUP.md)** (the canonical deploy
guide: `setup.sh` + `noble-pod` CLI). This doc holds the *decision layer* — when self-host
beats cloud, how to scale, what RunPod can't do, and how to stress-test — distilled from the
benchmark/brainstorm work. For deploy/ops steps go to SETUP.md.

---

## 0. TL;DR — the three decisions

- **Replace OpenAI with vLLM on RunPod?** ✅ only as **1-pod co-located** (agent + vLLM same pod) → TTFA <700ms. ❌ never split agent/LLM across pods — RunPod "VPC" is cross-region (~344ms) and breaks the latency budget.
- **Scale?** ✅ horizontal via LiveKit Cloud dispatch (N identical pods, same `LIVEKIT_AGENT_NAME`). ❌ no native autoscale; must pin same datacenter. ~$1.89/h/pod.
- **Telephony on RunPod?** ❌ RunPod has no UDP → no SIP/RTP. Keep Asterisk on EC2 + LiveKit SIP bridge, or use LiveKit native SIP.

---

## 1. Bench numbers (measured, 1× PRO 6000 / 2× A40)

| Path | TTFT p50 | TPS | Note |
|---|---|---|---|
| vLLM loopback (same pod) | **123ms** | 80 | ⭐ target floor |
| same pod via TCP 10.0.x.x | 115ms | 83 | ≈ loopback |
| **Pod B → Pod A "VPC"** | **344ms** | 60 | ⚠️ RunPod "VPC" is cross-region |
| EC2 SG → Pod TCP public | 596ms | 46 | cross-continent |
| OpenAI gpt-5.4-mini from SG | ~300–400ms | cloud | baseline |

**Rule:** self-hosted LLM beats cloud **only when co-located (loopback) or same-DC pinned (<10ms hop)**. Cross-region self-host is slower than OpenAI — an anti-pattern.

---

## 2. Latency budget (voice TTFA target <700ms)

| Component | Co-located | Same-DC split | Cross-region | EC2 SG + OpenAI |
|---|---|---|---|---|
| STT finalize (Soniox) | 250 | 250 | 250 | 250 |
| RAG (FlatStore) | 30 | 30 | 30 | 30 |
| Agent→LLM network | ~0 | 5–10 | **300** | 60 |
| LLM TTFT | 123 | 123 | 123 | 300 |
| Sentence buffer | 50 | 50 | 50 | 50 |
| TTS first chunk | 250 | 250 | 250 | 250 |
| **E2E TTFA** | **~700ms** ✅ | ~710ms ✅ | ~1000ms ❌ | ~940ms ⚠️ |

→ Self-host must be co-located or same-DC. Network hop budget for voice is ~70ms.

---

## 3. Scale patterns

**Pattern A — fat-pod replication (recommended MVP).** Each pod = full stack (agent + vLLM + local Redis). LiveKit dispatcher load-balances calls across pods with the same `LIVEKIT_AGENT_NAME`, based on `WORKER_MAX_CONCURRENT_SESSIONS`. Zero cross-pod latency, linear capacity, failure isolation. Downside: local Redis isn't shared (use Upstash/ElastiCache if a caller must resume on another pod); cost = N × $1.89/h.

- **1-pod capacity:** ~8–10 concurrent calls, ~500 calls/h. Past that → add pods.
- **Same-DC pinning is mandatory** for any multi-pod or split setup: RunPod Console → Template → Advanced → Data Center → pin one (`US-GA-1`, `EU-RO-1`, …). The 344ms "VPC" measurement proves the default is *not* intra-DC.
- **No native autoscale** for Pods (only Serverless has it). A custom EC2 cron can poll Grafana p95 and spawn/terminate pods via RunPod GraphQL — scale-up cold start is ~8 min (pod boot + model load), so prefer running a warm floor.

Pattern B (CPU agent pool + GPU vLLM pool behind a LB) and Pattern C (microservice split) only pay off at >5k / >10k concurrent calls with a real ops team — not Noble's current scale.

**External Redis/MongoDB:** agent only reads `REDIS_URL` / `MONGODB_URI`. Managed cloud (Upstash + Atlas) works from a pod over outbound TLS — easiest. A company-private VPC needs WireGuard from the pod (note: WireGuard is UDP, so the pod must be the *client* dialing out, never the hub). On-prem VN data residency → don't use RunPod (cross-Pacific 200–300ms kills voice).

---

## 4. RunPod hard limits (from official docs)

- **No UDP** ([docs](https://docs.runpod.io/pods/configuration/expose-ports)): no Asterisk SIP (UDP 5060 + RTP 10000–20000), no inbound WireGuard. TLS/WebSocket/TCP-direct only. → telephony stays off-pod.
- **No static IP / no inbound:** pod IP and TCP port change on every restart. Agent connects *outbound* to LiveKit Cloud; nothing dials into the pod.
- **One exposure per port:** a port is HTTP **or** TCP, never both. HTTP proxy (`<POD_ID>-8000.proxy.runpod.net`) is convenient but Cloudflare-buffered (TTFT jitter 220–900ms, 100s timeout) — use TCP-direct for any latency-sensitive external call.
- **Serverless cold-start 30–60s** for Qwen3.6-35B (loading 70GB) and no real WebSocket → unusable for voice. Fine for batch (transcript summarize, nightly RAG re-index).
- **No Docker-in-Docker:** the pod *is* a container. Run native Python + tmux (what `setup.sh` does). `Dockerfile.*` / `docker-compose.runpod.yml` are for VPS/Fly.io only.

---

## 5. Telephony — why not on RunPod, and the two patterns

RunPod can't receive PSTN/SIP (no UDP, no fixed inbound IP, no privileged bind). Keep the agent outbound-only on RunPod and bridge telephony elsewhere:

- **Pattern A — Asterisk on EC2 + LiveKit SIP bridge** (if you already run Asterisk): PSTN → Asterisk EC2 → LiveKit Cloud SIP → agent on RunPod. See [freebpx-setup.md](../freebpx-setup.md) + https://docs.livekit.io/sip/.
- **Pattern B — LiveKit native SIP** (simpler): buy a VN SIP trunk (Viettel/VNPT business SIP), point it straight at LiveKit Cloud, drop Asterisk entirely. Cheaper, but DTMF/IVR logic lives in LiveKit.

---

## 6. Cost & break-even vs OpenAI

```
OpenAI  ≈ calls/day × 30 × tokens/call × $0.00015/1k   (gpt-5.4-mini)
RunPod  ≈ $1.89/h × 24 × 30 = ~$1,360/month             (1 pod, fixed)
Break-even ≈ 6,000 calls/day  (assuming ~5k tokens/call)
```

- **< 5,000 calls/day → keep OpenAI** (savings marginal, ops overhead not worth it).
- **5,000–10,000 → A/B test** RunPod (10% traffic) before committing.
- **> 10,000 → migrate** (cost win + co-located latency win).

Quality is model+prompt dependent — A/B via `tests/bench_llm.py` before any swap. Qwen3.6-35B: good VN, mature tool-calling, medium hallucination; gpt-5.4-mini: low hallucination, excellent tool-calling.

---

## 7. CI/CD

GitLab `.gitlab-ci.yml` has a `deploy:runpod` job gated to the deploy branch: it SSHes into the pod, `git pull`, applies patches + agent venv, and restarts services via `noble-pod restart` (vLLM is **not** restarted — keeps the model warm, ~30s redeploy). Pod IP/port change on restart, so `RUNPOD_POD_IP` / `RUNPOD_SSH_PORT` GitLab variables must be updated (or queried via RunPod GraphQL in a pre-deploy step). For zero-downtime, run blue-green (2 pods, swap LiveKit dispatch weight) — cost 2×, only worth it in prod.

---

## 8. Stress-test checklist

Run after deploy (`noble-pod bench "<câu test>"` for raw vLLM TTFT; full scripts were folded out — reproduce inline if needed). Pass thresholds vs the §1 baseline:

| Test | What | Pass |
|---|---|---|
| Baseline loopback | `noble-pod bench` on pod | TTFT p50 100–180ms, TPS >70 |
| Concurrency N=8 | 8 parallel streams | TTFT p50 <250ms (1 pod ≈ 8–10 calls) |
| Sustained 5 min | N=4 rolling, watch `nvidia-smi` | last-30s p50 ≤ 1.2× first-30s, 0 errors, stable VRAM |
| E2E TTFA | Playground, "Noble Crystal Long Biên" | p50 <700ms, p95 <1200ms |
| Failure recovery | kill vLLM mid-call | falls back to Gemini/OpenAI, no crash (needs `GEMINI_API_KEY`) |
| Cold start | Stop → Start pod | vLLM ~5–8 min, agent ~20–30s, total <10 min |

**Migrate if:** baseline + concurrency + sustained pass, E2E p50 <700ms, and §6 break-even favorable. **Keep OpenAI if:** EC2→RunPod >1.3× OpenAI, or <5k calls/day.

---

## See also

- **[infra/runpod/SETUP.md](../../infra/runpod/SETUP.md)** — deploy steps, `noble-pod` CLI, troubleshooting, MongoDB, file map.
- **[monitoring-alerting.md](./monitoring-alerting.md)** — observability layers + alerting.
- **[freebpx-setup.md](../freebpx-setup.md)** — Asterisk/FreePBX telephony bridge.
