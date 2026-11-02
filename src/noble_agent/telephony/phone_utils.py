"""Vietnamese phone number normalization for telephony caller IDs.

Asterisk / FreePBX may deliver CALLERID in multiple formats depending on the
SIP trunk: "0912345678", "+84912345678", "84912345678", "912345678". This
module collapses them to a single canonical form ("0912345678") so Redis and
DB lookups are deterministic.
"""

from __future__ import annotations

import re

# Vietnamese mobile prefixes: 03x, 05x, 07x, 08x, 09x — 10 digits total
_VN_MOBILE_PATTERN = re.compile(r"^0(3|5|7|8|9)\d{8}$")


def normalize_phone(raw: str) -> str:
    """Return canonical `0xxxxxxxxx` form. Empty string if invalid.

    Handles:
    - "+84 912 345 678"  → "0912345678"
    - "84912345678"      → "0912345678"
    - "0912-345-678"     → "0912345678"
    - "0912345678"       → "0912345678"
    - "anonymous"        → ""
    """
    if not raw:
        return ""
    phone = re.sub(r"[\s\-\.\(\)]", "", str(raw)).strip()
    phone = phone.removeprefix("+")
    if phone.startswith("84") and len(phone) == 11:
        phone = "0" + phone[2:]
    if _VN_MOBILE_PATTERN.match(phone):
        return phone
    return ""


def is_valid_vn_phone(phone: str) -> bool:
    """True if phone matches canonical Vietnamese mobile pattern."""
    return bool(_VN_MOBILE_PATTERN.match(phone or ""))
