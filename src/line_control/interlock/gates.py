"""Pre-gates: named conditions that must hold before a step runs.

A gate stands for a list of requirements.  Each requirement is bound to a
live probe -- a callable that answers the question for one unit by reading
the record stream.  Evaluating the gate runs every probe and reports the
requirements that do not currently hold.  A requirement without a probe
fails closed, so a miswired gate can never silently open.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from line_control.runtime.errors import (
    GateBlockedError,
    UnknownReferenceError,
    ValidationError,
)

RequirementProbe = Callable[[str], bool]


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
    probes: dict[str, RequirementProbe] = field(default_factory=dict)


class GateBoard:
    """A registry of named gates whose requirements are read live."""

    def __init__(self) -> None:
        self._gates: dict[str, _Gate] = {}

    def define(self, gate: str, requirements: Sequence[str]) -> None:
        """Declare a gate and the conditions it stands for."""
        if not gate:
            raise ValidationError("gate name is required")
        if not requirements:
            raise ValidationError("a gate needs at least one requirement", gate=gate)
        self._gates[gate] = _Gate(name=gate, requirements=list(requirements))

    def bind(
        self, gate: str, requirement: str, probe: RequirementProbe
    ) -> None:
        """Bind one requirement of a gate to the live probe that proves it."""
        declared = self._lookup(gate)
        if requirement not in declared.requirements:
            raise ValidationError(
                f"{requirement} is not a requirement of gate {gate}",
                gate=gate,
                requirement=requirement,
            )
        declared.probes[requirement] = probe

    def names(self) -> list[str]:
        """Return every declared gate name."""
        return sorted(self._gates)

    def requirements(self, gate: str) -> list[str]:
        """Return the requirement names of a gate."""
        return list(self._lookup(gate).requirements)

    def evaluate(self, gate: str, unit: str) -> GateVerdict:
        """Evaluate a gate without raising, naming every missing requirement."""
        declared = self._lookup(gate)
        missing: list[str] = []
        for requirement in declared.requirements:
            probe = declared.probes.get(requirement)
            # An unbound requirement fails closed: a gate is only as open as
            # the evidence wired behind each of its conditions.
            if probe is None or not probe(unit):
                missing.append(requirement)
        return GateVerdict(
            gate=gate,
            unit=unit,
            open=not missing,
            blocked_by=tuple(missing),
        )

    def require(self, gate: str, unit: str) -> GateVerdict:
        """Evaluate a gate and refuse the step when it is closed."""
        verdict = self.evaluate(gate, unit)
        if not verdict.open:
            raise GateBlockedError(
                f"gate {gate} is closed for unit {unit}; "
                f"unmet requirement(s): {', '.join(verdict.blocked_by)}",
                gate=gate,
                unit=unit,
                blocked_by=list(verdict.blocked_by),
            )
        return verdict

    def report(self, unit: str) -> list[GateVerdict]:
        """Evaluate every declared gate for one unit."""
        return [self.evaluate(gate, unit) for gate in self.names()]

    def _lookup(self, gate: str) -> _Gate:
        try:
            return self._gates[gate]
        except KeyError as missing:
            raise UnknownReferenceError(f"gate {gate} is not declared", gate=gate) from missing
