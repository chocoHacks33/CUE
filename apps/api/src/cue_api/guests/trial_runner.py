"""Turning labelled captures into the numbers the identity report asks for.

Stage 3 prep built the instrument that judges trials. This runs them: labelled
frames in, `LabelledPair`s and trial rows out, ready for
`identity_eval.summarise` and `Calibration.fit`.

It exists so that the moment real captures are on disk, producing the identity
report is a command rather than a coding job — and so the labelling is decided by
the filenames a human chose, not by anything this code infers.

Two things it refuses to do:

- **A capture with no detectable face is not a trial result.** It is recorded as a
  skipped capture with a reason. Counting it as a refusal would flatter the
  refusal rate with photographs that never reached the matcher.
- **It never invents a label.** A positive capture must name the guest it is
  supposed to be; a negative names only a subject label, never an identity,
  because those people are not enrolled and must not be given a guest ID.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from cue_api.guests.capture_quality import DEFAULT_QUALITY_POLICY, QualityPolicy, assess
from cue_api.guests.face_matching import (
    DEFAULT_THRESHOLDS,
    MatchDecision,
    MatchThresholds,
    match,
)
from cue_api.guests.identity_eval import LabelledPair, NegativeTrial, PositiveTrial
from cue_api.guests.reference_gallery import ReferenceGallery, cosine_similarity, normalise
from cue_api.guests.types import (
    DecodedFrame,
    Embedding,
    FaceDetection,
    ObservationStatus,
)


def status_for(decision: MatchDecision) -> ObservationStatus:
    """A match decision as the status the rest of the system speaks.

    `MatchDecision` is the matcher's internal vocabulary; `ObservationStatus` is
    what the contract, the producer UI and the identity report use. Leaking
    CANDIDATE or EMPTY_GALLERY into a trials document would put words in the
    report that appear nowhere else in the system.

    A single frame maps CANDIDATE to PROVISIONAL, never CONFIRMED, because one
    frame is not an identity — the same rule the ledger enforces live.
    """
    if decision is MatchDecision.AMBIGUOUS:
        return ObservationStatus.AMBIGUOUS
    if decision is MatchDecision.CANDIDATE:
        return ObservationStatus.PROVISIONAL
    # UNKNOWN and EMPTY_GALLERY both mean "nobody was named", which is what
    # `observation_pipeline` reports as UNKNOWN too.
    return ObservationStatus.UNKNOWN


class FaceDetector(Protocol):
    name: str
    version: str

    def detect(self, frame: DecodedFrame) -> Sequence[FaceDetection]: ...


class FaceEmbedder(Protocol):
    name: str
    version: str

    def embed(self, frame: DecodedFrame, detection: FaceDetection) -> Embedding: ...


@dataclass(frozen=True)
class Capture:
    """One labelled photograph, already decoded.

    `guest_id` is set for a capture of an enrolled guest and None for someone who
    never enrolled. `label` is how the human identified the file, and is carried
    through only so a skipped capture can be traced back to it.
    """

    label: str
    frame: DecodedFrame
    guest_id: str | None


@dataclass(frozen=True)
class SkippedCapture:
    label: str
    reason: str


@dataclass
class TrialResults:
    positives: list[PositiveTrial] = field(default_factory=list)
    negatives: list[NegativeTrial] = field(default_factory=list)
    #: Similarity against the *correct* guest for positives, and against the best
    #: scoring guest for negatives. What `fit()` and the threshold sweep consume.
    pairs: list[LabelledPair] = field(default_factory=list)
    skipped: list[SkippedCapture] = field(default_factory=list)

    def to_document(self) -> dict[str, object]:
        """The JSON shape `cue-guests evaluate` reads."""
        return {
            "positives": [
                {
                    "guestId": trial.guest_id,
                    "namedGuestId": trial.named_guest_id,
                    "status": trial.status,
                    "msToConfirmed": trial.ms_to_confirmed,
                }
                for trial in self.positives
            ],
            "negatives": [
                {
                    "subject": trial.subject,
                    "namedGuestId": trial.named_guest_id,
                    "status": trial.status,
                }
                for trial in self.negatives
            ],
            "pairs": [
                {"similarity": pair.similarity, "samePerson": pair.same_person}
                for pair in self.pairs
            ],
            "skipped": [
                {"label": skip.label, "reason": skip.reason} for skip in self.skipped
            ],
        }


def run_captures(
    captures: Sequence[Capture],
    gallery: ReferenceGallery,
    detector: FaceDetector,
    embedder: FaceEmbedder,
    *,
    thresholds: MatchThresholds = DEFAULT_THRESHOLDS,
    quality_policy: QualityPolicy = DEFAULT_QUALITY_POLICY,
) -> TrialResults:
    """Score every capture once, as a single-frame trial.

    Single-frame on purpose: this measures the *matcher*, not the confirmation
    ledger. Whether repeated agreement confirms is already covered by the pipeline
    tests, and mixing the two here would hide which one a failure came from.
    """
    # Validate every label first: discovering a bad one after scoring fifty
    # captures through a real model would throw away all of that work.
    for capture in captures:
        if capture.guest_id is not None and gallery.get(capture.guest_id) is None:
            raise ValueError(
                f"{capture.label} is labelled as {capture.guest_id}, who is not in the "
                "gallery; enrol them first or relabel the capture"
            )

    results = TrialResults()

    for capture in captures:
        detections = detector.detect(capture.frame)
        if not detections:
            results.skipped.append(SkippedCapture(capture.label, "no face detected"))
            continue

        detection = max(detections, key=lambda found: found.score)
        verdict = assess(capture.frame, detection, quality_policy)
        if not verdict.passed:
            results.skipped.append(
                SkippedCapture(
                    capture.label,
                    "failed the capture-quality gate: " + ", ".join(verdict.failed_checks),
                )
            )
            continue

        embedding = normalise(embedder.embed(capture.frame, detection))
        outcome = match(embedding, gallery, thresholds)
        named = outcome.guest_id if outcome.decision is MatchDecision.CANDIDATE else None
        status = status_for(outcome.decision).value

        if capture.guest_id is not None:
            results.positives.append(
                PositiveTrial(
                    guest_id=capture.guest_id,
                    named_guest_id=named,
                    status=status,
                    ms_to_confirmed=None,
                )
            )
            results.pairs.append(
                LabelledPair(
                    similarity=_similarity_against(embedding, gallery, capture.guest_id),
                    same_person=True,
                )
            )
        else:
            results.negatives.append(
                NegativeTrial(
                    subject=capture.label,
                    named_guest_id=named,
                    status=status,
                )
            )
            if outcome.similarity is not None:
                # The best score any enrolled guest gave this stranger: the number
                # a threshold has to clear.
                results.pairs.append(
                    LabelledPair(similarity=outcome.similarity, same_person=False)
                )

    return results


def _similarity_against(
    embedding: Embedding, gallery: ReferenceGallery, guest_id: str
) -> float:
    """Score against the guest this capture is *supposed* to be.

    Not against the best-scoring guest: for a positive pair the honest number is
    how well the system matched the right person, even when somebody else scored
    higher.
    """
    guest = gallery.get(guest_id)
    if guest is None:  # pragma: no cover - run_captures validates labels up front
        raise ValueError(f"{guest_id} is not in the gallery")
    return max(cosine_similarity(embedding, reference) for reference in guest.embeddings)
