"""Where the capture gate starts refusing, condition by condition.

Stage 4 asks B to vary seats, angles and lighting. Seats and cameras are already
covered by the pipeline tests — an old seat loses its name, and identity never
follows a guest to another camera. What was missing is the **envelope**: at what
point does a dim room, a blown highlight, motion blur or distance stop being
usable?

This sweeps each condition one axis at a time and records the boundary, so that
when real captures exist on the Mac somebody can compare a measured frame against
a written expectation instead of guessing whether a refusal was correct.

Every number here is a **threshold this project chose**, not a measured property of
any camera. `DEFAULT_QUALITY_POLICY` was set before anyone looked at a real webcam
frame, and the sweep exists partly to make retuning it a visible, deliberate
change rather than a quiet one.
"""

from __future__ import annotations

import pytest
from conftest import make_detection, make_frame

from cue_api.guests.capture_quality import DEFAULT_QUALITY_POLICY, assess

POLICY = DEFAULT_QUALITY_POLICY


def passes(**overrides) -> bool:
    return assess(make_frame(), make_detection(**overrides), POLICY).passed


def checks(**overrides) -> tuple[str, ...]:
    return assess(make_frame(), make_detection(**overrides), POLICY).failed_checks


# -- lighting --------------------------------------------------------------


@pytest.mark.parametrize(
    ("brightness", "usable"),
    [
        (0.02, False),  # a dark room with the lights off
        (0.15, False),  # dim, below the floor
        (0.20, True),   # exactly the floor
        (0.55, True),   # the middle of the range
        (0.92, True),   # exactly the ceiling
        (0.97, False),  # blown out by a window or a key light
    ],
)
def test_the_usable_brightness_band(brightness: float, usable: bool) -> None:
    assert passes(brightness=brightness) is usable


def test_both_ends_of_the_brightness_band_say_which_way_it_failed() -> None:
    """"Too dark" and "blown out" need different fixes, so they are named apart."""
    assert "underexposed" in checks(brightness=0.02)
    assert "overexposed" in checks(brightness=0.99)
    # And never both at once.
    assert "overexposed" not in checks(brightness=0.02)
    assert "underexposed" not in checks(brightness=0.99)


def test_the_band_edges_match_the_policy_not_a_guess() -> None:
    assert passes(brightness=POLICY.min_brightness) is True
    assert passes(brightness=POLICY.min_brightness - 0.01) is False
    assert passes(brightness=POLICY.max_brightness) is True
    assert passes(brightness=POLICY.max_brightness + 0.01) is False


# -- motion and focus -----------------------------------------------------


@pytest.mark.parametrize(
    ("sharpness", "usable"),
    [
        (0.01, False),  # panned camera, or a guest turning fast
        (0.24, False),
        (0.25, True),   # exactly the floor
        (0.80, True),
    ],
)
def test_the_usable_sharpness_band(sharpness: float, usable: bool) -> None:
    assert passes(sharpness=sharpness) is usable


def test_motion_blur_is_refused_rather_than_matched_weakly() -> None:
    """The whole point of the gate: a blurry face is not a cheaper match."""
    verdict = assess(make_frame(), make_detection(sharpness=0.02), POLICY)

    assert verdict.passed is False
    assert verdict.failed_checks


# -- distance -------------------------------------------------------------


@pytest.mark.parametrize(
    ("width", "usable"),
    [
        (40, False),   # across the room
        (100, False),  # still short of the floor on a 1280-wide frame
        (103, True),   # 0.08 of the frame width, the floor
        (200, True),   # a comfortable close-up
    ],
)
def test_the_usable_face_size_band(width: float, usable: bool) -> None:
    assert passes(width=width, height=width * 1.2) is usable


def test_the_size_floor_is_a_ratio_of_the_frame_not_a_pixel_count() -> None:
    """So the gate behaves the same when A changes capture resolution."""
    frame_width = make_frame().width
    floor_pixels = POLICY.min_face_width_ratio * frame_width

    assert passes(width=floor_pixels + 1, height=floor_pixels * 1.2) is True
    assert passes(width=floor_pixels - 1, height=floor_pixels * 1.2) is False


# -- framing and angle ----------------------------------------------------


@pytest.mark.parametrize(
    ("x", "usable"),
    [
        (-120, False),  # guest leaning out of shot
        (-20, False),   # clipped at the edge
        (500, True),    # centred
        (1180, False),  # clipped at the other edge
    ],
)
def test_a_face_cut_by_the_frame_edge_is_refused(x: float, usable: bool) -> None:
    assert passes(x=x) is usable


def test_a_weak_detection_is_refused_however_well_lit() -> None:
    """A low detector score usually means an angle the model cannot read."""
    assert passes(score=0.40, brightness=0.55, sharpness=0.9) is False
    assert passes(score=POLICY.min_detector_score, brightness=0.55, sharpness=0.9) is True


# -- combinations ---------------------------------------------------------


def test_every_failing_condition_is_named_not_just_the_first() -> None:
    """An operator fixing one problem should not discover two more one at a time."""
    failed = checks(brightness=0.03, sharpness=0.01, width=40, height=48, score=0.3)

    assert len(failed) >= 3


def test_conditions_that_each_pass_alone_still_pass_together() -> None:
    """The gate must not reject a frame merely for being near several edges."""
    assert passes(
        brightness=POLICY.min_brightness,
        sharpness=POLICY.min_sharpness,
        score=POLICY.min_detector_score,
        width=200,
        height=240,
    ) is True


def test_a_single_bad_axis_is_enough_to_refuse() -> None:
    """Good lighting does not buy a pass for a blurred face."""
    assert passes(brightness=0.55, sharpness=0.9, score=0.95) is True
    assert passes(brightness=0.55, sharpness=0.01, score=0.95) is False


def test_thresholds_are_policy_so_retuning_is_a_visible_change() -> None:
    """These numbers are choices. Changing them should take an argument, not a patch."""
    assert POLICY.min_face_width_ratio == 0.08
    assert POLICY.min_detector_score == 0.70
    assert POLICY.min_sharpness == 0.25
    assert POLICY.min_brightness == 0.20
    assert POLICY.max_brightness == 0.92
