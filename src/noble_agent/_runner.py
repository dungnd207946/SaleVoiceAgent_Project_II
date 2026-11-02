"""Compat shim — some scripts import `noble_agent._runner.main`."""

from noble_agent.__main__ import main

__all__ = ["main"]
