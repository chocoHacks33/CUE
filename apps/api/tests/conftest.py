"""Deterministic stand-ins for the OpenCV models.

These are fixtures, not recognition. Every test that uses them is testing the
policy around the models: quality gating, abstention, confirmation and expiry.
Real YuNet/SFace behaviour is only established by the Mac runtime check in
`docs/results/b-identity-report.template.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from cue_api.contracts import CameraId
from cue_api.guests.reference_gallery import GuestReferences, ReferenceGallery, normalise
from cue_api.guests.types import DecodedFrame, Embedding, FaceDetection, PixelBox
from cue_api.media_contracts import DecodedVideoFrame, PixelFormat

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


def make_video_frame(
    *,
    camera_id: CameraId = CameraId.GUEST,
    stream_epoch: int = 1,
    sequence: int = 0,
    width: int = FRAME_WIDTH,
    height: int = FRAME_HEIGHT,
    pixel_format: PixelFormat = PixelFormat.BGR24,
    orientation_degrees: int = 0,
    mirrored: bool = False,
    received_at_monotonic_s: float = 1_000.0,
    capture_time_s: float | None = 999.96,
    stride_bytes: int | None = None,
    event_id: str = "hackmit-demo",
    track_sid: str = "TR_guest_1",
) -> DecodedVideoFrame:
    """One of A's decoded frames, with a payload of the exact declared length.

    Defaults match `make_frame`, so a `make_detection` box lands inside the frame
    and reaches the matcher instead of being refused by the quality gate.
    """
    stride = stride_bytes if stride_bytes is not None else width * pixel_format.bytes_per_pixel
    return DecodedVideoFrame(
        event_id=event_id,
        camera_id=camera_id,
        stream_epoch=stream_epoch,
        track_sid=track_sid,
        sequence=sequence,
        width=width,
        height=height,
        stride_bytes=stride,
        pixel_format=pixel_format,
        orientation_degrees=orientation_degrees,
        mirrored=mirrored,
        received_at_monotonic_s=received_at_monotonic_s,
        capture_time_s=capture_time_s,
        data=bytes(stride * height),
    )


@dataclass
class RecordingSink:
    """A backend that remembers what it was told, and can be told to fail."""

    gallery: ReferenceGallery = field(default_factory=ReferenceGallery.empty)
    posted: list[dict] = field(default_factory=list)
    invalidations: list[dict] = field(default_factory=list)
    fail_post: bool = False
    fail_gallery: bool = False
    fail_invalidate: bool = False

    def fetch_gallery(self, event_id: str) -> ReferenceGallery:
        if self.fail_gallery:
            raise RuntimeError("backend unreachable")
        return self.gallery

    def post_observation(self, observation: dict) -> dict:
        if self.fail_post:
            raise RuntimeError("backend refused the observation")
        self.posted.append(observation)
        return observation

    def invalidate(
        self,
        *,
        event_id: str,
        camera_id: str,
        current_stream_epoch: int,
        reason: str,
    ) -> dict:
        if self.fail_invalidate:
            raise RuntimeError("backend unreachable")
        record = {
            "eventId": event_id,
            "cameraId": camera_id,
            "currentStreamEpoch": current_stream_epoch,
            "reason": reason,
        }
        self.invalidations.append(record)
        return record
