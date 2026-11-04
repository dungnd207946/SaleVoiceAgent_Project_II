"""Vietnamese phone normalization — standalone port of legacy phone_utils."""

from __future__ import annotations

import re

_VN_MOBILE_PATTERN = re.compile(r"^0(3|5|7|8|9)\d{8}$")


def normalize_phone(raw: str) -> str:
    """Return canonical `0xxxxxxxxx` form. Empty string if invalid."""
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
    return bool(_VN_MOBILE_PATTERN.match(phone or ""))
