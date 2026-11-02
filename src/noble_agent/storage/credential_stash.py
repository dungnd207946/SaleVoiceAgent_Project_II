"""Stash credential PG per-tenant qua Redis nội bộ — cầu nối gateway → LiveKit voice worker.

Voice không có hop trực tiếp gateway→worker (dispatch đi qua LiveKit Cloud, không
nhét secret vào metadata được). Gateway ghi credential đã MÃ HOÁ Fernet vào Redis
(key ``noble:pgcred:<tenant>``, TTL = giây còn lại tới expires_at — Redis tự xoá);
worker job fetch + giải mã + đăng ký vào ``tenant_credentials`` lúc vào cuộc.

Khoá Fernet dẫn xuất từ ``GATEWAY_WORKER_SECRET`` (SHA-256 → urlsafe-b64) — hai
process vốn đã bắt buộc chung secret này cho chat forwarding, không thêm env mới.
Secret rỗng ⇒ không stash, không fetch (nhất quán hardening chat: hop không xác
thực thì không tin credential). Mọi lỗi (lệch secret, token rác, JSON hỏng,
expires_at hỏng) → None/False — caller rơi về shared DSN, không bao giờ raise
trên đường cuộc gọi. Payload bind ``tenant_id`` để chặn transplant: ai đó ghi được
Redis vẫn không thể copy ciphertext của tenant A sang key của tenant B."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import UTC, datetime

logger = logging.getLogger("noble_agent.storage.credential_stash")

_KEY_PREFIX = "noble:pgcred:"


def stash_key(tenant_id: str) -> str:
    return f"{_KEY_PREFIX}{tenant_id}"


def derive_key(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())


def _fernet(secret: str):
    from cryptography.fernet import Fernet  # lazy: giữ import storage nhẹ

    return Fernet(derive_key(secret))


def encrypt_credential(secret: str, payload: dict) -> str:
    return _fernet(secret).encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")


def decrypt_credential(secret: str, token: str) -> dict | None:
    """Lệch secret / token rác / JSON hỏng → None. Không raise."""
    if not token:
        return None
    try:
        raw = _fernet(secret).decrypt(token.encode("ascii") if isinstance(token, str) else bytes(token))
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 — mọi lỗi giải mã đều là "không có credential"
        return None
    return data if isinstance(data, dict) else None


def ttl_seconds(expires_at: datetime, *, now: datetime | None = None) -> int:
    left = (expires_at - (now or datetime.now(UTC))).total_seconds()
    return max(1, int(left))


async def stash(
    redis, secret: str, tenant_id: str, *,
    role: str, password: str, expires_at: datetime,
    agent_key_id: str = "",
) -> bool:
    """Gateway gọi trước khi dispatch voice. Best-effort: False khi thiếu điều kiện.

    `deployment_id`/`kind` đã bỏ khỏi payload (`0941`/`0919`): cả hai vắng khỏi response
    `/runtime-credentials` từ lâu, và người đọc duy nhất — phép so kind trong
    `pg_heartbeat.beat()` — đã gỡ. Stash cũ trong Redis còn hai khoá đó vẫn giải mã
    được; `register()` bỏ qua khoá thừa.
    """
    if not secret or not role or not password:
        return False
    payload = {
        "role": role, "password": password,
        "expires_at": expires_at.isoformat(), "tenant_id": tenant_id,
        "agent_key_id": agent_key_id,
    }
    await redis.set(stash_key(tenant_id), encrypt_credential(secret, payload), ex=ttl_seconds(expires_at))
    return True


async def fetch(redis, secret: str, tenant_id: str) -> dict | None:
    if not secret:
        return None
    token = await redis.get(stash_key(tenant_id))
    if token is None:
        return None
    if isinstance(token, (bytes, bytearray)):
        token = token.decode("ascii", errors="replace")
    data = decrypt_credential(secret, token)
    if data is None:
        # Có key mà không mở được = hai process lệch GATEWAY_WORKER_SECRET — đáng báo.
        logger.warning("credential_stash: giải mã fail cho tenant %s (lệch secret giữa gateway và worker?)", tenant_id)
    return data


async def fetch_and_register(redis, secret: str, tenant_id: str) -> bool:
    """Voice worker gọi lúc vào job. True = đã đăng ký credential per-tenant."""
    data = await fetch(redis, secret, tenant_id)
    if data is None:
        return False
    if data.get("tenant_id") != tenant_id:
        # Ciphertext hợp lệ nhưng bind sai tenant — key bị transplant hoặc lệch state.
        # Không log role/password, chỉ log tenant_id (không phải secret).
        logger.warning("credential_stash: tenant_id trong payload không khớp key (expected %s)", tenant_id)
        return False
    role = str(data.get("role") or "")
    password = str(data.get("password") or "")
    raw_exp = str(data.get("expires_at") or "")
    if not role or not password or not raw_exp:
        return False
    try:
        expires_at = datetime.fromisoformat(raw_exp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    from noble_agent.storage import tenant_credentials

    tenant_credentials.register(
        tenant_id, role=role, password=password, expires_at=expires_at,
        agent_key_id=str(data.get("agent_key_id") or ""),
    )
    logger.info("credential_stash: đã đăng ký credential per-tenant cho %s (role=%s)", tenant_id, role)
    return True


def adopt_agent_key(tenant_id: str) -> str:
    """Đọc agent_key_id từ registry tenant_credentials và set vào contextvar
    của job hiện tại — voice worker gọi sau fetch_and_register để mọi ghi
    conversations trong cuộc mang định danh key. Không có credential / không có
    agent_key_id → no-op, trả rỗng."""
    from noble_agent.storage import tenant_credentials
    from noble_agent.tenant.current import set_current_agent_key_id

    cred = tenant_credentials.get(tenant_id)
    akid = cred.agent_key_id if cred is not None else ""
    if akid:
        set_current_agent_key_id(akid)
    return akid
