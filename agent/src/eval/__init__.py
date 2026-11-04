"""Teacher-forcing evaluation for the synthetic SFT reference data.

Two phases (CLI: ``PYTHONPATH=src python -m eval run|score``):
  run   — replay each reference prefix, ask the agent LLM for the next turn.
  score — rule-based tool-call metrics + Luna response axes + optional LLM judge.
"""
