"""Reusable LiveKit mocks for integration tests (Phase 5).

Exposes factories / pytest fixtures that can stand in for a real
`rtc.Room`, a `RemoteTrack`, and a PCM-yielding `AudioStream`. Built so
that `RoomSession` and `BaseSession` can be driven end-to-end without
docker.

Typical usage (in a test):

    from tests.fixtures.livekit import make_mock_room, make_pcm_stream

    room = make_mock_room(participants={"caller": make_mock_participant("caller", track)})
    # dispatch the registered "participant_disconnected" callback when needed:
    room.fire("participant_disconnected", participant)

The mocks are intentionally small and explicit — no MagicMock sprawl —
so regression diffs are readable.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# ----------------------------------------------------------------------
# Stand-ins for rtc.RemoteTrack / rtc.RemoteTrackPublication /
# rtc.RemoteParticipant. They're duck-typed — RoomSession only touches
# these attributes.
# ----------------------------------------------------------------------


@dataclass
class FakeRemoteTrack:
    sid: str = "TR_fake"
    kind: Any = None  # set to rtc.TrackKind.KIND_AUDIO at construction

    def __post_init__(self) -> None:
        if self.kind is None:
            from livekit import rtc

            self.kind = rtc.TrackKind.KIND_AUDIO


@dataclass
class FakeTrackPublication:
    kind: Any
    track: FakeRemoteTrack | None
    sid: str = "TP_fake"


@dataclass
class FakeRemoteParticipant:
    identity: str = "caller"
    track_publications: dict[str, FakeTrackPublication] = field(default_factory=dict)


class FakeRoom:
    """Minimal drop-in for `rtc.Room` as used by RoomSession.

    Registers event handlers via `.on(event)(fn)`. Tests dispatch events
    by calling `.fire(event, *args)`.
    """

    def __init__(self, *, name: str = "fake-room") -> None:
        self.name = name
        self.remote_participants: dict[str, FakeRemoteParticipant] = {}
        self._handlers: dict[str, list[Callable[..., Any]]] = {}
        self.local_participant = FakeLocalParticipant()

    def on(self, event: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def _register(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._handlers.setdefault(event, []).append(fn)
            return fn

        return _register

    def fire(self, event: str, *args: Any) -> None:
        for fn in self._handlers.get(event, []):
            fn(*args)


class FakeLocalParticipant:
    """Minimal stand-in for `room.local_participant`. Tracks published
    tracks so tests can assert on them."""

    def __init__(self) -> None:
        self.published_tracks: list[Any] = []

    async def publish_track(self, track: Any) -> Any:
        self.published_tracks.append(track)
        return track

    async def unpublish_track(self, track_sid: str) -> None:
        self.published_tracks = [t for t in self.published_tracks if getattr(t, "sid", None) != track_sid]


# ----------------------------------------------------------------------
# Factories
# ----------------------------------------------------------------------


def make_mock_caller_track(identity: str = "caller") -> FakeRemoteTrack:
    """A subscribed audio track stand-in for `RoomSession._wait_for_caller_audio_track`."""
    track = FakeRemoteTrack(sid=f"TR_{identity}")
    return track


def make_mock_participant(
    identity: str = "caller",
    *,
    track: FakeRemoteTrack | None = None,
) -> FakeRemoteParticipant:
    p = FakeRemoteParticipant(identity=identity)
    if track is not None:
        from livekit import rtc

        p.track_publications[f"TP_{identity}"] = FakeTrackPublication(kind=rtc.TrackKind.KIND_AUDIO, track=track)
    return p


def make_mock_room(
    *,
    participants: dict[str, FakeRemoteParticipant] | None = None,
    name: str = "fake-room",
) -> FakeRoom:
    room = FakeRoom(name=name)
    if participants:
        room.remote_participants.update(participants)
    return room


# ----------------------------------------------------------------------
# Audio generators
# ----------------------------------------------------------------------


def tone_pcm(
    freq_hz: int = 440,
    duration_s: float = 1.0,
    sample_rate: int = 8000,
    amplitude: int = 10_000,
) -> bytes:
    """Pre-recorded PCM16 sine tone. Good enough for RMS/FFT assertions."""
    n = int(sample_rate * duration_s)
    t = np.arange(n) / sample_rate
    samples = (np.sin(2 * math.pi * freq_hz * t) * amplitude).astype(np.int16)
    return samples.tobytes()


def silence_pcm(duration_s: float = 0.1, sample_rate: int = 8000) -> bytes:
    n = int(sample_rate * duration_s)
    return b"\x00\x00" * n


async def chunked_async_iter(pcm: bytes, *, chunk_bytes: int = 640) -> AsyncIterator[bytes]:
    """Yield the buffer as `chunk_bytes`-sized async chunks, with an
    event-loop yield between each — enough to let the pipeline schedule.
    """
    for i in range(0, len(pcm), chunk_bytes):
        yield pcm[i : i + chunk_bytes]
        await asyncio.sleep(0)


# ----------------------------------------------------------------------
# pytest fixtures (opt-in: import explicitly or via conftest.py)
# ----------------------------------------------------------------------

import pytest  # noqa: E402 — fixtures must follow definitions


@pytest.fixture
def mock_room() -> FakeRoom:
    return make_mock_room()


@pytest.fixture
def mock_caller_track() -> FakeRemoteTrack:
    return make_mock_caller_track()


@pytest.fixture
def mock_audio_stream() -> Callable[[bytes | None], AsyncIterator[bytes]]:
    """Returns a factory — call with a pcm buffer to get an async iterator."""

    def _factory(pcm: bytes | None = None) -> AsyncIterator[bytes]:
        return chunked_async_iter(pcm if pcm is not None else silence_pcm())

    return _factory
