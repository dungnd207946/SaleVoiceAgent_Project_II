"""`evals.tenant_creds` — nạp credential PG per-tenant cho lượt `evals run`.

Không đụng mạng: bơm `CredentialsClient` giả qua monkeypatch module `noble_agent.gateway.credentials`,
và dùng registry thật (`storage.tenant_credentials`) vì nó là dict thuần.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from evals import tenant_creds

from noble_agent.gateway.credentials import CredentialsError, RuntimeCredentials
from noble_agent.storage import tenant_credentials


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    tenant_credentials.clear_for_tests()
    monkeypatch.delenv(tenant_creds.ENV_KEY, raising=False)
    yield
    tenant_credentials.clear_for_tests()


def _creds(tenant: str, *, ttl_min: int = 60) -> RuntimeCredentials:
    return RuntimeCredentials(
        tenant_id=tenant, postgres_role=f"agent_{tenant}", postgres_password="pw",
        expires_at=datetime.now(UTC) + timedelta(minutes=ttl_min), agent_key_id="12",
    )


class _FakeClient:
    """Đếm số lần authorize để chứng minh hàm không gọi lại khi credential còn hạn."""

    calls = 0

    def __init__(self, url, ttl, **_kw):
        self.url = url

    async def authorize(self, api_key):
        type(self).calls += 1
        if api_key == "bad":
            raise CredentialsError("bad_credential")
        return _creds("aina_prod")

    async def aclose(self):
        pass


def _patch(monkeypatch, *, client=_FakeClient, api_url="https://auth.example/runtime-credentials",
           server_dsn="postgresql://host:5442/portal"):
    monkeypatch.setattr("noble_agent.gateway.credentials.CredentialsClient", client)

    class _S:
        gateway_credentials_api_url = api_url
        gateway_cred_cache_ttl_sec = 60.0
        postgres_server_dsn = server_dsn

    monkeypatch.setattr("noble_agent.config.get_settings", lambda: _S())


async def test_noop_khi_chua_dat_env(monkeypatch):
    _patch(monkeypatch)
    assert await tenant_creds.ensure("aina_prod") is False
    assert tenant_credentials.get("aina_prod") is None
    assert tenant_creds.configured() is False


async def test_fetch_va_dang_ky(monkeypatch):
    monkeypatch.setenv(tenant_creds.ENV_KEY, "ody_ag_x")
    _patch(monkeypatch)
    assert tenant_creds.configured() is True
    assert await tenant_creds.ensure("aina_prod") is True
    cred = tenant_credentials.get("aina_prod")
    assert cred is not None
    assert cred.role == "agent_aina_prod"
    assert cred.agent_key_id == "12"


async def test_khong_goi_lai_khi_con_han(monkeypatch):
    monkeypatch.setenv(tenant_creds.ENV_KEY, "ody_ag_x")
    _patch(monkeypatch)
    _FakeClient.calls = 0
    assert await tenant_creds.ensure("aina_prod") is True
    assert await tenant_creds.ensure("aina_prod") is False
    assert await tenant_creds.ensure("aina_prod") is False
    assert _FakeClient.calls == 1, "auth API có rate-limit — chỉ được gọi khi hết hạn"


async def test_fetch_lai_khi_het_han(monkeypatch):
    """Lượt 100 case tuần tự dài hơn TTL (~1h) → phải tự lấy lại, không im lặng rơi về shared DSN."""
    monkeypatch.setenv(tenant_creds.ENV_KEY, "ody_ag_x")
    _patch(monkeypatch)
    tenant_credentials.register(
        "aina_prod", role="agent_aina_prod", password="pw",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    _FakeClient.calls = 0
    assert await tenant_creds.ensure("aina_prod") is True
    assert _FakeClient.calls == 1


async def test_key_sai_raise_ro_rang(monkeypatch):
    monkeypatch.setenv(tenant_creds.ENV_KEY, "bad")
    _patch(monkeypatch)
    with pytest.raises(tenant_creds.CredentialError, match="bad_credential"):
        await tenant_creds.ensure("aina_prod")
    assert tenant_credentials.get("aina_prod") is None


async def test_key_thuoc_tenant_khac_bi_tu_choi(monkeypatch):
    """Đăng ký sai tenant thì pool đúng role nhưng app.current_tenant khác ⇒ 0 row IM LẶNG."""
    monkeypatch.setenv(tenant_creds.ENV_KEY, "ody_ag_x")
    _patch(monkeypatch)
    with pytest.raises(tenant_creds.CredentialError, match="thuộc tenant 'aina_prod'"):
        await tenant_creds.ensure("aina")
    assert tenant_credentials.get("aina") is None


async def test_thieu_gateway_url(monkeypatch):
    monkeypatch.setenv(tenant_creds.ENV_KEY, "ody_ag_x")
    _patch(monkeypatch, api_url="")
    with pytest.raises(tenant_creds.CredentialError, match="GATEWAY_CREDENTIALS_API_URL"):
        await tenant_creds.ensure("aina_prod")


async def test_thieu_postgres_server_dsn(monkeypatch):
    """Có credential mà không có DSN server ⇒ pool_for_tenant rơi về shared pool — phải chặn."""
    monkeypatch.setenv(tenant_creds.ENV_KEY, "ody_ag_x")
    _patch(monkeypatch, server_dsn="")
    with pytest.raises(tenant_creds.CredentialError, match="POSTGRES_SERVER_DSN"):
        await tenant_creds.ensure("aina_prod")
    assert tenant_credentials.get("aina_prod") is None
