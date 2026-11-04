"""Monkey-patches for v7-bench — apply v7 routing/FAQ improvements WITHOUT touching src/.

Activated by bench_llm.py when --version v7-bench is selected.
Reverted by _unpatch_prompt_version().

Changes applied:
  A1 — Inject _COMMON.md always into system prompt (brand-common 20 Q/A).
  A2 — Expand _PROJECT_FAQ_MAP with phonetic / no-diacritic aliases.
  A3 — Scan last-5 messages from session history to infer project_interest.
  A4 — Tier 1 auto-set project_interest after action tools (check_availability,
       schedule_viewing, update_booking_info).

Design principles:
  - Idempotent: apply_v7_patches() multiple times = same result.
  - Restorable: revert_v7_patches() restores exact originals.
  - Safe: each patch wrapped in try/except, log warn on failure.
  - No prompt content change: prompts stay v6, only registry/tools logic patched.

Promote path: when bench validates v7 stable, port logic to:
  src/agent/registry.py (A1+A2+A3) and src/agent/tools/__init__.py (A4).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("bench.v7_patches")


# ─── A2 data: phonetic / no-diacritic aliases for ASR Vietnamese ──────
PHONETIC_ALIASES = {
    "tay ho": "NCTH",
    "long bien": "NCLB",
    "long biên": "NCLB",
    "thang long": "NTTL",
    "thăng long": "NTTL",
    "tay thang long": "NTTL",
    "sunshine": "SSLC",
    "legend": "SSLC",
    "sslc": "SSLC",
    "palace long bien": "NPLB",
}


# ─── A4 config: Tier 1 tools auto-set project_interest ────────────────
# Tools that imply customer commits to a specific project. Safe to auto-persist.
TIER_1_AUTO_SET_TOOLS = {
    "check_availability": "project_code",
    "schedule_viewing": "project_code",
    "update_booking_info": "project_interest",
}
VALID_PROJECT_CODES = {"NCLB", "NCTH", "NPLB", "NTTL", "SSLC"}


# ─── Stash for restore ────────────────────────────────────────────────
_originals: dict = {}


def apply_v7_patches() -> None:
    """Apply A1+A2+A3+A4 patches. Idempotent.

    Called by bench_llm.py:_patch_prompt_version when version == "v7-bench".
    """
    if _originals:
        logger.info("[v7-patches] already applied, skipping")
        return

    try:
        import noble_agent.agent.registry as _reg
        import noble_agent.agent.tools as _tools
    except ImportError as e:
        logger.error("[v7-patches] cannot import agent.registry/tools: %s", e)
        return

    # Stash originals for restore
    _originals["build_agent_prompt"] = _reg.build_agent_prompt
    _originals["execute_tool"] = _tools.execute_tool
    _originals["_PROJECT_FAQ_MAP"] = dict(_reg._PROJECT_FAQ_MAP)

    # ─── A2 — expand _PROJECT_FAQ_MAP in-place ───────────────────────
    _reg._PROJECT_FAQ_MAP.update(PHONETIC_ALIASES)
    logger.info(
        "[v7-A2] phonetic aliases added: %d new entries (%d total)",
        len(PHONETIC_ALIASES),
        len(_reg._PROJECT_FAQ_MAP),
    )

    # ─── A1 + A3 — wrap build_agent_prompt ───────────────────────────
    original_build = _originals["build_agent_prompt"]

    async def patched_build_agent_prompt(agent_id: str, session_id: str = "") -> str:
        # A3: pre-scan history → save_customer if project found (before original build reads customer)
        await _maybe_infer_project_from_history(session_id, _reg)

        # Call original build (now reads possibly-updated customer.project_interest)
        prompt = await original_build(agent_id, session_id)

        # A1: inject _COMMON.md
        try:
            common_path = _reg._FAQ_DIR / "_COMMON.md"
            if common_path.exists():
                common_text = common_path.read_text("utf-8").strip()
                if common_text:
                    # Insert _COMMON BEFORE project FAQ block if exists,
                    # otherwise prepend near top of dynamic context.
                    if "═══ FAQ DỰ ÁN" in prompt:
                        prompt = prompt.replace(
                            "═══ FAQ DỰ ÁN",
                            common_text + "\n\n═══ FAQ DỰ ÁN",
                            1,
                        )
                    else:
                        # No project FAQ injected — prepend _COMMON near top
                        # (after any customer context block but before SOUL/IDENTITY)
                        # Simplest: prepend at start of full prompt.
                        prompt = common_text + "\n\n" + prompt
                    logger.debug(
                        "[v7-A1] _COMMON.md injected (%d chars)",
                        len(common_text),
                    )
        except Exception as e:
            logger.warning("[v7-A1] _COMMON.md inject failed: %s", e)

        return prompt

    _reg.build_agent_prompt = patched_build_agent_prompt
    logger.info("[v7-A1+A3] build_agent_prompt wrapped")

    # ─── A4 — wrap execute_tool ──────────────────────────────────────
    original_exec = _originals["execute_tool"]

    async def patched_execute_tool(name: str, args: dict, session_id: str = "") -> str:
        result = await original_exec(name, args, session_id)

        # Tier 1 auto-set after success (best-effort, never block tool result)
        try:
            field = TIER_1_AUTO_SET_TOOLS.get(name)
            if field and session_id:
                code = (args.get(field, "") or "").upper()
                if code in VALID_PROJECT_CODES:
                    from noble_agent.storage import session_store

                    current = await session_store.load_customer(session_id)
                    if current.get("project_interest") != code:
                        await session_store.save_customer(session_id, {"project_interest": code})
                        logger.info(
                            "[v7-A4] auto-set project_interest=%s from tool=%s",
                            code,
                            name,
                        )
        except Exception as e:
            logger.debug("[v7-A4] auto-set hook failed: %s", e)

        return result

    _tools.execute_tool = patched_execute_tool
    logger.info("[v7-A4] execute_tool wrapped")

    logger.info("[v7-patches] all applied: A1, A2, A3, A4")


async def _maybe_infer_project_from_history(session_id: str, _reg: Any) -> None:
    """A3 logic: scan last-5 messages, infer project_interest, save_customer if found.

    Skipped when project_interest already set, or session_id empty.
    """
    if not session_id:
        return

    try:
        from noble_agent.storage import session_store

        # Skip if already set
        customer = await session_store.load_customer(session_id)
        if customer.get("project_interest"):
            return

        # Scan recent history + state.switch_query + customer_snapshot
        state = await session_store.load_state(session_id)
        history = await session_store.load_history(session_id)
        recent = history[-5:] if history else []

        blob_parts = [
            state.get("switch_query", "") or "",
            (state.get("customer_snapshot") or {}).get("project_interest", "") or "",
        ]
        for msg in recent:
            content = msg.get("content", "")
            if isinstance(content, str):
                blob_parts.append(content)
        blob = " ".join(blob_parts).lower()
        if not blob.strip():
            return

        # Match longest keyword first to prevent ambiguity ("noble palace" vs "noble palace long biên")
        for kw, code in sorted(_reg._PROJECT_FAQ_MAP.items(), key=lambda x: -len(x[0])):
            if kw.lower() in blob:
                await session_store.save_customer(session_id, {"project_interest": code})
                logger.info(
                    "[v7-A3] inferred project_interest=%s from history (kw=%r)",
                    code,
                    kw,
                )
                return
    except Exception as e:
        logger.debug("[v7-A3] history scan failed: %s", e)


def revert_v7_patches() -> None:
    """Restore originals. Called from bench_llm.py:_unpatch_prompt_version."""
    if not _originals:
        return

    try:
        import noble_agent.agent.registry as _reg
        import noble_agent.agent.tools as _tools

        if "build_agent_prompt" in _originals:
            _reg.build_agent_prompt = _originals["build_agent_prompt"]
        if "execute_tool" in _originals:
            _tools.execute_tool = _originals["execute_tool"]
        if "_PROJECT_FAQ_MAP" in _originals:
            _reg._PROJECT_FAQ_MAP.clear()
            _reg._PROJECT_FAQ_MAP.update(_originals["_PROJECT_FAQ_MAP"])

        _originals.clear()
        logger.info("[v7-patches] reverted")
    except Exception as e:
        logger.warning("[v7-patches] revert failed: %s", e)
