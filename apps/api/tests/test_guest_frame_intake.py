"""The seam between A's decoded frames and B's analysis.

These tests are about refusal and about time. A frame that is rotated, mirrored or
in the wrong pixel format is dropped with a reason naming who can fix it, because
a detector fed such a frame returns plausible boxes with wrong geometry rather
than failing loudly.
"""

from __future__ import annotations

import pytest
from conftest import make_video_frame

from cue_api.contracts import CameraId
from cue_api.guests.frame_intake import (
    FramePayload,
    FrameRejected,
    WorkerClock,
    adapt,
)
from cue_api.media_contracts import PixelFormat

#: Wall time 1_700_000_000_000 ms was sampled when the monotonic clock read 1_000 s.
CLOCK = WorkerClock(
    wall_reference_ms=1_700_000_000_000,
    monotonic_reference_s=1_000.0,
    uncertainty_ms=50,
)


def test_an_upright_bgr_frame_is_accepted_unchanged() -> None:
    adapted = adapt(
        make_video_frame(stream_epoch=3, sequence=17, width=640, height=360), CLOCK
    )

    assert adapted.camera_id == "CAM-GUEST"
    assert adapted.stream_epoch == 3
    assert adapted.sequence == 17
    assert adapted.width == 640
    assert adapted.height == 360
    assert adapted.orientation_degrees == 0
    assert adapted.pixel_format == "BGR24"


def test_the_monotonic_clock_is_mapped_onto_backend_wall_time() -> None:
    # 1_002.5 s monotonic is 2.5 s after the anchor, so 2500 ms after the anchor.
    adapted = adapt(make_video_frame(received_at_monotonic_s=1_002.5), CLOCK)

    assert adapted.received_at_ms == 1_700_000_002_500


def test_the_capture_time_is_mapped_on_the_same_anchor() -> None:
    adapted = adapt(
        make_video_frame(received_at_monotonic_s=1_002.5, capture_time_s=1_002.46),
        CLOCK,
    )

    assert adapted.captured_at_ms == 1_700_000_002_460
    # Capture must not appear to happen after arrival.
    assert adapted.captured_at_ms < adapted.received_at_ms


def test_a_frame_without_a_capture_time_stays_null() -> None:
    adapted = adapt(make_video_frame(capture_time_s=None), CLOCK)

    assert adapted.captured_at_ms is None


def test_a_rotated_frame_is_refused_rather_than_rotated_here() -> None:
    with pytest.raises(FrameRejected, match="rotate it upright"):
        adapt(make_video_frame(orientation_degrees=90), CLOCK)


def test_a_mirrored_frame_is_refused() -> None:
    with pytest.raises(FrameRejected, match="un-mirror"):
        adapt(make_video_frame(mirrored=True), CLOCK)


def test_a_frame_in_the_wrong_pixel_format_is_refused() -> None:
    with pytest.raises(FrameRejected, match="does not convert"):
        adapt(make_video_frame(pixel_format=PixelFormat.RGB24), CLOCK)


def test_every_refusal_names_the_camera() -> None:
    with pytest.raises(FrameRejected, match="CAM-WIDE"):
        adapt(make_video_frame(camera_id=CameraId.WIDE, mirrored=True), CLOCK)


def test_the_payload_keeps_the_stride_so_the_adapter_need_not_guess() -> None:
    frame = make_video_frame(width=8, height=4, stride_bytes=32)
    adapted = adapt(frame, CLOCK)

    assert isinstance(adapted.image, FramePayload)
    assert adapted.image.stride_bytes == 32
    assert adapted.image.pixel_format is PixelFormat.BGR24
    assert len(adapted.image.data) == 32 * 4


def test_a_padded_stride_survives_the_handover() -> None:
    # 8 BGR pixels pack into 24 bytes; A may still pad the row to 32.
    frame = make_video_frame(width=8, height=4, stride_bytes=32)

    assert adapt(frame, CLOCK).image.stride_bytes > 8 * 3


def test_sampling_the_clock_anchors_both_readings() -> None:
    clock = WorkerClock.sample(uncertainty_ms=25)

    assert clock.uncertainty_ms == 25
    assert clock.wall_reference_ms > 0
    # The anchor maps to itself.
    assert clock.to_wall_ms(clock.monotonic_reference_s) == clock.wall_reference_ms


def test_a_negative_clock_uncertainty_is_refused() -> None:
    with pytest.raises(ValueError, match="uncertainty"):
        WorkerClock(wall_reference_ms=0, monotonic_reference_s=0.0, uncertainty_ms=-1)


def test_an_unpadded_payload_is_returned_untouched() -> None:
    # 4 BGR pixels pack into 12 bytes with no padding.
    payload = FramePayload(
        data=bytes(range(24)), width=4, height=2, stride_bytes=12,
        pixel_format=PixelFormat.BGR24,
    )

    assert payload.row_bytes == 12
    assert payload.packed_bytes() == bytes(range(24))


def test_row_padding_is_stripped_row_by_row() -> None:
    """The arithmetic most likely to be wrong, checked without numpy."""
    # Two rows of 2 BGR pixels (6 bytes) padded to an 8-byte stride.
    row_one = bytes([1, 2, 3, 4, 5, 6]) + bytes([0xEE, 0xEE])
    row_two = bytes([7, 8, 9, 10, 11, 12]) + bytes([0xEE, 0xEE])
    payload = FramePayload(
        data=row_one + row_two, width=2, height=2, stride_bytes=8,
        pixel_format=PixelFormat.BGR24,
    )

    packed = payload.packed_bytes()

    assert payload.row_bytes == 6
    assert packed == bytes([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
    assert 0xEE not in packed
    # Exactly width * height * 3 bytes, which is what the reshape assumes.
    assert len(packed) == 2 * 2 * 3


def test_a_payload_whose_length_contradicts_its_stride_is_refused() -> None:
    with pytest.raises(ValueError, match="stride_bytes"):
        FramePayload(
            data=bytes(10), width=2, height=2, stride_bytes=8,
            pixel_format=PixelFormat.BGR24,
        )


def test_a_padded_frame_from_a_survives_the_whole_seam() -> None:
    adapted = adapt(make_video_frame(width=4, height=3, stride_bytes=16), CLOCK)

    assert len(adapted.image.packed_bytes()) == 4 * 3 * 3
