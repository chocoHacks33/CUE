"""The measuring instrument for B's identity report.

Most of these tests are about what the harness refuses to say. That is the point
of building it before the trials exist: the rules for judging a number are fixed
while nobody knows what the number will be.
"""

from __future__ import annotations

import pytest

from cue_api.guests.face_matching import MatchThresholds
from cue_api.guests.identity_eval import (
    InsufficientEvidence,
    LabelledPair,
    NegativeTrial,
    PositiveTrial,
    evaluate_threshold,
    recommend_accept_similarity,
    summarise,
    summary_lines,
    sweep,
)


def pairs(positives: list[float], negatives: list[float]) -> list[LabelledPair]:
    return [LabelledPair(s, True) for s in positives] + [
        LabelledPair(s, False) for s in negatives
    ]


def good_positives(count: int = 30) -> list[PositiveTrial]:
    return [
        PositiveTrial(
            guest_id="guest-sarah",
            named_guest_id="guest-sarah",
            status="CONFIRMED",
            ms_to_confirmed=600 + index * 10,
        )
        for index in range(count)
    ]


def good_negatives(count: int = 30) -> list[NegativeTrial]:
    return [
        NegativeTrial(subject=f"unenrolled-{index}", named_guest_id=None, status="UNKNOWN")
        for index in range(count)
    ]


# -- threshold arithmetic ---------------------------------------------------


def test_acceptance_uses_the_same_comparison_as_the_matcher() -> None:
    """`match` refuses when `similarity < accept_similarity`, so equality accepts."""
    outcome = evaluate_threshold([LabelledPair(0.40, True)], 0.40)

    assert outcome.true_accepts == 1
    assert outcome.false_rejects == 0


def test_a_threshold_is_scored_against_both_arms() -> None:
    outcome = evaluate_threshold(pairs([0.8, 0.7, 0.2], [0.1, 0.5]), 0.6)

    assert outcome.true_accepts == 2
    assert outcome.false_rejects == 1
    assert outcome.false_accepts == 0
    assert outcome.true_rejects == 2
    assert outcome.recall == pytest.approx(2 / 3)
    assert outcome.false_accept_rate == 0.0


def test_a_false_accept_rate_is_unmeasured_not_zero_without_strangers() -> None:
    """Zero out of zero is not zero. This is the number most easily faked."""
    outcome = evaluate_threshold(pairs([0.9, 0.8], []), 0.5)

    assert outcome.negatives == 0
    assert outcome.false_accept_rate is None
    assert outcome.recall == 1.0


def test_recall_is_unmeasured_without_any_true_matches() -> None:
    outcome = evaluate_threshold(pairs([], [0.1, 0.2]), 0.5)

    assert outcome.recall is None
    assert outcome.false_accept_rate == 0.0


def test_a_sweep_is_ordered_and_covers_every_candidate() -> None:
    outcomes = sweep(pairs([0.8, 0.6], [0.1, 0.3]), [0.7, 0.2, 0.5])

    assert [o.accept_similarity for o in outcomes] == [0.2, 0.5, 0.7]
    # At 0.2 the stranger scoring 0.3 gets through; the one at 0.1 does not.
    assert outcomes[0].false_accepts == 1
    assert outcomes[0].true_accepts == 2
    # By 0.7 no stranger passes, and one true match is lost with them.
    assert outcomes[-1].false_accepts == 0
    assert outcomes[-1].false_rejects == 1


# -- recommending a threshold ----------------------------------------------


def test_a_recommendation_clears_the_worst_stranger() -> None:
    recommendation = recommend_accept_similarity(
        pairs([0.80, 0.78, 0.75, 0.72, 0.70], [0.40, 0.35, 0.30, 0.22, 0.10])
    )

    assert recommendation.highest_negative_similarity == 0.40
    assert recommendation.accept_similarity > 0.40
    assert recommendation.outcome.false_accepts == 0
    assert recommendation.positives_measured == 5
    assert recommendation.negatives_measured == 5


def test_a_recommendation_prefers_losing_a_name_to_risking_a_wrong_one() -> None:
    """A positive that overlaps the strangers is sacrificed, not accommodated."""
    recommendation = recommend_accept_similarity(
        # One true match at 0.30 sits below a stranger at 0.45.
        pairs([0.90, 0.85, 0.80, 0.75, 0.30], [0.45, 0.20, 0.15, 0.10, 0.05])
    )

    assert recommendation.outcome.false_accepts == 0
    assert recommendation.outcome.false_rejects == 1
    assert "refused" in recommendation.note


def test_a_one_sided_sample_is_refused_like_a_calibration_fit() -> None:
    with pytest.raises(InsufficientEvidence, match="negative"):
        recommend_accept_similarity(pairs([0.9] * 20, []))


