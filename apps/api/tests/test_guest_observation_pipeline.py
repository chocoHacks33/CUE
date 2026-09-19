from __future__ import annotations

from conftest import (
    BETWEEN_TWO_GUESTS,
    DANIEL,
    SARAH,
    STRANGER,
    KeyedEmbedder,
    ScriptedDetector,
    make_detection,
    make_frame,
)

from cue_api.guests.observation_pipeline import VisionPipeline
from cue_api.guests.reference_gallery import GuestReferences, ReferenceGallery
from cue_api.guests.types import ObservationStatus

FRAME_INTERVAL_MS = 80


def build_pipeline(gallery: ReferenceGallery, embedding=SARAH) -> VisionPipeline:
    detector = ScriptedDetector()
    detector.queue([make_detection()])
    return VisionPipeline(
        event_id="hackmit-demo",
        detector=detector,
        embedder=KeyedEmbedder(vectors={500: embedding}),
        gallery=gallery,
    )


def run_frames(
    pipeline: VisionPipeline,
    count: int,
    *,
    camera_id: str = "CAM-GUEST",
    stream_epoch: int = 1,
    start_ms: int = 1_000_000,
):
    observations = []
    for index in range(count):
        frame = make_frame(
            camera_id=camera_id,
            stream_epoch=stream_epoch,
            sequence=index,
            received_at_ms=start_ms + index * FRAME_INTERVAL_MS,
        )
        observations.extend(pipeline.observe(frame))
    return observations


def test_a_named_take_needs_repeated_agreement(gallery: ReferenceGallery) -> None:
    pipeline = build_pipeline(gallery)

    observations = run_frames(pipeline, 3)

    assert [observation.status for observation in observations] == [
        ObservationStatus.PROVISIONAL,
        ObservationStatus.PROVISIONAL,
        ObservationStatus.CONFIRMED,
    ]
    assert [observation.usable_for_named_take for observation in observations] == [
        False,
        False,
        True,
    ]
    assert observations[-1].guest_id == "guest-sarah"
    assert observations[-1].display_name == "Sarah"


def test_an_unenrolled_person_is_never_named(gallery: ReferenceGallery) -> None:
    pipeline = build_pipeline(gallery, embedding=STRANGER)

    observations = run_frames(pipeline, 5)

    assert {observation.status for observation in observations} == {ObservationStatus.UNKNOWN}
    assert all(observation.guest_id is None for observation in observations)
    assert all(not observation.usable_for_named_take for observation in observations)


def test_two_plausible_guests_produce_an_abstention(gallery: ReferenceGallery) -> None:
    pipeline = build_pipeline(gallery, embedding=BETWEEN_TWO_GUESTS)

    observations = run_frames(pipeline, 4)

    assert {observation.status for observation in observations} == {ObservationStatus.AMBIGUOUS}
    assert all(observation.display_name is None for observation in observations)


def test_an_unreadable_frame_withdraws_the_confirmation(gallery: ReferenceGallery) -> None:
    detector = ScriptedDetector()
    for _ in range(3):
        detector.queue([make_detection()])
    detector.queue([make_detection(sharpness=0.02)])
    pipeline = VisionPipeline(
        event_id="hackmit-demo",
        detector=detector,
        embedder=KeyedEmbedder(vectors={500: SARAH}),
        gallery=gallery,
    )

    observations = run_frames(pipeline, 4)

    assert observations[2].status is ObservationStatus.CONFIRMED
    assert observations[3].status is ObservationStatus.LOW_QUALITY
    assert observations[3].guest_id is None
    assert "motion_blur_or_soft_focus" in observations[3].quality.failed_checks
    assert len(pipeline.ledger) == 0


def test_an_empty_frame_reports_no_face(gallery: ReferenceGallery) -> None:
    detector = ScriptedDetector()
    detector.queue([])
    pipeline = VisionPipeline(
        event_id="hackmit-demo",
        detector=detector,
        embedder=KeyedEmbedder(),
        gallery=gallery,
    )

    observations = run_frames(pipeline, 1)

    assert observations[0].status is ObservationStatus.NO_FACE
    assert observations[0].box is None
    assert observations[0].guest_id is None


def test_a_republished_camera_must_earn_its_confirmation_again(
    gallery: ReferenceGallery,
) -> None:
    pipeline = build_pipeline(gallery)
    run_frames(pipeline, 3)

    pipeline.invalidate_camera("CAM-GUEST", reason="republished with a new webcam")
    after = run_frames(pipeline, 1, stream_epoch=2, start_ms=1_000_400)

    assert after[0].status is ObservationStatus.PROVISIONAL
    assert after[0].usable_for_named_take is False
    assert after[0].stream_epoch == 2


