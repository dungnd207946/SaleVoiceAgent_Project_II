"""One-time, per-session customer-profile bootstrap.

At the first turn of a call we look the caller up by phone in Postgres
(``tenant_data.contacts``) and merge what we find into the live ``Customer``.
The DB is the source of truth for the frozen profile snapshot: a DB value
overwrites the current field; a missing/empty DB value leaves the current field
untouched. Falls back to the most recent ``tenant_data.appointments`` row for
name/project when the contact profile lacks them. No-op (and no I/O) when
``customer.phone`` is empty (blocked/withheld first-ever caller).
"""

from __future__ import annotations

import logging

from noble_agent.storage.models import Customer

logger = logging.getLogger("noble_agent.agent.customer_bootstrap")

# Fields accepted from the DB profile into the frozen snapshot. Mirrors the
# Customer model minus `phone` (the lookup key) and `is_buyer` (session-only).
_MERGE_FIELDS = (
    "name",
    "full_name",
    "gender",
    "project_interest",
    "purpose",
    "budget",
    "preferred_area",
    "bedroom_count",
    "is_noble_customer",
    "noble_info",
)


async def bootstrap_customer_profile(customer: Customer) -> None:
    """Merge the DB profile for ``customer.phone`` into ``customer`` in place."""
    phone = (customer.phone or "").strip()
    if not phone:
        logger.info("bootstrap: no phone on session — skipping profile lookup")
        return

    from noble_agent.agent import catalog
    from noble_agent.storage import session_store

    profile = await session_store.load_customer_by_phone(phone)
    hint = await session_store.load_latest_booking_hint_by_phone(phone)

    # appointment fallback for the two fields it carries.
    if not profile.get("name") and not profile.get("full_name") and hint.get("customer_name"):
        profile["name"] = hint["customer_name"]
    if not profile.get("project_interest") and hint.get("project"):
        profile["project_interest"] = hint["project"]

    applied: list[str] = []
    for field in _MERGE_FIELDS:
        value = profile.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if field == "project_interest":
            value = catalog.normalize(value)
            if not value:
                continue
        setattr(customer, field, value)
        applied.append(field)
    logger.info("bootstrap: phone=%s applied=%s", phone, applied)
