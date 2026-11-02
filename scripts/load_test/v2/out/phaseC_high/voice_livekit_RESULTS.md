# Phase C — E2E voice (LiveKit, production path)

ttfr = emit → first agent_speaking. total = emit → agent_done. Events read from the `agent-events` LiveKit data channel. LLM stubbed to isolate infra.

| calls | turns ok | failed turns | failed calls | ttfr p50 | ttfr p95 | total p50 | total p95 | greet p50 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 8 | 0 | 0 | 6589 | 6715 | 18568 | 18701 | 23291 |
| 16 | 29 | 0 | 0 | 6531 | 6916 | 18272 | 18698 | 17933 |
| 24 | 41 | 0 | 0 | 6593 | 8329 | 18303 | 19688 | 23167 |
| 32 | 42 | 0 | 0 | 10205 | 21674 | 23839 | 38282 | 24934 |
