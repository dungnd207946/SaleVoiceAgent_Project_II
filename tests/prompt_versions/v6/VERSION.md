# v5 — Emergent skill routing + 4-layer cache-friendly prompts

Changes vs v3:
- Layer A shared (ORG_BASE + VOICE_STYLE) — positive directives, no negative repetition
- Layer B agent persona — trimmed, no duplicate with RULES
- Layer C skill manifest — natural-language use_when, NO trigger_keywords
- Layer D dynamic — customer + FAQ + handoff_summary AFTER cache boundary (───DYN───)
- Tool docs moved to JSON schemas (tools API param, strict=true)
- Emergent skill routing via LLM tool_choice="auto" + allowed_tools filter when router hints suggested_skill
- NO keyword matching for intent/skill routing (research-backed, Anthropic Agent Skills pattern)

Expected tokens:
- Router: 1100 (from 4430, -75%)
- Consultant (no skill scope, full 4 skill + FAQ): ~3800 (from 11055, -66%)
- Support (full 2 skill): ~1900 (from 5540, -66%)

See: docs/analysis/llm-optimization/11-skill-routing-final.md for decision rationale.
