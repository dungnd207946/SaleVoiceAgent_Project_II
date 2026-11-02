"""Tool: update_customer — multi-field form (legacy parity).

Accepts arbitrary subset of CUSTOMER_FIELDS in a single call (matches legacy
behavior so SFT-trained models don't have to learn a new shape). Mutates the
shared Customer object; the runner persists it to Redis at turn end.
project_interest is normalized via the canonical catalog; ambiguous/unknown
values are dropped silently.
"""

from __future__ import annotations

import json
import logging
import re

from noble_agent.agent.tools.schemas import CUSTOMER_FIELDS

logger = logging.getLogger("noble_agent.agent.tools.update_customer")

_PHONE_REGEX = re.compile(r"^(0[35789])\d{8}$")
_NOTES_MAX = 300


def _merge_notes(existing: str | None, new: str) -> str:
    """Cộng dồn ghi chú bối cảnh: LLM gửi từng mẩu khi khách kể ("làm ở Long
    Biên", rồi "con sắp lớp 1") — ghi đè sẽ quên mẩu trước. Bỏ mẩu trùng, giữ
    phần MỚI nhất khi vượt _NOTES_MAX."""
    new = " ".join(str(new).split())
    if not existing:
        return new[:_NOTES_MAX]
    if new.lower() in existing.lower():
        return existing
    merged = f"{existing}; {new}"
    return merged[-_NOTES_MAX:] if len(merged) > _NOTES_MAX else merged


async def run(customer, args: dict) -> str:
    from noble_agent.agent import catalog

    updated: list[str] = []
    for field, value in (args or {}).items():
        if field not in CUSTOMER_FIELDS:
            continue
        if value is None:
            continue
        # Skip empty strings (LLM sometimes passes "") but keep booleans.
        if isinstance(value, str) and not value.strip():
            continue
        if field == "project_interest":
            norm = catalog.normalize(value)
            if not norm:
                logger.warning("update_customer: dropping unknown project_interest=%r", value)
                continue
            value = norm
        if field == "phone":
            cleaned = re.sub(r"[\s.\-]", "", str(value))
            if not _PHONE_REGEX.match(cleaned):
                logger.warning(
                    "update_customer: dropping invalid phone=%r (need 10 digits, starts 03/05/07/08/09)", value
                )
                continue
            value = cleaned
        if field == "notes":
            value = _merge_notes(getattr(customer, "notes", None), value)
        setattr(customer, field, value)
        updated.append(field)

    if not updated:
        return json.dumps(
            {"ok": False, "error": "Không có field hợp lệ nào được cập nhật."},
            ensure_ascii=False,
        )

    # Incremental cross-session persist. Fire-and-forget so the tool loop (which
    # is TTFT-adjacent) is never blocked by a DB round-trip. Only when a phone
    # is known — the customers collection is keyed by phone.
    if customer.phone:
        from noble_agent.storage import session_store
        from noble_agent.storage.persist import fire_and_forget

        fire_and_forget(session_store.save_customer_persistent(customer.phone, customer.model_dump(exclude_none=True)))

    return json.dumps(
        {"ok": True, "success": True, "updated_fields": updated},
        ensure_ascii=False,
    )
