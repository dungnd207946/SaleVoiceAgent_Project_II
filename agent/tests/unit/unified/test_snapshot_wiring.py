"""Bootstrap no longer gates short-term on a removed enable flag."""

from __future__ import annotations

import inspect

from noble_agent.agent import orchestrator


def test_orchestrator_no_user_memory_enabled_gate():
    src = inspect.getsource(orchestrator)
    # The removed flag must not be referenced anywhere in the orchestrator.
    assert "user_memory_enabled" not in src
    # short-term block is still wired in.
    assert "short_term_block" in src
