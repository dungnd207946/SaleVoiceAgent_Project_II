"""SP-D heartbeat emitter (Odyssey contract C3).

The agent **proactively** writes ``<tenant_id>/_heartbeat.json`` to the tenant
store every ~``heartbeat_sec`` (BR02 — Backend never calls down to the agent).
Backend/Dashboard read that file and *infer* status from version comparison +
``ts`` freshness (fresh ≤ 60 s, "applying" > 2 min → E03); the agent only emits
the shape truthfully.

Each beat resolves the published version straight off the store pointer (the
heartbeat IS the ~20 s config poller), then — for a versioned tenant — proactively
builds+checksums that version via the facade so ``running_version`` catches up to
``published_version_seen`` even when no new conversation arrives (the condition
that lets the Dashboard's E03 inference be correct) and the next conversation's
build cache is warm. A checksum (E04) / build failure keeps the last-good
``running_version`` and reports ``status_hint="degraded"`` with ``last_error``.

A store outage on the *read* side skips the beat entirely (nothing to write, and
a stale ``ts`` is exactly the honest "Mất kết nối" / E02 signal). Scope: wired
into the aiortc server process only (see ``server/http.py``); the LiveKit worker
process model has no clean persistent-loop hook — deferred follow-up.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from noble_agent.tenant.version_resolver import ChecksumError, materialize_version

logger = logging.getLogger("noble_agent.tenant.heartbeat")

# status_hint enum (C3.1): "starting" | "loading" | "serving" | "degraded".


def should_emit(settings) -> bool:
    """Gate: emit the heartbeat only when there is a store to write to.

    In db-mode (``agent_config_source == "db"``) the heartbeat writes to
    ``control.agent_heartbeats`` in Postgres, not the tenant store — so the
    gate is just ``heartbeat_enabled``, no ``tenant_store_enabled`` required.

    Otherwise (legacy MinIO path): ``tenant_store_enabled AND heartbeat_enabled``
    — with the store disabled (the live Noble default) there is nowhere to
    write, so the feature is inert.
    """
    if getattr(settings, "agent_config_source", "legacy") == "db":
        return bool(getattr(settings, "heartbeat_enabled", True))
    return bool(getattr(settings, "tenant_store_enabled", False)) and bool(
        getattr(settings, "heartbeat_enabled", True)
    )


def build_heartbeat_supervisor(settings, kind: str):
    """Pick the PG (db-mode) or MinIO (legacy) heartbeat supervisor.

    Both transports (aiortc chat, LiveKit voice) call this instead of
    constructing ``HeartbeatSupervisor`` directly, so the config-source split
    lives in one place.
    """
    if getattr(settings, "agent_config_source", "legacy") == "db":
        from noble_agent.tenant.pg_heartbeat import PgHeartbeatSupervisor

        return PgHeartbeatSupervisor(
            kind, getattr(settings, "agent_version", ""), float(getattr(settings, "heartbeat_sec", 20.0))
        )
    from noble_agent.tenant.loader import _build_store

    return HeartbeatSupervisor(_build_store(settings), settings)


def build_materialize_fn(store, settings, tenant_id):
    """A ``build_fn`` that only materializes + checksums a version to disk.

    For a dispatch-only process (the LiveKit main worker) that must NOT build a
    full LLM runner (no providers/Redis there) but should still prove the
    published version is fetchable + checksum-valid (E04) — which is exactly what
    lets ``running_version`` advance truthfully — and warm the shared on-disk
    materialized dir for the job subprocesses. Propagates ``ChecksumError`` /
    ``FileNotFoundError`` so the emitter classifies degraded.
    """

    async def _fn(version: int) -> None:
        await asyncio.to_thread(
            materialize_version, store, tenant_id, version, settings.tenant_materialize_dir
        )

    return _fn


def _utc_iso() -> str:
    """UTC timestamp in the contract's ``2026-07-30T04:03:53Z`` shape."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_heartbeat(
    tenant_id: str,
    running_version: int,
    published_version_seen: int,
    status_hint: str,
    last_error: dict | None,
    started_at: str,
    ts: str,
) -> dict:
    """Assemble the C3.1 heartbeat document (pure)."""
    return {
        "tenant_id": tenant_id,
        "running_version": running_version,
        "published_version_seen": published_version_seen,
        "status_hint": status_hint,
        "last_error": last_error,
        "started_at": started_at,
        "ts": ts,
    }


