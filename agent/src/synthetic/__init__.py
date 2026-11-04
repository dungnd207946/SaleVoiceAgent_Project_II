"""Customer Agent (CA) simulator for synthesizing Noble Voice Agent SFT data.

Spins up a persona-driven LLM that plays a Vietnamese real-estate customer,
calls the live Noble Agent (`noble_agent.agent.facade.NobleAgent`),
captures the full OpenAI-format thread (assistant tool_calls + tool results
+ assistant text), and dumps it as JSONL matching `data/eval_processed/eval_sft.json`.
"""
