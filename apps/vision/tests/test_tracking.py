from __future__ import annotations

from conftest import make_detection

from cue_vision.tracking import LocalTracker


def test_the_same_face_keeps_its_track_across_frames() -> None:
    tracker = LocalTracker()

    first = tracker.assign("CAM-GUEST", 1, [make_detection(x=500)], 1000)
    drifted = tracker.assign("CAM-GUEST", 1, [make_detection(x=520)], 1080)

    assert first == drifted


def test_two_faces_get_separate_tracks() -> None:
    tracker = LocalTracker()

    keys = tracker.assign("CAM-GUEST", 1, [make_detection(x=200), make_detection(x=900)], 1000)

    assert len(set(keys)) == 2


def test_a_face_that_jumps_across_the_frame_starts_a_new_track() -> None:
    tracker = LocalTracker()

    first = tracker.assign("CAM-GUEST", 1, [make_detection(x=100)], 1000)
    jumped = tracker.assign("CAM-GUEST", 1, [make_detection(x=1000)], 1080)

    assert first != jumped


def test_a_new_epoch_never_reuses_a_track_key() -> None:
    tracker = LocalTracker()

    before = tracker.assign("CAM-GUEST", 1, [make_detection(x=500)], 1000)
    after = tracker.assign("CAM-GUEST", 2, [make_detection(x=500)], 1080)

    assert before != after
    assert after[0].startswith("CAM-GUEST:2:")


def test_a_track_expires_once_the_face_is_gone() -> None:
    tracker = LocalTracker(track_ttl_ms=500)
    tracker.assign("CAM-GUEST", 1, [make_detection(x=500)], 1000)

    assert tracker.expired_keys("CAM-GUEST", 1, 1600) != []

    resumed = tracker.assign("CAM-GUEST", 1, [make_detection(x=500)], 1700)

    assert resumed[0].endswith("face-2")


def test_resetting_a_camera_leaves_the_others_alone() -> None:
    tracker = LocalTracker()
    guest = tracker.assign("CAM-GUEST", 1, [make_detection(x=500)], 1000)
    wide = tracker.assign("CAM-WIDE", 1, [make_detection(x=500)], 1000)

    tracker.reset_camera("CAM-GUEST")

    assert tracker.assign("CAM-GUEST", 1, [make_detection(x=500)], 1080) != guest
    assert tracker.assign("CAM-WIDE", 1, [make_detection(x=500)], 1080) == wide
