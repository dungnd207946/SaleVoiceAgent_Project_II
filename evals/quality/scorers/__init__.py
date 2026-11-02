"""Scorers — pure functions from (cases, traces) to an `AxisScore`.

Every scorer takes the eval cases plus the traces produced by a run and returns
one `AxisScore`. No I/O, no LLM, no env reads: that is what makes the scorecard
testable with fabricated traces, and a scorer bug is a bug you can catch in
`make eval-test` rather than one that quietly produces a convincing number.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Finding:
    case_id: str
    turn: int
    kind: str
    detail: str


@dataclass(frozen=True)
class AxisScore:
    axis: str
    checks: int
    failures: int
    findings: tuple[Finding, ...] = ()
    # `None` = this scorer's sample for that metric was EMPTY, so it measured
    # nothing. Never the value that would pass: `scorecard.evaluate_gates` treats
    # `None` exactly like an absent key and fails the gate closed. Only use it for
    # metrics a gate reads — elsewhere it is noise.
    metrics: dict[str, float | None] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        """Fraction of checks that passed. Vacuously 1.0 when nothing was checked."""
        if self.checks <= 0:
            return 1.0
        return (self.checks - self.failures) / self.checks
