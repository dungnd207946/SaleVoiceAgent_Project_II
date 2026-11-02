# v6-bench — v5 content in v0-v3 compat layout

Purpose: Run bench_llm.py --version v6-bench against full production pipeline
(StreamingLLM + real tools + session_store) using v5 prompt content.

Changes vs v3:
- Positive voice style (ORG_BASE + VOICE_STYLE merged into shared/RULES.md)
- Emergent skill routing — no trigger_keywords, natural-language use_when descriptions
- Trimmed IDENTITY (duplicate with RULES removed)
- Skill manifest in consultant/support IDENTITY explains when each skill applies

Limitations vs pure v5 (tests/registry_v5.py):
- Customer context stays in system prompt (no user_prefix split)
- No per-skill tool filtering (all agent tools exposed)
- No ───DYN─── cache boundary marker
- No allowed_tools narrowing based on suggested_skill hint

For pure v5 validation use:
  python tests/bench_v5.py --url ... --model ... --category all

For production integration test use:
  python tests/bench_llm.py --version v6-bench
