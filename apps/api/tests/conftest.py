"""Deterministic stand-ins for the OpenCV models.

These are fixtures, not recognition. Every test that uses them is testing the
policy around the models: quality gating, abstention, confirmation and expiry.
Real YuNet/SFace behaviour is only established by the Mac runtime check in
`docs/results/b-identity-report.template.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from cue_api.guests.reference_gallery import GuestReferences, ReferenceGallery, normalise
from cue_api.guests.types import DecodedFrame, Embedding, FaceDetection, PixelBox

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


@dataclass
class ScriptedDetector:
    """Returns whatever the test queued, one list per frame."""

    name: str = "fixture-detector"
    version: str = "test"
    script: list[list[FaceDetection]] = field(default_factory=list)
    calls: int = 0

    def queue(self, detections: list[FaceDetection]) -> None:
        self.script.append(detections)

    def detect(self, frame: DecodedFrame) -> list[FaceDetection]:
        if self.calls < len(self.script):
            detections = self.script[self.calls]
        else:
            detections = self.script[-1] if self.script else []
        self.calls += 1
        return list(detections)


@dataclass
class KeyedEmbedder:
    """Maps a detection to a fixed embedding chosen by the test.

    The key is the detection's x position, so a test can move a face and keep
    its embedding, or keep the position and change who is in the chair.
    """

    name: str = "fixture-embedder"
    version: str = "test"
    dimension: int = 4
    vectors: dict[float, Embedding] = field(default_factory=dict)
    default: Embedding = (0.0, 0.0, 0.0, 1.0)

    def embed(self, frame: DecodedFrame, detection: FaceDetection) -> Embedding:
        return self.vectors.get(detection.box.x, self.default)


SARAH = normalise((1.0, 0.0, 0.0, 0.0))
DANIEL = normalise((0.0, 1.0, 0.0, 0.0))
#: Sits between the two enrolled guests: above threshold for both, separable
#: from neither, so the margin rule has to decide rather than the threshold.
BETWEEN_TWO_GUESTS = normalise((0.71, 0.70, 0.0, 0.0))
STRANGER = normalise((0.0, 0.0, 1.0, 0.0))


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
