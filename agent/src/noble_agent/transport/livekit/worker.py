"""LiveKit worker entrypoint — Phase 3 of LIVEKIT_MIGRATION.md.

Runs one `RoomSession` per job. Lifecycle is driven by
`livekit.agents.JobContext`: the framework handles SIGTERM, job dispatch,
health, and graceful shutdown.

See plan §8.4 for the reference shape.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading

from livekit import agents

from noble_agent.config import settings
from noble_agent.transport.livekit.agent_audio_io import AudioIOConfig
from noble_agent.transport.livekit.room_session import RoomSession

logger = logging.getLogger("server")


def _install_tracemalloc_if_enabled() -> None:
    """Opt-in memory profiling for Phase 6 soak runs.

    Set `TRACEMALLOC_ENABLED=1` to start tracing on process boot. Send
    SIGUSR1 to the job-process at any time to dump the top allocation
    sites to `/tmp/noble_tracemalloc_<pid>.txt`:

        kill -USR1 <worker-pid>

    Kept off by default — tracemalloc adds ~5-20% overhead on allocation
    heavy code paths. Only flip on while hunting leaks under load.
    """
    if os.environ.get("TRACEMALLOC_ENABLED") != "1":
        return

    import signal as _signal
    import tracemalloc

    tracemalloc.start(25)  # 25 frames of stack per allocation
    logger.info("[tracemalloc] enabled (25-frame depth)")

    def _dump(_sig: int, _frame: object) -> None:
        import tempfile

        snapshot = tracemalloc.take_snapshot().filter_traces(
            (
                tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
                tracemalloc.Filter(False, "<frozen importlib._bootstrap_external>"),
                tracemalloc.Filter(False, tracemalloc.__file__),
            )
        )
        top = snapshot.statistics("lineno")[:30]
        path = os.path.join(tempfile.gettempdir(), f"noble_tracemalloc_{os.getpid()}.txt")
        with open(path, "w") as f:
            f.write(f"# tracemalloc snapshot pid={os.getpid()} at {__import__('time').time():.0f}\n")
            for i, stat in enumerate(top, 1):
                f.write(f"{i:2d}. {stat}\n")
        logger.info("[tracemalloc] SIGUSR1 → %s (top %d)", path, len(top))

    try:
        _signal.signal(_signal.SIGUSR1, _dump)
    except (ValueError, OSError) as exc:
        logger.warning("[tracemalloc] SIGUSR1 hook failed: %s", exc)


def _prewarm(_proc: agents.JobProcess) -> None:
    """Runs once per job-process BEFORE the first caller is dispatched.

    Eager-loads heavyweight models (Silero VAD, FlatStore e5-large ONNX,
    Smart Turn, gender detector) so the first RAG query in a session doesn't
    eat a ~10-15s cold-start while the caller sits in silence. Any
    failure is logged — the session can still run without a given model.
    """
    _install_tracemalloc_if_enabled()

    # Thay logging của livekit-agents trong job subprocess bằng formatter màu
    # + icon theo loại (server/logging_config.py) — toàn bộ log phiên
    # (STT/TTS/LLM/[Speaker]/[VAD]) phát từ process này. Process cha (dispatch)
    # giữ nguyên logging của cli.run_app.
    from noble_agent.server.logging_config import setup_logging

    setup_logging()

    # Per job-subprocess: register Phoenix tracing once so this process's LLM
    # SDK calls are instrumented (no-op when the endpoint is unset).
    from noble_agent.observability.phoenix_tracing import init_tracing

    init_tracing(settings)

    import time

    t0 = time.monotonic()

    try:
        from noble_agent.voice.vad import SileroVAD

        SileroVAD()
    except Exception as exc:  # noqa: BLE001
        logger.warning("prewarm: SileroVAD failed: %s", exc)

    try:
        from noble_agent.voice.gender_detector import GenderDetector

        GenderDetector.get_instance()
    except Exception as exc:  # noqa: BLE001
        logger.warning("prewarm: GenderDetector failed: %s", exc)

    if settings.smart_turn_enabled:
        try:
            from noble_agent.voice.turn_detection.smart_turn import get_detector

            get_detector()
        except Exception as exc:  # noqa: BLE001
            logger.warning("prewarm: Smart Turn failed: %s", exc)

    # Step 9: warm ONLY what the configured RAG backend actually uses. Warming the
    # wrong thing here is not a slow boot, it is an outage: FlatStore encodes 285
    # chunks on CPU when `data/flat_store/*.npy` is absent (gitignored → not in the
    # image), which blows LiveKit's init timeout, and the supervisor then kills and
    # respawns the job-process forever — no call is ever served. This gate used to
    # be `== "qdrant"` else FlatStore, so `kb_service` (retrieval fully in Qdrant,
    # embedding over HTTP) took the FlatStore branch and hit exactly that loop.
    #   flat_store        → the whole store (chunks + embeddings)
    #   qdrant, hipporag  → embedder singleton only (hipporag's sparse triple-seed
    #                       embeds queries through it too); no chunk encode
    #   kb_service, grep_faq, empty → nothing in-process to warm
    import asyncio as _asyncio

    from noble_agent.config import settings as _settings

    _backend = (_settings.noble_rag_backend or "flat_store").lower()
    try:
        if _backend in ("qdrant", "hipporag"):
            from noble_agent.agent.rag.qdrant_adapter import _embed_query

            _embed_query("warmup")
        elif _backend == "flat_store":
            from noble_agent.agent.rag.flat_store_adapter import _ensure_flat_store

            _asyncio.run(_ensure_flat_store())
        else:
            logger.info("prewarm: RAG backend %s needs no in-process warm", _backend)
    except Exception as exc:  # noqa: BLE001
        logger.warning("prewarm: RAG warm failed (backend=%s): %s", _backend, exc)

    # Eager-load the configured STT (sherpa) + TTS (vieneu) singletons. The helper
    # does its own per-backend try/except → a single call never aborts the process.
    from noble_agent.voice.prewarm import prewarm_voice_models

    prewarm_voice_models()

    # Warm the registry cache on a throwaway loop, then DROP the pool it created
    # — otherwise the singleton stays bound to this now-closed asyncio.run loop
    # and the first live query on the real job loop dies with "Event loop is
    # closed". _cache (loop-independent) survives.
    async def _warm_registry() -> None:
        from noble_agent.data import db_project_registry
        from noble_agent.storage.postgres_client import close_pool

        try:
            await db_project_registry.warm()
        finally:
            # The pg provider (pg_kb) opens a pool inside warm(); drop it here.
            await close_pool()

    try:
        _asyncio.run(_warm_registry())
    except Exception as exc:  # noqa: BLE001 — prewarm must never abort the worker
        logger.warning("prewarm: db_project_registry.warm failed: %s", exc)

    logger.info("prewarm complete in %.1fs", time.monotonic() - t0)


# How long to wait for a caller to show up after the job is assigned. The
# LiveKit SIP service dispatches the room *before* the caller finishes
# SIP INVITE handshake, so a short wait is expected even on fast links.
CALLER_WAIT_TIMEOUT_S = 10.0


def _job_tenant(metadata_json: str, default: str) -> str:
    """Per-job tenant from the caller's participant metadata (gateway-set),
    else the process default. De-globalize: a voice job resolves its own
    tenant, it does NOT assume the worker's home tenant."""
    import json as _json

    try:
        data = _json.loads(metadata_json) if metadata_json else {}
    except (ValueError, TypeError):
        return default
    tid = data.get("tenant_id") if isinstance(data, dict) else None
    return tid or default


