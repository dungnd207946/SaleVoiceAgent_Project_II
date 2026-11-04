"""Test LiveKit bridge helpers: room_name + build_dispatch_token."""
from noble_agent.gateway import livekit_bridge as b


def test_room_name_scoped_and_unique():
    """room_name includes tenant_id and call_id, and is unique on re-run."""
    r1 = b.room_name("t1", "call-abc")
    assert r1.startswith("t1-") and "call-abc" in r1
    # Verify uniqueness (ms + random suffix).
    r2 = b.room_name("t1", "call-abc")
    assert r1 != r2


class FakeToken:
    """Fake minter that records .with_*() calls for assertion."""
    def __init__(self, *a, **k):
        self.calls = []

    def with_identity(self, v):
        self.calls.append(("identity", v))
        return self

    def with_name(self, v):
        self.calls.append(("name", v))
        return self

    def with_metadata(self, v):
        self.calls.append(("metadata", v))
        return self

    def with_grants(self, v):
        self.calls.append(("grants", v))
        return self

    def with_room_config(self, v):
        self.calls.append(("room_config", v))
        return self

    def to_jwt(self):
        return "JWT"


def test_build_dispatch_token_shared_agent_and_tenant_metadata():
    """Dispatch uses the shared agent_name; metadata carries tenant_id merged into identity."""
    import json

    tok = FakeToken()
    jwt, url, room = b.build_dispatch_token(
        "t1",
        '{"name":"An"}',
        api_key="k",
        api_secret="s",
        url="wss://lk",
        agent_name="noble-hotline-agent",
        minter=lambda *a, **k: tok,
    )
    assert jwt == "JWT" and url == "wss://lk" and room.startswith("t1-")
    kinds = dict(tok.calls)
    meta = json.loads(kinds["metadata"])
    assert meta["tenant_id"] == "t1"
    assert meta["name"] == "An"
    assert kinds["room_config"].agents[0].agent_name == "noble-hotline-agent"


def test_build_dispatch_token_empty_identity_still_carries_tenant():
    import json

    tok = FakeToken()
    b.build_dispatch_token(
        "t2", "", api_key="k", api_secret="s", url="u", agent_name="A", minter=lambda *a, **k: tok
    )
    assert json.loads(dict(tok.calls)["metadata"]) == {"tenant_id": "t2"}


def test_session_id_frame_carries_the_room_name_verbatim():
    """The voice session id IS the room name — worker/livekit_bridge must not drift.

    transport/livekit/worker.py builds RoomSession(session_id=ctx.room.name), and
    that id is what lands in tenant_data.conversations. A client can only tie its
    feedback (POST /agent/feedback) to the right session if the gateway hands it
    exactly that string, so assert on the value, not just the shape.
    """
    import json

    room = b.room_name("t1", "call-abc")
    msg = json.loads(b.session_id_frame(room))

    assert msg == {"type": "session_id", "session_id": room}
