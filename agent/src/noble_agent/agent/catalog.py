"""Single source of truth for Noble project identity — alias → canonical code.

Standalone copy of the legacy noble_agent.agent.project_catalog, owned by the
unified package so it can be deployed without the legacy noble_agent
codebase present.

Import-safe from anywhere (no top-level deps / circular-import risk).
`normalize()` does a lazy, call-time consult of the DB-warmed registry
(`data.db_project_registry`) as a fallback so it accepts current DB codes
even when they postdate this hardcoded map.

Golden rule: `normalize()` returns a code if-and-only-if the input uniquely
maps to a single project. Ambiguous tokens (e.g. "crystal" ∈ NCLB+NCTH, or
"long biên" ∈ NCLB+NPLB) are deliberately NOT in any alias list — the catalog
returns "" and the agent's knowledge handles clarification through dialog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Project:
    id: int
    code: str
    name_vi: str
    region: str
    aliases: tuple[str, ...]


_REGISTRY: tuple[Project, ...] = (
    Project(
        1,
        "NCLB",
        "Noble Crystal Long Biên",
        "Long Biên",
        (
            "nclb",
            "crystal long biên",
            "crystal long bien",
            "noble crystal long biên",
            "noble crystal long bien",
        ),
    ),
    Project(
        2,
        "NCTH",
        "Noble Crystal Tây Hồ",
        "Tây Hồ",
        (
            "ncth",
            "crystal tây hồ",
            "crystal tay ho",
            "noble crystal tây hồ",
            "noble crystal tay ho",
        ),
    ),
    Project(
        3,
        "NPLB",
        "Noble Palace Long Biên",
        "Long Biên",
        (
            "nplb",
            "palace long biên",
            "palace long bien",
            "noble palace long biên",
            "noble palace long bien",
        ),
    ),
    Project(
        4,
        "NPTTL",
        "Noble Palace Tây Thăng Long",
        "Tây Thăng Long",
        (
            "npttl",
            "nttl",
            "tây thăng long",
            "tay thang long",
            "thăng long",
            "thang long",
            "palace tây thăng long",
            "palace tay thang long",
            "noble palace tây thăng long",
            "noble palace tay thang long",
        ),
    ),
    Project(
        5,
        "SLC",
        "Sunshine Legend City",
        "Hà Nội",
        (
            "sslc",
            "sunshine legend city",
            "sunshine legend",
            "legend city",
            "legend",
        ),
    ),
    Project(
        6,
        "NCR",
        "Noble Crystal Riverside",
        "",
        (
            "ncrs",
            "crystal riverside",
            "noble crystal riverside",
        ),
    ),
    Project(
        7,
        "NPTH",
        "Noble Palace Tây Hồ",
        "Tây Hồ",
        (
            "npth",
            "palace tây hồ",
            "palace tay ho",
            "noble palace tây hồ",
            "noble palace tay ho",
        ),
    ),
    Project(
        8,
        "SSC",
        "Sunshine Sky City",
        "Quận 7",
        (
            "ssc",
            "sssc",
            "sky city",
            "sunshine sky city",
        ),
    ),
    Project(
        9,
        "SGR",
        "Sunshine Golden River",
        "Tây Hồ",
        (
            "sgr",
            "golden river",
            "sunshine golden river",
        ),
    ),
    Project(
        10,
        "SGI",
        "Sunshine Green Iconic",
        "Long Biên",
        (
            "sgi",
            "green iconic",
            "sunshine green iconic",
        ),
    ),
    Project(
        11,
        "SRP",
        "Sunshine River Park",
        "",
        (
            "srp",
            "river park",
            "sunshine river park",
        ),
    ),
    Project(
        12,
        "SCHN",
        "Sunshine City Hà Nội",
        "Bắc Từ Liêm",
        (
            "schn",
            "sunshine city hà nội",
            "sunshine city hanoi",
        ),
    ),
    Project(
        13,
        "SBR",
        "Sunshine Bay Retreat",
        "",
        (
            "sbr",
            "ssbr",
            "bay retreat",
            "sunshine bay retreat",
        ),
    ),
    Project(
        14,
        "ASM",
        "Alluvia Sunshine Marina",
        "",
        (
            "asm",
            "alluvia sunshine marina",
        ),
    ),
    Project(
        15,
        "ALM",
        "Tổ hợp căn hộ Alumi (Alluvia City)",
        "Văn Giang",
        (
            "alm",
            "alumi",
            "alumi premium",
            "alluvia city",
        ),
    ),
)


VALID_CODES: frozenset[str] = frozenset(p.code for p in _REGISTRY)
_BY_ID: dict[int, Project] = {p.id: p for p in _REGISTRY}
# Case-insensitive code lookup — codes are compared upper() but the stored
# Project.code keeps DB casing (e.g. "Alumi"), so we map UPPER -> Project.
_BY_CODE_CI: dict[str, Project] = {p.code.upper(): p for p in _REGISTRY}

# Alias → code, compiled with word boundaries so a short alias ("legend")
# can't false-match inside a longer word ("legendary"). Longest-first so the
# most specific alias wins when several could match.
_ALIAS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{re.escape(alias)}\b"), code)
    for alias, code in sorted(
        ((alias.lower(), p.code) for p in _REGISTRY for alias in p.aliases),
        key=lambda t: -len(t[0]),
    )
)


def normalize(raw: str | int | None) -> str:
    """Return canonical project code or '' if input is missing/ambiguous."""
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return ""
    if isinstance(raw, int):
        proj = _BY_ID.get(raw)
        return proj.code if proj else ""
    s = str(raw).strip()
    if not s:
        return ""
    # Live DB codes are authoritative and MUST win over the hardcoded map. The
    # _REGISTRY above is an NL-alias map + offline default, NOT the authority on
    # which codes exist — project_du_an (ma_du_an) can change without a catalog
    # release. If the input already IS a live DB code, return it verbatim BEFORE
    # the hardcoded code/alias resolution can rewrite it to a stale canonical
    # (e.g. DB "ASM" must not be rewritten to the old alias target "ALLUVIA").
    # This keeps normalize in agreement with the prompt table + tool enums, which
    # are built from the same DB source. Lazy import keeps this module import-safe
    # (no top-level dependency / cycle); cached_codes() is sync (warmed cache or
    # bundled fallback, no I/O).
    from noble_agent.data import db_project_registry

    su = s.upper()
    for code in db_project_registry.cached_codes():
        if code.upper() == su:
            return code
    proj = _BY_CODE_CI.get(su)
    if proj:
        return proj.code
    low = s.lower()
    for pat, code in _ALIAS_PATTERNS:
        if pat.search(low):
            return code
    return ""


def by_code(code: str) -> Project | None:
    if not code:
        return None
    return _BY_CODE_CI.get(code.upper())


def by_id(n: int) -> Project | None:
    return _BY_ID.get(n)


def all_projects() -> tuple[Project, ...]:
    return _REGISTRY
