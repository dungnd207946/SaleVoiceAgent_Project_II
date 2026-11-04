"""Pure assertion engine for the e2e scenario harness.

`evaluate(expect, result)` turns one turn's `expect` block into a list of
pass/fail `AssertionResult`s. No I/O, no LLM — so it is unit-testable with a
fabricated `TurnResult`. See `loader.py` for the `expect` schema and
`runner.py` for how `TurnResult` is produced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Keys allowed inside a turn's `expect:` block. Validated at load time
# (loader.py) so a typo fails fast instead of silently passing.
KNOWN_KEYS: frozenset[str] = frozenset(
    {
        "tool_called",
        "reply_contains",
        "reply_contains_any",
        "reply_not_contains",
        "reply_matches",
        "reply_not_matches",
        "customer_field",
        "escalated",
    }
)


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict
    result: str | None = None


@dataclass(frozen=True)
class TurnResult:
    """What the agent did on one turn — the input to `evaluate`."""

    user: str
    reply: str
    tool_calls: tuple[ToolCall, ...] = ()
    customer: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AssertionResult:
    kind: str
    ok: bool
    detail: str


def _as_list(value) -> list:
    """Normalize str-or-list into a list; leave lists/tuples as lists."""
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _tool_names(result: TurnResult) -> list[str]:
    return [tc.name for tc in result.tool_calls]


def evaluate(expect: dict, result: TurnResult) -> list[AssertionResult]:
    """Evaluate one turn's `expect` block against `result`.

    Returns one `AssertionResult` per concrete check (a key with a list value
    expands to one result per element). An empty `expect` yields no results
    (vacuously passing).
    """
    out: list[AssertionResult] = []
    reply_lc = result.reply.lower()
    names = _tool_names(result)

    for key, value in expect.items():
        if key == "tool_called":
            for name in _as_list(value):
                out.append(
                    AssertionResult(
                        "tool_called",
                        name in names,
                        f"expected tool '{name}' called; called={names}",
                    )
                )

        elif key == "reply_contains":
            for needle in _as_list(value):
                out.append(
                    AssertionResult(
                        "reply_contains",
                        str(needle).lower() in reply_lc,
                        f"reply must contain {needle!r}",
                    )
                )

        elif key == "reply_contains_any":
            needles = _as_list(value)
            ok = any(str(n).lower() in reply_lc for n in needles)
            out.append(
                AssertionResult(
                    "reply_contains_any",
                    ok,
                    f"reply must contain any of {needles!r}",
                )
            )

        elif key == "reply_not_contains":
            for needle in _as_list(value):
                out.append(
                    AssertionResult(
                        "reply_not_contains",
                        str(needle).lower() not in reply_lc,
                        f"reply must NOT contain {needle!r}",
                    )
                )

        elif key == "reply_matches":
            ok = re.search(str(value), result.reply) is not None
            out.append(AssertionResult("reply_matches", ok, f"reply must match /{value}/"))

        elif key == "reply_not_matches":
            hit = re.search(str(value), result.reply)
            out.append(
                AssertionResult(
                    "reply_not_matches",
                    hit is None,
                    f"reply must NOT match /{value}/" + (f" (matched {hit.group(0)!r})" if hit else ""),
                )
            )

        elif key == "customer_field":
            for spec in _as_list(value):
                out.append(_check_customer_field(spec, result))

        elif key == "escalated":
            called = "escalate" in names
            out.append(
                AssertionResult(
                    "escalated",
                    called == bool(value),
                    f"expected escalated={bool(value)}; escalate called={called}",
                )
            )

    return out


def _check_customer_field(spec: dict, result: TurnResult) -> AssertionResult:
    field_name = spec.get("field")
    actual = result.customer.get(field_name)
    if "equals" in spec:
        want = spec["equals"]
        return AssertionResult(
            "customer_field",
            actual == want or str(actual) == str(want),
            f"customer.{field_name} == {want!r}; got {actual!r}",
        )
    if "contains" in spec:
        want = str(spec["contains"]).lower()
        return AssertionResult(
            "customer_field",
            want in str(actual).lower(),
            f"customer.{field_name} contains {spec['contains']!r}; got {actual!r}",
        )
    return AssertionResult("customer_field", False, f"customer_field spec needs 'equals' or 'contains': {spec!r}")
