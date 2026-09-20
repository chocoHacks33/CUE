"""Whether identity has earned the right to put a name on a cut.

Stage 4's exit gate: *"choose named AUTO only if evidence supports it. At H10,
unreliable wrong-person rejection means disclosed operator-confirmed/role-based
ASSIST."*

That is a judgement about evidence, and identity is B's lane, so this is where B
answers it. It does not decide the show's mode — `ControlMode` is A's and the
director's `Mode` is C's. It answers one narrower question and hands the result
over: **may a name come from face identity, and if so, may it do so unattended?**

The answer feeds two things that already exist: the `role_based` flag
`policy.director.decide` takes, which skips the identity check and names from the
roster instead, and the disclosure D's panel shows.

It **fails closed**. The default, with no evidence at all, is `ROLE_BASED`: the
guest camera is still cut to as the guest camera, but no name comes from a face.
Reaching `NAMED_AUTO` requires every one of these, and any missing one is named in
`blocking_reasons`:

- an identity report that is claimable at all — 30 trials per arm, **zero wrong
  names**
- a `MEASURED` calibration, not the provisional anchor
- the Mac runtime gate passed
- B's media checks passed
- a Stage 7 morning validation, **dated today**, with all three checks passed

A single wrong name anywhere drops straight to `ROLE_BASED`, skipping
`NAMED_ASSIST`, because an operator confirming a suggestion cannot fix a system
that sometimes offers the wrong person confidently: the suggestion is the thing
that is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from cue_api.guests.confidence_calibration import Calibration
from cue_api.guests.identity_eval import IdentityReport
from cue_api.guests.morning_validation import MorningValidation, missing_validation_reason
from cue_api.guests.types import CalibrationStatus


class NamingPolicy(StrEnum):
    #: Face identity may name a guest with no operator in the loop.
    NAMED_AUTO = "NAMED_AUTO"
    #: Face identity may *suggest* a name; an operator confirms before it airs.
    NAMED_ASSIST = "NAMED_ASSIST"
    #: No name comes from a face. Cameras are still chosen by role.
    ROLE_BASED = "ROLE_BASED"


@dataclass(frozen=True)
class IdentityReadiness:
    policy: NamingPolicy
    #: Pass straight to `policy.director.decide(role_based=...)`.
    role_based: bool
    #: Whether a name from identity may air without an operator confirming it.
    unattended_naming_permitted: bool
    #: What the demo must say out loud about identity. Never empty.
    disclosure: str
    blocking_reasons: tuple[str, ...]

    @property
    def names_from_identity(self) -> bool:
        return self.policy is not NamingPolicy.ROLE_BASED


ROLE_BASED_DISCLOSURE = (
    "Cameras are chosen by role, not by face recognition. Nothing on screen is "
    "identified by face."
)
ASSIST_DISCLOSURE = (
    "Face identity suggests a name; the operator confirms every named shot before "
    "it airs. Confidence figures are not measured."
)
ASSIST_DISCLOSURE_MEASURED = (
    "Face identity suggests a name; the operator confirms every named shot before "
    "it airs."
)
AUTO_DISCLOSURE = (
    "Face identity names guests unattended, on a measured calibration, within the "
    "conditions recorded in the identity report."
)


def assess_identity_readiness(
    *,
    calibration: Calibration,
    report: IdentityReport | None = None,
    mac_runtime_gate_passed: bool = False,
    media_checks_passed: bool = False,
    morning_validation: MorningValidation | None = None,
    today: date | None = None,
) -> IdentityReadiness:
    """What B's evidence permits. Absent evidence, it permits the least.

    `morning_validation` is Stage 7's re-check against today's conditions. It is
    one-directional: it can only remove capability, never grant it.
    """
    reasons: list[str] = []
    today = today or date.today()

    if report is None:
        reasons.append(
            "no identity report exists, so nothing is known about wrong-person "
            "rejection"
        )
    elif report.total_wrong_names:
        reasons.append(
            f"the identity report records {report.total_wrong_names} wrong name(s); "
            "an operator cannot confirm their way out of a wrong suggestion"
        )
    elif not report.claimable:
        reasons.extend(report.blocking_reasons)

    if calibration.status is not CalibrationStatus.MEASURED:
        reasons.append(
            f"the calibration is {calibration.status.value}, so any confidence "
            "shown is an anchor rather than a measurement"
        )
    if not mac_runtime_gate_passed:
        reasons.append("the Mac runtime gate has not passed")
    if not media_checks_passed:
        reasons.append("B's media checks have not run")

    # Stage 7: claims have to match *today's* conditions. Overnight the laptops
    # move, and moving a laptop changes framing.
    if morning_validation is None:
        reasons.append(missing_validation_reason(today))
        morning_failed = False
    else:
        validation_reasons = morning_validation.blocking_reasons(today)
        reasons.extend(validation_reasons)
        # A capability that failed this morning is disabled, not merely deducted.
        morning_failed = bool(morning_validation.failures)

    # A wrong name, or no evidence at all, means no naming from faces.
    wrong_names = report is not None and bool(report.total_wrong_names)
    no_usable_report = report is None or not report.claimable
    if wrong_names or no_usable_report or morning_failed:
        return IdentityReadiness(
            policy=NamingPolicy.ROLE_BASED,
            role_based=True,
            unattended_naming_permitted=False,
            disclosure=ROLE_BASED_DISCLOSURE,
            blocking_reasons=tuple(reasons),
        )

    if reasons:
        measured = calibration.status is CalibrationStatus.MEASURED
        return IdentityReadiness(
            policy=NamingPolicy.NAMED_ASSIST,
            role_based=False,
            unattended_naming_permitted=False,
            disclosure=ASSIST_DISCLOSURE_MEASURED if measured else ASSIST_DISCLOSURE,
            blocking_reasons=tuple(reasons),
        )

    return IdentityReadiness(
        policy=NamingPolicy.NAMED_AUTO,
        role_based=False,
        unattended_naming_permitted=True,
        disclosure=AUTO_DISCLOSURE,
        blocking_reasons=(),
    )


def readiness_lines(readiness: IdentityReadiness) -> list[str]:
    """Plain lines for the terminal, the producer panel and the run sheet."""
    lines = [
        f"naming policy:  {readiness.policy.value}",
        f"role_based:     {readiness.role_based}",
        f"unattended:     {readiness.unattended_naming_permitted}",
        f"disclose:       {readiness.disclosure}",
    ]
    if readiness.blocking_reasons:
        lines.append("why not more:")
        lines.extend(f"                - {reason}" for reason in readiness.blocking_reasons)
    return lines
