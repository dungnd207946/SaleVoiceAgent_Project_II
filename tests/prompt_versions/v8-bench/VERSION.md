# v8-bench — Prompt Hierarchy Cleanup + FAQ Search

Changes from v7-bench:
1. Removed duplicated `<portfolio>` and `<organization>` blocks from shared/RULES.md
   (kept single source in shared/PROJECTS.md).
2. Added shared/FAQ_INSTRUCTION.md — 3-line rule for FAQ priority at prompt tail.
3. Removed A1 `_COMMON.md` prepend (replaced by searched FAQ at tail via v8 patches).
4. Added A5 layout reorder — customer context + FAQ move to prompt tail
   for prompt-caching stability (byte-identical stable prefix).

Expected impact:
- Prompt size: 42K -> ~15-18K chars (-60%)
- TTFT turn 2+: leverages prompt cache for stable prefix
- FAQ inject: every turn via searched top-K (not only on agent switch)

## Run

```bash
python3 tests/bench_llm.py --chat-full --version v8-bench
```
