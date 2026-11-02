"""Monkey-patches for v8-bench — builds on v7 but with A1 removed and A5 added.

Changes from v7 patches:
  A1 -- REMOVED (_COMMON.md prepend replaced by FAQ search at tail).
  A2 -- REPLACED (phonetic aliases moved to agent.project_catalog).
  A3 -- kept (history scan for project inference, now via catalog.normalize).
  A4 -- kept (tier-1 auto-set after action tools, now via catalog.normalize).
  A5 -- NEW (layout reorder: move customer + FAQ to prompt tail).
  A6 -- NEW (strip tool header decoration).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("bench.v8_patches")


TIER_1_AUTO_SET_TOOLS = {
    "check_availability": "project_code",
    "schedule_viewing": "project_code",
    "update_booking_info": "project_interest",
    # Expanded (v8 fix): capture project from info-retrieval tools too,
    # so FAQ search can inject on the NEXT turn without requiring user
    # to explicitly mention project keyword in their message.
    "get_project_overview": "project_code",
    "get_project_financial": "project_code",
    "search_units": "project_code",
    "kb_search": "project_filter",
}

_originals: dict = {}


def apply_v8_patches() -> None:
    if _originals:
        logger.info("[v8-patches] already applied")
        return
    try:
        import noble_agent.agent.registry as _reg
        import noble_agent.agent.tools as _tools
    except ImportError as e:
        logger.error("[v8-patches] import failed: %s", e)
        return

    _originals["build_agent_prompt"] = _reg.build_agent_prompt
    _originals["execute_tool"] = _tools.execute_tool
    _originals["_PROJECT_FAQ_MAP"] = dict(_reg._PROJECT_FAQ_MAP)

    original_build = _originals["build_agent_prompt"]

    async def patched_build_agent_prompt(agent_id: str, session_id: str = "") -> str:
        # A3 -- history scan
        await _maybe_infer_project_from_history(session_id, _reg)

        # Call original build, then A5 reorder
        prompt = await original_build(agent_id, session_id)

        # A5 — layout reorder: move customer context + FAQ blocks to prompt tail
        try:
            import re as _re

            moved: list[str] = []
            # Customer context markers (actual Unicode from registry.format_customer_context)
            for marker in ("── Thông tin khách hàng", "══ CUSTOMER", "── Khách hàng"):
                if marker in prompt:
                    start = prompt.find(marker)
                    end = prompt.find("\n\n", start + 1)
                    if end > start:
                        block = prompt[start:end].strip()
                        prompt = (prompt[:start] + prompt[end + 2 :]).rstrip()
                        moved.append(block)
            # FAQ block (registry auto-injected)
            for faq_marker in ("═══ FAQ DỰ ÁN", "═══ FAQ CHUNG"):
                if faq_marker in prompt:
                    start = prompt.find(faq_marker)
                    end_block = prompt.find("\n\n", start + 10)
                    if end_block > start:
                        block = prompt[start:end_block].strip()
                        prompt = (prompt[:start] + prompt[end_block + 2 :]).rstrip()
                        moved.append(block)
                    break
            if moved:
                prompt = prompt.rstrip() + "\n\n" + "\n\n".join(moved)
                logger.debug("[v8-A5] reordered %d dynamic blocks to tail", len(moved))

            # A6 — strip tool header decoration `═══ TOOL: <name> ═══\n`
            # (registry.py:248 hardcodes these; v8 treats tool docs as schema supplement)
            before_len = len(prompt)
            prompt = _re.sub(r"═══ TOOL: [a-z_]+ ═══\n", "", prompt)
            if len(prompt) < before_len:
                logger.debug("[v8-A6] stripped tool headers (-%d chars)", before_len - len(prompt))
        except Exception as e:
            logger.warning("[v8-A5/A6] prompt cleanup failed: %s", e)

        return prompt

    _reg.build_agent_prompt = patched_build_agent_prompt
    logger.info("[v8-A3+A5] build_agent_prompt wrapped")

    # A4 -- wrap execute_tool
    original_exec = _originals["execute_tool"]

    async def patched_execute_tool(name: str, args: dict, session_id: str = "") -> str:
        result = await original_exec(name, args, session_id)
        try:
            from noble_agent.agent import project_catalog as _catalog

            field = TIER_1_AUTO_SET_TOOLS.get(name)
            if field and session_id:
                code = _catalog.normalize(args.get(field, ""))
                if code:
                    from noble_agent.storage import session_store

                    current = await session_store.load_customer(session_id)
                    if current.get("project_interest") != code:
                        await session_store.save_customer(session_id, {"project_interest": code})
                        logger.info("[v8-A4] auto-set project_interest=%s from %s", code, name)
        except Exception as e:
            logger.debug("[v8-A4] auto-set failed: %s", e)
        return result

    _tools.execute_tool = patched_execute_tool
    # Also rebind the frozen import in agent.llm.streaming — otherwise
    # stream_response() calls the un-patched original (A4 bypass).
    try:
        import noble_agent.agent.llm.streaming as _streaming

        _originals["streaming.execute_tool"] = _streaming.execute_tool
        _streaming.execute_tool = patched_execute_tool
    except Exception as _e:
        logger.warning("[v8-A4] failed to rebind agent.llm.streaming.execute_tool: %s", _e)
    logger.info("[v8-A4] execute_tool wrapped")

    logger.info("[v8-patches] applied: A2, A3, A4, A5 (A1 removed, FAQ via search at tail)")


async def _maybe_infer_project_from_history(session_id: str, _reg: Any) -> None:
    if not session_id:
        return
    try:
        from noble_agent.agent import project_catalog as _catalog
        from noble_agent.storage import session_store

        customer = await session_store.load_customer(session_id)
        if customer.get("project_interest"):
            return
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
        blob = " ".join(blob_parts).strip()
        if not blob:
            return
        inferred = _catalog.normalize(blob)
        if inferred:
            await session_store.save_customer(session_id, {"project_interest": inferred})
            logger.info("[v8-A3] inferred project_interest=%s from history", inferred)
    except Exception as e:
        logger.debug("[v8-A3] history scan failed: %s", e)


def revert_v8_patches() -> None:
    if not _originals:
        return
    try:
        import noble_agent.agent.registry as _reg
        import noble_agent.agent.tools as _tools

        if "build_agent_prompt" in _originals:
            _reg.build_agent_prompt = _originals["build_agent_prompt"]
        if "execute_tool" in _originals:
            _tools.execute_tool = _originals["execute_tool"]
        if "streaming.execute_tool" in _originals:
            try:
                import noble_agent.agent.llm.streaming as _streaming

                _streaming.execute_tool = _originals["streaming.execute_tool"]
            except Exception as _e:
                logger.debug("[v8-patches] streaming.execute_tool restore failed: %s", _e)
        if "_PROJECT_FAQ_MAP" in _originals:
            _reg._PROJECT_FAQ_MAP.clear()
            _reg._PROJECT_FAQ_MAP.update(_originals["_PROJECT_FAQ_MAP"])
        _originals.clear()
        logger.info("[v8-patches] reverted")
    except Exception as e:
        logger.warning("[v8-patches] revert failed: %s", e)
