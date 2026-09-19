"""Capture-quality gate.

A face that is too small, too soft, too dark or half out of frame is refused
before matching. Lowering these thresholds to rescue a blurry face would only
move the failure from an abstention to a wrong-person cut.
"""

from __future__ import annotations

from dataclasses import dataclass

from cue_api.vision.types import DecodedFrame, FaceDetection, PixelBox


@dataclass(frozen=True)
class QualityPolicy:
    #: Face width as a fraction of frame width. 0.08 of 1280px is ~102px.
    min_face_width_ratio: float = 0.08
    min_detector_score: float = 0.70
    min_sharpness: float = 0.25
    min_brightness: float = 0.20
    max_brightness: float = 0.92
    #: Fraction of the box allowed to sit outside the frame.
    max_out_of_frame: float = 0.02
    #: Aggregate score a face must reach to be matched at all.
    min_score: float = 0.45


#: Shared immutable default so callers do not each build their own.
DEFAULT_QUALITY_POLICY = QualityPolicy()


@dataclass(frozen=True)
class QualityVerdict:
    passed: bool
    score: float
    face_width_ratio: float
    sharpness: float
    brightness: float
    detector_score: float
    failed_checks: tuple[str, ...]

    def as_contract(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "score": round(self.score, 4),
            "faceWidthRatio": round(self.face_width_ratio, 4),
            "sharpness": round(self.sharpness, 4),
            "brightness": round(self.brightness, 4),
            "detectorScore": round(self.detector_score, 4),
            "failedChecks": list(self.failed_checks),
        }


def _out_of_frame_fraction(box: PixelBox, frame: DecodedFrame) -> float:
    if box.area <= 0:
        return 1.0
    clipped = PixelBox(
        x=max(0.0, box.x),
        y=max(0.0, box.y),
        width=min(box.x + box.width, float(frame.width)) - max(0.0, box.x),
        height=min(box.y + box.height, float(frame.height)) - max(0.0, box.y),
    )
    if clipped.width <= 0 or clipped.height <= 0:
        return 1.0
    return 1.0 - (clipped.area / box.area)


def assess(
    frame: DecodedFrame,
    detection: FaceDetection,
    policy: QualityPolicy = DEFAULT_QUALITY_POLICY,
) -> QualityVerdict:
    face_width_ratio = detection.box.width / frame.width
    failed: list[str] = []

    if face_width_ratio < policy.min_face_width_ratio:
        failed.append("face_too_small")
    if detection.score < policy.min_detector_score:
        failed.append("weak_detection")
    if detection.sharpness < policy.min_sharpness:
        failed.append("motion_blur_or_soft_focus")
    if detection.brightness < policy.min_brightness:
        failed.append("underexposed")
    if detection.brightness > policy.max_brightness:
        failed.append("overexposed")
    if _out_of_frame_fraction(detection.box, frame) > policy.max_out_of_frame:
        failed.append("face_cropped_by_frame_edge")

    # A blunt average is enough to rank faces; the pass/fail verdict is what the
    # policy layer reads, and that comes from the named checks above.
    size_component = min(1.0, face_width_ratio / (policy.min_face_width_ratio * 3))
    exposure_component = 1.0 - min(1.0, abs(detection.brightness - 0.55) / 0.55)
    score = (
        0.35 * size_component
        + 0.30 * min(1.0, detection.sharpness)
        + 0.20 * min(1.0, detection.score)
        + 0.15 * exposure_component
    )
    if score < policy.min_score:
        failed.append("aggregate_quality_below_threshold")

    return QualityVerdict(
        passed=not failed,
        score=score,
        face_width_ratio=face_width_ratio,
        sharpness=detection.sharpness,
        brightness=detection.brightness,
        detector_score=detection.score,
        failed_checks=tuple(failed),
    )
