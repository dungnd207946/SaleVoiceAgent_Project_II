"""Transport layer abstractions for the voice agent.

Concrete transports live in submodules:
- `noble_agent.server.ws_handler` + `noble_agent.server.session` — aiortc/WebSocket (legacy)
- `noble_agent.transport.livekit` — LiveKit RTC + SIP (migration target, see LIVEKIT_MIGRATION.md)

Both paths coexist until Phase 9 cleanup. Selection is driven by the
`TRANSPORT_BACKEND` env var.
"""
