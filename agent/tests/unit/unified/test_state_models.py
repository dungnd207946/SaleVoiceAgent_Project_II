from datetime import UTC, datetime

from noble_agent.storage.models import (
    Customer,
    Meta,
    State,
    ThreadMessage,
    ThreadSummary,
)


def test_meta_has_no_active_agent():
    m = Meta(
        session_id="s1",
        started_at=datetime.now(UTC),
        last_active=datetime.now(UTC),
    )
    assert not hasattr(m, "active_agent")


def test_customer_defaults_all_optional():
    c = Customer()
    assert c.name is None
    assert c.phone is None
    assert c.project_interest is None


def test_customer_has_noble_user_id():
    c = Customer(noble_user_id="6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb", name="Nga")
    assert c.noble_user_id == "6cb7cc1d-d5d0-4b59-bbe1-5c797fc58afb"
    # round-trips through JSON (StateRepo persists via model_dump_json)
    assert Customer.model_validate_json(c.model_dump_json()).noble_user_id == c.noble_user_id
    # default stays None (back-compat with existing persisted blobs)
    assert Customer().noble_user_id is None


def test_state_defaults_empty():
    s = State()
    assert s.history == []
    assert s.summary is None
    assert s.scratchpad == {}


def test_thread_message_to_openai_user():
    m = ThreadMessage(role="user", content="hi")
    assert m.to_openai() == {"role": "user", "content": "hi"}


def test_thread_message_to_openai_assistant_with_tool_calls():
    tc = [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]
    m = ThreadMessage(role="assistant", content="ok", tool_calls=tc)
    out = m.to_openai()
    assert out["role"] == "assistant"
    assert out["content"] == "ok"
    assert out["tool_calls"] == tc


def test_thread_message_to_openai_tool():
    m = ThreadMessage(role="tool", tool_call_id="c1", name="f", content="result")
    out = m.to_openai()
    assert out == {"role": "tool", "tool_call_id": "c1", "name": "f", "content": "result"}


def test_state_round_trip_json():
    s = State(
        history=[
            ThreadMessage(role="user", content="hello"),
            ThreadMessage(role="assistant", content="hi"),
        ],
        summary=ThreadSummary(text="prev calls", covers_turns=4, updated_at=datetime.now(UTC)),
        scratchpad={"note": "test"},
    )
    blob = s.model_dump_json()
    s2 = State.model_validate_json(blob)
    assert len(s2.history) == 2
    assert s2.summary.covers_turns == 4
    assert s2.scratchpad == {"note": "test"}
