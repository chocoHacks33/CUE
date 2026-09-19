"""CUE guest identity: model provenance, capture quality and reference handling.

Person B owns this package. It observes; it never directs. Import the OpenCV
adapters from `cue_vision.adapters.opencv_models` only where real pixels exist.

Stage 0/1 scope: model files and their checksums, the capture-quality gate, the
reference gallery, and enrolment. Matching, calibration, tracking, identity
expiry and the observation pipeline are Stage 2/3 and live on
`codex/b-vision-stage2` until the Mac runtime gate passes.
"""

from cue_vision.gallery import GuestReferences, ReferenceGallery, cosine_similarity, normalise
from cue_vision.quality import DEFAULT_QUALITY_POLICY, QualityPolicy, QualityVerdict, assess
from cue_vision.types import (
    CalibrationStatus,
    DecodedFrame,
    FaceDetection,
    ObservationStatus,
    PixelBox,
)
from cue_vision.version import PACKAGE_VERSION, PIPELINE_VERSION, VISION_CONTRACT_VERSION

__all__ = [
    "DEFAULT_QUALITY_POLICY",
    "PACKAGE_VERSION",
    "PIPELINE_VERSION",
    "VISION_CONTRACT_VERSION",
    "CalibrationStatus",
    "DecodedFrame",
    "FaceDetection",
    "GuestReferences",
    "ObservationStatus",
    "PixelBox",
    "QualityPolicy",
    "QualityVerdict",
    "ReferenceGallery",
    "assess",
    "cosine_similarity",
    "normalise",
]
