"""Gateway request authorization: Bearer API key → Portal runtime-credentials API.

Kiến trúc single-domain (noble-saas.<domain>): tenant KHÔNG còn nằm trong Host —
mọi thông tin (tenant_id, PG role/password, expires_at) đến từ credential API.
Fail-closed: mọi lỗi hỏi API đều là ok=False với reason phân loại rõ (bad_credential
vs auth_api_unavailable) để người debug không xoay nhầm khoá khi lỗi là hạ tầng."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from noble_agent.gateway.credentials import REASON_UNAVAILABLE, CredentialsError, RuntimeCredentials

logger = logging.getLogger("gateway.auth")

_BEARER = "Bearer "


@dataclass(frozen=True)
class AuthResult:
    """Result of gateway authorization attempt."""

    ok: bool
    tenant_id: str = ""
    key_id: str = ""
    reason: str = ""
    credentials: RuntimeCredentials | None = None


async def authorize(authorization: str, *, credentials) -> AuthResult:
    """Authorize một request gateway bằng Bearer API key.

    `credentials`: đối tượng có `async authorize(api_key) -> RuntimeCredentials`
    (CredentialsClient thật, hoặc fake trong test). Reasons: "no_bearer",
    "bad_credential" (API trả 401/403 — khoá sai/revoked), "auth_api_unavailable"
    (API down/5xx/thiếu config/response hỏng — KHÔNG phải lỗi của khoá)."""
    if not authorization or not authorization.startswith(_BEARER):
        return AuthResult(False, reason="no_bearer")
    api_key = authorization[len(_BEARER) :]
    try:
        creds = await credentials.authorize(api_key)
    except CredentialsError as exc:
        return AuthResult(False, reason=exc.reason)
    except Exception:
        logger.exception("gateway: lỗi bất ngờ khi hỏi credentials API")
        return AuthResult(False, reason=REASON_UNAVAILABLE)
    key_id = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]
    return AuthResult(True, tenant_id=creds.tenant_id, key_id=key_id, credentials=creds)
