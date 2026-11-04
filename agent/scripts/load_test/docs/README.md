# Load Testing — Phase 6

End-to-end load harness for the `noble-hotline-agent` over LiveKit SIP.
See `LIVEKIT_MIGRATION.md` §5 Phase 6 for the exit criteria.

```
sipp → LiveKit SIP → LiveKit Server → worker (RoomSession)
                                         └── STT → LLM → TTS → RTP back
```

sipp plays a pre-baked Vietnamese utterance at the caller side; the
worker runs the real pipeline (STT, RAG, LLM, TTS). Per-session latency
rolls up to MongoDB `session_metrics`; the driver aggregates it at the
end of the run.

## Layout

```
tests/load/
├── README.md                        — this file
├── CONCERNS_7_2_AUDIT.md            — pre-run singleton audit
├── scenarios/
│   └── basic_call.xml               — sipp scenario (INVITE/RTP/BYE)
├── fixtures/
│   └── utterance_pcmu.pcap          — 20 ms-framed PCMU (generated)
└── out/                             — per-run artefacts (gitignored)
    └── <ISO8601>/
        ├── sipp_stdout.log
        ├── sipp_stats.csv
        ├── sipp_errors.log
        ├── aggregate.json
        ├── mem_samples.json
        └── LOAD_TEST_RESULTS.md

scripts/load_test/
├── gen_pcap.py                      — PCM16/WAV → PCMU pcap
└── run_load_test.py                 — orchestrator + report writer
```

## Prereqs

| what | how |
|---|---|
| `sipp` | `brew install sipp` |
| LiveKit + LiveKit-SIP | `docker compose --profile livekit up -d` |
| `.env` | `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, real `OPENAI_API_KEY` / `ELEVENLABS_API_KEY` / `SONIOX_API_KEY` |
| Mongo + Redis | already in the default compose profile |
| Agent worker | `uv run python -m noble_agent --transport livekit dev` (leave running in its own terminal) |
| SIP trunk + dispatch rule | `uv run python scripts/load_test/provision_sip.py` (once per container restart — trunks live in Redis) |

Before the first run the driver auto-generates `fixtures/utterance_pcmu.pcap`
from `assets/voice/acks/01_em_can_kiem_tra...pcm` via `gen_pcap.py`.
Drop in your own utterance if you want longer STT input (must be 16-bit
PCM; pass `--raw --rate <Hz>` if not a `.wav`).

## The SIP trunk + dispatch rule

LiveKit SIP v1.11+ stores trunks/rules in Redis, not in `sip.yaml`.
`scripts/load_test/provision_sip.py` wipes any previous `loadtest-*`
entries and recreates:

- trunk `loadtest-trunk` — number `+84999000001`, `allowed_addresses: 0.0.0.0/0`
- dispatch rule `loadtest-dispatch` — wires incoming calls to agent `noble-hotline-agent`

Re-run it any time you recreate the compose stack (Redis volume is
ephemeral if you `docker compose down -v`).

## Smoke test (1 call)

```bash
docker compose --profile livekit up -d
uv run python scripts/load_test/provision_sip.py      # once per stack boot
uv run python -m noble_agent --transport livekit dev    # terminal A
uv run python scripts/load_test/run_load_test.py \
    --concurrent 1 --calls 1                            # terminal B
```

Inspect `tests/load/out/<ts>/LOAD_TEST_RESULTS.md`. Success = return
code 0 + `session_count: 1` in the aggregate + non-zero latency rows
for `stt`, `llm`, `tts`, `e2e`.

## Phase 6 soaks

Targets (plan §5 Phase 6):

| Run | concurrent | calls / duration | target |
|---|---:|---|---|
| 10-conc soak | 10  | duration 1800  | p95 E2E < 1.5 s |
| 50-conc soak | 50  | duration 3600  | no voice bleed, stable RSS |
| 100-conc soak | 100 | duration 3600  | no crashes, no state leak |

```bash
# 10-concurrent, 30 min
uv run python scripts/load_test/run_load_test.py \
    --concurrent 10 --calls 0 --duration 1800 --rate 2 \
    --worker-pid $(pgrep -f 'noble_agent.*livekit' | head -1)

# 50-concurrent, 1 h
uv run python scripts/load_test/run_load_test.py \
    --concurrent 50 --calls 0 --duration 3600 --rate 5 \
    --worker-pid $(pgrep -f 'noble_agent.*livekit' | head -1)

# 100-concurrent, 1 h
uv run python scripts/load_test/run_load_test.py \
    --concurrent 100 --calls 0 --duration 3600 --rate 10 \
    --worker-pid $(pgrep -f 'noble_agent.*livekit' | head -1)
```

`--worker-pid` enables 5-s-interval RSS sampling; the markdown report
shows drift (last − first) and peak. Skip it (pass `0`) if the worker
is inside a docker container — sample the container instead via
`docker stats`.

## Memory profiling (hunt leaks)

1. Start the worker with tracemalloc on:
   ```bash
   TRACEMALLOC_ENABLED=1 uv run python -m noble_agent --transport livekit
   ```
2. During/after a soak, dump the top-30 allocation sites:
   ```bash
   kill -USR1 $(pgrep -f 'noble_agent.*livekit' | head -1)
   cat /tmp/noble_tracemalloc_<pid>.txt
   ```

## Failure scenarios (plan §5 Phase 6 bullet 4)

Run the 10-concurrent soak and in a separate terminal:

| failure | command | expected |
|---|---|---|
| worker killed | `kill -9 $WORKER_PID` | sipp reports `FailedCall(C)` spike; no Mongo corruption |
| Redis down | `docker compose stop redis` | active calls keep running (in-mem state); new writes DLQ |
| Mongo down | `docker compose stop mongo` | Mongo DLQ pushes to Redis (`tenacity` + `with_mongo_retry_and_dlq`) |
| LLM 5xx | `unset OPENAI_API_KEY` | StreamingLLM falls through to Qwen → Gemini |
| LiveKit restart | `docker compose restart livekit` | in-flight calls drop; worker reconnects on next job |

Observe via the aggregate latency + `counters` section of the generated
report.

## Exit criteria

- 10/50/100-concurrent runs all return `sipp_returncode=0` (every
  `INVITE` got a `200 OK`).
- p95 E2E `ttfa` < 1500 ms at 10-concurrent, < 2500 ms at 100-concurrent
  (Plan §10 allows soft degradation).
- RSS drift over 1 h < 50 MiB per worker process.
- No `FailedCallUnexpectedMessage(C)` in sipp stats (i.e. no SIP flow
  breakage).
- Each session's RAG context correct for its `project_interest` — see
  `CONCERNS_7_2_AUDIT.md` §1; fix that cache-bleed before the 50-conc
  run.

## Known blockers (from `docs/migration/CHECKPOINT.md`)

- `tests/test_telephony_pipeline.py` fails on `soxr` missing; unrelated
  to Phase 6.

## Regenerating the utterance pcap

```bash
# from a wav (any rate, 16-bit mono)
uv run python scripts/load_test/gen_pcap.py \
    --in path/to/voice.wav \
    --out tests/load/fixtures/utterance_pcmu.pcap

# from a raw PCM16 @ 24 kHz (e.g. the ack asset)
uv run python scripts/load_test/gen_pcap.py \
    --in assets/voice/acks/01_em_can_kiem_tra_thong_tin_trong_he_thong_quy_khach.pcm \
    --raw --rate 24000 \
    --out tests/load/fixtures/utterance_pcmu.pcap
```
