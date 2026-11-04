"""Runtime-credentials client — gateway auth qua Portal API (kiến trúc single-domain).

Thay hẳn đường subdomain + đọc control.*: gateway POST API key lên
GATEWAY_CREDENTIALS_API_URL, nhận credential per-tenant (tenant_id, PG role/password,
storage/kb, expires_at). Cache in-RAM keyed sha256(api_key), sống tới
min(expires_at, now + GATEWAY_CRED_CACHE_TTL_SEC) — cache hit vẫn phục vụ khi auth
API down; cache miss + API lỗi → fail-closed (`CredentialsError.reason` đi thẳng vào
close frame 4001, phân biệt "khoá sai" với "không hỏi được" như gateway/errors.py cũ)."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger("gateway.credentials")

REASON_BAD_CREDENTIAL = "bad_credential"
REASON_UNAVAILABLE = "auth_api_unavailable"

_TIMEOUT_SEC = 5.0


class CredentialsError(Exception):
    """Auth API từ chối hoặc không trả lời được. `reason` đi vào close frame."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RuntimeCredentials:
    tenant_id: str
    postgres_role: str
    postgres_password: str
    storage: dict = field(default_factory=dict)
    kb: dict = field(default_factory=dict)
    live_url: str = ""
    expires_at: datetime | None = None
    # Định danh API key phía Portal (optional — Portal cũ chưa trả thì rỗng).
    # Đóng dấu vào tenant_data.conversations.agent_key_id để biết conversation
    # đến từ key nào; không phải secret.
    agent_key_id: str = ""


def parse_credentials(data: dict) -> RuntimeCredentials:
    """Parse response 200. Thiếu tenant_id/expires_at hoặc expires_at hỏng →
    CredentialsError(auth_api_unavailable): không tin dữ liệu nửa vời."""
    tenant_id = str(data.get("tenant_id") or "").strip()
    raw_exp = str(data.get("expires_at") or "").strip()
    if not tenant_id or not raw_exp:
        raise CredentialsError(REASON_UNAVAILABLE)
    try:
        expires_at = datetime.fromisoformat(raw_exp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CredentialsError(REASON_UNAVAILABLE) from exc
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    # `deployment_id` (bỏ ở Portal `0940`) và `kind` (bỏ ở `0919`) KHÔNG còn được đọc.
    # Cả hai đã vắng khỏi response từ lâu; giữ chỗ cho chúng chỉ tạo ảo giác là pod
    # còn biết mình là pod nào.
    return RuntimeCredentials(
        tenant_id=tenant_id,
        postgres_role=str(data.get("postgres_role") or ""),
        postgres_password=str(data.get("postgres_password") or ""),
        storage=data.get("storage") or {},
        kb=data.get("kb") or {},
        live_url=str(data.get("live_url") or ""),
        expires_at=expires_at,
        agent_key_id=str(data.get("agent_key_id") or "").strip(),
    )


class CredentialsClient:
    """`transport`/`clock`/`now_utc` inject được cho unit test (httpx.MockTransport)."""

    def __init__(
        self, url: str, cache_ttl_sec: float, *, transport=None, clock=time.monotonic, now_utc=None
    ):
        self._url = url
        self._ttl = cache_ttl_sec
        self._transport = transport
        self._clock = clock
        self._now_utc = now_utc or (lambda: datetime.now(UTC))
        self._cache: dict[str, tuple[float, RuntimeCredentials]] = {}
        self._client = None

    def _http(self):
        import httpx  # lazy: giữ import gateway nhẹ

        if self._client is None:
            kwargs: dict = {"timeout": _TIMEOUT_SEC}
            if self._transport is not None:
                kwargs["transport"] = self._transport
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def authorize(self, api_key: str) -> RuntimeCredentials:
        cache_key = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        now = self._clock()
        hit = self._cache.get(cache_key)
        if hit is not None and now < hit[0]:
            return hit[1]
        creds = await self._fetch(api_key)
        wall_left = max(0.0, (creds.expires_at - self._now_utc()).total_seconds()) if creds.expires_at else 0.0
        self._cache[cache_key] = (now + min(self._ttl, wall_left), creds)
        return creds

    async def _fetch(self, api_key: str) -> RuntimeCredentials:
        if not self._url:
            logger.error("gateway: GATEWAY_CREDENTIALS_API_URL chưa cấu hình — từ chối kết nối (fail-closed)")
            raise CredentialsError(REASON_UNAVAILABLE)
        try:
            resp = await self._http().post(self._url, headers={"Authorization": f"Bearer {api_key}"})
        except CredentialsError:
            raise
        except Exception as exc:  # noqa: BLE001 — mọi lỗi mạng/timeout đều là "không hỏi được"
            logger.warning("gateway: auth API không phản hồi: %s", exc)
            raise CredentialsError(REASON_UNAVAILABLE) from exc
        if resp.status_code in (401, 403):
            raise CredentialsError(REASON_BAD_CREDENTIAL)
        if resp.status_code != 200:
            logger.warning("gateway: auth API trả %s", resp.status_code)
            raise CredentialsError(REASON_UNAVAILABLE)
        try:
            data = resp.json()
        except ValueError as exc:
            raise CredentialsError(REASON_UNAVAILABLE) from exc
        return parse_credentials(data if isinstance(data, dict) else {})

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
