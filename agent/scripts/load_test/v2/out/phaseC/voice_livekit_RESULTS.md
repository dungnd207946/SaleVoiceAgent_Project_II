# Phase C — E2E voice (LiveKit, production path)

ttfr = emit → first agent_speaking. total = emit → agent_done. Events read from the `agent-events` LiveKit data channel. LLM stubbed to isolate infra.

| calls | turns ok | failed turns | failed calls | ttfr p50 | ttfr p95 | total p50 | total p95 | greet p50 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 3 | 0 | 0 | 6264 | 6511 | 18120 | 18867 | 13155 |
| 2 | 6 | 0 | 0 | 6125 | 6401 | 17952 | 18689 | 12987 |
| 4 | 10 | 0 | 0 | 6141 | 6446 | 18129 | 18618 | 16480 |
| 6 | 17 | 0 | 0 | 6185 | 6624 | 18097 | 18891 | 13944 |
| 8 | 21 | 0 | 0 | 6229 | 6763 | 17977 | 18664 | 15836 |
| 10 | 28 | 0 | 0 | 6320 | 6687 | 18070 | 18558 | 14600 |
| 12 | 30 | 0 | 0 | 6362 | 6852 | 18328 | 18918 | 16210 |
| 16 | 38 | 0 | 0 | 6314 | 6922 | 18216 | 19121 | 16929 |
