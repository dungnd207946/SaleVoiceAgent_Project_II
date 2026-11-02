# src/noble_agent/tenant/current.py
"""Per-request tenant identity via a ContextVar.

The single source of truth for "which tenant is this request for" inside a
shared multi-tenant process. NEVER read settings.tenant_id on the request/data
path — call current_tenant() instead. Unset → falls back to settings.tenant_id
so single-tenant deployments are byte-identical.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token

_current: ContextVar[str | None] = ContextVar("noble_current_tenant", default=None)


def set_current_tenant(tenant_id: str | None) -> Token:
    """Set the current tenant; returns a token for reset_current_tenant()."""
    return _current.set(tenant_id or None)


def reset_current_tenant(token: Token) -> None:
    _current.reset(token)


def current_tenant() -> str:
    """The request's tenant id, else the process default (settings.tenant_id)."""
    tid = _current.get()
    if tid:
        return tid
    from noble_agent.config import get_settings

    return get_settings().tenant_id


# ── agent_key_id per-connection ──────────────────────────────────────────────
# Định danh API key Portal đã auth ra connection này (gateway trả về cùng
# credential). Per-CONNECTION chứ không per-tenant: một tenant có nhiều key
# (chat/voice) nên không để trong registry tenant_credentials được. Đặt ở entry
# transport (text_chat / LiveKit job); pg_data_plane đọc để đóng dấu
# conversations.agent_key_id. Unset → "" → cột NULL (dev/REPL/telephony).
_current_agent_key: ContextVar[str | None] = ContextVar("noble_current_agent_key_id", default=None)


def set_current_agent_key_id(agent_key_id: str | None) -> Token:
    """Set agent_key_id của connection hiện tại; trả token để reset."""
    return _current_agent_key.set(agent_key_id or None)


def reset_current_agent_key_id(token: Token) -> None:
    _current_agent_key.reset(token)


def current_agent_key_id() -> str:
    """agent_key_id của connection hiện tại, rỗng khi không đi qua gateway."""
    return _current_agent_key.get() or ""


@contextmanager
def use_tenant(tenant_id: str | None):
    """Scope a block to a tenant. Empty/None → inherit the outer value."""
    token = _current.set(tenant_id or None) if tenant_id else _current.set(_current.get())
    try:
        yield
    finally:
        _current.reset(token)



# Hàm trả "org của tenant hiện tại" XOÁ 2026-08-15: không còn khái niệm org.
