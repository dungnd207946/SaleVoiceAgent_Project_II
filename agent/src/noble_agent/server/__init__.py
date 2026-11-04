"""Server package — WebSocket + HTTP handlers + session management.

Imports are lazy for the aiortc-dependent modules (websockets/aiortc are
heavy and optional in a LiveKit-only deployment). `base_session` is
imported eagerly because it has no transport-specific dependencies and is
shared by both transports.
"""

from noble_agent.server import base_session  # noqa: F401 — eager for patch/import
from noble_agent.server.logging_config import setup_logging


def __getattr__(name):
    """Lazy-load heavy transport-specific modules only when accessed."""
    if name == "process_request":
        from noble_agent.server.http import process_request

        return process_request
    if name == "handler":
        from noble_agent.server.ws_handler import handler

        return handler
    if name == "Session":
        from noble_agent.server.session import Session

        return Session
    raise AttributeError(f"module 'server' has no attribute {name!r}")


__all__ = ["setup_logging", "process_request", "handler", "Session", "base_session"]
