"""OpenCV YuNet and SFace adapters.

The only module that touches pixels or imports cv2. It is imported lazily so the
rest of the package stays installable and testable without OpenCV, and so a
missing native wheel on the Mac fails with a clear message at the point of use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cue_api.guests.face_models import DEFAULT_MODEL_DIR, SFACE, YUNET, verify
from cue_api.guests.types import DecodedFrame, Embedding, FaceDetection, PixelBox


def _import_cv2() -> Any:
    try:
        import cv2  # noqa: PLC0415 - deliberately lazy: the core must import without it
    except ImportError as error:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "OpenCV is required for live inference. Install the extra: "
            'python -m pip install -e "apps/api[opencv]"'
        ) from error
    return cv2


def _require_image(frame: DecodedFrame) -> Any:
    if frame.image is None:
        raise ValueError("This adapter needs real pixels; frame.image is None")
    if frame.pixel_format != "BGR24":
        raise ValueError(
            f"Expected BGR24 pixels from the ingest side, received {frame.pixel_format}"
        )
    if frame.orientation_degrees != 0:
        raise ValueError(
            "Frames must be delivered upright; rotate in ingest so one owner handles orientation"
        )
    return frame.image


class YuNetDetector:
    """OpenCV's FaceDetectorYN, plus the patch statistics the quality gate needs."""

    name = "opencv-yunet"
    version = "2023mar"

    def __init__(
        self,
        model_dir: Path = DEFAULT_MODEL_DIR,
        *,
        score_threshold: float = 0.6,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
    ) -> None:
        cv2 = _import_cv2()
        verify(YUNET, model_dir)
        self._cv2 = cv2
        self._detector = cv2.FaceDetectorYN.create(
            model=str(YUNET.path(model_dir)),
            config="",
            input_size=(320, 320),
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
            top_k=top_k,
        )
        self._input_size: tuple[int, int] | None = None

    def detect(self, frame: DecodedFrame) -> list[FaceDetection]:
        cv2 = self._cv2
        image = _require_image(frame)

        size = (frame.width, frame.height)
        if size != self._input_size:
            self._detector.setInputSize(size)
            self._input_size = size

        _, faces = self._detector.detect(image)
        if faces is None:
            return []

        grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        detections: list[FaceDetection] = []
        for face in faces:
            x, y, width, height = (float(value) for value in face[:4])
            box = PixelBox(x=x, y=y, width=width, height=height)
            sharpness, brightness = _patch_statistics(cv2, grey, box)
            landmarks = tuple(
                (float(face[4 + index * 2]), float(face[5 + index * 2])) for index in range(5)
            )
            detections.append(
                FaceDetection(
                    box=box,
                    score=float(face[-1]),
                    sharpness=sharpness,
                    brightness=brightness,
                    landmarks=landmarks,
                )
            )

        detections.sort(key=lambda detection: detection.box.area, reverse=True)
        return detections


def _patch_statistics(cv2: Any, grey_image: Any, box: PixelBox) -> tuple[float, float]:
    """Normalised sharpness and brightness for the face patch, both 0..1."""
    height, width = grey_image.shape[:2]
    left = max(0, int(box.x))
    top = max(0, int(box.y))
    right = min(width, int(box.x + box.width))
    bottom = min(height, int(box.y + box.height))
    if right <= left or bottom <= top:
        return 0.0, 0.0

    patch = grey_image[top:bottom, left:right]
    # Variance of Laplacian is the usual blur proxy. 500 is a working ceiling
    # for a well-focused webcam face; it is a scaling choice, not a measurement.
    variance = float(cv2.Laplacian(patch, cv2.CV_64F).var())
    sharpness = min(1.0, variance / 500.0)
    brightness = float(patch.mean()) / 255.0
    return sharpness, brightness


class SFaceEmbedder:
    """OpenCV's FaceRecognizerSF: aligned crop to a 128-d embedding."""

    name = "opencv-sface"
    version = "2021dec"
    dimension = 128

    def __init__(self, model_dir: Path = DEFAULT_MODEL_DIR) -> None:
        cv2 = _import_cv2()
        verify(SFACE, model_dir)
        self._cv2 = cv2
        self._recognizer = cv2.FaceRecognizerSF.create(
            model=str(SFACE.path(model_dir)),
            config="",
        )

    def embed(self, frame: DecodedFrame, detection: FaceDetection) -> Embedding:
        import numpy  # noqa: PLC0415 - only needed on the live inference path

        image = _require_image(frame)
        if len(detection.landmarks) != 5:
            raise ValueError("SFace alignment needs the five YuNet landmarks")

        row = [
            detection.box.x,
            detection.box.y,
            detection.box.width,
            detection.box.height,
        ]
        for point in detection.landmarks:
            row.extend(point)
        row.append(detection.score)

        aligned = self._recognizer.alignCrop(image, numpy.array([row], dtype=numpy.float32))
        feature = self._recognizer.feature(aligned)
        return tuple(float(value) for value in feature.flatten())