def test_too_few_strangers_is_refused_even_with_many_positives() -> None:
    with pytest.raises(InsufficientEvidence, match="at least 5"):
        recommend_accept_similarity(pairs([0.9] * 50, [0.1, 0.2]))


def test_the_prd_threshold_is_not_assumed_to_be_right() -> None:
    """The recommendation comes from the data, not from the PRD's starting point."""
    recommendation = recommend_accept_similarity(
        pairs([0.95] * 5, [0.80, 0.79, 0.78, 0.77, 0.76])
    )

    # Strangers scoring 0.8 mean the PRD's 0.363 would name all of them.
    assert recommendation.accept_similarity > MatchThresholds().accept_similarity
    assert evaluate_threshold(
        pairs([0.95] * 5, [0.80, 0.79, 0.78, 0.77, 0.76]),
        MatchThresholds().accept_similarity,
    ).false_accepts == 5


# -- the report ------------------------------------------------------------


def test_a_full_clean_run_is_claimable() -> None:
    report = summarise(good_positives(), good_negatives())

    assert report.positives_run == 30
    assert report.negatives_run == 30
    assert report.correct_completions == 30
    assert report.total_wrong_names == 0
    assert report.claimable
    assert report.blocking_reasons == ()


def test_one_wrong_person_makes_an_otherwise_perfect_run_unclaimable() -> None:
    """A wrong confident cut is the worst outcome, so no average absorbs it."""
    positives = good_positives(29) + [
        PositiveTrial(
            guest_id="guest-sarah",
            named_guest_id="guest-daniel",
            status="CONFIRMED",
            ms_to_confirmed=700,
        )
    ]

    report = summarise(positives, good_negatives())

    assert report.wrong_person_confirmations == 1
    assert report.correct_completions == 29
    assert report.claimable is False
    assert any("wrong name" in reason for reason in report.blocking_reasons)


def test_a_stranger_who_gets_named_is_counted_and_blocks_the_claim() -> None:
    negatives = good_negatives(29) + [
        NegativeTrial(subject="stranger", named_guest_id="guest-sarah", status="CONFIRMED")
    ]

    report = summarise(good_positives(), negatives)

    assert report.wrongly_named == 1
    assert report.correctly_refused == 29
    assert report.claimable is False


def test_a_short_run_names_which_arm_is_short() -> None:
    report = summarise(good_positives(4), good_negatives(31))

    assert report.claimable is False
    assert any("only 4 positive trials" in reason for reason in report.blocking_reasons)
    assert not any("unknown/ambiguous" in reason for reason in report.blocking_reasons)


def test_a_run_without_strangers_cannot_claim_a_refusal_rate() -> None:
    report = summarise(good_positives(40), [])

    assert report.refusal_rate is None
    assert report.claimable is False
    assert any("unmeasured rather than zero" in r for r in report.blocking_reasons)


def test_a_refusal_on_a_positive_trial_is_not_a_wrong_name() -> None:
    """Failing to name an enrolled guest is a miss, not a safety failure."""
    positives = good_positives(29) + [
        PositiveTrial(
            guest_id="guest-sarah", named_guest_id=None, status="AMBIGUOUS", ms_to_confirmed=None
        )
    ]

    report = summarise(positives, good_negatives())

    assert report.correct_completions == 29
    assert report.wrong_person_confirmations == 0
    assert report.total_wrong_names == 0
    assert report.claimable  # a miss does not block the claim
    assert report.completion_rate == pytest.approx(29 / 30)


def test_timing_ignores_trials_that_never_confirmed() -> None:
    positives = [
        PositiveTrial("guest-sarah", "guest-sarah", "CONFIRMED", ms_to_confirmed=500),
        PositiveTrial("guest-sarah", "guest-sarah", "CONFIRMED", ms_to_confirmed=900),
        PositiveTrial("guest-sarah", None, "UNKNOWN", ms_to_confirmed=None),
    ]

    report = summarise(positives, good_negatives(), minimum_per_arm=1)

    assert report.median_ms_to_confirmed == 700
    assert report.slowest_ms_to_confirmed == 900


def test_an_empty_run_claims_nothing() -> None:
    report = summarise([], [])

    assert report.completion_rate is None
    assert report.refusal_rate is None
    assert report.claimable is False


# -- what a human reads ----------------------------------------------------


def test_the_summary_spells_out_why_a_run_is_not_claimable() -> None:
    lines = summary_lines(summarise(good_positives(2), []))
    text = "\n".join(lines)

    assert "NOT claimable" in text
    assert "unmeasured" in text
    assert "only 2 positive trials" in text


def test_the_summary_of_a_clean_run_says_it_is_supported() -> None:
    text = "\n".join(summary_lines(summarise(good_positives(), good_negatives())))

    assert "supports a stated accuracy number" in text
    assert "wrong names:  0" in text
