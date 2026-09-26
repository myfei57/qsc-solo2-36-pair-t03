"""Pre-gates: named conditions that must hold before a step runs.

A gate is evaluated against the live plant state every time it is asked:
each requirement names a registered condition probe, and the verdict lists
only the requirements whose probe says the condition does not hold right
now.  A gate is never something an operator arms by hand; it is a question
the interlock answers with evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from line_control.runtime.errors import (
    GateBlockedError,
    UnknownReferenceError,
    ValidationError,
)


@dataclass(frozen=True)
class GateVerdict:
    """The outcome of evaluating a gate."""

    gate: str
    unit: str
    open: bool
    blocked_by: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Render the verdict for the wire."""
        return {
            "gate": self.gate,
            "unit": self.unit,
            "open": self.open,
            "blockedBy": list(self.blocked_by),
        }


@dataclass
class _Gate:
    name: str
    requirements: list[str] = field(default_factory=list)


class GateBoard:
    """A registry of named gates evaluated against live conditions."""

    def __init__(self) -> None:
        self._gates: dict[str, _Gate] = {}
        self._conditions: dict[str, Callable[[str], bool]] = {}

    def condition(self, name: str, probe: Callable[[str], bool]) -> None:
        """Register the probe that reports whether a requirement holds."""
        if not name:
            raise ValidationError("condition name is required")
        if not callable(probe):
            raise ValidationError("a condition probe must be callable", condition=name)
        self._conditions[name] = probe

    def define(self, gate: str, requirements: Sequence[str]) -> None:
        """Declare a gate and the conditions it stands for."""
        if not gate:
            raise ValidationError("gate name is required")
        if not requirements:
            raise ValidationError("a gate needs at least one requirement", gate=gate)
        unknown = [name for name in requirements if name not in self._conditions]
        if unknown:
            raise ValidationError(
                "every gate requirement needs a registered condition",
                gate=gate,
                unknown=unknown,
            )
        self._gates[gate] = _Gate(name=gate, requirements=list(requirements))

    def names(self) -> list[str]:
        """Return every declared gate name."""
        return sorted(self._gates)

    def requirements(self, gate: str) -> list[str]:
        """Return the requirement names of a gate."""
        return list(self._lookup(gate).requirements)

    def evaluate(self, gate: str, unit: str) -> GateVerdict:
        """Evaluate a gate without raising."""
        declared = self._lookup(gate)
        blocked = tuple(
            name for name in declared.requirements if not self._holds(name, unit)
        )
        return GateVerdict(gate=gate, unit=unit, open=not blocked, blocked_by=blocked)

    def require(self, gate: str, unit: str) -> GateVerdict:
        """Evaluate a gate and refuse the step when it is closed."""
        verdict = self.evaluate(gate, unit)
        if not verdict.open:
            raise GateBlockedError(
                f"gate {gate} is closed for unit {unit}",
                gate=gate,
                unit=unit,
                blocked_by=list(verdict.blocked_by),
            )
        return verdict

    def report(self, unit: str) -> list[GateVerdict]:
        """Evaluate every declared gate for one unit."""
        return [self.evaluate(gate, unit) for gate in self.names()]

    def _holds(self, condition: str, unit: str) -> bool:
        """Report whether one requirement holds, failing closed."""
        probe = self._conditions.get(condition)
        if probe is None:
            return False
        return bool(probe(unit))

    def _lookup(self, gate: str) -> _Gate:
        try:
            return self._gates[gate]
        except KeyError as missing:
            raise UnknownReferenceError(f"gate {gate} is not declared", gate=gate) from missing
