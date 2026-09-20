"""Stage 7's morning re-validation, and the one rule it must never break.

The rule: **a morning validation can only take capability away, never grant it.**
Most of these tests exist to hold that line, because the tempting shortcut at 08:40
with a demo at 10:00 is a flag that turns naming back on.
"""

from __future__ import annotations

from datetime import date

import pytest

from cue_api.guests.confidence_calibration import PROVISIONAL_CALIBRATION, Calibration
from cue_api.guests.identity_eval import NegativeTrial, PositiveTrial, summarise
from cue_api.guests.identity_readiness import NamingPolicy, assess_identity_readiness
from cue_api.guests.morning_validation import (
    CheckOutcome,
    MorningValidation,
    MorningValidationError,
    validation_lines,
)
from cue_api.guests.types import CalibrationStatus

TODAY = date(2026, 9, 20)
YESTERDAY = date(2026, 9, 19)

MEASURED = Calibration(
    calibration_id="held-out-2026-09-19",
    status=CalibrationStatus.MEASURED,
    slope=11.4,
    intercept=-4.2,
    sample_count=60,
)


def validation(**overrides) -> MorningValidation:
    values = {
        "validated_on": TODAY,
        "validated_by": "B",
        "re_enrolment": CheckOutcome.PASSED,
        "reframe": CheckOutcome.PASSED,
        "unknown_rejection": CheckOutcome.PASSED,
    }
    values.update(overrides)
    return MorningValidation(**values)


def clean_report():
    return summarise(
        [PositiveTrial("guest-sarah", "guest-sarah", "CONFIRMED", 600) for _ in range(30)],
        [NegativeTrial(f"unenrolled-{i}", None, "UNKNOWN") for i in range(30)],
    )


def readiness(**overrides):
    values = {
        "calibration": MEASURED,
        "report": clean_report(),
        "mac_runtime_gate_passed": True,
        "media_checks_passed": True,
        "morning_validation": validation(),
        "today": TODAY,
    }
    values.update(overrides)
    return assess_identity_readiness(**values)


# -- the record itself -----------------------------------------------------


def test_a_validation_must_name_who_ran_it() -> None:
    with pytest.raises(MorningValidationError, match="who ran it"):
        validation(validated_by="   ")


def test_failures_are_listed_by_name() -> None:
    record = validation(unknown_rejection=CheckOutcome.FAILED)

    assert record.failures == ("unknown_rejection",)
    assert record.all_passed is False


def test_checks_nobody_ran_are_distinguished_from_checks_that_failed() -> None:
    """"We did not try" and "we tried and it broke" are different facts."""
    record = validation(reframe=CheckOutcome.NOT_RUN)

    assert record.failures == ()
    assert record.not_run == ("reframe",)
    assert record.all_passed is False


def test_the_document_records_what_was_checked_and_by_whom() -> None:
    record = validation(unknown_rejection=CheckOutcome.FAILED, note="north window sun")
    document = record.to_document()

    assert document["validatedOn"] == "2026-09-20"
    assert document["validatedBy"] == "B"
    assert document["unknownRejection"] == "FAILED"
    assert document["allPassed"] is False
    assert document["failures"] == ["unknown rejection in this morning's lighting"]
    assert document["note"] == "north window sun"


# -- it can only remove capability ----------------------------------------


def test_a_passing_validation_grants_nothing_on_its_own() -> None:
    """With no other evidence it is still ROLE_BASED."""
    result = assess_identity_readiness(
        calibration=PROVISIONAL_CALIBRATION,
        morning_validation=validation(),
        today=TODAY,
    )

    assert result.policy is NamingPolicy.ROLE_BASED
    assert result.role_based is True


def test_a_passing_validation_does_not_excuse_a_wrong_name() -> None:
    report = summarise(
        [PositiveTrial("guest-sarah", "guest-daniel", "CONFIRMED", 600)] * 30,
        [NegativeTrial(f"unenrolled-{i}", None, "UNKNOWN") for i in range(30)],
    )

    assert readiness(report=report).policy is NamingPolicy.ROLE_BASED


def test_full_evidence_with_a_passing_validation_reaches_named_auto() -> None:
    """The only path through. Everything, including today's re-check."""
    result = readiness()

    assert result.policy is NamingPolicy.NAMED_AUTO
    assert result.unattended_naming_permitted is True
    assert result.blocking_reasons == ()


# -- a failure this morning disables, it does not deduct ------------------


def test_a_failed_unknown_rejection_switches_naming_off_entirely() -> None:
    """The case the exit gate is written for: it names somebody it should not."""
    result = readiness(morning_validation=validation(unknown_rejection=CheckOutcome.FAILED))

    assert result.policy is NamingPolicy.ROLE_BASED
    assert result.role_based is True
    assert result.unattended_naming_permitted is False
    assert any("unknown rejection" in reason for reason in result.blocking_reasons)
    assert any("FAILED" in reason for reason in result.blocking_reasons)


