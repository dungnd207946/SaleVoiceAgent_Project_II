# Load test v2 — santa-hotline-agent

Stress-to-break tooling. Load runs **from a LAN client** (e.g. the Mac) against
`10.50.12.70`; resource sampling runs **on the server**. Replaces the dead sipp
harness in `scripts/load_test/` (self-hosted LiveKit SIP no longer exists — voice
is on LiveKit Cloud).

## Layout

| File | Role |
|---|---|
| `common.py` | ramp schedule / async step driver / percentiles / knee detection / report writer. Pure parts unit-tested: `python -m pytest test_common.py` |
| `phase_a_embed.py` | embed service load client (`:8013`, HTTP `POST /embed`) |
| `phase_a_tts.py` | TTS service load client (`:8011`, WS) — GPU-bound |
| `phase_a_stt.py` | STT service load client (`:8012`, WS) — reads `fixture_16k.pcm` |
| `build_stt_fixture.py` | (re)builds `fixture_16k.pcm` from an ack asset (24k→16k + 3 s trailing silence). Needs numpy+scipy; not needed by the client at runtime. |
| `phase_b_chat.py` | chat WS end-to-end client (`:8766/chat`), persistent sessions |
| `llm_stub.py` | OpenAI-compatible streaming fake (Phase B infra isolation) |
| `sampler.sh` | server-side `nvidia-smi` + `docker stats` sampler → `gpu.csv` + `containers.log` |

## Breaking point

Each concurrency step is held ~60 s; the client ramps `1,2,4,8,…,max`. With
`full_ramp=True` (the default in the clients) every step runs and the **knee** =
highest concurrency where throughput still scaled ≥15% over the previous step and
errors stayed <1% (`knee_by_plateau`). The raw curve + the 2×-baseline signal are
both in the results table.

## Run Phase A (no server change)

```bash
python phase_a_embed.py --hold 60 --max 128 --out out/phaseA/embed
python phase_a_stt.py   --hold 60 --max 128 --out out/phaseA/stt
python phase_a_tts.py   --hold 60 --max 16  --out out/phaseA/tts
```

Sampler (run on the server, per run; SSH is interactive/password):

```bash
# on the server
nohup bash /tmp/sampler.sh /tmp/samp_X 2 >/tmp/samp_X.log 2>&1 & echo $! >/tmp/samp_X.pid
# ...run the client from the LAN client...
kill $(cat /tmp/samp_X.pid)
# then read /tmp/samp_X/gpu.csv + containers.log
```

> Note: starting/stopping the sampler over a **detached/background** SSH session is
> unreliable (no controlling terminal for the password prompt, and `&`-detached jobs
> get orphaned). Start it from a foreground SSH call with an explicit pidfile + a short
> `sleep` before the session exits, and pull the logs with a plain `cat` (not inside a
> `for`-loop/pipe, which mangled capture in testing).

## Run Phase B (chat E2E, LLM stubbed)

The stub isolates infra from gemini's latency/rate-limits. It is **text-only** (emits
no tool calls), so Phase B exercises orchestration + Redis + Mongo + LLM plumbing, but
**not** the `noble_search`→Qdrant/embed path (that's covered by Phase A's embed test).

```bash
# 1. run the stub on the LAN client
python llm_stub.py --port 8099 --tps 50 &
# 2. on the server: back up .env, repoint the OpenAI slot + pin all model roles to the stub
cd ~/deploy/santa-hotline-agent && cp .env .env.loadtest-bak
sed -i 's#^OPENAI_BASE_URL=.*#OPENAI_BASE_URL=http://<CLIENT_IP>:8099/v1#' .env
sed -i 's#^OPENAI_MODEL=.*#OPENAI_MODEL=stub#;s#^OPENAI_API_KEY=.*#OPENAI_API_KEY=stub#' .env
sed -i 's#^NOBLE_AGENT_MODEL=.*#NOBLE_AGENT_MODEL=stub#' .env
sed -i 's#^NOBLE_SUMMARY_MODEL=.*#NOBLE_SUMMARY_MODEL=stub#' .env
sed -i 's#^NOBLE_SUGGESTIONS_MODEL=.*#NOBLE_SUGGESTIONS_MODEL=stub#' .env
docker compose -f docker-compose.local.yml up -d agent agent-lk
# 3. run the campaign
python phase_b_chat.py --hold 60 --max 128 --out out/phaseB
```

## Revert checklist (Phase B) — MANDATORY

1. `cd ~/deploy/santa-hotline-agent && mv .env.loadtest-bak .env`
2. `docker compose -f docker-compose.local.yml up -d agent agent-lk`
3. Verify a chat turn returns varied gemini text (not the canned stub sentence
   "Dạ em xin phép trả lời…").
4. Kill the stub on the client: `pkill -f llm_stub.py`.
