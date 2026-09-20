"""Stage 7's re-validation: do yesterday's claims still hold this morning?

Stage 7's exit gate is *"claims match today's conditions. If a capability fails,
disable/disclose it and update the saved submission."*

Until now the readiness gate had no way to say that. Its four inputs — calibration,
identity report, Mac gate, media checks — all **accumulate**. Evidence goes in and
capability comes out, and nothing could express "we re-tested this morning and it
broke". Somebody would have had to hand-edit an attestation, which means lying in a
file, to represent a real regression.

This is that channel, and it is deliberately one-directional: **a morning
validation can only take capability away, never grant it.**

- No validation for today → claims are not shown to match today's conditions, so a
  named policy is refused. Yesterday's trials do not describe a room whose laptops
  were moved overnight, and moving a laptop changes framing.
- Any check FAILED → refused, with the failing check and its date named. A failure
  is not cleared by the clock; it is cleared by a passing re-run.
- All three PASSED today → grants nothing on its own. Every other piece of evidence
  is still required.

The three checks are the three things Stage 7 asks B to do, and the last one is the
one that matters: if an unenrolled person gets named, the honest response is to
switch identity off and say so, not to retune a threshold before a demo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class CheckOutcome(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"


class MorningValidationError(ValueError):
    """A validation record nobody could act on."""


#: The three checks Stage 7 asks B for, in the order the run sheet performs them.
CHECK_LABELS = {
    "re_enrolment": "re-enrolment after the memory-clearing restart",
    "reframe": "guest-camera reframe invalidating identity",
    "unknown_rejection": "unknown rejection in this morning's lighting",
}


@dataclass(frozen=True)
class MorningValidation:
    """What B re-checked against today's conditions, and who checked it."""

    validated_on: date
    #: A person. An unsigned validation is not evidence.
    validated_by: str
    re_enrolment: CheckOutcome = CheckOutcome.NOT_RUN
    reframe: CheckOutcome = CheckOutcome.NOT_RUN
    unknown_rejection: CheckOutcome = CheckOutcome.NOT_RUN
    note: str = ""

    def __post_init__(self) -> None:
        if not self.validated_by.strip():
            raise MorningValidationError(
                "A morning validation must name who ran it; an unsigned check is not "
                "evidence"
            )

    def outcomes(self) -> dict[str, CheckOutcome]:
        return {
            "re_enrolment": self.re_enrolment,
            "reframe": self.reframe,
            "unknown_rejection": self.unknown_rejection,
        }

    @property
    def failures(self) -> tuple[str, ...]:
        """Checks that were run and did not pass."""
        return tuple(
            name for name, outcome in self.outcomes().items() if outcome is CheckOutcome.FAILED
        )

    @property
    def not_run(self) -> tuple[str, ...]:
        return tuple(
            name for name, outcome in self.outcomes().items() if outcome is CheckOutcome.NOT_RUN
        )

    @property
    def all_passed(self) -> bool:
        return all(outcome is CheckOutcome.PASSED for outcome in self.outcomes().values())

    def is_current(self, today: date) -> bool:
        return self.validated_on == today

    def blocking_reasons(self, today: date) -> tuple[str, ...]:
        """Why this validation does not support a claim about today.

        Empty means it does not stand in the way. It never means "therefore allowed".
        """
        reasons: list[str] = []
        for name in self.failures:
            reasons.append(
                f"{CHECK_LABELS[name]} FAILED on {self.validated_on.isoformat()} "
                f"(checked by {self.validated_by.strip()})"
            )
        if not self.is_current(today):
            reasons.append(
                f"the last validation was {self.validated_on.isoformat()}, not today "
                f"({today.isoformat()}); claims must match today's conditions"
            )
        elif self.not_run:
            missing = ", ".join(CHECK_LABELS[name] for name in self.not_run)
            reasons.append(f"not re-checked against today's conditions: {missing}")
        return tuple(reasons)

    def to_document(self) -> dict[str, object]:
        return {
            "validatedOn": self.validated_on.isoformat(),
            "validatedBy": self.validated_by.strip(),
            "reEnrolment": self.re_enrolment.value,
            "reframe": self.reframe.value,
            "unknownRejection": self.unknown_rejection.value,
            "allPassed": self.all_passed,
            "failures": [CHECK_LABELS[name] for name in self.failures],
            "note": self.note.strip(),
        }


def missing_validation_reason(today: date) -> str:
    """What to say when nobody has re-validated at all."""
    return (
        f"no validation against today's conditions ({today.isoformat()}); "
        "yesterday's trials do not describe a room whose cameras may have moved"
    )


def validation_lines(validation: MorningValidation | None, today: date) -> list[str]:
    """What a human reads at 08:30."""
    if validation is None:
        return [f"morning check: NOT RUN — {missing_validation_reason(today)}"]

    lines = [
        f"validated on: {validation.validated_on.isoformat()}"
        f"{'' if validation.is_current(today) else '  (NOT today)'}",
        f"validated by: {validation.validated_by.strip()}",
    ]
    for name, outcome in validation.outcomes().items():
        lines.append(f"  {outcome.value:8} {CHECK_LABELS[name]}")
    if validation.note.strip():
        lines.append(f"note:         {validation.note.strip()}")

    blocking = validation.blocking_reasons(today)
    if blocking:
        lines.append("verdict:      does NOT support a named policy today:")
        lines.extend(f"              - {reason}" for reason in blocking)
    else:
        lines.append("verdict:      stands up for today; other evidence still required")
    return lines
