"""The live loop, driven by fixture frames.

The detector and embedder here are scripted stand-ins, so what these tests
establish is the worker's behaviour, not recognition. Specifically: that it
analyses the freshest frame, that a republish voids the identities the old epoch
supported, that a withdrawal takes effect on the next gallery refresh, and that a
failing backend never stops it looking at frames.
"""

from __future__ import annotations

from conftest import (
    DANIEL,
    SARAH,
    KeyedEmbedder,
    RecordingSink,
    ScriptedDetector,
    make_detection,
    make_video_frame,
)

from cue_api.contracts import CameraId
from cue_api.guests.frame_intake import WorkerClock
from cue_api.guests.observation_pipeline import VisionPipeline
from cue_api.guests.observation_worker import ObservationWorker
from cue_api.guests.reference_gallery import GuestReferences, ReferenceGallery
from cue_api.guests.types import ObservationStatus
from cue_api.media_contracts import LatestFrameSlot, PixelFormat

CLOCK = WorkerClock(
    wall_reference_ms=1_700_000_000_000,
    monotonic_reference_s=1_000.0,
    uncertainty_ms=50,
)
SARAH_AT_X = 500.0


def sarah_gallery(version: int = 7) -> ReferenceGallery:
    return ReferenceGallery(
        version=version,
        guests=(
            GuestReferences(
                guest_id="guest-sarah",
                display_name="Sarah",
                reference_version=2,
                embeddings=(SARAH,),
            ),
            GuestReferences(
                guest_id="guest-daniel",
                display_name="Daniel",
                reference_version=1,
                embeddings=(DANIEL,),
            ),
        ),
    )


def build(gallery: ReferenceGallery | None = None) -> tuple[ObservationWorker, RecordingSink]:
    detector = ScriptedDetector()
    detector.queue([make_detection(x=SARAH_AT_X)])
    embedder = KeyedEmbedder(vectors={SARAH_AT_X: SARAH})
    pipeline = VisionPipeline(
        event_id="hackmit-demo",
        detector=detector,
        embedder=embedder,
        gallery=gallery if gallery is not None else sarah_gallery(),
    )
    sink = RecordingSink(gallery=sarah_gallery())
    worker = ObservationWorker(
        event_id="hackmit-demo",
        pipeline=pipeline,
        sink=sink,
        clock=CLOCK,
    )
    return worker, sink


def feed(
    worker: ObservationWorker,
    count: int,
    *,
    stream_epoch: int = 1,
    start_s: float = 1_000.2,
    step_s: float = 0.2,
):
    """Poll `count` frames with advancing timestamps; return the last observations."""
    latest = []
    for index in range(count):
        slot = LatestFrameSlot(CameraId.GUEST)
        slot.put(
            make_video_frame(
                stream_epoch=stream_epoch,
                sequence=index + 1,
                received_at_monotonic_s=start_s + index * step_s,
            )
        )
        latest = worker.poll([slot])
    return latest


def slot_with(*frames) -> LatestFrameSlot:
    slot = LatestFrameSlot(CameraId.GUEST)
    for frame in frames:
        slot.put(frame)
    return slot


# -- frames ----------------------------------------------------------------


def test_an_empty_slot_produces_nothing() -> None:
    worker, sink = build()

    assert worker.poll([LatestFrameSlot(CameraId.GUEST)]) == []
    assert sink.posted == []
    assert worker.counters.frames_analysed == 0


def test_a_frame_is_analysed_and_the_observation_is_posted() -> None:
    worker, sink = build()

    observations = worker.poll([slot_with(make_video_frame())])

    assert len(observations) == 1
    assert len(sink.posted) == 1
    assert sink.posted[0]["cameraId"] == "CAM-GUEST"
    assert worker.counters.frames_analysed == 1
    assert worker.counters.observations_posted == 1


def test_only_the_freshest_frame_is_analysed() -> None:
    """The slot is capacity-one: latency must not grow behind a slow analyser."""
    worker, sink = build()
    slot = slot_with(
        make_video_frame(sequence=1),
        make_video_frame(sequence=2),
        make_video_frame(sequence=3),
    )

    worker.poll([slot])

    assert worker.counters.frames_analysed == 1
    assert sink.posted[0]["frameSequence"] == 3


def test_a_rejected_frame_is_counted_with_a_reason_and_does_not_raise() -> None:
    worker, sink = build()

    assert worker.poll([slot_with(make_video_frame(mirrored=True))]) == []
    assert worker.counters.frames_rejected == 1
    assert worker.counters.frames_analysed == 0
    assert sink.posted == []
    assert worker.last_rejection is not None
    assert "un-mirror" in worker.last_rejection


def test_a_wrong_format_frame_does_not_stop_the_next_good_one() -> None:
    worker, _ = build()

    worker.poll([slot_with(make_video_frame(pixel_format=PixelFormat.RGBA32))])
    worker.poll([slot_with(make_video_frame(sequence=2))])

    assert worker.counters.frames_rejected == 1
    assert worker.counters.frames_analysed == 1


# -- epochs ----------------------------------------------------------------


