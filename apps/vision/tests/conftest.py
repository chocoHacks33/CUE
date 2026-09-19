"""Deterministic stand-ins for the OpenCV models.

These are fixtures, not recognition. Every test that uses them is testing the
policy around the models: today, the capture-quality gate and the model file
registry. Real YuNet/SFace behaviour is only established by the Mac runtime
check in `docs/results/b-identity-report.template.md`.
"""

from __future__ import annotations

import pytest

from cue_vision.gallery import GuestReferences, ReferenceGallery, normalise
from cue_vision.types import DecodedFrame, FaceDetection, PixelBox

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


SARAH = normalise((1.0, 0.0, 0.0, 0.0))
DANIEL = normalise((0.0, 1.0, 0.0, 0.0))


@pytest.fixture
def gallery() -> ReferenceGallery:
    return ReferenceGallery(
        version=7,
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
