"""Fail-closed operational release gate for Person A's Stage 4 trials.

The gate records evidence; it does not manufacture it. Routing, failover,
backend and provider trials require live-system evidence, while access-control
boundaries may be proven by deterministic automated tests. Passing this gate is
necessary for AUTO, but B and C's separate identity/semantic gates must also
pass before AUTO is actually enabled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class EvidenceKind(StrEnum):
    AUTOMATED = "AUTOMATED"
    REPLAY = "REPLAY"
    LIVE = "LIVE"


class ProbeArea(StrEnum):
    ROUTING_RECONNECT = "ROUTING_RECONNECT"
    SOURCE_LOSS = "SOURCE_LOSS"
    BACKEND_FAILURE = "BACKEND_FAILURE"
    SPEECH_PROVIDER_FAILURE = "SPEECH_PROVIDER_FAILURE"
    SEMANTIC_PROVIDER_FAILURE = "SEMANTIC_PROVIDER_FAILURE"
    EVENT_ACCESS = "EVENT_ACCESS"
    OBSERVER_CONTROL = "OBSERVER_CONTROL"


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"


_EVIDENCE_RANK = {
    EvidenceKind.AUTOMATED: 0,
    EvidenceKind.REPLAY: 1,
    EvidenceKind.LIVE: 2,
}


@dataclass(frozen=True)
class TrialRequirement:
    minimum_trials: int
    minimum_evidence: EvidenceKind
    maximum_p95_ms: float | None = None


REQUIREMENTS: dict[ProbeArea, TrialRequirement] = {
    ProbeArea.ROUTING_RECONNECT: TrialRequirement(20, EvidenceKind.LIVE),
    ProbeArea.SOURCE_LOSS: TrialRequirement(10, EvidenceKind.LIVE, 1_500),
    ProbeArea.BACKEND_FAILURE: TrialRequirement(1, EvidenceKind.LIVE),
    ProbeArea.SPEECH_PROVIDER_FAILURE: TrialRequirement(1, EvidenceKind.LIVE),
    ProbeArea.SEMANTIC_PROVIDER_FAILURE: TrialRequirement(1, EvidenceKind.LIVE),
    ProbeArea.EVENT_ACCESS: TrialRequirement(1, EvidenceKind.AUTOMATED),
    ProbeArea.OBSERVER_CONTROL: TrialRequirement(3, EvidenceKind.AUTOMATED),
}


@dataclass(frozen=True)
class TrialResult:
    trial_id: str
    area: ProbeArea
    passed: bool
    evidence_kind: EvidenceKind
    latency_ms: float | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.trial_id.strip():
            raise ValueError("trial_id must not be empty")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms must not be negative")
        if not self.passed and not self.detail.strip():
            raise ValueError("a failed trial must explain what failed")

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> TrialResult:
        latency = value.get("latencyMs")
        return cls(
            trial_id=str(value.get("trialId", "")),
            area=ProbeArea(value.get("area")),
            passed=value.get("passed") is True,
            evidence_kind=EvidenceKind(value.get("evidenceKind")),
            latency_ms=None if latency is None else float(latency),
            detail=str(value.get("detail", "")),
        )


@dataclass(frozen=True)
class AreaAssessment:
    area: ProbeArea
    status: GateStatus
    qualifying_trials: int
    required_trials: int
    p95_latency_ms: float | None
    blocking_reasons: tuple[str, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "area": self.area.value,
            "status": self.status.value,
            "qualifyingTrials": self.qualifying_trials,
            "requiredTrials": self.required_trials,
            "p95LatencyMs": self.p95_latency_ms,
            "blockingReasons": list(self.blocking_reasons),
        }


@dataclass(frozen=True)
class Stage4Assessment:
    status: GateStatus
    auto_eligible: bool
    areas: tuple[AreaAssessment, ...]
    disclosure: str

    @property
    def blocking_reasons(self) -> tuple[str, ...]:
        return tuple(reason for area in self.areas for reason in area.blocking_reasons)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "autoEligible": self.auto_eligible,
            "disclosure": self.disclosure,
            "blockingReasons": list(self.blocking_reasons),
            "areas": [area.to_mapping() for area in self.areas],
        }


def _percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _assess_area(area: ProbeArea, trials: list[TrialResult]) -> AreaAssessment:
    requirement = REQUIREMENTS[area]
    qualifying = [
        trial
        for trial in trials
        if trial.area is area
        and _EVIDENCE_RANK[trial.evidence_kind] >= _EVIDENCE_RANK[requirement.minimum_evidence]
    ]
    reasons: list[str] = []
    failed = [trial for trial in qualifying if not trial.passed]
    if failed:
        reasons.extend(f"{trial.trial_id}: {trial.detail}" for trial in failed)

    missing = requirement.minimum_trials - len(qualifying)
    if missing > 0:
        reasons.append(
            f"{area.value}: needs {missing} more {requirement.minimum_evidence.value} trial(s)"
        )

    p95: float | None = None
    if requirement.maximum_p95_ms is not None:
        without_latency = [trial.trial_id for trial in qualifying if trial.latency_ms is None]
        if without_latency:
            reasons.append(
                f"{area.value}: missing latency for {', '.join(without_latency)}"
            )
        p95 = _percentile_95(
            [trial.latency_ms for trial in qualifying if trial.latency_ms is not None]
        )
        if p95 is not None and p95 > requirement.maximum_p95_ms:
            reasons.append(
                f"{area.value}: p95 {p95:.0f} ms exceeds "
                f"{requirement.maximum_p95_ms:.0f} ms"
            )

    if failed or (p95 is not None and p95 > (requirement.maximum_p95_ms or math.inf)):
        status = GateStatus.FAIL
    elif reasons:
        status = GateStatus.INCOMPLETE
    else:
        status = GateStatus.PASS
    return AreaAssessment(
        area=area,
        status=status,
        qualifying_trials=len(qualifying),
        required_trials=requirement.minimum_trials,
        p95_latency_ms=p95,
        blocking_reasons=tuple(reasons),
    )


def assess_stage4(trials: list[TrialResult]) -> Stage4Assessment:
    trial_ids = [trial.trial_id for trial in trials]
    if len(set(trial_ids)) != len(trial_ids):
        raise ValueError("trial IDs must be unique")

    areas = tuple(_assess_area(area, trials) for area in REQUIREMENTS)
    if any(area.status is GateStatus.FAIL for area in areas):
        status = GateStatus.FAIL
    elif any(area.status is GateStatus.INCOMPLETE for area in areas):
        status = GateStatus.INCOMPLETE
    else:
        status = GateStatus.PASS

    if status is GateStatus.PASS:
        disclosure = (
            "A's operational failure gate passed. Named AUTO still requires B's identity "
            "gate, C's semantic gate and D's soak/recording gate."
        )
    elif status is GateStatus.FAIL:
        disclosure = (
            "A's operational failure gate failed. Keep the show in ASSIST/local manual "
            "operation and disclose the failing paths."
        )
    else:
        disclosure = (
            "A's operational failure gate has not been completed. AUTO is not authorised "
            "by this evidence."
        )
    return Stage4Assessment(status, status is GateStatus.PASS, areas, disclosure)
