"""Measuring whether identity actually works, once real trials exist.

Stage 3 asks B to calibrate matching and to test held-out and unenrolled people.
That needs real faces on real cameras, which is a hardware gate. What can be built
first is the measuring instrument, and building it first is the point: deciding
how a number will be judged *before* seeing the number is the only way the
judgement stays honest.

Three refusals are wired in deliberately, because each one is a way a demo could
otherwise claim more than it measured:

1. **A rate is never invented from an empty arm.** No negatives means the
   false-accept rate is `None`, not `0.0`. Zero out of zero is not zero.
2. **One wrong-person confirmation makes a run unclaimable**, however good the
   rest looks. A wrong confident cut is the worst outcome this project can
   produce, so it is not something a good average can absorb.
3. **A threshold is never recommended from a one-sided sample**, for the same
   reason `Calibration.fit` refuses one: a threshold chosen from positives alone
   would accept everybody.

Nothing here decides anything at runtime. It reads trials that a human ran and
reports what they support.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import median

#: The plan's target for each arm of the identity report.
PLAN_MINIMUM_TRIALS = 30

#: Fitting or recommending on fewer than this per arm is not evidence.
MINIMUM_PER_ARM = 5


class InsufficientEvidence(ValueError):
    """The sample cannot support the question being asked of it."""


# -- threshold selection from labelled similarity pairs ---------------------


@dataclass(frozen=True)
class LabelledPair:
    """One scored comparison, and whether it was really the same person."""

    similarity: float
    same_person: bool


@dataclass(frozen=True)
class ThresholdOutcome:
    """What one candidate accept threshold would have done to a labelled set.

    Acceptance is `similarity >= accept_similarity`, the same comparison
    `face_matching.match` makes, so these counts describe production behaviour
    rather than an approximation of it.
    """

    accept_similarity: float
    true_accepts: int
    false_accepts: int
    true_rejects: int
    false_rejects: int

    @property
    def positives(self) -> int:
        return self.true_accepts + self.false_rejects

    @property
    def negatives(self) -> int:
        return self.false_accepts + self.true_rejects

    @property
    def recall(self) -> float | None:
        """Share of real matches accepted. None when there were no positives."""
        return None if not self.positives else self.true_accepts / self.positives

    @property
    def false_accept_rate(self) -> float | None:
        """Share of strangers named. None when there were no negatives.

        Deliberately not 0.0 for an empty arm: a false-accept rate measured on
        nobody is the most misleading number this module could return.
        """
        return None if not self.negatives else self.false_accepts / self.negatives


def evaluate_threshold(
    pairs: Sequence[LabelledPair], accept_similarity: float
) -> ThresholdOutcome:
    true_accepts = false_accepts = true_rejects = false_rejects = 0
    for pair in pairs:
        accepted = pair.similarity >= accept_similarity
        if pair.same_person and accepted:
            true_accepts += 1
        elif pair.same_person:
            false_rejects += 1
        elif accepted:
            false_accepts += 1
        else:
            true_rejects += 1
    return ThresholdOutcome(
        accept_similarity=accept_similarity,
        true_accepts=true_accepts,
        false_accepts=false_accepts,
        true_rejects=true_rejects,
        false_rejects=false_rejects,
    )


def sweep(
    pairs: Sequence[LabelledPair], thresholds: Sequence[float]
) -> list[ThresholdOutcome]:
    return [evaluate_threshold(pairs, threshold) for threshold in sorted(thresholds)]


@dataclass(frozen=True)
class ThresholdRecommendation:
    accept_similarity: float
    outcome: ThresholdOutcome
    positives_measured: int
    negatives_measured: int
    #: Highest similarity any stranger scored. The threshold must clear it.
    highest_negative_similarity: float
    note: str


def recommend_accept_similarity(
    pairs: Sequence[LabelledPair],
    *,
    minimum_per_arm: int = MINIMUM_PER_ARM,
    step: float = 0.001,
) -> ThresholdRecommendation:
    """The lowest threshold that named nobody it should not have.

    Chosen this way round on purpose. Losing a name costs a wide shot; naming the
    wrong person costs the demo. So the search maximises accepted true matches
    *subject to* zero false accepts, rather than balancing the two.
    """
    positives = [pair for pair in pairs if pair.same_person]
    negatives = [pair for pair in pairs if not pair.same_person]
    if len(positives) < minimum_per_arm or len(negatives) < minimum_per_arm:
        raise InsufficientEvidence(
            f"Recommending a threshold needs at least {minimum_per_arm} positive and "
            f"{minimum_per_arm} negative pairs; received {len(positives)} positive "
            f"and {len(negatives)} negative"
        )

    highest_negative = max(pair.similarity for pair in negatives)
    # `>=` acceptance means the threshold must sit strictly above the worst
    # stranger, so one step past it is the lowest safe value.
    threshold = highest_negative + step
    outcome = evaluate_threshold(pairs, threshold)
    rejected = outcome.false_rejects
    note = (
        f"Zero false accepts at {threshold:.4f}. "
        f"{rejected} of {len(positives)} true matches fall below it and would be "
        "refused, which is the trade this project prefers."
    )
    return ThresholdRecommendation(
        accept_similarity=threshold,
        outcome=outcome,
        positives_measured=len(positives),
        negatives_measured=len(negatives),
        highest_negative_similarity=highest_negative,
        note=note,
    )


# -- trial tallies for the identity report ----------------------------------


@dataclass(frozen=True)
class PositiveTrial:
    """A trial where an enrolled, consenting guest was in front of the camera."""

    guest_id: str
    #: Who the system named, or None if it refused to name anyone.
    named_guest_id: str | None
    status: str
    ms_to_confirmed: int | None = None

    @property
    def correct(self) -> bool:
        return self.named_guest_id == self.guest_id

    @property
    def wrong_person(self) -> bool:
        return self.named_guest_id is not None and self.named_guest_id != self.guest_id


@dataclass(frozen=True)
class NegativeTrial:
    """A trial where nobody nameable was in front of the camera."""

    #: A label, never an identity: these people are not enrolled.
    subject: str
    named_guest_id: str | None
    status: str

    @property
    def correctly_refused(self) -> bool:
        return self.named_guest_id is None


@dataclass(frozen=True)
class IdentityReport:
    positives_run: int
    correct_completions: int
    wrong_person_confirmations: int
    negatives_run: int
    correctly_refused: int
    wrongly_named: int
    median_ms_to_confirmed: float | None
    slowest_ms_to_confirmed: int | None
    blocking_reasons: tuple[str, ...] = field(default=())

    @property
    def claimable(self) -> bool:
        """Whether B may state an accuracy number from this run at all."""
        return not self.blocking_reasons

    @property
    def completion_rate(self) -> float | None:
        if not self.positives_run:
            return None
        return self.correct_completions / self.positives_run

    @property
    def refusal_rate(self) -> float | None:
        """None with no negatives. Not 1.0 — refusing nobody proves nothing."""
        if not self.negatives_run:
            return None
        return self.correctly_refused / self.negatives_run

    @property
    def total_wrong_names(self) -> int:
        return self.wrong_person_confirmations + self.wrongly_named


def summarise(
    positives: Sequence[PositiveTrial],
    negatives: Sequence[NegativeTrial],
    *,
    minimum_per_arm: int = PLAN_MINIMUM_TRIALS,
) -> IdentityReport:
    """Tally trials into the shape `b-identity-report.template.md` asks for."""
    correct = sum(1 for trial in positives if trial.correct)
    wrong_person = sum(1 for trial in positives if trial.wrong_person)
    refused = sum(1 for trial in negatives if trial.correctly_refused)
    wrongly_named = len(negatives) - refused

    times = [t.ms_to_confirmed for t in positives if t.ms_to_confirmed is not None]

    reasons: list[str] = []
    if wrong_person or wrongly_named:
        reasons.append(
            f"{wrong_person + wrongly_named} wrong name(s) were produced; the target "
            "is zero, and no completion rate excuses one"
        )
    if len(positives) < minimum_per_arm:
        reasons.append(
            f"only {len(positives)} positive trials; the plan asks for at least "
            f"{minimum_per_arm}"
        )
    if len(negatives) < minimum_per_arm:
        reasons.append(
            f"only {len(negatives)} unknown/ambiguous trials; the plan asks for at "
            f"least {minimum_per_arm}"
        )
    if not negatives:
        reasons.append(
            "no negative trials at all, so the false-accept rate is unmeasured "
            "rather than zero"
        )

    return IdentityReport(
        positives_run=len(positives),
        correct_completions=correct,
        wrong_person_confirmations=wrong_person,
        negatives_run=len(negatives),
        correctly_refused=refused,
        wrongly_named=wrongly_named,
        median_ms_to_confirmed=median(times) if times else None,
        slowest_ms_to_confirmed=max(times) if times else None,
        blocking_reasons=tuple(reasons),
    )


def summary_lines(report: IdentityReport) -> list[str]:
    """Plain lines for the terminal and for pasting into the identity report."""

    def rate(value: float | None) -> str:
        return "unmeasured" if value is None else f"{value * 100:.1f}%"

    lines = [
        f"positives:    {report.correct_completions}/{report.positives_run} correct "
        f"({rate(report.completion_rate)})",
        f"negatives:    {report.correctly_refused}/{report.negatives_run} correctly "
        f"refused ({rate(report.refusal_rate)})",
        f"wrong names:  {report.total_wrong_names}  (target: 0)",
    ]
    if report.median_ms_to_confirmed is not None:
        lines.append(
            f"to CONFIRMED: median {report.median_ms_to_confirmed:.0f} ms, "
            f"slowest {report.slowest_ms_to_confirmed} ms"
        )
    if report.claimable:
        lines.append("verdict:      the run supports a stated accuracy number")
    else:
        lines.append("verdict:      NOT claimable -")
        lines.extend(f"              - {reason}" for reason in report.blocking_reasons)
    return lines
