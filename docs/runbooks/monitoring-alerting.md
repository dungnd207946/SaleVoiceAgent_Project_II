# Monitoring & Alerting — Pod / Cloud / Backend

**Câu hỏi gốc**: làm sao biết backend server không call qua / lỗi / chậm?

**4 layer trả lời 4 câu hỏi khác nhau**:

| Layer | Trả lời câu hỏi | Where |
|-------|------------------|-------|
| **L1: HTTP health** | "Service có sống không?" | `curl :8082/health` |
| **L2: Process logs** | "Có lỗi gì trong runtime?" | `agent.log` + `noble-pod logs` |
| **L3: MongoDB metrics** | "P50/P95 latency có đạt SLO?" | `session_metrics` collection |
| **L4: Cloud alerting** | "Khi nào page on-call?" | UptimeRobot / BetterStack / cron |

---

## L1 — Health endpoints (real-time, < 100ms)

Agent expose 2 endpoint trên port `LIVEKIT_WORKER_PORT=8082`:

| Endpoint | Trả về | Dùng khi |
|----------|--------|----------|
| `GET /health` | `{"status":"ok","ts":...}` | Liveness — process còn chạy không |
| `GET /health/ready` | `{"status":"ok\|degraded","services":{mongo,redis,llm,embeddings,...}}` 200/503 | Readiness — tất cả deps sẵn sàng phục vụ |

```bash
# Pod (local):
curl -sf http://localhost:8082/health/ready | jq

# Mac (qua RunPod proxy — nếu expose 8082, hoặc qua SSH tunnel):
ssh root@69.30.85.116 -p 22085 -L 8082:localhost:8082 -N &
curl -sf http://localhost:8082/health/ready | jq
```

Output `degraded` mẫu (LLM down):
```json
{
  "status": "degraded",
  "services": {
    "mongo": "ok",
    "redis": "ok",
    "llm": "error: timeout",
    "embeddings": "ok (onnx, 3741 chunks, 1024d)"
  }
}
```

---

## L2 — Process logs (richest signal, real-time)

`agent.log` chứa mọi event runtime. Filter qua `noble-pod logs`:

```bash
noble-pod logs --watch       # live tail filtered
noble-pod logs --ttft        # TTFT/TTFA events, >1s đỏ
noble-pod logs --fallback    # khi LLM rớt sang Gemini/Qwen cloud
noble-pod logs --errors      # ERROR + WARNING only
noble-pod logs --tools       # tool-call success/fail
noble-pod logs --turns       # pretty per-turn summary
noble-pod metrics            # tổng hợp avg/min/max + count slow events
```

### Pattern cần alert

| Pattern trong log | Ý nghĩa | Severity |
|-------------------|---------|----------|
| `Falling back from openai to gemini` | vLLM lỗi → cloud LLM gánh | ⚠️ warn (acceptable nếu rare) |
| `LLM TTFT: [12]\d{3}ms` (>=1s) | First-token chậm | ⚠️ warn |
| `E2E TTFA: [3-9]\d{3}ms` (>=3s) | Tổng latency user-cảm-được chậm | 🔴 critical |
| `[ToolHint] Pre-compute failed: 404` | Embedding endpoint sai | 🔴 critical |
| `[V10] FAQ semantic inject error` | e5-large ONNX miss | 🔴 critical |
| `bind on address ('0.0.0.0', 8082): address already in use` | Zombie process | 🔴 critical |
| `not registered worker` (60s sau start) | LiveKit không nhận agent | 🔴 critical |
| `No project_interest` + tools call empty result | Catalog logic broken | ⚠️ warn |

---

## L3 — MongoDB session metrics (historic, P50/P95/P99)

Mỗi session kết thúc, agent tự ghi vào collection `session_metrics`:
- LLM TTFT, E2E TTFA, TTS TTFB
- STT latency
- Tool-call durations
- Cloud fallback count
- Session length

### Query qua HTTP API

```bash
# Aggregate report 24h gần nhất:
curl -sf http://localhost:8082/api/metrics/report?hours=24 | jq

# Single session:
curl -sf http://localhost:8082/api/metrics/<session_id> | jq
```

### CLI

```bash
noble-pod metrics                                   # last 24h từ agent.log (in-memory)
python scripts/perf_report.py --hours 24            # MongoDB aggregate (cross-session)
python scripts/perf_report.py --hours 168           # 7 ngày
```

