"""build_greeting: the voice opening line comes from the tenant config
(``agent_config.greeting`` via ``NobleAgent.get_identity``) with a brand-aware
default fallback — it no longer lives in SOUL.md / the system prompt."""

from __future__ import annotations

from noble_agent.voice.voice_agent import VoiceAgent


class _FacadeStub:
    def __init__(self, identity: dict):
        self._identity = identity

    def get_identity(self) -> dict:
        return self._identity


def _agent(identity: dict) -> VoiceAgent:
    # __new__ skips the heavy __init__ (TTS backend); build_greeting only
    # touches self._llm and settings.
    va = VoiceAgent.__new__(VoiceAgent)
    va._llm = _FacadeStub(identity)
    return va


async def test_uses_configured_greeting_verbatim():
    va = _agent({"agent_name": "Mai", "brand": "An Phú Land", "greeting": "Alô, Mai của An Phú Land nghe đây ạ!"})
    text = await va.build_greeting("sid")
    assert "Alô, Mai của An Phú Land nghe đây ạ!" in text
    assert "Em chào anh chị" not in text  # default line not mixed in


async def test_default_when_greeting_empty():
    va = _agent({"agent_name": "Mai", "brand": "An Phú Land", "greeting": ""})
    text = await va.build_greeting("sid")
    assert "Em chào anh chị, em là Mai bên An Phú Land." in text
    assert "quan tâm dự án nào" in text


async def test_default_without_brand_has_no_dangling_ben():
    va = _agent({"agent_name": "Mai", "brand": "", "greeting": ""})
    text = await va.build_greeting("sid")
    assert "em là Mai." in text
    assert " bên " not in text


async def test_default_is_not_call_centre_register():
    # The fallback must not re-teach the "Dạ … ạ" tổng-đài habit the persona bans.
    va = _agent({"agent_name": "Mai", "brand": "An Phú Land", "greeting": ""})
    text = await va.build_greeting("sid")
    assert "Dạ" not in text
    assert "Quý Khách" not in text
    assert text.count(" ạ") == 1  # one closing "ạ" on the question, nowhere else


async def test_falls_back_when_facade_lacks_get_identity():
    va = VoiceAgent.__new__(VoiceAgent)
    va._llm = object()  # no get_identity → default line with settings.agent_name
    text = await va.build_greeting("sid")
    assert "Em chào anh chị" in text