async def entrypoint(ctx: agents.JobContext) -> None:
    """Per-job entrypoint. Invoked by the LiveKit agents framework once per
    caller/room.
    """
    # Connect storage on the first job per subprocess (idempotent after).
    # Without this every Redis-backed read/write silently no-ops because the
    # worker never initializes the Redis singleton — the aiortc entrypoint
    # used to do it, but LiveKit workers don't go through agent.app.main().
    from noble_agent.storage.connection import get_connection_manager

    await get_connection_manager().initialize()

    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)
    logger.info("worker joined room=%s (job=%s)", ctx.room.name, ctx.job.id if ctx.job else "?")

    try:
        caller = await ctx.wait_for_participant()
    except TimeoutError:
        logger.warning("no caller appeared in room=%s — exiting job", ctx.room.name)
        return

    logger.info("caller joined: identity=%s kind=%s", caller.identity, caller.kind)

    # Slice #2: gateway puts the end-user identity in the caller's participant
    # metadata (JSON). Seed Customer before the session starts so the frozen
    # customer block picks it up — same field mapping as app_session.
    import json as _json

    from noble_agent.server.app_session import identity_to_fields
    from noble_agent.storage.models import Customer
    from noble_agent.storage.redis_client import get_redis
    from noble_agent.storage.repo import StateRepo

    try:
        identity = _json.loads(caller.metadata) if getattr(caller, "metadata", "") else {}
    except (ValueError, TypeError):
        identity = {}

    # De-globalize: resolve this job's own tenant from the caller's participant
    # metadata (gateway-set) instead of assuming the worker's home tenant. No
    # reset — the job owns its subprocess/task; NobleAgent.create captures this
    # per-job tenant downstream.
    from noble_agent.tenant.current import set_current_tenant

    job_tenant = _job_tenant(getattr(caller, "metadata", "") or "", settings.tenant_id)
    set_current_tenant(job_tenant)

    # Per-tenant PG credential: gateway stash vào Redis (mã hoá) trước khi dispatch —
    # ingest ở đây để pool_for_tenant dựng pool bằng chính role tenant. Best-effort:
    # không có stash / secret rỗng / giải mã fail → shared DSN như cũ.
    try:
        from noble_agent.storage.credential_stash import adopt_agent_key, fetch_and_register

        if settings.gateway_worker_secret:
            await fetch_and_register(await get_redis(), settings.gateway_worker_secret, job_tenant)
            # Đóng dấu agent_key_id (định danh API key Portal) vào contextvar của
            # job — pg_data_plane đọc để ghi conversations.agent_key_id.
            adopt_agent_key(job_tenant)
    except Exception:  # noqa: BLE001 — credential là tăng cường, không được chặn cuộc gọi
        logger.warning("worker: ingest PG credential fail (tenant=%s) — dùng shared DSN", job_tenant)

    if isinstance(identity, dict) and identity:
        fields = identity_to_fields(identity)
        if fields:
            redis = await get_redis()
            repo = StateRepo(redis_client=redis, ttl_seconds=settings.session_ttl_seconds)
            meta, customer, state = await repo.load(ctx.room.name)
            merged = customer.model_dump()
            for k, v in fields.items():
                if isinstance(v, bool) or v:
                    merged[k] = v
            await repo.save_all(ctx.room.name, meta, Customer.model_validate(merged), state)

    # Browser callers (Opus @ 48 kHz) need LiveKit to resample. Set the two
    # directions independently so TTS output doesn't play back slow/deep:
    #   input  = stt_sample_rate  (16 kHz — what Soniox/Scribe expect)
    #   output = tts_sample_rate  (24 kHz — what ElevenLabs emits)
    audio_config = AudioIOConfig(
        input_sample_rate=settings.stt_sample_rate,
        output_sample_rate=settings.tts_sample_rate,
        queue_size_ms=settings.tts_output_queue_ms,
    )
    # db-mode voice heartbeat: fork-safe, runs here in the job subprocess for
    # this call's tenant and lifetime (see _start_job_heartbeat). Inert (None)
    # in legacy mode / when the gate is closed.
    hb_task, hb_stop = _start_job_heartbeat(job_tenant)

    session = RoomSession(
        room=ctx.room,
        session_id=ctx.room.name,
        caller_identity=caller.identity,
        audio_config=audio_config,
    )
    try:
        await session.start()
        await session.wait_until_end()
    finally:
        if hb_stop is not None:
            import asyncio as _asyncio

            hb_stop.set()
            if hb_task is not None:
                hb_task.cancel()
                with contextlib.suppress(_asyncio.CancelledError, Exception):
                    await hb_task
        await session.stop()


