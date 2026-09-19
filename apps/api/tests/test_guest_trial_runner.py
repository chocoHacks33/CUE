"""Running labelled captures into the identity report's inputs.

The detector and embedder are scripted stand-ins, so these tests establish how
captures are turned into trials and pairs — not anything about recognition.
"""

from __future__ import annotations

import pytest
from conftest import DANIEL, SARAH, KeyedEmbedder, ScriptedDetector, make_detection, make_frame

from cue_api.guests.reference_gallery import GuestReferences, ReferenceGallery, normalise
from cue_api.guests.trial_runner import Capture, run_captures

SARAH_X = 500.0
DANIEL_X = 300.0
STRANGER_X = 700.0
STRANGER = normalise((0.0, 0.0, 1.0, 0.0))
#: Sits between the two enrolled guests, so the margin rule has to decide.
BETWEEN = normalise((0.71, 0.70, 0.0, 0.0))


def gallery_of_two() -> ReferenceGallery:
    return ReferenceGallery(
        version=3,
        guests=(
            GuestReferences("guest-sarah", "Sarah", 1, (SARAH,)),
            GuestReferences("guest-daniel", "Daniel", 1, (DANIEL,)),
        ),
    )


def detector_for(*positions: float) -> ScriptedDetector:
    detector = ScriptedDetector()
    for position in positions:
        detector.queue([make_detection(x=position)])
    return detector


def embedder() -> KeyedEmbedder:
    return KeyedEmbedder(
        vectors={SARAH_X: SARAH, DANIEL_X: DANIEL, STRANGER_X: STRANGER},
        default=BETWEEN,
    )


def capture(label: str, guest_id: str | None) -> Capture:
    """The frame is identical every time; who is in it comes from the detector."""
    return Capture(label=label, frame=make_frame(), guest_id=guest_id)


# -- positives -------------------------------------------------------------


def test_a_matching_positive_capture_is_named_and_paired() -> None:
    results = run_captures(
        [capture("sarah-1.jpg", "guest-sarah")],
        gallery_of_two(),
        detector_for(SARAH_X),
        embedder(),
    )

    assert len(results.positives) == 1
    trial = results.positives[0]
    assert trial.guest_id == "guest-sarah"
    assert trial.named_guest_id == "guest-sarah"
    assert trial.correct
    assert not trial.wrong_person
    assert results.pairs == [results.pairs[0]]
    assert results.pairs[0].same_person is True
    assert results.pairs[0].similarity == pytest.approx(1.0)


def test_a_positive_is_scored_against_the_guest_it_should_be() -> None:
    """Not against whoever scored highest: the honest number for a positive pair
    is how well the system matched the *right* person."""
    detector = detector_for(DANIEL_X)
    results = run_captures(
        # Labelled as Sarah, but the embedding is Daniel's.
        [Capture("mislabelled.jpg", make_frame(), "guest-sarah")],
        gallery_of_two(),
        detector,
        embedder(),
    )

    assert results.positives[0].wrong_person
    assert results.positives[0].named_guest_id == "guest-daniel"
    # Sarah and Daniel are orthogonal, so the pair against Sarah scores ~0.
    assert results.pairs[0].same_person is True
    assert results.pairs[0].similarity == pytest.approx(0.0)


def test_a_capture_labelled_for_an_unenrolled_guest_is_refused() -> None:
    with pytest.raises(ValueError, match="not in the gallery"):
        run_captures(
            [Capture("ghost.jpg", make_frame(), "guest-nobody")],
            gallery_of_two(),
            detector_for(SARAH_X),
            embedder(),
        )


# -- negatives -------------------------------------------------------------


def test_a_stranger_is_refused_and_never_given_a_guest_id() -> None:
    results = run_captures(
        [Capture("unenrolled-1.jpg", make_frame(), None)],
        gallery_of_two(),
        detector_for(STRANGER_X),
        embedder(),
    )

    assert len(results.negatives) == 1
    trial = results.negatives[0]
    assert trial.subject == "unenrolled-1.jpg"
    assert trial.named_guest_id is None
    assert trial.correctly_refused
    assert trial.status == "UNKNOWN"


