"""CredentialsClient: gọi runtime-credentials API, cache theo expires_at, fail-closed."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from noble_agent.gateway.credentials import (
    REASON_BAD_CREDENTIAL,
    REASON_UNAVAILABLE,
    CredentialsClient,
    CredentialsError,
    parse_credentials,
)

URL = "http://portal.test/api/v1/agent/runtime-credentials"


def _payload(**over):
    base = {
        "tenant_id": "anphu",
        "postgres_role": "agent_anphu",
        "postgres_password": "s3cret",
        "storage": {"endpoint": "http://minio", "bucket": "b"},
        "kb": {"url": "http://qdrant", "collection": "kb_anphu"},
        "live_url": "tenants/anphu/LIVE",
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    base.update(over)
    return base


def _client(handler, ttl=30.0, url=URL, clock=None):
    transport = httpx.MockTransport(handler)
    kwargs = {"transport": transport}
    if clock is not None:
        kwargs["clock"] = clock
    return CredentialsClient(url, ttl, **kwargs)


def test_parse_credentials_full():
    c = parse_credentials(_payload())
    assert c.tenant_id == "anphu"
    assert c.postgres_role == "agent_anphu"
    assert c.postgres_password == "s3cret"
    assert c.kb["collection"] == "kb_anphu"
    assert c.expires_at is not None and c.expires_at.tzinfo is not None


def test_parse_credentials_z_suffix():
    c = parse_credentials(_payload(expires_at="2026-08-10T09:00:00Z"))
    assert c.expires_at == datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def test_parse_credentials_agent_key_id():
    c = parse_credentials(_payload(agent_key_id="ak_123"))
    assert c.agent_key_id == "ak_123"


def test_parse_credentials_agent_key_id_numeric_coerced_to_str():
    c = parse_credentials(_payload(agent_key_id=42))
    assert c.agent_key_id == "42"


def test_parse_credentials_agent_key_id_absent_is_empty():
    """Portal cũ chưa trả field này → rỗng, KHÔNG fail-closed."""
    c = parse_credentials(_payload())
    assert c.agent_key_id == ""


@pytest.mark.parametrize("missing", ["tenant_id", "expires_at"])
def test_parse_credentials_missing_required(missing):
    data = _payload()
    data[missing] = ""
    with pytest.raises(CredentialsError) as e:
        parse_credentials(data)
    assert e.value.reason == REASON_UNAVAILABLE


async def test_authorize_ok_and_bearer_header():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=_payload())

    c = _client(handler)
    creds = await c.authorize("key_abc")
    assert creds.tenant_id == "anphu"
    assert seen["auth"] == "Bearer key_abc"


async def test_authorize_caches_within_ttl():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=_payload())

    c = _client(handler)
    await c.authorize("key_abc")
    await c.authorize("key_abc")
    assert calls["n"] == 1  # cache hit, không gọi lại API


async def test_authorize_cache_expires_by_clock():
    calls = {"n": 0}
    t = {"now": 100.0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=_payload())

    c = _client(handler, ttl=30.0, clock=lambda: t["now"])
    await c.authorize("key_abc")
    t["now"] += 31.0
    await c.authorize("key_abc")
    assert calls["n"] == 2


async def test_authorize_cache_capped_by_expires_at():
    """expires_at gần hơn TTL cap → hết expires_at là gọi lại API."""
    calls = {"n": 0}
    t = {"now": 100.0}

    def handler(request):
        calls["n"] += 1
        # expires sau 10s (wall clock thật) — ngắn hơn ttl=3600
        return httpx.Response(200, json=_payload(
            expires_at=(datetime.now(UTC) + timedelta(seconds=10)).isoformat()))

    c = _client(handler, ttl=3600.0, clock=lambda: t["now"])
    await c.authorize("key_abc")
    t["now"] += 11.0
    await c.authorize("key_abc")
    assert calls["n"] == 2


async def test_authorize_401_bad_credential_not_cached():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, json={"detail": "invalid"})

    c = _client(handler)
    for _ in range(2):
        with pytest.raises(CredentialsError) as e:
            await c.authorize("key_bad")
        assert e.value.reason == REASON_BAD_CREDENTIAL
    assert calls["n"] == 2  # không negative-cache


async def test_authorize_5xx_unavailable():
    c = _client(lambda request: httpx.Response(503))
    with pytest.raises(CredentialsError) as e:
        await c.authorize("key_abc")
    assert e.value.reason == REASON_UNAVAILABLE


async def test_authorize_network_error_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused")

    c = _client(handler)
    with pytest.raises(CredentialsError) as e:
        await c.authorize("key_abc")
    assert e.value.reason == REASON_UNAVAILABLE


async def test_authorize_missing_url_unavailable():
    c = _client(lambda request: httpx.Response(200), url="")
    with pytest.raises(CredentialsError) as e:
        await c.authorize("key_abc")
    assert e.value.reason == REASON_UNAVAILABLE


async def test_authorize_bad_json_unavailable():
    c = _client(lambda request: httpx.Response(200, content=b"not-json"))
    with pytest.raises(CredentialsError) as e:
        await c.authorize("key_abc")
    assert e.value.reason == REASON_UNAVAILABLE
