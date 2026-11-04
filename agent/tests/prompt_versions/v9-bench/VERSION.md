# v9-bench — Production-Clean + Outreach Activation

Snapshot of `src/noble_agent/agent/definitions/` AFTER the DRY cleanup of
the `send_via_app` (outreach) workflow. No runtime patches are applied
for v9; all behaviour comes from production code paths.

## Origin
- Cloned from `src/noble_agent/agent/definitions/` (production).
- 4 agents: router, consultant, support, outbound_callback.
- 19 tools (full production set) including `send_via_app`.

## DRY changes vs. pre-cleanup production
The following files were trimmed in production BEFORE v9-bench was cut.
v9-bench inherits the trimmed versions:

1. `agents/consultant/skills/consultant-info/SKILL.md`
   - `INQ_RICH_CONTENT` block: 13 lines → 5 lines.
   - Channel-aware confirmation rules (noblex / sms / fallback narration)
     deleted from skill — single source of truth is
     `tools/send_via_app/TOOL.md`.

2. `agents/support/skills/support-escalation/SKILL.md`
   - `<post_transfer_followup>` block: 14 lines → 8 lines.
   - Same channel rules deleted; skill now points to TOOL.md.

3. `tools/send_via_app/TOOL.md` — unchanged (52 lines, the single source
   of truth for filler / channel rules / fallback narration).

## What v9-bench adds for the outreach benchmark
Nothing inside this directory. v9-bench IS the production prompt; the
bench infrastructure additions live outside:

- `tests/bench_rag/scenarios/outreach.jsonl` — 6 cases (3 positive
  expecting `send_via_app`, 3 negative).
- `_FAKE_TOOL_RESPONSES["send_via_app"]` in `tests/bench_llm.py` for
  non-`--chat-full` modes (returns `channel="noblex"` so the
  confirmation pattern can be inspected).
- `tests/prompt_versions/registry.json` entry.

## Run

### Scenario accuracy (fake responses)
```bash
python3 tests/bench_llm.py --rag --scenario outreach
```

### Full pipeline with real outreach (requires HOTLINE_OUTREACH_* env)
```bash
python3 tests/bench_llm.py --chat-full --version v9-bench
```
Then in chat:
```
You: số mình là 0 9 4 2 8 6 6 9 3 9
You: cho xin map quy hoạch Noble Crystal Long Biên
```
Real backend at `HOTLINE_OUTREACH_URL` will deliver SMS / NobleX push to
the seeded phone.