def test_a_negative_pair_records_the_best_score_any_guest_gave_the_stranger() -> None:
    """That score is the number a threshold has to clear."""
    results = run_captures(
        [Capture("unenrolled-1.jpg", make_frame(), None)],
        gallery_of_two(),
        detector_for(STRANGER_X),
        embedder(),
    )

    assert results.pairs[0].same_person is False
    assert results.pairs[0].similarity == pytest.approx(0.0)


def test_an_ambiguous_stranger_counts_as_correctly_refused() -> None:
    results = run_captures(
        # The default embedding sits between both enrolled guests.
        [Capture("near-pair.jpg", make_frame(), None)],
        gallery_of_two(),
        detector_for(999.0),
        embedder(),
    )

    trial = results.negatives[0]
    assert trial.status == "AMBIGUOUS"
    assert trial.named_guest_id is None
    assert trial.correctly_refused


# -- captures that never became trials -------------------------------------


def test_a_capture_with_no_face_is_skipped_not_counted_as_a_refusal() -> None:
    """Counting it would flatter the refusal rate with photos that never matched."""
    detector = ScriptedDetector()
    detector.queue([])

    results = run_captures(
        [Capture("blurry.jpg", make_frame(), None)], gallery_of_two(), detector, embedder()
    )

    assert results.negatives == []
    assert results.positives == []
    assert results.pairs == []
    assert len(results.skipped) == 1
    assert results.skipped[0].label == "blurry.jpg"
    assert "no face detected" in results.skipped[0].reason


def test_a_capture_that_fails_the_quality_gate_is_skipped_with_its_reasons() -> None:
    detector = ScriptedDetector()
    detector.queue([make_detection(x=SARAH_X, sharpness=0.01, width=40, height=48)])

    results = run_captures(
        [Capture("motion-blur.jpg", make_frame(), "guest-sarah")],
        gallery_of_two(),
        detector,
        embedder(),
    )

    assert results.positives == []
    assert len(results.skipped) == 1
    assert "capture-quality gate" in results.skipped[0].reason
    assert results.skipped[0].reason.count(",") >= 1  # more than one failed check


def test_a_skipped_capture_does_not_stop_the_rest() -> None:
    detector = ScriptedDetector()
    detector.queue([])
    detector.queue([make_detection(x=SARAH_X)])

    results = run_captures(
        [
            Capture("bad.jpg", make_frame(), "guest-sarah"),
            Capture("good.jpg", make_frame(), "guest-sarah"),
        ],
        gallery_of_two(),
        detector,
        embedder(),
    )

    assert len(results.skipped) == 1
    assert len(results.positives) == 1
    assert results.positives[0].correct


# -- the document the harness reads ----------------------------------------


def test_the_document_is_the_shape_evaluate_reads() -> None:
    detector = detector_for(SARAH_X, STRANGER_X)
    results = run_captures(
        [
            Capture("sarah-1.jpg", make_frame(), "guest-sarah"),
            Capture("unenrolled-1.jpg", make_frame(), None),
        ],
        gallery_of_two(),
        detector,
        embedder(),
    )

    document = results.to_document()

    assert set(document) == {"positives", "negatives", "pairs", "skipped"}
    assert document["positives"][0]["guestId"] == "guest-sarah"
    assert document["positives"][0]["namedGuestId"] == "guest-sarah"
    assert document["negatives"][0]["subject"] == "unenrolled-1.jpg"
    assert document["negatives"][0]["namedGuestId"] is None
    assert {pair["samePerson"] for pair in document["pairs"]} == {True, False}


def test_an_empty_gallery_names_nobody_and_records_no_pairs() -> None:
    results = run_captures(
        [Capture("unenrolled-1.jpg", make_frame(), None)],
        ReferenceGallery.empty(),
        detector_for(STRANGER_X),
        embedder(),
    )

    assert results.negatives[0].named_guest_id is None
    assert results.negatives[0].status == "EMPTY_GALLERY"
    # No guest scored it, so there is no similarity to pair.
    assert results.pairs == []
