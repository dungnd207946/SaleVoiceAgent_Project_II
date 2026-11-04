# v5 — Test harness for emergent skill routing

**Purpose:** Test full LLM logic with v5 prompt architecture **without modifying `src/`**.

## What's in v5

- 4-layer prompt architecture (ORG_BASE + VOICE_STYLE + agent persona + skill manifest + optional active skill) with `───DYN───` cache boundary.
- **No keyword-based routing**: skills loaded as natural-language descriptions, LLM emerges routing via `tool_choice="auto"`.
- Tool schemas loaded dynamically from `src/agent/tools/schemas.py` (source of truth, no duplication).
- Router hint via `switch_agent.suggested_skill` → narrows `tool_groups` filter, optional.

## File tree

```
tests/
├── prompt_versions/
│   └── v5/
│       ├── VERSION.md               # changelog
│       ├── config.json              # agents + tool_groups
│       ├── base/
│       │   ├── ORG_BASE.md          # Layer A shared
│       │   └── VOICE_STYLE.md       # Layer A positive voice rules
│       ├── agents/
│       │   ├── router.md            # Layer B Luna Router
│       │   ├── consultant.md        # Layer B Consultant + skill_manifest
│       │   └── support.md           # Layer B Support
│       ├── skills/                  # Layer C flat (not nested in agents/)
│       │   ├── info.md              # use_when: natural-language, no keywords
│       │   ├── pricing.md
│       │   ├── advisor.md
│       │   ├── booking.md
│       │   ├── support-crm.md
│       │   └── support-escalation.md
│       └── tools/
│           ├── schemas.md           # doc (not loaded at runtime)
│           └── handoff.md           # doc for switch_agent design
├── registry_v5.py                   # standalone registry (reads v5 only)
├── eval_v5_scenarios.py             # labeled scenarios for emergent routing
└── bench_v5.py                      # test runner
```

## Usage

### Quick sanity check — inspect generated prompts

```bash
cd tests
python registry_v5.py --agent router
python registry_v5.py --agent consultant --skill pricing --project NCLB --name Cường --gender M
python registry_v5.py --agent consultant  # no hint → full skill expose
python registry_v5.py --agent support --skill support-crm --json
```

### Run emergent routing bench

```bash
# Quick: 1 case, 1 run
python tests/bench_v5.py --url $LLM_URL --model $MODEL \
  --case E-INFO-01 --runs 1

# Full suite
python tests/bench_v5.py --url http://localhost:8000/v1 \
  --model Qwen/Qwen3-14B-Instruct --category all --runs 3 \
  --json-output /tmp/v5_bench.json

# Compare hint vs no-hint on same cases (measure hint value)
python tests/bench_v5.py --url ... --model ... \
  --category emergent_hint --runs 3                       # with hint
python tests/bench_v5.py --url ... --model ... \
  --category emergent_hint --runs 3 --no-hint             # forced no hint

# CI gate
python tests/bench_v5.py --url ... --model ... \
  --category all --runs 5 \
  --fail-if-leak-above 0.01 --fail-if-acc-below 0.85
```

## Scenarios structure (9 categories)

| Category | Purpose | Expected behavior |
|---|---|---|
| `emergent_info` / `_pricing` / `_advisor` / `_booking` | Consultant picks right skill from 4 WITHOUT router hint | LLM reads skill_manifest, calls tool from correct skill group |
| `emergent_adversarial` | User message lacks obvious keyword (e.g. "đắt không" instead of "giá") | LLM still routes correctly via semantic understanding |
| `emergent_topic_switch` | Mid-conversation topic change (info→pricing or pricing→booking) | Consultant switches tool call WITHOUT calling switch_agent again |
| `emergent_hint` | Router passes `suggested_skill` → tools narrowed | LLM calls from narrowed tool group |
| `emergent_support` | Support routes between support-crm and support-escalation | LLM picks right support skill |
| `emergent_no_leak` | Validate no "chuyển cuộc gọi" leak during switch_agent | No forbidden phrases in response |

## How it avoids modifying `src/`

1. **Registry**: `registry_v5.py` is standalone — does NOT import `src/agent/registry.py`. Reads v5 files from `tests/prompt_versions/v5/` directly.
2. **Tool schemas**: `registry_v5.py` dynamically imports `TOOL_DEFINITIONS` from `src/agent/tools/schemas.py` to avoid duplicating 18 schemas — but doesn't modify that file, just reads it.
3. **Session state**: `customer_state` and `handoff_summary` are passed as kwargs to `build_agent_prompt_v5()`, not pulled from Redis. Tests are self-contained.
4. **FAQ data**: reads `data/faq/*.md` same as production; no changes needed.
5. **No monkey-patching**: bench_v5.py doesn't patch `src/agent/registry.py` like `bench_prompt.py:_patch_registry()` does — it calls `registry_v5` directly.

## Promotion path (when ready)

After v5 proves out in bench:

1. Copy `tests/prompt_versions/v5/` → `src/agent/definitions_v5/` (or replace `src/agent/definitions/`).
2. Copy `tests/registry_v5.py` → `src/agent/registry_v5.py` and adjust `_V5_ROOT` + imports.
3. Update `src/agent/llm/streaming.py` to call `build_agent_prompt_v5()` instead of `registry.build_agent_prompt()`, passing `suggested_skill` from `switch_agent.suggested_skill` + `customer_state` from `session_store`.
4. Flip `USE_REGISTRY_V5` feature flag.
5. Deprecate legacy `registry.py` after 2-week soak.

## Acceptance thresholds

Before promoting v5 to `src/`:

| Metric | Target |
|---|---|
| Tool accuracy (exact name match, no hint) | ≥ 85% |
| Tool-in-group accuracy (suggested_skill correctly narrows) | ≥ 95% |
| Forbidden phrase leak rate | ≤ 0.5% |
| Topic switch handling (consultant pricing→booking) | ≥ 90% |
| Avg prompt tokens consultant (with FAQ, no hint) | ≤ 4000 |
| Avg prompt tokens consultant (with hint, active skill only) | ≤ 2200 |

Run `bench_v5.py --category all --runs 5` and validate against these.
