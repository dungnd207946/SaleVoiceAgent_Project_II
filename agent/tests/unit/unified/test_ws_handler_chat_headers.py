"""Pure header helpers for the /chat gateway hop in ws_handler."""
from noble_agent.server import ws_handler as h


def test_tenant_from_headers_reads_value():
    assert h._tenant_from_headers({"X-Tenant-Id": "acme"}) == "acme"


def test_tenant_from_headers_missing_or_blank_is_none():
    assert h._tenant_from_headers({}) is None
    assert h._tenant_from_headers({"X-Tenant-Id": "  "}) is None
    assert h._tenant_from_headers(None) is None


def test_gateway_secret_ok_disabled_when_secret_empty():
    # No configured secret → always OK (dev / trust-network, unchanged behavior).
    assert h._gateway_secret_ok("", {}) is True
    assert h._gateway_secret_ok("", {"X-Gateway-Secret": "whatever"}) is True


def test_gateway_secret_ok_requires_match_when_configured():
    assert h._gateway_secret_ok("shh", {"X-Gateway-Secret": "shh"}) is True
    assert h._gateway_secret_ok("shh", {"X-Gateway-Secret": "nope"}) is False
    assert h._gateway_secret_ok("shh", {}) is False
    assert h._gateway_secret_ok("shh", None) is False
