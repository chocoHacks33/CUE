"""Value types shared across the vision pipeline.

The core carries no numeric dependency: an embedding is a tuple of floats and a
frame's pixels are an opaque object only the OpenCV adapters ever touch. That is
what lets this package import and test on A's, B's, C's and D's machines alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

Embedding = tuple[float, ...]


class ObservationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    PROVISIONAL = "PROVISIONAL"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"
    LOW_QUALITY = "LOW_QUALITY"
    NO_FACE = "NO_FACE"


class CalibrationStatus(StrEnum):
    MEASURED = "MEASURED"
    PROVISIONAL_DEFAULT = "PROVISIONAL_DEFAULT"
    UNCALIBRATED = "UNCALIBRATED"


@dataclass(frozen=True)
class DecodedFrame:
    """A's worker-to-vision handover.

    `image` is whatever the ingest side decoded (a numpy BGR array in practice).
    The pure-Python core never indexes it; only the OpenCV adapters do.
    """

    camera_id: str
    stream_epoch: int
    sequence: int
    width: int
    height: int
    received_at_ms: int
    image: Any = None
    pixel_format: str = "BGR24"
    orientation_degrees: int = 0
    captured_at_ms: int | None = None

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("A decoded frame needs positive dimensions")
        if self.stream_epoch < 1:
            raise ValueError("Stream epochs start at 1")
        if self.orientation_degrees not in (0, 90, 180, 270):
            raise ValueError("Orientation must be a right-angle rotation")


@dataclass(frozen=True)
class PixelBox:
    x: float
    y: float
    width: float
    height: float

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def normalised(self, frame_width: int, frame_height: int) -> dict[str, float]:
        def clamp(value: float) -> float:
            return min(1.0, max(0.0, value))

        x = clamp(self.x / frame_width)
        y = clamp(self.y / frame_height)
        return {
            "x": x,
            "y": y,
            "width": clamp(self.width / frame_width),
            "height": clamp(self.height / frame_height),
        }


@dataclass(frozen=True)
class FaceDetection:
    """One detected face plus the patch statistics the detector already had.

    Sharpness and brightness are measured where the pixels live, so the quality
    policy stays a pure threshold decision that tests can drive directly.
    """

    box: PixelBox
    score: float
    sharpness: float
    brightness: float
    landmarks: tuple[tuple[float, float], ...] = field(default=())
