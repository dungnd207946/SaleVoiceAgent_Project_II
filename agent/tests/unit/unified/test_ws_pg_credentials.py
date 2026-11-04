"""Worker ingest PG credential từ header gateway (chỉ sau khi secret-check pass)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from noble_agent.server.ws_handler import _agent_key_from_headers, _register_pg_credentials
from noble_agent.storage import tenant_credentials as tc

_SECRET = "shh"


def setup_function():
    tc.clear_for_tests()


def _headers(**over):
    h = {
        "X-PG-Role": "agent_anphu",
        "X-PG-Password": "pw",
        "X-PG-Expires": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    h.update(over)
    return {k: v for k, v in h.items() if v is not None}


def test_register_ok():
    assert _register_pg_credentials(_headers(), "anphu", _SECRET) is True
    cred = tc.get("anphu")
    assert cred is not None and cred.role == "agent_anphu"


def test_missing_any_header_skips():
    for drop in ("X-PG-Role", "X-PG-Password", "X-PG-Expires"):
        tc.clear_for_tests()
        assert _register_pg_credentials(_headers(**{drop: None}), "anphu", _SECRET) is False
        assert tc.get("anphu") is None


def test_bad_expires_skips():
    assert _register_pg_credentials(_headers(**{"X-PG-Expires": "hôm-qua"}), "anphu", _SECRET) is False
    assert tc.get("anphu") is None


def test_no_tenant_skips():
    assert _register_pg_credentials(_headers(), None, _SECRET) is False


def test_z_suffix_expires_ok():
    assert _register_pg_credentials(_headers(**{"X-PG-Expires": "2099-01-01T00:00:00Z"}), "anphu", _SECRET) is True


def test_ingest_skipped_when_secret_empty():
    """No configured GATEWAY_WORKER_SECRET → the hop is unauthenticated
    (_gateway_secret_ok is open to anyone) → never trust forwarded X-PG-* headers,
    even when they look valid, to avoid poisoning the shared credential registry."""
    assert _register_pg_credentials(_headers(), "anphu", "") is False
    assert tc.get("anphu") is None


def test_register_bo_qua_header_deployment_va_kind_con_sot():
    """Gateway bản cũ còn gửi `X-PG-Deployment`/`X-PG-Kind` — worker bản mới phải BỎ QUA
    chứ không nổ.

    Ba bài cũ ở đây canh việc PARSE hai header đó (hợp lệ · rác · vắng mặt). `0941` bỏ
    cả hai khỏi `TenantPgCredential`, nên thứ đáng canh giờ là khả năng dung thứ: trong
    lúc triển khai luân phiên, gateway cũ và worker mới chạy cạnh nhau.
    """
    h = _headers(**{"X-PG-Deployment": "6", "X-PG-Kind": "chat"})
    assert _register_pg_credentials(h, "anphu", _SECRET) is True
    cred = tc.get("anphu")
    assert cred is not None
    assert not hasattr(cred, "deployment_id")
    assert not hasattr(cred, "kind")


def test_register_khong_co_header_thua_van_dang_ky_duoc():
    assert _register_pg_credentials(_headers(), "anphu", _SECRET) is True
    assert tc.get("anphu") is not None


def test_agent_key_from_headers_ok():
    h = _headers(**{"X-Agent-Key-Id": "ak_9"})
    assert _agent_key_from_headers(h, _SECRET) == "ak_9"


def test_agent_key_from_headers_absent_is_empty():
    assert _agent_key_from_headers(_headers(), _SECRET) == ""


def test_agent_key_from_headers_untrusted_when_secret_empty():
    """Hop không xác thực (secret rỗng) → không tin header, tránh đóng dấu giả."""
    h = _headers(**{"X-Agent-Key-Id": "ak_9"})
    assert _agent_key_from_headers(h, "") == ""


def test_agent_key_from_headers_garbage_headers_do_not_raise():
    assert _agent_key_from_headers(MagicMock(), _SECRET) == ""
    assert _agent_key_from_headers(None, _SECRET) == ""


def test_garbage_header_values_do_not_raise_or_register():
    """Non-str header values (e.g. a MagicMock .headers on a fake ws in tests)
    must degrade to 'skip', never raise — covers the TypeError regression from
    datetime.fromisoformat(non-str)."""
    bad_headers = MagicMock()
    assert _register_pg_credentials(bad_headers, "anphu", _SECRET) is False
    assert tc.get("anphu") is None