def test_a_failed_reframe_check_also_switches_naming_off() -> None:
    result = readiness(morning_validation=validation(reframe=CheckOutcome.FAILED))

    assert result.policy is NamingPolicy.ROLE_BASED
    assert any("reframe" in reason for reason in result.blocking_reasons)


def test_a_failure_names_the_date_and_the_person() -> None:
    """So a stale failure cannot be mistaken for a fresh one."""
    reasons = readiness(
        morning_validation=validation(validated_by="D", unknown_rejection=CheckOutcome.FAILED)
    ).blocking_reasons

    assert any("2026-09-20" in reason and "D" in reason for reason in reasons)


def test_a_failure_is_not_cleared_by_the_clock() -> None:
    """Yesterday's failure still blocks; only a passing re-run clears it."""
    result = readiness(
        morning_validation=validation(
            validated_on=YESTERDAY, unknown_rejection=CheckOutcome.FAILED
        )
    )

    assert result.policy is NamingPolicy.ROLE_BASED


# -- claims must match *today's* conditions -------------------------------


def test_no_validation_at_all_refuses_unattended_naming() -> None:
    """Yesterday's trials do not describe a room whose cameras may have moved.

    This lands on NAMED_ASSIST rather than ROLE_BASED on purpose: nothing is known
    to be broken, so a human in the loop is the proportionate answer. What it may
    never do is name somebody unattended.
    """
    result = readiness(morning_validation=None)

    assert result.unattended_naming_permitted is False
    assert result.policy is NamingPolicy.NAMED_ASSIST
    assert any("today's conditions" in reason for reason in result.blocking_reasons)


def test_yesterdays_passing_validation_does_not_permit_unattended_naming() -> None:
    result = readiness(morning_validation=validation(validated_on=YESTERDAY))

    assert result.unattended_naming_permitted is False
    assert any("not today" in reason for reason in result.blocking_reasons)


def test_a_partially_run_validation_does_not_permit_unattended_naming() -> None:
    result = readiness(morning_validation=validation(reframe=CheckOutcome.NOT_RUN))

    assert result.unattended_naming_permitted is False
    assert any("not re-checked" in reason for reason in result.blocking_reasons)


def test_a_known_failure_is_treated_differently_from_missing_evidence() -> None:
    """The distinction this module turns on, pinned so nobody flattens it later.

    A FAILED check means the suggestion itself is untrustworthy, and an operator
    cannot confirm their way out of that — so naming is switched off entirely. A
    check nobody ran means only that we do not know, which a human in the loop
    covers. Collapsing the two either over-blocks or under-blocks.
    """
    failed = readiness(morning_validation=validation(unknown_rejection=CheckOutcome.FAILED))
    absent = readiness(morning_validation=None)

    assert failed.policy is NamingPolicy.ROLE_BASED
    assert failed.role_based is True

    assert absent.policy is NamingPolicy.NAMED_ASSIST
    assert absent.role_based is False

    # The one thing both refuse.
    assert failed.unattended_naming_permitted is False
    assert absent.unattended_naming_permitted is False


def test_unattended_naming_requires_todays_complete_pass() -> None:
    """The load-bearing invariant of this whole module."""
    weakened = [
        readiness(morning_validation=None),
        readiness(morning_validation=validation(validated_on=YESTERDAY)),
        readiness(morning_validation=validation(reframe=CheckOutcome.NOT_RUN)),
        readiness(morning_validation=validation(unknown_rejection=CheckOutcome.FAILED)),
    ]

    assert all(not result.unattended_naming_permitted for result in weakened)
    assert readiness().unattended_naming_permitted is True


def test_a_partial_run_is_not_reported_as_a_failure() -> None:
    """It is an unfinished check, and the wording must not imply a regression."""
    reasons = readiness(
        morning_validation=validation(unknown_rejection=CheckOutcome.NOT_RUN)
    ).blocking_reasons

    assert not any("FAILED" in reason for reason in reasons)


# -- what a human reads at 08:30 ------------------------------------------


def test_the_lines_say_plainly_when_nobody_has_checked() -> None:
    text = "\n".join(validation_lines(None, TODAY))

    assert "NOT RUN" in text
    assert "2026-09-20" in text


def test_the_lines_flag_a_validation_that_is_not_todays() -> None:
    text = "\n".join(validation_lines(validation(validated_on=YESTERDAY), TODAY))

    assert "NOT today" in text
    assert "does NOT support a named policy today" in text


def test_the_lines_of_a_clean_check_do_not_promise_capability() -> None:
    """It stands up for today; it does not mean identity is allowed."""
    text = "\n".join(validation_lines(validation(), TODAY))

    assert "other evidence still required" in text
    assert "does NOT support" not in text


def test_the_lines_list_every_check_with_its_outcome() -> None:
    text = "\n".join(validation_lines(validation(reframe=CheckOutcome.FAILED), TODAY))

    assert "PASSED   re-enrolment" in text
    assert "FAILED   guest-camera reframe" in text
    assert "PASSED   unknown rejection" in text