Output `perf_report.py` mẫu:
```
| Component | Operation     | Count | P50 ms | P95 ms | P99 ms |
| llm       | first_token   |   823 |    156 |    412 |   1234 |
| tts       | first_byte    |   823 |     89 |    234 |    567 |
| stt       | end_of_speech |   823 |    280 |    520 |    890 |
```

### SLO targets cho 1-pod RunPod (Qwen3.6-35B-A3B local vLLM)

| Metric | P50 | P95 | P99 |
|--------|-----|-----|-----|
| LLM TTFT | < 200ms | < 500ms | < 1000ms |
| E2E TTFA | < 1000ms | < 2000ms | < 3500ms |
| TTS TTFB | < 150ms | < 400ms | < 800ms |
| Cloud fallback rate | 0% | < 5% | < 10% |

P95 vượt threshold > 5 phút liên tiếp → page on-call.

---

## L4 — Cloud alerting (page on-call)

3 phương án theo độ phức tạp:

### A. UptimeRobot (free, 5 phút resolution, đơn giản)

1. https://uptimerobot.com → Add Monitor
2. Type: HTTP(s)
3. URL: `http://<pod_ip>:<exposed_port_for_8082>/health/ready`
4. Interval: 5 phút
5. Alert contacts: Telegram bot / email / SMS

**Cần expose port 8082 ra public** trên RunPod (Edit Template → Expose HTTP Ports → 8082).

### B. BetterStack / Pingdom (paid, sub-minute resolution)

Same pattern, nhưng đo từ multi-region + integrate Slack/PagerDuty.

### C. Self-hosted cron + curl (free, full control)

Trên VPS riêng:
```bash
# /etc/cron.d/noble-monitor — chạy mỗi phút
* * * * * root /usr/local/bin/noble-check.sh
```

`noble-check.sh`:
```bash
#!/bin/bash
RESPONSE=$(curl -sf -m 5 http://<pod_ip>:8082/health/ready 2>&1)
STATUS=$(echo "$RESPONSE" | jq -r '.status')
if [[ "$STATUS" != "ok" ]]; then
    # Telegram bot alert
    curl -sf "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
         -d "chat_id=$CHAT_ID" \
         -d "text=🚨 Noble agent DEGRADED at $(date): $RESPONSE"
fi
```

### D. RunPod native (basic, free)

RunPod Console → Pod → **Telemetry** tab có:
- GPU usage real-time
- VRAM usage
- CPU/RAM
- Network I/O

Không có HTTP probe alerting, chỉ tốt cho infra-level signals (GPU OOM, network drop).

---

## "Backend server không call?" — debug flowchart

Nếu user nói "agent không trả lời":

```
1. noble-pod doctor                       # toàn cảnh ✓ hay ✗
   ├─ ✗ Redis           → redis-cli ping  → restart redis
   ├─ ✗ vLLM            → tail vllm.log   → check OOM/CUDA
   ├─ ✗ Agent registered → tail agent.log → check LIVEKIT_*
   └─ ✗ MongoDB         → check Atlas IP allowlist (RunPod IP đổi mỗi pod)

2. curl :8082/health/ready                # service-level
   └─ services."llm" có error → vLLM fallback đang trigger

3. noble-pod logs --watch                 # turn-by-turn
   ├─ "registered worker" có không? → nếu không = LiveKit chưa nhận
   ├─ "Final transcript" sau khi user nói? → nếu không = STT lỗi
   ├─ "LLM TTFT" sau transcript? → nếu không = LLM hang
   └─ "TTS TTFB" sau LLM? → nếu không = TTS lỗi

4. noble-pod bench "test"                 # vLLM-only smoke test
   └─ TTFT > 500ms → vLLM chậm hoặc model chưa load

5. noble-pod metrics                      # historic
   └─ fallback count tăng → vLLM unstable, switch to cloud tạm thời
```

---

## Setup tối thiểu (5 phút, không cần infra mới)

```bash
# Pod đã chạy noble-pod start xong:
nohup bash -c 'while true; do
  curl -sf http://localhost:8082/health/ready > /tmp/health.json 2>&1 || \
    echo "$(date) DOWN" >> /workspace/health-alerts.log
  sleep 60
done' > /workspace/health-monitor.log 2>&1 &

# Theo dõi:
tail -f /workspace/health-alerts.log
```

→ Mỗi phút check, nếu fail ghi vào file. Log nhỏ, không cần cloud setup.

Production: thay `echo` bằng curl Telegram/Slack webhook.
