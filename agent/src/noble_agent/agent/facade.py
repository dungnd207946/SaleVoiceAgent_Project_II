"""Drop-in NobleAgent facade for transport (text_chat, voice loop).

Mirrors the legacy StreamingLLM / refactor NobleAgent callable surface so
transport code passes sync callbacks unchanged.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import random
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from noble_agent.agent.base import PERSONA_CHANNELS, load_agent_def, resolve_persona_dir
from noble_agent.agent.llm.client import StreamingClient
from noble_agent.agent.llm.thinking import ThinkStripper
from noble_agent.agent.orchestrator import TurnRunner
from noble_agent.agent.prompts.builder import render_customer_block
from noble_agent.agent.qwen_transcript import TranscriptWriter
from noble_agent.agent.rag.noble_kb import query_noble_kb
from noble_agent.config import get_settings
from noble_agent.storage.agent_config_store import read_published_config
from noble_agent.storage.models import Customer
from noble_agent.storage.redis_client import get_redis
from noble_agent.storage.repo import StateRepo

logger = logging.getLogger("noble_agent.facade")

# version 0 (package/store-disabled), keyed (tenant, channel)
_legacy_runners: dict[tuple[str, str], TurnRunner] = {}
_runner_lock = asyncio.Lock()

# Version-keyed runner registry (SP-C2), now ALSO keyed by tenant so a shared
# multi-tenant process never serves tenant A the runner built for tenant B,
# and by persona channel ("chat" | "voice") so the two transports keep their
# own prompt (persona skeleton split, 2026-08-12).
# Cap 256 to cover O4 = 200 concurrent tenants (runner init is cheap: prompt
# text + schemas dict; provider clients are process-global one-time).
_runners: OrderedDict[tuple[str, int, str], TurnRunner] = OrderedDict()
_runners_lock = asyncio.Lock()
_RUNNERS_MAX = 256

# VN mobile prefixes (Viettel/Vina/Mobi/Vietnamobile/Gmobile ranges). A random
# draw matches update_customer's regex ^(0[35789])\d{8}$.
_VN_MOBILE_PREFIXES = ("03", "05", "07", "08", "09")


def _random_vn_mobile() -> str:
    """Return a random valid-shaped VN mobile number (10 digits)."""
    prefix = random.choice(_VN_MOBILE_PREFIXES)
    return prefix + "".join(random.choices("0123456789", k=8))


def _seed_sim_customer(customer: Customer, phone_number: str, customer_json: str) -> tuple[Customer, bool]:
    """Seed a simulated caller identity for testing (chat / LiveKit paths).

    Fills an EMPTY ``customer.phone`` from ``phone_number`` (fixed), else the
    ``"phone"`` in ``customer_json`` (fallback), else a random VN mobile. Then
    seeds the other non-empty valid ``Customer`` fields from ``customer_json``
    (app-client sim — mirrors the browser ``set_customer`` push). The DB bootstrap
    at the first turn still runs and wins over these seeded values. Any parse or
    validation problem logs a warning and drops the field seed (phone still set).
    Returns ``(customer, changed)``.
    """
    data: dict = {}
    if customer_json:
        try:
            parsed = json.loads(customer_json)
        except (ValueError, TypeError):
            logger.warning("NOBLE_SIMULATE_CUSTOMER is not valid JSON — ignoring seed")
            parsed = None
        if isinstance(parsed, dict):
            data = parsed
        elif parsed is not None:
            logger.warning("NOBLE_SIMULATE_CUSTOMER is not a JSON object — ignoring seed")

    changed = False
    if not customer.phone:
        json_phone = data.get("phone")
        json_phone = json_phone if isinstance(json_phone, str) else ""
        customer.phone = phone_number or json_phone or _random_vn_mobile()
        changed = True

    valid = set(Customer.model_fields)
    updates = {k: v for k, v in data.items() if k in valid and k != "phone" and (isinstance(v, bool) or v)}
    if updates:
        try:
            customer = Customer.model_validate({**customer.model_dump(), **updates})
            changed = True
        except ValidationError:
            logger.warning("NOBLE_SIMULATE_CUSTOMER has invalid values — ignoring seed")

    return customer, changed


class _NobleKBAdapter:
    """Thin adapter so noble_search tool can call `rag.search(query=..., project_filter=...)`."""

    async def search(
        self,
        *,
        query: str,
        project_filter: str | None,
        dinh_kem: list[dict] | None = None,
        du_an: list[str] | None = None,
        numbers: dict[str, int] | None = None,
    ) -> str:
        """`dinh_kem`, `du_an` và `numbers` là bồn chứa — xem `noble_kb.query_noble_kb`."""
        return await query_noble_kb(query or "", project_filter or "", dinh_kem, du_an, numbers)


def build_llm_providers() -> list[tuple[str, object]]:
    """Construct the ordered LLM provider list from settings.

    Exposed at module level so the readiness probe in `server/http.py` can
    list models against the active provider without spinning up the full
    `TurnRunner`.

    Three OpenAI-compatible slots are distinct (no shared template):
      - ``vllm``      — local self-host, ``VLLM_*`` (built when ``VLLM_MODEL`` set).
      - ``openai``    — the hosted OpenAI API, ``OPENAI_*`` (built when ``OPENAI_API_KEY`` set;
        default base_url ``api.openai.com`` → real-OpenAI request shaping).
      - ``dashscope`` — Qwen / Alibaba DashScope, ``DASHSCOPE_*`` (built when ``DASHSCOPE_API_KEY`` set).

    Order depends on whether vLLM is enabled (``VLLM_MODEL`` set):
      - vLLM ON:  vLLM → OpenAI → DashScope → Gemini → Anthropic (anthropic LAST, a
        final safety net that never preempts the intended chain).
      - vLLM OFF: Anthropic → OpenAI → DashScope → Gemini.
    Each slot is built only when its key/model is configured. Build order is just
    the fallback tie-break — the active provider is pinned per path via
    ``NOBLE_AGENT_MODEL`` / ``primary_for`` (which reorders the chain).
    """
    settings = get_settings()
    providers: list[tuple[str, object]] = []

    def _anthropic() -> tuple[str, object] | None:
        if not (anthropic_key := settings.anthropic_api_key):
            return None
        try:
            from noble_agent.agent.llm.anthropic_provider import AnthropicProvider

            return (
                "anthropic",
                AnthropicProvider(
                    api_key=anthropic_key,
                    model=settings.anthropic_model,
                    base_url=settings.anthropic_base_url or None,
                ),
            )
        except ImportError:
            logger.error("anthropic SDK not installed — skipping")
            return None

    try:
        import openai
    except ImportError:
        openai = None
        logger.error("openai SDK not installed")

    vllm_enabled = bool(settings.vllm_model)

    # Anthropic leads only in the no-vLLM chain (unchanged from before).
    if not vllm_enabled and (a := _anthropic()) is not None:
        providers.append(a)

    if openai is not None:
        if vllm_enabled:
            providers.append(
                (
                    "vllm",
                    openai.AsyncOpenAI(api_key=settings.vllm_api_key, base_url=settings.vllm_base_url),
                )
            )
        if openai_key := settings.openai_api_key:
            kwargs: dict[str, Any] = {"api_key": openai_key}
            if settings.openai_base_url:
                kwargs["base_url"] = settings.openai_base_url
            providers.append(("openai", openai.AsyncOpenAI(**kwargs)))
        if dashscope_key := settings.dashscope_api_key:
            providers.append(
                (
                    "dashscope",
                    openai.AsyncOpenAI(
                        api_key=dashscope_key,
                        base_url=settings.dashscope_base_url,
                    ),
                )
            )
        if settings.gemini_api_key:
            providers.append(
                (
                    "gemini",
                    openai.AsyncOpenAI(
                        api_key=settings.gemini_api_key,
                        base_url=settings.gemini_base_url,
                    ),
                )
            )

    # Anthropic appended LAST when vLLM leads — a fallback that never preempts.
    if vllm_enabled and (a := _anthropic()) is not None:
        providers.append(a)

    return providers


async def _build_runner(tenant_id: str, channel: str) -> TurnRunner:
    """Legacy single-runner build for version 0 (store-disabled/package mode)."""
    from noble_agent.tenant.current import use_tenant
    from noble_agent.tenant.loader import get_tenant_context

    with use_tenant(tenant_id):
        return await _build_runner_from_ctx(get_tenant_context(), channel)


def _skeleton_dir():
    import noble_agent

    return Path(noble_agent.__file__).resolve().parent / "persona"


async def _agent_def_from_db(tenant_id: str, channel: str):
    """Build an AgentDef from the tenant's PUBLISHED Postgres config + on-disk
    skeleton (AGENT_CONFIG_SOURCE=db). Raises if no published config exists."""
    from noble_agent.agent.agent_config import parse_config
    from noble_agent.agent.base import build_agent_def_from_config
    from noble_agent.voice.tts._normalize import set_tenant_overrides

    settings = get_settings()
    pc = await read_published_config(tenant_id)
    if pc is None:
        raise RuntimeError(f"no published config for tenant {tenant_id!r}")
    cfg = parse_config(pc.config, force_tool_first_round=settings.llm_force_tool_first_round)
    # Single call site: _build_runner_for_version parses a config too, but it then delegates
    # here, so wiring it once is enough. parse_config stays pure — do not put this inside it.
    set_tenant_overrides(cfg.tts_normalization)
    return build_agent_def_from_config(
        resolve_persona_dir(_skeleton_dir(), channel),
        cfg,
        model=settings.agent_model if getattr(settings, "agent_model", "") else settings.agent_name,
        temperature=settings.agent_temperature,
        max_tokens=settings.agent_max_tokens,
    )


async def _build_runner_from_ctx(ctx, channel: str, version: int = 0) -> TurnRunner:
    settings = get_settings()
    if settings.agent_config_source == "db":
        agent_def = await _agent_def_from_db(ctx.tenant_id, channel)
    else:
        # Legacy bundles are flat (no chat/voice subdirs) → resolve falls back
        # to the same persona for both channels.
        from noble_agent.agent.agent_config import NO_LOOKUP_TOOL

        tool_names = list(ctx.enabled_tools)
        # Van xả cho tool_choice=required vòng đầu — manifest legacy không liệt
        # kê nó, tự append khi cờ bật để lượt xã giao không bị ép gọi tool rác.
        if settings.llm_force_tool_first_round and NO_LOOKUP_TOOL not in tool_names:
            tool_names.append(NO_LOOKUP_TOOL)
        agent_def = load_agent_def(
            resolve_persona_dir(ctx.persona_dir, channel),
            tool_names=tool_names,
            agent_name=settings.agent_name,
            brand=dict(ctx.brand),
        )

    # Note: `agent_def.model` is now a no-op for live-turn routing. The
    # TurnRunner picks a per-provider model map via `provider_model_map`
    # and pins the primary provider via `NOBLE_AGENT_MODEL` →
    # `primary_for`. We still leave `agent_def.model` populated from
    # `config.json` so direct unit tests calling `runner.run_turn(...)`
    # without explicit routing fall back to a single model name.

    providers = build_llm_providers()

    if not providers:
        raise RuntimeError("No LLM providers configured (ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY)")
    logger.info("facade: LLM provider order = %s", " → ".join(n for n, _ in providers))

    llm = StreamingClient(
        providers=providers,
        enable_thinking=settings.llm_enable_thinking,
        openai_reasoning_effort=settings.openai_reasoning_effort,
    )
    logger.info("facade: thinking mode = %s", "on" if settings.llm_enable_thinking else "off")
    redis_client = await get_redis()
    repo = StateRepo(redis_client=redis_client, ttl_seconds=settings.session_ttl_seconds)
    rag = _NobleKBAdapter()

    transcript_writer: TranscriptWriter | None = None
    if settings.transcript_log_enabled:
        transcript_writer = TranscriptWriter(settings.transcript_log_dir, agent_def)
        logger.info("facade: transcript logging → %s", settings.transcript_log_dir)

    semcache = None
    if settings.semcache_enabled:
        from noble_agent.semcache import SemCacheManager

        semcache = SemCacheManager(
            redis=redis_client,
            agent_def=agent_def,
            llm=llm,
            rag=rag,
            settings=settings,
        )
        logger.info(
            "facade: semantic cache enabled (n=%d threshold=%.2f model=%s)",
            settings.semcache_num_predictions,
            settings.semcache_threshold,
            settings.semcache_embed_model,
        )

    return TurnRunner(
        repo=repo,
        agent_def=agent_def,
        llm=llm,
        rag=rag,
        settings=settings,
        transcript_writer=transcript_writer,
        semcache=semcache,
        channel=channel,
        version=version,
    )


async def _get_runner(tenant_id: str, channel: str) -> TurnRunner:
    key = (tenant_id, channel)
    existing = _legacy_runners.get(key)
    if existing is not None:
        return existing
    async with _runner_lock:
        existing = _legacy_runners.get(key)
        if existing is None:
            existing = await _build_runner(tenant_id, channel)
            _legacy_runners[key] = existing
    return existing


async def _resolve_current_version(tenant_id: str) -> int:
    """Published config version to serve NEW conversations, or 0 for legacy.

    db-mode (``AGENT_CONFIG_SOURCE=db``): version of the tenant's published
    config row (``read_published_config``), 0 when there is none.

    Legacy (MinIO tenant-store) mode: returns 0 (→ legacy ``_get_runner``
    package path) when the tenant store is disabled or the tenant isn't
    ``active`` in the store (or the store is unreachable at the gate).
    Otherwise resolves the TTL-cached pointer via ``current_published_version``
    (which itself serves last-good on a store outage, E01)."""
    settings = get_settings()
    if settings.agent_config_source == "db":
        pc = await read_published_config(tenant_id)
        return pc.version if pc is not None else 0
    if not getattr(settings, "tenant_store_enabled", False):
        return 0
    from noble_agent.tenant.loader import _build_store
    from noble_agent.tenant.version_resolver import current_published_version

    store = _build_store(settings)
    try:
        ptr = store.read_pointer(tenant_id)
    except Exception:
        # Store outage at the gate (E01): keep serving the last-good version this
        # process already resolved (its context is cached → store-free), instead
        # of silently dropping to the package bundle. No prior version → legacy.
        from noble_agent.tenant.version_resolver import last_good_version

        return last_good_version(tenant_id) or 0
    if ptr is None:
        # No published pointer → a legacy in-place tenant (has a bundle but no
        # versions/, e.g. imported before SP-C1) OR the tenant is absent. Use the
        # legacy loader path (get_tenant_context → read_bundle read-compat), which
        # serves the in-place bundle. The versioned path (materialize_version →
        # read_version_bundle) has nothing to read for such a tenant.
        return 0
    return current_published_version(store, settings, tenant_id)


async def _build_runner_for_version(tenant_id: str, version: int, channel: str) -> TurnRunner:
    """Build a runner whose agent_def comes from the tenant's config `version`."""
    settings = get_settings()
    from noble_agent.tenant.current import use_tenant

    if settings.agent_config_source == "db":
        # `version` is advisory in db-mode: the runner is always built from the CURRENT
        # published config (`read_published_config` re-read — the `agent_published_config`
        # VIEW only exposes the current published row), relying on version immutability;
        # historical-version pinning is a deferred follow-up.
        from noble_agent.agent.agent_config import parse_config
        from noble_agent.tenant.db_context import context_from_config, set_db_context

        pc = await read_published_config(tenant_id)
        if pc is None:
            raise RuntimeError(f"no published config for tenant {tenant_id!r}")
        ctx = context_from_config(tenant_id, parse_config(pc.config), skeleton_dir=_skeleton_dir())
        set_db_context(tenant_id, ctx)
        with use_tenant(tenant_id):
            return await _build_runner_from_ctx(ctx, channel, version)

    from noble_agent.tenant.loader import _build_store
    from noble_agent.tenant.version_resolver import context_for_version

    store = _build_store(settings)
    ctx = context_for_version(store, settings, tenant_id, version)
    with use_tenant(tenant_id):
        return await _build_runner_from_ctx(ctx, channel, version)


