"""Snapshot memory settings: lock knobs present, removed long-term knobs gone."""

from __future__ import annotations

from noble_agent.config import get_settings


def test_snapshot_lock_settings_defaults():
    s = get_settings()
    assert s.snapshot_lock_wait_sec == 10.0
    assert s.snapshot_lock_ttl_sec == 60
    assert s.user_memory_short_term_turns == 6
    assert s.user_memory_since_days == 30


def test_removed_long_term_settings_absent():
    s = get_settings()
    for gone in (
        "user_memory_enabled",
        "user_memory_backend",
        "user_memory_qdrant_collection",
        "user_memory_recall_top_k",
        "user_memory_dedup_enabled",
        "user_memory_dedup_threshold",
    ):
        assert not hasattr(s, gone), f"{gone} should be removed"
