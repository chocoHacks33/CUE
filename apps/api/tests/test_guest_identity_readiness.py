"""Stage 4's exit gate: may a name come from a face, and may it air unattended?

The whole value of this module is what it refuses to permit, so most of these
tests drive it with incomplete evidence and check that it fails closed.
"""

from __future__ import annotations

from datetime import date

from cue_api.guests.confidence_calibration import (
    NO_CALIBRATION,
    PROVISIONAL_CALIBRATION,
    Calibration,
)
from cue_api.guests.identity_eval import NegativeTrial, PositiveTrial, summarise
from cue_api.guests.identity_readiness import (
    NamingPolicy,
    assess_identity_readiness,
    readiness_lines,
)
from cue_api.guests.morning_validation import CheckOutcome, MorningValidation
from cue_api.guests.types import CalibrationStatus

TODAY = date(2026, 9, 20)


def validated_today(**overrides) -> MorningValidation:
    """Stage 7's re-check, all three passed, dated today."""
    values = {
        "validated_on": TODAY,
        "validated_by": "B",
        "re_enrolment": CheckOutcome.PASSED,
        "reframe": CheckOutcome.PASSED,
        "unknown_rejection": CheckOutcome.PASSED,
    }
    values.update(overrides)
    return MorningValidation(**values)


MEASURED = Calibration(
    calibration_id="held-out-2026-09-19",
    status=CalibrationStatus.MEASURED,
    slope=11.4,
    intercept=-4.2,
    sample_count=60,
)


def clean_report(positives: int = 30, negatives: int = 30, wrong_person: int = 0):
    good = [
        PositiveTrial("guest-sarah", "guest-sarah", "CONFIRMED", 600)
        for _ in range(positives - wrong_person)
    ]
    bad = [
        PositiveTrial("guest-sarah", "guest-daniel", "CONFIRMED", 600)
        for _ in range(wrong_person)
    ]
    refusals = [
        NegativeTrial(f"unenrolled-{index}", None, "UNKNOWN") for index in range(negatives)
    ]
    return summarise(good + bad, refusals)


def everything_passed(**overrides):
    values = {
        "calibration": MEASURED,
        "report": clean_report(),
        "mac_runtime_gate_passed": True,
        "media_checks_passed": True,
        "morning_validation": validated_today(),
        "today": TODAY,
    }
    values.update(overrides)
    return assess_identity_readiness(**values)


# -- the default, which is where the project actually is -------------------


def test_with_no_evidence_at_all_no_name_comes_from_a_face() -> None:
    readiness = assess_identity_readiness(calibration=PROVISIONAL_CALIBRATION)

    assert readiness.policy is NamingPolicy.ROLE_BASED
    assert readiness.role_based is True
    assert readiness.names_from_identity is False
    assert readiness.unattended_naming_permitted is False
    assert "Nothing on screen is identified by face" in readiness.disclosure
    assert any("no identity report" in reason for reason in readiness.blocking_reasons)


def test_the_default_names_every_missing_piece() -> None:
    readiness = assess_identity_readiness(calibration=PROVISIONAL_CALIBRATION, today=TODAY)
    joined = " | ".join(readiness.blocking_reasons)

    assert "no identity report" in joined
    assert "PROVISIONAL_DEFAULT" in joined
    assert "Mac runtime gate" in joined
    assert "media checks" in joined
    assert "today's conditions" in joined


def test_a_disclosure_is_never_empty() -> None:
    """Something must always be sayable out loud about identity."""
    for readiness in (
        assess_identity_readiness(calibration=NO_CALIBRATION),
        assess_identity_readiness(calibration=PROVISIONAL_CALIBRATION, report=clean_report()),
        everything_passed(),
    ):
        assert readiness.disclosure.strip()


# -- a wrong name is disqualifying, not a deduction ------------------------


def test_one_wrong_name_drops_straight_past_assist_to_role_based() -> None:
    """An operator cannot confirm their way out of a wrong suggestion."""
    readiness = everything_passed(report=clean_report(wrong_person=1))

    assert readiness.policy is NamingPolicy.ROLE_BASED
    assert readiness.role_based is True
    assert any("wrong name" in reason for reason in readiness.blocking_reasons)