def _start_heartbeat() -> None:
    """SP-D heartbeat supervisor for the LiveKit worker (contract C3).

    LEGACY MinIO path only. In db-mode this returns immediately — the voice
    heartbeat runs per-job inside ``entrypoint`` (``_start_job_heartbeat``),
    which is fork-safe; a main-process supervisor here could never observe a
    job subprocess's ``mark_active``.

    Runs in a daemon thread with its OWN event loop — the agents framework owns
    the main loop via ``cli.run_app`` and exposes no persistent-coroutine hook.
    The supervisor manages heartbeats for all active tenants using a materialize-only
    build function: the dispatch process must not build a full LLM runner (no
    providers/Redis here), but materialize+checksum proves the published version is
    loadable and warms the shared on-disk dir for the job subprocesses. Best-effort —
    a failure never blocks the worker. The daemon thread runs for the process lifetime
    (dies with it); no explicit stop needed.

    Note: in a split deploy (aiortc chat + LiveKit voice for the same tenant) both
    may write ``<tenant>/_heartbeat.json`` (last-writer-wins each ~20 s); since both
    poll the same pointer they converge on the same published version.
    """
    from noble_agent.tenant.heartbeat import should_emit

    if not should_emit(settings):
        return

    # db-mode: the voice heartbeat runs PER-JOB inside ``entrypoint`` (see
    # ``_start_job_heartbeat``), because ``mark_active`` runs in the fork-per-job
    # subprocess that a main-process supervisor here could never observe. So the
    # main worker process starts NO heartbeat thread in db-mode. Only the legacy
    # MinIO supervisor (which enumerates ``store.list_ids()`` and is
    # process-independent) runs from the main process.
    if settings.agent_config_source == "db":
        return

    def _run() -> None:
        import asyncio as _asyncio

        from noble_agent.tenant.heartbeat import build_heartbeat_supervisor

        async def _main() -> None:
            supervisor = build_heartbeat_supervisor(settings, "voice")
            await supervisor.run(_asyncio.Event())  # never set → runs for the worker's life

        try:
            _asyncio.run(_main())
        except Exception:  # noqa: BLE001 — heartbeat must never take down the worker
            logger.warning("heartbeat: LiveKit thread crashed", exc_info=True)

    threading.Thread(target=_run, name="sp-d-heartbeat", daemon=True).start()
    logger.info("heartbeat: LiveKit supervisor daemon thread started")


