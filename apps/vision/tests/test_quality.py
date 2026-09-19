from __future__ import annotations

from conftest import make_detection, make_frame

from cue_vision.quality import QualityPolicy, assess


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