def test_a_stranger_who_was_named_is_equally_disqualifying() -> None:
    negatives = [NegativeTrial(f"unenrolled-{i}", None, "UNKNOWN") for i in range(29)]
    negatives.append(NegativeTrial("stranger", "guest-sarah", "CONFIRMED"))
    report = summarise(
        [PositiveTrial("guest-sarah", "guest-sarah", "CONFIRMED", 600) for _ in range(30)],
        negatives,
    )

    assert everything_passed(report=report).policy is NamingPolicy.ROLE_BASED


def test_a_perfect_but_too_small_run_is_not_enough() -> None:
    readiness = everything_passed(report=clean_report(positives=5, negatives=5))

    assert readiness.policy is NamingPolicy.ROLE_BASED
    assert any("only 5 positive trials" in r for r in readiness.blocking_reasons)


def test_positives_without_any_strangers_is_not_enough() -> None:
    readiness = everything_passed(report=clean_report(negatives=0))

    assert readiness.policy is NamingPolicy.ROLE_BASED


# -- the middle ground -----------------------------------------------------


def test_a_clean_run_on_an_unmeasured_calibration_is_assist_only() -> None:
    readiness = everything_passed(calibration=PROVISIONAL_CALIBRATION)

    assert readiness.policy is NamingPolicy.NAMED_ASSIST
    assert readiness.role_based is False
    assert readiness.names_from_identity is True
    assert readiness.unattended_naming_permitted is False
    assert "operator confirms" in readiness.disclosure
    assert "not measured" in readiness.disclosure


def test_a_clean_run_without_the_mac_gate_is_assist_only() -> None:
    readiness = everything_passed(mac_runtime_gate_passed=False)

    assert readiness.policy is NamingPolicy.NAMED_ASSIST
    assert readiness.unattended_naming_permitted is False
    assert any("Mac runtime gate" in r for r in readiness.blocking_reasons)
    # The calibration is measured here, so the disclosure does not disclaim it.
    assert "not measured" not in readiness.disclosure


def test_a_clean_run_without_media_checks_is_assist_only() -> None:
    readiness = everything_passed(media_checks_passed=False)

    assert readiness.policy is NamingPolicy.NAMED_ASSIST
    assert any("media checks" in r for r in readiness.blocking_reasons)


# -- the only path to unattended naming ------------------------------------


def test_named_auto_needs_every_piece_and_then_says_so() -> None:
    readiness = everything_passed()

    assert readiness.policy is NamingPolicy.NAMED_AUTO
    assert readiness.role_based is False
    assert readiness.unattended_naming_permitted is True
    assert readiness.blocking_reasons == ()
    assert "unattended" in readiness.disclosure
    assert "identity report" in readiness.disclosure


def test_removing_any_single_piece_removes_unattended_naming() -> None:
    """No one input is optional."""
    weakened = [
        everything_passed(calibration=PROVISIONAL_CALIBRATION),
        everything_passed(mac_runtime_gate_passed=False),
        everything_passed(media_checks_passed=False),
        everything_passed(report=clean_report(positives=10)),
        everything_passed(report=None),
    ]

    assert all(not readiness.unattended_naming_permitted for readiness in weakened)


# -- what C and D consume --------------------------------------------------


def test_role_based_is_the_flag_the_director_already_takes() -> None:
    """The output is not a new vocabulary: it is the keyword C's director accepts."""
    import inspect

    from cue_api.policy.director import decide

    readiness = assess_identity_readiness(calibration=PROVISIONAL_CALIBRATION)
    parameter = inspect.signature(decide).parameters["role_based"]

    assert isinstance(readiness.role_based, bool)
    assert parameter.annotation in (bool, "bool")


def test_the_lines_explain_a_refusal_to_a_human() -> None:
    text = "\n".join(readiness_lines(assess_identity_readiness(calibration=NO_CALIBRATION)))

    assert "naming policy:  ROLE_BASED" in text
    assert "role_based:     True" in text
    assert "why not more:" in text
    assert "no identity report" in text


def test_the_lines_of_a_ready_system_list_nothing_blocking() -> None:
    text = "\n".join(readiness_lines(everything_passed()))

    assert "NAMED_AUTO" in text
    assert "why not more:" not in text