def test_the_first_epoch_seen_is_not_treated_as_a_republish() -> None:
    worker, sink = build()

    worker.poll([slot_with(make_video_frame(stream_epoch=4))])

    assert sink.invalidations == []
    assert worker.counters.epochs_invalidated == 0


def test_frames_on_an_unchanged_epoch_never_invalidate() -> None:
    worker, sink = build()

    worker.poll([slot_with(make_video_frame(sequence=1))])
    worker.poll([slot_with(make_video_frame(sequence=2))])
    worker.poll([slot_with(make_video_frame(sequence=3))])

    assert sink.invalidations == []


def test_a_republished_camera_invalidates_once_locally_and_on_the_backend() -> None:
    worker, sink = build()

    worker.poll([slot_with(make_video_frame(stream_epoch=1, sequence=1))])
    worker.poll([slot_with(make_video_frame(stream_epoch=2, sequence=1))])

    assert worker.counters.epochs_invalidated == 1
    assert len(sink.invalidations) == 1
    assert sink.invalidations[0]["cameraId"] == "CAM-GUEST"
    assert sink.invalidations[0]["currentStreamEpoch"] == 2
    assert "republished" in sink.invalidations[0]["reason"]


def test_a_reframe_voids_identity_even_on_an_unchanged_epoch() -> None:
    worker, sink = build()
    worker.poll([slot_with(make_video_frame(stream_epoch=1))])

    worker.reframed("CAM-GUEST", 1, "guest camera reframed")

    assert len(sink.invalidations) == 1
    assert sink.invalidations[0]["currentStreamEpoch"] == 1
    # And the epoch is remembered, so the next frame is not a republish.
    worker.poll([slot_with(make_video_frame(stream_epoch=1, sequence=9))])
    assert len(sink.invalidations) == 1


def test_repeated_agreement_confirms_and_permits_a_named_take() -> None:
    """The positive path: without this, the refusal tests prove nothing."""
    worker, _ = build()

    first = feed(worker, 1)
    confirmed = feed(worker, 3)

    assert first[0].status is ObservationStatus.PROVISIONAL
    assert first[0].usable_for_named_take is False
    assert confirmed[0].status is ObservationStatus.CONFIRMED
    assert confirmed[0].guest_id == "guest-sarah"
    assert confirmed[0].usable_for_named_take is True


def test_a_republished_camera_must_earn_its_confirmation_again() -> None:
    worker, _ = build()
    assert feed(worker, 4)[0].status is ObservationStatus.CONFIRMED

    after = feed(worker, 1, stream_epoch=2, start_s=1_002.0)

    assert after[0].status is ObservationStatus.PROVISIONAL
    assert after[0].usable_for_named_take is False


# -- consent ---------------------------------------------------------------


def test_a_gallery_refresh_drops_a_withdrawn_guest() -> None:
    worker, sink = build()
    assert feed(worker, 4)[0].usable_for_named_take is True

    # Sarah withdraws: the refreshed gallery simply no longer lists her.
    sink.gallery = ReferenceGallery(
        version=8,
        guests=(
            GuestReferences(
                guest_id="guest-daniel",
                display_name="Daniel",
                reference_version=1,
                embeddings=(DANIEL,),
            ),
        ),
    )
    assert worker.refresh_gallery() is True

    after = feed(worker, 1, start_s=1_001.0)

    assert all(o.guest_id != "guest-sarah" for o in after)
    assert all(not o.usable_for_named_take for o in after)


def test_forgetting_a_guest_does_not_wait_for_the_next_refresh() -> None:
    worker, _ = build()
    assert feed(worker, 4)[0].usable_for_named_take is True

    worker.forget_guest("guest-sarah")
    after = feed(worker, 1, start_s=1_001.0)

    assert all(not o.usable_for_named_take for o in after)


def test_a_refresh_counts_and_adopts_the_new_gallery_version() -> None:
    worker, sink = build()
    sink.gallery = sarah_gallery(version=11)

    assert worker.refresh_gallery() is True
    assert worker.pipeline.gallery.version == 11
    assert worker.counters.gallery_refreshes == 1


# -- a backend that is having a bad time -----------------------------------


def test_a_failing_gallery_refresh_keeps_the_gallery_it_had() -> None:
    worker, sink = build()
    sink.fail_gallery = True

    assert worker.refresh_gallery() is False
    assert worker.pipeline.gallery.version == 7
    assert worker.counters.backend_failures == 1
    assert worker.counters.gallery_refreshes == 0


def test_a_failing_post_does_not_stop_the_worker() -> None:
    worker, sink = build()
    sink.fail_post = True

    observations = worker.poll([slot_with(make_video_frame())])

    assert observations  # the analysis still happened
    assert worker.counters.observations_posted == 0
    assert worker.counters.backend_failures == 1
    assert worker.counters.frames_analysed == 1


def test_a_failing_invalidate_still_voids_the_local_evidence() -> None:
    worker, sink = build()
    worker.poll([slot_with(make_video_frame(stream_epoch=1))])
    sink.fail_invalidate = True

    worker.poll([slot_with(make_video_frame(stream_epoch=2))])

    assert worker.counters.epochs_invalidated == 1
    assert worker.counters.backend_failures == 1
    assert sink.invalidations == []
