"""Gallery matching with an explicit abstention.

Three outcomes, never two: a candidate, an ambiguous pair the system refuses to
separate, or an unknown face. "Closest enrolled guest" is not an identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cue_vision.calibration import SFACE_COSINE_REFERENCE
from cue_vision.gallery import ReferenceGallery, cosine_similarity
from cue_vision.types import Embedding


class MatchDecision(StrEnum):
    CANDIDATE = "CANDIDATE"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"
    EMPTY_GALLERY = "EMPTY_GALLERY"


@dataclass(frozen=True)
class MatchThresholds:
    #: Below this, the face is not the guest, however close it ranks.
    accept_similarity: float = SFACE_COSINE_REFERENCE
    #: The best guest must beat the runner-up by this much to be separable.
    margin: float = 0.06
    #: Consistent observations on one track before an identity is confirmed.
    confirmations_required: int = 3
    #: A gap longer than this restarts the confirmation count.
    confirmation_window_ms: int = 1200


#: Shared immutable default so callers do not each build their own.
DEFAULT_THRESHOLDS = MatchThresholds()


@dataclass(frozen=True)
class MatchResult:
    decision: MatchDecision
    guest_id: str | None = None
    display_name: str | None = None
    reference_version: int | None = None
    similarity: float | None = None
    runner_up_guest_id: str | None = None
    #: Best minus runner-up. None when there is nobody to be confused with.
    margin: float | None = None


def match(
    embedding: Embedding,
    gallery: ReferenceGallery,
    thresholds: MatchThresholds = DEFAULT_THRESHOLDS,
) -> MatchResult:
    if not gallery.guests:
        return MatchResult(decision=MatchDecision.EMPTY_GALLERY)

    scored: list[tuple[float, str]] = []
    for guest in gallery.guests:
        # A guest's score is their best reference: enrolment angles vary, and
        # averaging them would punish a guest who enrolled from two poses.
        best = max(cosine_similarity(embedding, reference) for reference in guest.embeddings)
        scored.append((best, guest.guest_id))

    scored.sort(key=lambda item: (-item[0], item[1]))
    best_similarity, best_guest_id = scored[0]
    runner_up_similarity, runner_up_guest_id = scored[1] if len(scored) > 1 else (None, None)
    margin = None if runner_up_similarity is None else best_similarity - runner_up_similarity

    if best_similarity < thresholds.accept_similarity:
        return MatchResult(
            decision=MatchDecision.UNKNOWN,
            similarity=best_similarity,
            runner_up_guest_id=runner_up_guest_id,
            margin=margin,
        )

    if margin is not None and margin < thresholds.margin:
        return MatchResult(
            decision=MatchDecision.AMBIGUOUS,
            similarity=best_similarity,
            runner_up_guest_id=runner_up_guest_id,
            margin=margin,
        )

    guest = gallery.get(best_guest_id)
    assert guest is not None  # scored entries come from this gallery
    return MatchResult(
        decision=MatchDecision.CANDIDATE,
        guest_id=guest.guest_id,
        display_name=guest.display_name,
        reference_version=guest.reference_version,
        similarity=best_similarity,
        runner_up_guest_id=runner_up_guest_id,
        margin=margin,
    )
