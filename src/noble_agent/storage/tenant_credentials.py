"""Credential Postgres per-tenant do gateway forward (X-PG-Role/-Password/-Expires).

Registry in-process {tenant_id → TenantPgCredential}: ws_handler đăng ký khi mở
session chat qua gateway; `postgres_client.pool_for_tenant` đọc để dựng pool riêng.
Không có entry (dev local, REPL, voice, heartbeat) nghĩa là "dùng shared DSN" —
không phải lỗi. Hết `expires_at` → coi như chưa đăng ký (drop + None).

`deployment_id`/`kind` ĐÃ BỎ: Portal `0941` xoá `control.deployments`, và `kind` biến
mất khỏi response `/runtime-credentials` từ `0919` nên trường đó luôn rỗng — người đọc
duy nhất của nó là một phép so trong `pg_heartbeat.beat()` không bao giờ đúng, và chính
phép so đó giữ nhịp tim chết suốt từ đấy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class TenantPgCredential:
    role: str
    password: str
    expires_at: datetime
    # Định danh API key phía Portal (không phải secret) — voice worker đọc để
    # đóng dấu tenant_data.conversations.agent_key_id. Rỗng = gateway/Portal chưa gửi.
    agent_key_id: str = ""


_creds: dict[str, TenantPgCredential] = {}


def register(
    tenant_id: str,
    *,
    role: str,
    password: str,
    expires_at: datetime,
    agent_key_id: str = "",
) -> None:
    _creds[tenant_id] = TenantPgCredential(
        role=role, password=password, expires_at=expires_at, agent_key_id=agent_key_id
    )


def get(tenant_id: str, *, now: datetime | None = None) -> TenantPgCredential | None:
    cred = _creds.get(tenant_id)
    if cred is None:
        return None
    if (now or datetime.now(UTC)) >= cred.expires_at:
        _creds.pop(tenant_id, None)
        return None
    return cred


def clear_for_tests() -> None:
    _creds.clear()
