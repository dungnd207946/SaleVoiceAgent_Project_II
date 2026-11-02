# v7-bench — v6 prompts + code patches A1+A2+A3+A4 (tests-only, no src/ change)

## Includes (vs v6-bench)

Prompts: identical to v6-bench (no prompt content change).

Runtime patches via `tests/registry_v6_patches.py` activated when `--version v7-bench`:

- **A1** — inject `_COMMON.md` always into system prompt (brand-common 20 Q/A).
  → "đặt cọc nhiêu", "VAT", "phí bảo trì", "hotline", "vay ngân hàng" answer ngay không tool call.

- **A2** — expand `_PROJECT_FAQ_MAP` với phonetic aliases ("tay ho", "long bien", "thang long", "sunshine", "legend", "palace long bien").
  → Catch ASR no-diacritic + variant tên dự án.

- **A3** — scan last-5 messages từ session history để infer project_interest (thay vì chỉ `switch_query` block).
  → Catch khi khách nói "long biên" / "tây hồ" trong giữa cuộc.

- **A4** — Tier 1 auto-set project_interest sau action tools: `check_availability`, `schedule_viewing`, `update_booking_info`.
  → Persist project ngay khi khách commit (đặt lịch / xem slot trống).

## How it works

`bench_llm.py:_patch_prompt_version("v7-bench")`:
1. Swap `agent.registry._REGISTRY_DIR` → `tests/prompt_versions/v7-bench/`.
2. Import + call `tests.registry_v6_patches.apply_v7_patches()` → monkey-patch:
   - `agent.registry._PROJECT_FAQ_MAP` (in-place dict update, A2)
   - `agent.registry.build_agent_prompt` (wrapped async, A1+A3)
   - `agent.tools.execute_tool` (wrapped async, A4)

`_unpatch_prompt_version()`:
1. Restore `_REGISTRY_DIR`.
2. Call `revert_v7_patches()` → restore originals.

## Run

```bash
python3 tests/bench_llm.py --version v7-bench
```

## Validation expected vs v6-bench

Same conversation flow trace (user's session), expected behavior changes:
- "đặt cọc nhiêu tiền" → answer từ `_COMMON.md`, no `get_project_financial` call.
- After "long biên e ơi" turn → A3 history scan → save NCLB → next turn FAQ NCLB injected.
- After `check_availability(NCLB)` fire → A4 auto-set project_interest=NCLB.
- "căn ở tây hồ bị hỏng bếp" turn → A3 catch "tây hồ" → inject NCTH FAQ for support agent.

## Promote về src/ sau bench OK

Khi v7 bench stable → port logic A1+A2+A3+A4 từ `registry_v6_patches.py` về:
- `src/agent/registry.py` (A1+A2+A3)
- `src/agent/tools/__init__.py` (A4)

Pattern wrapper → inline integration.
