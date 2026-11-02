from noble_agent.agent.memory import snapshot


def test_flatten_history_uses_agent_name():
    h = [{"role": "assistant", "content": "dạ em chào"}]
    out = snapshot._flatten_history(h, agent_name="Aria")
    assert "Aria: dạ em chào" in out
    assert "Luna" not in out


def test_build_merge_prompt_threads_agent_name():
    h = [{"role": "assistant", "content": "dạ em chào"}]
    p = snapshot.build_merge_prompt("cũ", h, agent_name="Aria")
    assert "Aria: dạ em chào" in p


def test_render_uses_agent_name():
    turns = [{"role": "agent", "content": "dạ em tư vấn"}]
    out = snapshot._render("", turns, agent_name="Aria")
    assert "Aria: dạ em tư vấn" in out
    assert "Luna" not in out


def test_flatten_history_default_luna():
    h = [{"role": "assistant", "content": "dạ em chào"}]
    assert "Luna: dạ em chào" in snapshot._flatten_history(h)
