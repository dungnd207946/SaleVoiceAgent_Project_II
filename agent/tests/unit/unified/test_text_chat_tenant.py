import inspect

from noble_agent.server import text_chat


def test_handle_text_session_accepts_tenant_id():
    sig = inspect.signature(text_chat.handle_text_session)
    assert "tenant_id" in sig.parameters
    assert sig.parameters["tenant_id"].default is None