class HeartbeatEmitter:
    """Periodically writes the tenant's heartbeat file to the store."""

    def __init__(self, store, settings, tenant_id, *, build_fn=None, now_iso=_utc_iso):
        self._store = store
        self._settings = settings
        self._tenant = tenant_id
        # Async ``version -> None`` warmer; None → resolve the facade lazily (kept
        # injectable so unit tests don't need LLM providers / Redis).
        self._build_fn = build_fn
        self._now_iso = now_iso
        self._interval = float(getattr(settings, "heartbeat_sec", 20.0))
        self.started_at = now_iso()
        self._running = 0
        self._last_error: dict | None = None

    def _resolve_published(self) -> tuple[int, str]:
        """Return ``(version, mode)`` where mode ∈ {versioned, legacy, absent}.

        Reads the pointer directly (the heartbeat is the poller, not a cache
        consumer). Raises on a store outage so ``beat`` skips the write.
        """
        ptr = self._store.read_pointer(self._tenant)
        if ptr is None:
            meta = self._store.read_meta(self._tenant)
            if meta is None:
                return 0, "absent"
            return meta.version, "legacy"  # legacy in-place bundle = v1
        return ptr, "versioned"

    async def _build(self, version: int) -> None:
        if self._build_fn is not None:
            await self._build_fn(version)
            return
        from noble_agent.agent.facade import ensure_version_built

        await ensure_version_built(version)

    async def beat(self) -> dict | None:
        """Emit one heartbeat; returns the written doc, or None if skipped."""
        now = self._now_iso()
        try:
            published, mode = await asyncio.to_thread(self._resolve_published)
        except Exception:
            logger.warning("heartbeat: store read failed for %s — skipping beat", self._tenant, exc_info=True)
            return None

        if mode == "absent":
            self._last_error = {"code": "tenant_absent", "message": f"{self._tenant} not in store", "ts": now}
            status, running, published_seen = "degraded", self._running, 0
        elif mode == "legacy":
            # In-place bundle already loaded at boot; report it serving without a
            # versioned build (there is no versions/<n>/ to materialize).
            self._running, self._last_error = published, None
            status, running, published_seen = "serving", published, published
        else:  # versioned
            published_seen = published
            try:
                await self._build(published)
                self._running, self._last_error = published, None
                status = "serving"
            except ChecksumError as e:
                self._last_error = {"code": "checksum_mismatch", "message": str(e), "ts": now}
                status = "degraded"
            except FileNotFoundError as e:
                self._last_error = {"code": "version_missing", "message": str(e), "ts": now}
                status = "degraded"
            except Exception as e:  # noqa: BLE001 — any build/provider failure is a degraded signal
                self._last_error = {"code": "load_error", "message": str(e), "ts": now}
                status = "degraded"
            running = self._running
            # A newer version is published but not yet running without an error
            # (transient) → "loading"; with inline build this collapses to serving.
            if status == "serving" and running < published_seen:
                status = "loading"

        doc = build_heartbeat(
            self._tenant, running, published_seen, status, self._last_error, self.started_at, now
        )
        try:
            await asyncio.to_thread(self._store.write_heartbeat, self._tenant, doc)
        except Exception:
            logger.warning("heartbeat: write failed for %s", self._tenant, exc_info=True)
        return doc

    async def run(self, stop_event: asyncio.Event) -> None:
        """Beat every ``heartbeat_sec`` until ``stop_event`` is set/cancelled."""
        logger.info("heartbeat: started tenant=%s interval=%.0fs", self._tenant, self._interval)
        try:
            while not stop_event.is_set():
                try:
                    await self.beat()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("heartbeat: beat raised (continuing)")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=self._interval)
        finally:
            logger.info("heartbeat: stopped tenant=%s", self._tenant)


class HeartbeatSupervisor:
    """Runs one :class:`HeartbeatEmitter` per ACTIVE tenant in the store, so a
    single shared process emits ``<tenant>/_heartbeat.json`` for every tenant it
    serves (not just ``settings.tenant_id``).

    Each cycle: refresh the active-tenant set from the store, reconcile the
    per-tenant emitters (add new, drop deactivated), then beat them all
    concurrently. A store-read error on the refresh keeps the current set — an
    emitter that can no longer read its own version already reports ``degraded`` /
    skips, and a stale ``ts`` is the honest "disconnected" signal. Emitters use a
    materialize-only ``build_fn`` (no full LLM runner) so serving N tenants never
    builds N runners.
    """

    def __init__(self, store, settings, *, build_fn_factory=None, now_iso=_utc_iso):
        self._store = store
        self._settings = settings
        self._now_iso = now_iso
        self._interval = float(getattr(settings, "heartbeat_sec", 20.0))
        # tenant_id -> async ``version -> None`` warmer; default = materialize-only.
        self._build_fn_factory = build_fn_factory or (
            lambda tid: build_materialize_fn(store, settings, tid)
        )
        self._emitters: dict[str, HeartbeatEmitter] = {}

    def _active_tenants(self) -> list[str]:
        out: list[str] = []
        for tid in self._store.list_ids():
            meta = self._store.read_meta(tid)
            if meta is not None and meta.status == "active":
                out.append(tid)
        return out

    def _reconcile(self, active: list[str]) -> None:
        active_set = set(active)
        for tid in active:
            if tid not in self._emitters:
                self._emitters[tid] = HeartbeatEmitter(
                    self._store,
                    self._settings,
                    tid,
                    build_fn=self._build_fn_factory(tid),
                    now_iso=self._now_iso,
                )
        for tid in list(self._emitters):
            if tid not in active_set:
                del self._emitters[tid]

    async def _cycle(self) -> None:
        try:
            active = await asyncio.to_thread(self._active_tenants)
        except Exception:
            logger.warning("heartbeat: active-tenant refresh failed — keeping current set", exc_info=True)
            active = list(self._emitters)
        self._reconcile(active)
        if self._emitters:
            await asyncio.gather(
                *(em.beat() for em in self._emitters.values()), return_exceptions=True
            )

    async def run(self, stop_event: asyncio.Event) -> None:
        """Beat every active tenant every ``heartbeat_sec`` until ``stop_event``."""
        logger.info("heartbeat supervisor: started interval=%.0fs", self._interval)
        try:
            while not stop_event.is_set():
                try:
                    await self._cycle()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("heartbeat supervisor: cycle raised (continuing)")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=self._interval)
        finally:
            logger.info("heartbeat supervisor: stopped (%d tenants)", len(self._emitters))
