"""Load scenario test cases from jsonl — convert to bench_llm CASES format."""

from __future__ import annotations

import json
from pathlib import Path

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"

SCENARIO_NAMES = ["rag_only", "faq_only", "multi_project", "lookalike", "outreach", "all"]


def load_scenarios(name: str) -> list[dict]:
    """
    Load scenarios from jsonl file by name.

    Each line format:
      {"id": "r1", "query": "...", "project": "NCLB" or "NCLB,NPLB" or "",
       "expected_tool": "kb_search" | null,
       "expected_keywords": ["..."] | null,
       "note": "..."}

    name="all" loads and concatenates rag_only + faq_only + multi_project +
    lookalike + outreach.
    """
    if name == "all":
        cases: list[dict] = []
        for sub in ["rag_only", "faq_only", "multi_project", "lookalike", "outreach"]:
            cases.extend(load_scenarios(sub))
        return cases

    path = SCENARIOS_DIR / f"{name}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")

    cases = []
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    return cases
