# Phase C — E2E voice (LiveKit, production path)

ttfr = emit → first agent_speaking. total = emit → agent_done. Events read from the `agent-events` LiveKit data channel. LLM stubbed to isolate infra.

| calls | turns ok | failed turns | failed calls | ttfr p50 | ttfr p95 | total p50 | total p95 | greet p50 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 32 | 40 | 0 | 0 | 9522 | 13379 | 23288 | 28367 | 21274 |