def test_identity_does_not_follow_a_guest_to_another_camera(
    gallery: ReferenceGallery,
) -> None:
    pipeline = build_pipeline(gallery)
    run_frames(pipeline, 3)

    moved = run_frames(pipeline, 1, camera_id="CAM-WIDE", start_ms=1_000_400)

    assert moved[0].camera_id == "CAM-WIDE"
    assert moved[0].status is ObservationStatus.PROVISIONAL
    assert moved[0].usable_for_named_take is False


def test_an_old_seat_does_not_keep_a_name_when_someone_else_sits_down(
    gallery: ReferenceGallery,
) -> None:
    detector = ScriptedDetector()
    for _ in range(4):
        detector.queue([make_detection()])
    embedder = KeyedEmbedder(vectors={500: SARAH})
    pipeline = VisionPipeline(
        event_id="hackmit-demo",
        detector=detector,
        embedder=embedder,
        gallery=gallery,
    )
    run_frames(pipeline, 3)

    # Same chair, same track, different person.
    embedder.vectors[500] = DANIEL
    after = run_frames(pipeline, 1, start_ms=1_000_240)

    assert after[0].guest_id == "guest-daniel"
    assert after[0].status is ObservationStatus.PROVISIONAL
    assert after[0].usable_for_named_take is False


def test_withdrawing_consent_drops_the_live_identity(gallery: ReferenceGallery) -> None:
    pipeline = build_pipeline(gallery)
    run_frames(pipeline, 3)

    remaining = ReferenceGallery(
        version=8,
        guests=tuple(guest for guest in gallery.guests if guest.guest_id != "guest-sarah"),
    )
    pipeline.set_gallery(remaining)
    after = run_frames(pipeline, 1, start_ms=1_000_240)

    assert len(pipeline.ledger) == 0
    assert after[0].status is ObservationStatus.UNKNOWN
    assert after[0].guest_id is None


def test_a_group_shot_reports_every_face_separately(gallery: ReferenceGallery) -> None:
    detector = ScriptedDetector()
    detector.queue([make_detection(x=200), make_detection(x=900)])
    pipeline = VisionPipeline(
        event_id="hackmit-demo",
        detector=detector,
        embedder=KeyedEmbedder(vectors={200: SARAH, 900: DANIEL}),
        gallery=gallery,
    )

    observations = run_frames(pipeline, 1)

    assert {observation.guest_id for observation in observations} == {
        "guest-sarah",
        "guest-daniel",
    }
    assert all(not observation.usable_for_named_take for observation in observations)


def test_an_empty_gallery_yields_unknown_rather_than_a_guess() -> None:
    pipeline = build_pipeline(ReferenceGallery.empty())

    observations = run_frames(pipeline, 3)

    assert {observation.status for observation in observations} == {ObservationStatus.UNKNOWN}


def test_confidence_is_only_reported_for_a_named_subject(gallery: ReferenceGallery) -> None:
    named = run_frames(build_pipeline(gallery), 1)[0]
    unknown = run_frames(build_pipeline(gallery, embedding=STRANGER), 1)[0]

    assert named.calibrated_confidence is not None
    assert unknown.calibrated_confidence is None
    assert unknown.similarity is not None  # the raw score stays as a diagnostic


def test_the_log_record_omits_the_guest_name(gallery: ReferenceGallery) -> None:
    observation = run_frames(build_pipeline(gallery), 3)[-1]

    record = observation.as_log_record()

    assert "display_name" not in record
    assert record["guest_id"] == "guest-sarah"


def test_a_guest_with_no_usable_reference_is_not_in_the_gallery() -> None:
    gallery = ReferenceGallery(
        version=1,
        guests=(
            GuestReferences(
                guest_id="guest-sarah",
                display_name="Sarah",
                reference_version=0,
                embeddings=(),
            ),
        ),
    )
    payload = {
        "galleryVersion": 1,
        "entries": [
            {
                "guestId": "guest-sarah",
                "displayName": "Sarah",
                "referenceVersion": 0,
                "embeddings": [],
            }
        ],
    }

    assert len(ReferenceGallery.from_payload(payload)) == 0
    assert len(gallery) == 1  # the dataclass itself does not filter; the loader does
