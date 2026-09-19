from __future__ import annotations

from conftest import BETWEEN_TWO_GUESTS, DANIEL, SARAH, STRANGER

from cue_vision.gallery import GuestReferences, ReferenceGallery, normalise
from cue_vision.matching import MatchDecision, MatchThresholds, match


def test_a_clear_match_names_the_guest(gallery: ReferenceGallery) -> None:
    result = match(SARAH, gallery)

    assert result.decision is MatchDecision.CANDIDATE
    assert result.guest_id == "guest-sarah"
    assert result.reference_version == 2
    assert result.runner_up_guest_id == "guest-daniel"


def test_an_unenrolled_face_stays_unknown(gallery: ReferenceGallery) -> None:
    result = match(STRANGER, gallery)

    assert result.decision is MatchDecision.UNKNOWN
    assert result.guest_id is None
    assert result.display_name is None


def test_two_plausible_guests_produce_an_abstention(gallery: ReferenceGallery) -> None:
    result = match(BETWEEN_TWO_GUESTS, gallery)

    assert result.decision is MatchDecision.AMBIGUOUS
    assert result.guest_id is None
    assert result.margin is not None and result.margin < MatchThresholds().margin


def test_an_empty_gallery_never_invents_a_name() -> None:
    result = match(SARAH, ReferenceGallery.empty())

    assert result.decision is MatchDecision.EMPTY_GALLERY
    assert result.guest_id is None


def test_a_guest_is_scored_on_their_best_reference() -> None:
    profile = normalise((0.6, 0.8, 0.0, 0.0))
    gallery = ReferenceGallery(
        version=1,
        guests=(
            GuestReferences(
                guest_id="guest-sarah",
                display_name="Sarah",
                reference_version=2,
                # Two enrolment angles: averaging them would punish the guest
                # who sensibly enrolled from more than one pose.
                embeddings=(SARAH, profile),
            ),
        ),
    )

    result = match(profile, gallery)

    assert result.decision is MatchDecision.CANDIDATE
    assert result.similarity is not None and result.similarity > 0.99


def test_a_single_enrolled_guest_has_no_runner_up() -> None:
    gallery = ReferenceGallery(
        version=1,
        guests=(
            GuestReferences(
                guest_id="guest-daniel",
                display_name="Daniel",
                reference_version=1,
                embeddings=(DANIEL,),
            ),
        ),
    )

    result = match(DANIEL, gallery)

    assert result.decision is MatchDecision.CANDIDATE
    assert result.runner_up_guest_id is None
    assert result.margin is None


def test_the_accept_threshold_is_tunable(gallery: ReferenceGallery) -> None:
    borderline = normalise((0.5, 0.0, 0.87, 0.0))

    lenient = match(borderline, gallery, MatchThresholds(accept_similarity=0.3))
    strict = match(borderline, gallery, MatchThresholds(accept_similarity=0.8))

    assert lenient.decision is MatchDecision.CANDIDATE
    assert strict.decision is MatchDecision.UNKNOWN
