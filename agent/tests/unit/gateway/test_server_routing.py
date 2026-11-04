from types import SimpleNamespace

from noble_agent.gateway import server as s


def test_route():
    assert s.route("/v1/voice") == "voice"
    assert s.route("/v1/voice?x=1") == "voice"
    assert s.route("/v1/chat") == "chat"
    assert s.route("/other") is None


def test_parse_handshake():
    assert s.parse_handshake('{"identity":{"full_name":"An"},"call_id":"c1"}') == {
        "identity": {"full_name": "An"},
        "call_id": "c1",
    }
    assert s.parse_handshake("not json") == {}
    assert s.parse_handshake("") == {}


def test_extract_request_modern_websockets_api():
    # websockets>=13 ServerConnection: request lives on ws.request (path + headers mapping),
    # NOT the legacy ws.path / ws.request_headers.
    ws = SimpleNamespace(
        request=SimpleNamespace(
            path="/v1/voice",
            headers={"Host": "t1.agents.noblex.vn", "Authorization": "Bearer x"},
        )
    )
    assert s._extract_request(ws) == ("/v1/voice", "t1.agents.noblex.vn", "Bearer x")
