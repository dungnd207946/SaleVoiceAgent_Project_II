"""Bearer ODYSSEY_MODELS_TOKEN."""

import logging

from fastapi import Header, HTTPException

log = logging.getLogger(__name__)


def require_token(token: str):
    """Trả về dependency. Nhận token qua tham số để test không phải sửa env toàn cục."""

    def dependency(authorization: str = Header(default="")):
        if not token:
            return
        sent = authorization.strip()
        if sent.lower().startswith("bearer "):
            sent = sent[7:].strip()
        if sent != token:
            log.warning("🔒 auth rejected (bad/missing bearer token)")
            raise HTTPException(status_code=401, detail="invalid or missing bearer token")

    return dependency
