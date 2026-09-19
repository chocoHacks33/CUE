"""Capture-quality gate tests for cue_api.vision.quality.

The frames and detections here are deterministic stand-ins, not recognition.
They cover the policy around the models; real YuNet/SFace behaviour is only
established by the Mac runtime check in `docs/results/b-identity-report.template.md`.
"""

from __future__ import annotations

from cue_api.vision.quality import QualityPolicy, assess
from cue_api.vision.types import DecodedFrame, FaceDetection, PixelBox

FRAME_WIDTH = 1280
FRAME_HEIGHT = 720


def make_frame(
    *,
    camera_id: str = "CAM-GUEST",
    stream_epoch: int = 1,
    sequence: int = 0,
    received_at_ms: int = 1_000_000,
) -> DecodedFrame:
    return DecodedFrame(
        camera_id=camera_id,
        stream_epoch=stream_epoch,
        sequence=sequence,
        width=FRAME_WIDTH,
        height=FRAME_HEIGHT,
        received_at_ms=received_at_ms,
        captured_at_ms=received_at_ms - 40,
    )


def make_detection(
    *,
    x: float = 500,
    y: float = 200,
    width: float = 200,
    height: float = 240,
    score: float = 0.95,
    sharpness: float = 0.8,
    brightness: float = 0.55,
) -> FaceDetection:
    return FaceDetection(
        box=PixelBox(x=x, y=y, width=width, height=height),
        score=score,
        sharpness=sharpness,
        brightness=brightness,
        landmarks=tuple((x + width / 2, y + height / 2) for _ in range(5)),
    )


def test_a_well_framed_face_passes() -> None:
    verdict = assess(make_frame(), make_detection())

    assert verdict.passed
    assert verdict.failed_checks == ()
    assert 0.0 <= verdict.score <= 1.0


def test_a_distant_face_is_refused_by_size() -> None:
    verdict = assess(make_frame(), make_detection(width=60, height=72))

    assert not verdict.passed
    assert "face_too_small" in verdict.failed_checks


def test_motion_blur_is_refused_rather_than_matched_weakly() -> None:
    verdict = assess(make_frame(), make_detection(sharpness=0.05))

    assert not verdict.passed
    assert "motion_blur_or_soft_focus" in verdict.failed_checks


def test_a_dark_face_is_refused() -> None:
    verdict = assess(make_frame(), make_detection(brightness=0.05))

    assert not verdict.passed
    assert "underexposed" in verdict.failed_checks


def test_a_face_cut_by_the_frame_edge_is_refused() -> None:
    verdict = assess(make_frame(), make_detection(x=-80))

    assert not verdict.passed
    assert "face_cropped_by_frame_edge" in verdict.failed_checks


def test_a_weak_detection_is_refused() -> None:
    verdict = assess(make_frame(), make_detection(score=0.4))

    assert not verdict.passed
    assert "weak_detection" in verdict.failed_checks


def test_every_failure_is_named() -> None:
    verdict = assess(make_frame(), make_detection(width=40, height=48, sharpness=0.01))

    assert not verdict.passed
    assert len(verdict.failed_checks) >= 2


def test_thresholds_are_policy_not_constants() -> None:
    detection = make_detection(width=90, height=108)
    strict = assess(make_frame(), detection, QualityPolicy(min_face_width_ratio=0.2))
    lenient = assess(make_frame(), detection, QualityPolicy(min_face_width_ratio=0.05))

    assert not strict.passed
    assert lenient.passed