async def _get_runner_for_version(tenant_id: str, version: int, channel: str) -> TurnRunner:
    """Get-or-build the runner for a (tenant, version, channel) triple into the bounded registry."""
    key = (tenant_id, version, channel)
    existing = _runners.get(key)
    if existing is not None:
        _runners.move_to_end(key)
        return existing
    async with _runners_lock:
        existing = _runners.get(key)
        if existing is not None:
            _runners.move_to_end(key)
            return existing
        runner = await _build_runner_for_version(tenant_id, version, channel)
        _runners[key] = runner
        _runners.move_to_end(key)
        while len(_runners) > _RUNNERS_MAX:
            _runners.popitem(last=False)  # evict oldest (build cache only)
        return runner


async def ensure_version_built(version: int, *, tenant_id: str | None = None, channel: str | None = None) -> None:
    """Warm (materialize + checksum + build) the runner for a config version.

    Used by the SP-D heartbeat to make ``running_version`` catch up to the
    published version even on an idle worker, and to warm the build cache for
    the next conversation. Goes through the SAME locked/cached path conversations
    use (``_get_runner_for_version``) so there is no duplicate build or race.
    Propagates ``ChecksumError`` (E04) / ``FileNotFoundError`` so the caller can
    classify a degraded state. ``tenant_id`` defaults to the process settings'
    tenant (the SP-D heartbeat caller doesn't have a request-scoped tenant).
    ``channel=None`` warms every persona channel (the heartbeat has no channel).
    """
    tid = tenant_id or get_settings().tenant_id
    for ch in PERSONA_CHANNELS if channel is None else (channel,):
        await _get_runner_for_version(tid, version, ch)


