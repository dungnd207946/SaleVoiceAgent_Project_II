"""Bench-only runtime patches for prompt versions v7-bench / v8-bench.

These monkey-patch noble_agent.agent.registry/tools at bench time only.
Not used in production. Imported by tests/bench_llm.py via _patch_prompt_version.
"""
