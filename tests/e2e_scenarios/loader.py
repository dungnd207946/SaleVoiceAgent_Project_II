"""Load + validate YAML scenario files into frozen dataclasses.

A scenario is a scripted multi-turn conversation plus per-turn `expect` blocks.
Validation is strict (unknown keys → ValueError) so authoring mistakes fail
fast at load time rather than silently passing at run time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from tests.e2e_scenarios.assertions import KNOWN_KEYS


@dataclass(frozen=True)
class Turn:
    user: str
    expect: dict


@dataclass(frozen=True)
class Scenario:
    name: str
    turns: tuple[Turn, ...]
    description: str = ""
    customer: dict | None = None


def parse_scenario(data: dict, *, source: str = "<dict>") -> Scenario:
    """Validate a parsed-YAML dict into a `Scenario`. Raises `ValueError`."""
    if not isinstance(data, dict):
        raise ValueError(f"{source}: scenario must be a mapping, got {type(data).__name__}")

    name = data.get("name")
    if not name or not isinstance(name, str):
        raise ValueError(f"{source}: scenario needs a non-empty string 'name'")

    raw_turns = data.get("turns")
    if not isinstance(raw_turns, list) or not raw_turns:
        raise ValueError(f"{source}: scenario '{name}' needs a non-empty 'turns' list")

    turns: list[Turn] = []
    for i, rt in enumerate(raw_turns):
        if not isinstance(rt, dict):
            raise ValueError(f"{source}: turn {i} must be a mapping")
        user = rt.get("user")
        if not user or not isinstance(user, str):
            raise ValueError(f"{source}: turn {i} needs a non-empty string 'user'")
        expect = rt.get("expect") or {}
        if not isinstance(expect, dict):
            raise ValueError(f"{source}: turn {i} 'expect' must be a mapping")
        unknown = set(expect) - KNOWN_KEYS
        if unknown:
            raise ValueError(
                f"{source}: turn {i} has unknown expect keys {sorted(unknown)}; allowed: {sorted(KNOWN_KEYS)}"
            )
        turns.append(Turn(user=user, expect=expect))

    customer = data.get("customer")
    if customer is not None and not isinstance(customer, dict):
        raise ValueError(f"{source}: scenario '{name}' 'customer' must be a mapping")

    return Scenario(
        name=name,
        turns=tuple(turns),
        description=data.get("description", "") or "",
        customer=customer,
    )


def load_scenario(path: Path) -> Scenario:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return parse_scenario(data, source=path.name)


def load_scenarios(directory: Path) -> list[Scenario]:
    """Load every ``*.yaml`` in ``directory``, sorted by filename."""
    paths = sorted(directory.glob("*.yaml"))
    return [load_scenario(p) for p in paths]