def _accepts_args(fn: Callable) -> bool:
    """True if fn can be called with positional args; False if it takes none.

    Uses inspect rather than try/except TypeError so real TypeErrors raised
    inside the callback are not swallowed and silently retried.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return True  # builtins / C funcs — assume the caller knows the shape
    for p in sig.parameters.values():
        if p.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            return True
        if p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return True
    return False


async def _maybe_await(fn: Callable | None, *args, **kwargs):
    if fn is None:
        return
    call_args = args if _accepts_args(fn) else ()
    call_kwargs = kwargs if call_args else {}
    try:
        result = fn(*call_args, **call_kwargs)
    except Exception:
        logger.exception("facade: callback raised")
        return
    if inspect.isawaitable(result):
        try:
            await result
        except Exception:
            logger.exception("facade: async callback raised")


class _Callbacks:
    def __init__(self, *, on_token, on_tool_start, on_tool_done, interrupt_check, sink, stripper=None):
        self._on_token = on_token
        self._on_tool_start = on_tool_start
        self._on_tool_done = on_tool_done
        self.interrupt_check = interrupt_check  # exposed for runner / stream client
        self._sink = sink
        # Display-channel <think> stripper. None = passthrough (show thinking).
        # Hides reasoning from UI/TTS while the history channel (StreamingClient
        # return → runner) keeps it raw.
        self._stripper = stripper

    async def on_token(self, token: str):
        if self._stripper is not None:
            token = self._stripper.feed(token)
            if not token:
                return
        self._sink.append(token)
        await _maybe_await(self._on_token, token)

    async def flush(self):
        """Drain any buffered tail from the display stripper at end of turn."""
        if self._stripper is None:
            return
        tail = self._stripper.flush()
        if tail:
            self._sink.append(tail)
            await _maybe_await(self._on_token, tail)

    async def on_tool_start(self, name: str, args: dict):
        await _maybe_await(self._on_tool_start, name, args)

    async def on_tool_done(self, name: str, result: str):
        await _maybe_await(self._on_tool_done, name, result)

    async def on_agent_switch(self, *, from_, to, reason):
        pass

    async def on_done(self):
        pass


class NobleAgent:
    def __init__(
        self,
        session_id: str,
        runner: TurnRunner,
        version: int = 0,
        tenant_id: str | None = None,
        channel: str = "chat",
    ):
        self.session_id = session_id
        self._runner = runner
        self._current_agent: str = "unified"
        # Persona channel this conversation's runner was built for ("chat"|"voice").
        self.channel = channel
        # Config version this conversation is pinned to for its whole lifetime
        # (BR05). 0 = legacy/package mode. The instance holding ``self._runner``
        # for its lifetime IS the per-conversation pin (SP-D reads this).
        self.pinned_version = version
        from noble_agent.tenant.current import current_tenant

        # Tenant this conversation is pinned to for its whole lifetime, mirroring
        # ``pinned_version``. Captured at construction time (create()'s
        # use_tenant scope, or the ambient tenant if built directly) so every
        # later call can re-establish the right ContextVar via use_tenant().
        self.tenant_id = tenant_id or current_tenant()

    @classmethod
    async def create(
        cls,
        session_id: str,
        customer: dict | None = None,
        *,
        tenant_id: str | None = None,
        channel: str,
    ) -> NobleAgent:
        """``channel`` is REQUIRED ("chat" | "voice") — every transport knows which
        one it is at its entry point; no default so a new call site can't silently
        pick up the wrong persona."""
        from noble_agent.tenant.current import current_tenant, use_tenant

        if channel not in PERSONA_CHANNELS:
            raise ValueError(f"unknown persona channel {channel!r}, expected one of {PERSONA_CHANNELS}")
        tid = tenant_id or current_tenant()
        # Mark this tenant as active in db-mode so the heartbeat can track it.
        settings = get_settings()
        if settings.agent_config_source == "db":
            from noble_agent.tenant.pg_heartbeat import mark_active

            mark_active(tid)
        with use_tenant(tid):
            version = await _resolve_current_version(tid)
            if version:
                runner = await _get_runner_for_version(tid, version, channel)
            else:
                runner = await _get_runner(tid, channel)
        return cls(session_id=session_id, runner=runner, version=version, tenant_id=tid, channel=channel)

    async def ensure_session_started(self) -> None:
        """Once-per-session hook, run at session open before the first turn.

        Simulates a caller identity when the session has none (unless
        ``NOBLE_SIMULATE_PHONE=false``): a phone from ``NOBLE_SIMULATE_PHONE_NUMBER``
        (else random) and optional pushed profile fields from
        ``NOBLE_SIMULATE_CUSTOMER`` (app-client sim) — see ``_seed_sim_customer``.
        Mirrors the phone onto meta and fires a best-effort ``call_started`` event.
        Only fills an EMPTY phone, so a real caller number is never overwritten.
        Best-effort: any failure is swallowed so a session never fails to open.
        """
        from noble_agent.tenant.current import use_tenant

        with use_tenant(self.tenant_id):
            try:
                repo = self._runner._repo
                sid = self.session_id
                meta, customer, state = await repo.load(sid)
                settings = get_settings()

                changed = False
                if settings.noble_simulate_phone:
                    customer, changed = _seed_sim_customer(
                        customer, settings.simulate_phone_number, settings.simulate_customer
                    )
                if not meta.phone and customer.phone:
                    meta.phone = customer.phone
                    changed = True
                if changed:
                    await repo.save_all(sid, meta, customer, state)
            except Exception:
                logger.exception("facade.ensure_session_started failed")

    async def stream_response(
        self,
        user_text: str,
        on_token: Callable | None = None,
        on_tool_start: Callable | None = None,
        on_tool_done: Callable | None = None,
        interrupt_check: Callable[[], bool] | None = None,
        on_agent_switch: Callable | None = None,
        show_thinking: bool = False,
        **_legacy_ignored,
    ) -> str:
        from noble_agent.tenant.current import use_tenant

        with use_tenant(self.tenant_id):
            sink: list[str] = []
            # Hide <think> from the display channel (UI/TTS) unless the caller opts
            # into showing it (chat tester debug). The history channel is untouched.
            stripper = None if show_thinking else ThinkStripper()
            cb = _Callbacks(
                on_token=on_token,
                on_tool_start=on_tool_start,
                on_tool_done=on_tool_done,
                interrupt_check=interrupt_check,
                sink=sink,
                stripper=stripper,
            )
            try:
                await self._runner.handle_turn(self.session_id, user_text, cb)
            finally:
                await cb.flush()
            return "".join(sink)

    async def suggest_followups(self, session_id: str) -> list[dict]:
        """Follow-up quick-reply chips for the last exchange. Delegates to the
        runner's read-only side call (never raises → ``[]`` on any failure)."""
        from noble_agent.tenant.current import use_tenant

        with use_tenant(self.tenant_id):
            return await self._runner.suggest_followups(session_id)

    async def reset(self) -> None:
        try:
            redis = self._runner._repo._redis
            sid = self.session_id
            await redis.delete(
                f"session:{sid}:meta",
                f"session:{sid}:customer",
                f"session:{sid}:state",
                f"session:{sid}:semcache",
            )
            semcache = getattr(self._runner, "_semcache", None)
            if semcache is not None:
                await semcache.cancel_refresh(sid)
        except Exception:
            logger.exception("facade.reset: failed to delete session keys")

    def get_identity(self) -> dict:
        """Identity for transport-level speech (the voice opening line):
        the agent's display name, spoken brand, and the tenant-configured
        greeting from ``agent_config.greeting`` ("" when unset)."""
        agent_def = getattr(self._runner, "_agent", None)
        return {
            "agent_name": getattr(agent_def, "name", "") or get_settings().agent_name,
            "brand": getattr(agent_def, "brand", "") or "",
            "greeting": getattr(agent_def, "greeting", "") or "",
        }

    async def get_customer(self) -> dict:
        """Return the unified Customer state as a plain dict.

        Use this from transport code (voice greeting, WS handlers) so they read
        from the SAME Redis key the agent's prompt is built from — not legacy
        session_store, which has an incompatible schema.
        """
        try:
            _meta, customer, _state = await self._runner._repo.load(self.session_id)
            return customer.model_dump(exclude_none=True)
        except Exception:
            logger.exception("facade.get_customer: load failed")
            return {}

    async def set_customer_fields(self, fields: dict) -> dict:
        """Merge ``fields`` into the unified Customer state and persist.

        Only truthy values overwrite existing fields (mirrors legacy
        ``session_store.save_customer`` semantics so a partial WS payload
        doesn't blank previously-set name/phone). Re-validates through the
        Customer model so type errors surface here instead of at next load.
        Returns the post-update Customer dict.
        """
        from noble_agent.storage.models import Customer
        from noble_agent.tenant.current import use_tenant

        with use_tenant(self.tenant_id):
            if not fields:
                return await self.get_customer()
            repo = self._runner._repo
            meta, customer, state = await repo.load(self.session_id)
            merged = customer.model_dump()
            for k, v in fields.items():
                if k in merged and (isinstance(v, bool) or v):
                    merged[k] = v
            new_customer = Customer.model_validate(merged)
            # Explicit identity seed (tester ⚙ sheet / app provision): re-freeze the
            # displayed profile block from the just-applied fields and mark the
            # profile as loaded, so it (a) takes effect even when applied mid-session
            # after the block was already frozen, and (b) is authoritative — the
            # first-turn DB bootstrap won't overwrite the hand-entered identity.
            state.scratchpad["customer_block"] = render_customer_block(self._runner._agent, new_customer)
            # This path freezes the block AND marks the profile loaded, so the
            # orchestrator's first-turn bootstrap (which also injects short-term
            # memory) is skipped. Mirror that short-term inject here so a caller
            # identity seeded via set_customer (tester "Áp dụng hồ sơ" / app
            # provisioning) still gets prior-call context. Safe: returns "" unless
            # a phone is present (memory is always on, no enable flag).
            settings = get_settings()
            if new_customer.phone:
                from noble_agent.agent.memory import short_term_block

                mem_block = await short_term_block(settings, phone=new_customer.phone, session_id=self.session_id)
                logger.info(
                    "[user_memory] set_customer short-term sid=%s phone=%s block_len=%d",
                    self.session_id,
                    new_customer.phone,
                    len(mem_block or ""),
                )
                if mem_block:
                    state.scratchpad["customer_block"] += "\n\n" + mem_block
            state.scratchpad["_profile_loaded"] = True
            await repo.save_all(self.session_id, meta, new_customer, state)
            return new_customer.model_dump(exclude_none=True)

    async def refresh_system_prompt(self) -> None:
        return None

    def set_interrupt_context(self, **_kwargs) -> None:
        return None

    async def note_interrupted(self, *, spoken_text: str) -> bool:
        """Khách ngắt lời khi TTS còn phát: cắt assistant cuối trong history về phần ĐÃ NGHE
        (`interrupt_trim`). Chạy SAU khi lượt đã persist; best-effort, không bao giờ raise.
        Trả True khi có sửa và đã save."""
        from noble_agent.agent.interrupt_trim import trim_last_assistant
        from noble_agent.tenant.current import use_tenant

        with use_tenant(self.tenant_id):
            try:
                repo = self._runner._repo
                meta, customer, state = await repo.load(self.session_id)
                new_history, idx = trim_last_assistant(state.history, spoken_text)
                if idx is None:
                    return False
                state.history = new_history
                await repo.save_all(self.session_id, meta, customer, state)
                # Transcript PG đã nhận bản đầy đủ (fire-and-forget lúc lượt chốt) — ghi đè
                # cùng seq, best-effort như mọi ghi PG khác.
                try:
                    from noble_agent.storage import pg_data_plane
                    from noble_agent.storage.persist import fire_and_forget

                    fire_and_forget(
                        pg_data_plane.persist_turn_messages(self.session_id, base_seq=idx, messages=[new_history[idx]])
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("note_interrupted: PG overwrite skipped", exc_info=True)
                logger.info("note_interrupted: cắt assistant idx=%d về %d ký tự", idx, len(new_history[idx].content))
                return True
            except Exception:  # noqa: BLE001 — bộ nhớ phụ, không được làm hỏng cuộc gọi
                logger.exception("facade.note_interrupted failed")
                return False


def reset_runner_for_tests() -> None:
    _legacy_runners.clear()
    _runners.clear()
