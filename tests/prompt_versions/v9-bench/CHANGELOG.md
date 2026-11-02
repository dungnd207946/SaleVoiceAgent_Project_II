# v9-bench Change Log

Detailed list of every file added or modified to ship v9-bench. Use this
file to audit the diff during code review or when bisecting regressions.

## Production cleanup (DRY) — done first, then snapshot to v9
File: `src/noble_agent/agent/definitions/agents/consultant/skills/consultant-info/SKILL.md`
- BEFORE: 76 lines. `INQ_RICH_CONTENT` (lines 22-34) duplicated the
  filler text + channel-aware confirmation table that already exists in
  `tools/send_via_app/TOOL.md`.
- AFTER: 69 lines. `INQ_RICH_CONTENT` reduced to 5 lines that delegate
  to `TOOL.md` for filler / channel rules / fallback narration.

File: `src/noble_agent/agent/definitions/agents/support/skills/support-escalation/SKILL.md`
- BEFORE: 87 lines. `<post_transfer_followup>` (lines 56-69) had the same
  duplication of channel rules and ok=true/false handling.
- AFTER: 83 lines. Block compressed to 8 lines that delegate channel
  handling to `TOOL.md`.

No tool schema or dispatcher code was touched. The send_via_app tool was
already wired end-to-end in production (schema → dispatcher → outreach
service → backend at `HOTLINE_OUTREACH_URL`).

## v9-bench prompt-version directory
Path: `tests/prompt_versions/v9-bench/`
- Created via `cp -r src/noble_agent/agent/definitions tests/prompt_versions/v9-bench`.
- 40 files, 196 KB.
- VERSION.md overwritten to describe v9 (the cp picked up an unrelated
  v8-bench VERSION.md that lives inside production by accident).
- This CHANGELOG.md added.

## Bench infrastructure changes outside v9-bench
File: `tests/bench_llm.py`
- `_FAKE_TOOL_RESPONSES` (around line 1149) — added `send_via_app` entry
  returning `{"ok": true, "channel": "noblex", "delivery_id":
  "out-mock-001"}` so non-`--chat-full` modes can simulate the
  channel-aware confirmation pattern.

File: `tests/bench_rag/scenarios_loader.py`
- `SCENARIO_NAMES` (line 9) — added `"outreach"`.
- `load_scenarios("all")` now includes the outreach set.

File: `tests/bench_rag/scenarios/outreach.jsonl` (new)
- 6 single-turn cases:
  - o1-o3: positive (`expected_tool=send_via_app`) — map / brochure /
    bản vẽ.
  - o4-o5: negative (`expected_tool=null`) — voice can answer well.
  - o6: discriminator (`expected_tool=search_units`) — make sure the
    model does not over-trigger send_via_app for product-type questions.

File: `tests/prompt_versions/registry.json`
- Added `v9-bench` entry, base `v8-bench`, expected_tokens estimated
  (router 2000 / consultant 5500 / support 3500); update after first
  bench run.

## How to verify
```bash
# Lint
ruff check src/noble_agent tests/

# Scenario accuracy on outreach (uses fake responses, no patches)
python3 tests/bench_llm.py --rag --scenario outreach

# Real-tool smoke test — requires HOTLINE_OUTREACH_* env (already in .env)
python3 tests/bench_llm.py --chat-full --version v9-bench
# In chat: provide phone "0 9 4 2 8 6 6 9 3 9", then ask "cho xin map
# quy hoạch Noble Crystal Long Biên" — backend should deliver SMS to
# 0942866939 (or NobleX push if number has the app).
```
