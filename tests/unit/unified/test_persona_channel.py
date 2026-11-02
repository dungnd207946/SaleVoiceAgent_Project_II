"""Persona channel split (2026-08-12): the shared skeleton ships persona/chat/
+ persona/voice/; flat legacy tenant bundles keep serving both channels."""

from pathlib import Path

import pytest

import noble_agent
from noble_agent.agent import facade
from noble_agent.agent.base import PERSONA_CHANNELS, resolve_persona_dir

SKELETON = Path(noble_agent.__file__).resolve().parent / "persona"
FLAT_BUNDLE = Path(noble_agent.__file__).resolve().parent / "tenants" / "noble" / "persona"


@pytest.mark.parametrize("channel", PERSONA_CHANNELS)
def test_skeleton_resolves_to_channel_subdir(channel):
    assert resolve_persona_dir(SKELETON, channel) == SKELETON / channel


@pytest.mark.parametrize("channel", PERSONA_CHANNELS)
def test_flat_legacy_bundle_falls_back_to_base(channel):
    # tenants/<id>/persona/ has no chat|voice subdirs → both channels share it
    assert resolve_persona_dir(FLAT_BUNDLE, channel) == FLAT_BUNDLE


def test_unknown_channel_rejected():
    with pytest.raises(ValueError, match="unknown persona channel"):
        resolve_persona_dir(SKELETON, "sms")


@pytest.mark.asyncio
async def test_create_requires_channel():
    # channel is keyword-only with NO default: a new call site that forgets it
    # must fail loudly instead of silently picking a persona.
    with pytest.raises(TypeError):
        await facade.NobleAgent.create("sess-x")


@pytest.mark.asyncio
async def test_create_rejects_unknown_channel():
    with pytest.raises(ValueError, match="unknown persona channel"):
        await facade.NobleAgent.create("sess-x", channel="sms")