def _start_job_heartbeat(tenant_id: str):
    """Per-job voice heartbeat for db-mode (fork-safe). Returns ``(task, stop)``
    or ``(None, None)`` when the gate is closed / not db-mode.

    Runs INSIDE the LiveKit job subprocess on the session event loop — the
    process that actually knows this call's tenant and where ``get_pool()``
    binds correctly — so it does not depend on a main-process supervisor seeing
    the subprocess's ``mark_active``. Beats ``tenant_id`` for the call's
    lifetime; the ``entrypoint`` stops it when the session ends.
    """
    import asyncio as _asyncio

    from noble_agent.tenant.heartbeat import should_emit

    if not should_emit(settings) or settings.agent_config_source != "db":
        return None, None

    from noble_agent.tenant.pg_heartbeat import run_job_heartbeat

    stop = _asyncio.Event()
    interval = float(getattr(settings, "heartbeat_sec", 20.0))
    agent_version = getattr(settings, "agent_version", "")
    task = _asyncio.create_task(run_job_heartbeat(tenant_id, "voice", agent_version, interval, stop))
    logger.info("heartbeat: per-job voice heartbeat started tenant=%s", tenant_id)
    return task, stop


def run_worker() -> None:
    """CLI entry used by `app.main()` when `TRANSPORT_BACKEND=livekit`.

    Concurrency note: the agents framework manages concurrency via process
    pools (`num_idle_processes`) and a load-threshold gate, not a single
    max-jobs integer. `settings.worker_max_concurrent_sessions` is retained
    as an advisory value — in Phase 8 we'll tune it to the right knobs for
    our production deployment.
    """
    _start_heartbeat()  # SP-D (contract C3): inert unless the tenant store is enabled
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=_prewarm,
            # Prewarm nạp ~900MB model (Silero + e5-large + friends) mỗi job —
            # ngưỡng mặc định 500MB spam "process memory usage is high" mỗi 5s.
            job_memory_warn_mb=2048,
            agent_name=settings.livekit_agent_name,
            ws_url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
            # Prewarm loads SileroVAD + FlatStore (e5-large ONNX) + friends. ~6-10s on a warm
            # HF cache, up to ~20s cold on Linux. Under concurrent spawns
            # on macOS (load-test / multi-process fork) it can hit 46 s
            # because disk I/O serializes — so allow 3 min. Override via
            # `INITIALIZE_PROCESS_TIMEOUT` env var if you need tighter.
            initialize_process_timeout=float(os.environ.get("INITIALIZE_PROCESS_TIMEOUT", "180.0")),
            # Keep at least one prewarmed job-process idling in dev so each
            # new call doesn't cold-spawn and reload FlatStore from scratch.
            # Prod default is 4; dev default is 0 (which is what made every
            # call pay ~10s of model-load latency). Override with
            # `NUM_IDLE_PROCESSES` env var to scale up.
            num_idle_processes=int(os.environ.get("NUM_IDLE_PROCESSES", "1")),
            # Internal HTTP health/metrics port. LK agents defaults to 8081
            # which collides with some host setups (e.g. RunPod's nginx proxy
            # template). Override via LIVEKIT_WORKER_PORT env var. Reads from
            # `settings` because pydantic loads .env into the Settings object —
            # unlike os.environ.get which doesn't see .env values that aren't
            # exported to the shell.
            port=settings.livekit_worker_port,
        )
    )
