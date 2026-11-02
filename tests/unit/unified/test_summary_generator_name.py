from noble_agent.agent.summary.generator import _format_history


def test_format_history_uses_agent_name():
    h = [{"role": "user", "content": "hỏi giá"}, {"role": "assistant", "content": "dạ 2 tỷ"}]
    out = _format_history(h, agent_name="Aria")
    assert "Aria: dạ 2 tỷ" in out
    assert "Luna" not in out


def test_format_history_default_luna():
    h = [{"role": "assistant", "content": "dạ 2 tỷ"}]
    assert "Luna: dạ 2 tỷ" in _format_history(h)
