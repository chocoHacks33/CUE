from cue_api.camera_health import CameraHealthTracker


def test_health_keeps_transport_and_visual_quality_separate() -> None:
    tracker = CameraHealthTracker()
    tracker.update_transport(
        connected=True,
        publishing=True,
        receiving=True,
        renderable=True,
        visually_usable=False,
        warnings=("face_too_small",),
    )
    tracker.observe_frame(1, 100)

    health = tracker.snapshot(200)
    assert health.decoding is True
    assert health.renderable is True
    assert health.visually_usable is False
    assert health.warnings == ("face_too_small",)


def test_stall_requires_two_seconds_of_continuous_progress_to_recover() -> None:
    tracker = CameraHealthTracker(stall_after_ms=1_000, recover_after_ms=2_000)
    tracker.update_transport(
        connected=True,
        publishing=True,
        receiving=True,
        renderable=True,
        visually_usable=True,
    )
    tracker.observe_frame(1, 0)
    assert tracker.snapshot(1_001).stalled is True

    tracker.observe_frame(2, 1_100)
    assert tracker.snapshot(1_100).recovering is True
    tracker.observe_frame(3, 1_900)
    tracker.observe_frame(4, 2_700)
    assert tracker.snapshot(2_700).stalled is True
    tracker.observe_frame(5, 3_200)

    recovered = tracker.snapshot(3_200)
    assert recovered.stalled is False
    assert recovered.decoding is True
    assert recovered.renderable is True


def test_duplicate_frame_sequence_does_not_fake_progress() -> None:
    tracker = CameraHealthTracker()
    tracker.update_transport(
        connected=True,
        publishing=True,
        receiving=True,
        renderable=True,
        visually_usable=True,
    )
    assert tracker.observe_frame(7, 100) is True
    assert tracker.observe_frame(7, 900) is False
    assert tracker.snapshot(1_101).stalled is True
