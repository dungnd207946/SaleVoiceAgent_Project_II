from noble_agent.config import UnifiedSettings


def test_default_poll_sec():
    assert UnifiedSettings(_env_file=None).noble_config_poll_sec == 20.0
