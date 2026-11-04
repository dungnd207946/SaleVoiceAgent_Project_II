import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import websockets

from noble_agent.gateway.chat_proxy import first_messages, proxy_chat, proxy_headers, worker_chat_url
from noble_agent.gateway.credentials import RuntimeCredentials


def test_worker_chat_url_is_fixed_shared_url():
    s = SimpleNamespace(worker_chat_internal_url_template="ws://agent:8766/chat")
    assert worker_chat_url("t1", s) == "ws://agent:8766/chat"
    assert worker_chat_url("t2", s) == "ws://agent:8766/chat"


def test_proxy_headers_include_tenant():
    s = SimpleNamespace(gateway_worker_secret="")
    assert proxy_headers(s, "t1") == {"X-Tenant-Id": "t1"}


def test_proxy_headers_include_secret_when_set():
    s = SimpleNamespace(gateway_worker_secret="shh")
    assert proxy_headers(s, "t1") == {"X-Tenant-Id": "t1", "X-Gateway-Secret": "shh"}


def _creds(role="agent_anphu", pw="s3cret"):
    return RuntimeCredentials(
        tenant_id="anphu",
        postgres_role=role,
        postgres_password=pw,
        expires_at=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
    )


def test_proxy_headers_include_pg_credentials():
    s = SimpleNamespace(gateway_worker_secret="")
    h = proxy_headers(s, "anphu", credentials=_creds())
    assert h["X-PG-Role"] == "agent_anphu"
    assert h["X-PG-Password"] == "s3cret"
    assert h["X-PG-Expires"] == "2026-08-10T09:00:00+00:00"


def test_proxy_headers_no_credentials_no_pg_headers():
    s = SimpleNamespace(gateway_worker_secret="")
    h = proxy_headers(s, "anphu", credentials=None)
    assert "X-PG-Role" not in h and "X-PG-Password" not in h


def test_proxy_headers_empty_role_skipped():
    s = SimpleNamespace(gateway_worker_secret="")
    h = proxy_headers(s, "anphu", credentials=_creds(role=""))
    assert "X-PG-Role" not in h


def test_proxy_headers_khong_con_deployment_va_kind():
    """`X-PG-Deployment`/`X-PG-Kind` đã bỏ (`0941`/`0919`).

    Gộp hai bài cũ (`include_deployment_and_kind` + `no_deployment_header_when_none`):
    chúng canh hai nhánh của một điều kiện không còn tồn tại. Bài này canh điều đáng
    canh — ba header credential thật vẫn đi, hai header chết thì không.
    """
    s = SimpleNamespace(gateway_worker_secret="")
    h = proxy_headers(s, "anphu", credentials=_creds())
    assert set(h) == {"X-Tenant-Id", "X-PG-Role", "X-PG-Password", "X-PG-Expires"}


def test_proxy_headers_include_agent_key_id():
    s = SimpleNamespace(gateway_worker_secret="")
    creds = RuntimeCredentials(
        tenant_id="anphu",
        postgres_role="agent_anphu",
        postgres_password="s3cret",
        expires_at=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
        agent_key_id="ak_123",
    )
    h = proxy_headers(s, "anphu", credentials=creds)
    assert h["X-Agent-Key-Id"] == "ak_123"


def test_proxy_headers_no_agent_key_header_when_empty():
    s = SimpleNamespace(gateway_worker_secret="")
    h = proxy_headers(s, "anphu", credentials=_creds())
    assert "X-Agent-Key-Id" not in h


def test_proxy_headers_agent_key_id_sent_even_without_pg_role():
    """agent_key_id độc lập với PG credential — key không kèm role vẫn phải đóng dấu."""
    s = SimpleNamespace(gateway_worker_secret="")
    creds = RuntimeCredentials(
        tenant_id="anphu",
        postgres_role="",
        postgres_password="",
        expires_at=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
        agent_key_id="ak_123",
    )
    h = proxy_headers(s, "anphu", credentials=creds)
    assert h["X-Agent-Key-Id"] == "ak_123"
    assert "X-PG-Role" not in h


def test_first_messages_seeds_identity():
    msgs = first_messages({"full_name": "An", "phone": "090"})
    assert len(msgs) == 1
    d = json.loads(msgs[0])
    assert d["type"] == "set_customer" and d["identity"]["full_name"] == "An"


def test_first_messages_empty_identity():
    assert first_messages({}) == []


class _FakeClientWS:
    """Client leg that yields nothing then ends — a provider that disconnected."""

    def __init__(self):
        self.sent: list = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def send(self, m):
        self.sent.append(m)


class _FakeWorkerWS:
    """Worker leg that stays silent forever until closed (idle /chat socket)."""

    def __init__(self):
        self.closed = False
        self._close_evt = asyncio.Event()
        self.sent: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True
        self._close_evt.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self._close_evt.wait()
        raise StopAsyncIteration

    async def send(self, m):
        self.sent.append(m)


async def test_proxy_chat_tears_down_worker_leg_when_client_disconnects(monkeypatch):
    """When the provider side closes, the worker /chat socket must be closed too.

    The worker only persists the conversation (PG tenant_data.conversations) in
    its on-close finally — a relay that waits for BOTH directions leaves the
    worker leg open forever and nothing is ever persisted."""
    worker = _FakeWorkerWS()
    monkeypatch.setattr(websockets, "connect", lambda url, additional_headers=None: worker)
    s = SimpleNamespace(worker_chat_internal_url_template="ws://agent:8766/chat", gateway_worker_secret="")

    await asyncio.wait_for(proxy_chat(_FakeClientWS(), s, "t1", {}), timeout=2.0)

    assert worker.closed
