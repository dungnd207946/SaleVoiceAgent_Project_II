"""Gateway authorization: Bearer key → runtime-credentials API (không còn Host subdomain)."""

from noble_agent.gateway.auth import AuthResult, authorize
from noble_agent.gateway.credentials import (
    REASON_BAD_CREDENTIAL,
    REASON_UNAVAILABLE,
    CredentialsError,
    RuntimeCredentials,
)

_CREDS = RuntimeCredentials(
    tenant_id="anphu", postgres_role="agent_anphu", postgres_password="pw",
)


class _Client:
    """Fake CredentialsClient: trả creds cho key 'good', raise cho phần còn lại."""

    def __init__(self, error: CredentialsError | None = None):
        self._error = error

    async def authorize(self, api_key: str) -> RuntimeCredentials:
        if self._error is not None:
            raise self._error
        if api_key == "good":
            return _CREDS
        raise CredentialsError(REASON_BAD_CREDENTIAL)


async def test_authorize_happy():
    r = await authorize("Bearer good", credentials=_Client())
    assert r.ok
    assert r.tenant_id == "anphu"
    assert r.credentials is _CREDS
    assert r.key_id  # sha256 prefix, chỉ cần khác rỗng
    assert r.reason == ""


async def test_authorize_no_bearer():
    for bad in ("", "Basic abc", "bearer good"):
        r = await authorize(bad, credentials=_Client())
        assert not r.ok and r.reason == "no_bearer"


async def test_authorize_bad_credential():
    r = await authorize("Bearer wrong", credentials=_Client())
    assert not r.ok and r.reason == REASON_BAD_CREDENTIAL
    assert r.credentials is None


async def test_authorize_api_unavailable():
    r = await authorize("Bearer good", credentials=_Client(error=CredentialsError(REASON_UNAVAILABLE)))
    assert not r.ok and r.reason == REASON_UNAVAILABLE


async def test_authorize_unexpected_error_fail_closed():
    class _Boom:
        async def authorize(self, api_key):
            raise RuntimeError("bug")

    r = await authorize("Bearer good", credentials=_Boom())
    assert not r.ok and r.reason == REASON_UNAVAILABLE


def test_authresult_defaults():
    r = AuthResult(False)
    assert r.tenant_id == "" and r.key_id == "" and r.credentials is None
