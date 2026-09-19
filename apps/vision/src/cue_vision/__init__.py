"""CUE guest identity: detection, quality, calibrated matching and expiry.

Person B owns this package. It observes; it never directs. Import the OpenCV
adapters from `cue_vision.adapters.opencv_models` only where real pixels exist.
"""

from cue_vision.calibration import (
    NO_CALIBRATION,
    PROVISIONAL_CALIBRATION,
    Calibration,
)
from cue_vision.gallery import GuestReferences, ReferenceGallery
from cue_vision.ledger import DEFAULT_IDENTITY_TTL_MS, IdentityLedger
from cue_vision.matching import MatchDecision, MatchThresholds, match
from cue_vision.pipeline import Observation, VisionPipeline
from cue_vision.quality import QualityPolicy, QualityVerdict, assess
from cue_vision.tracking import LocalTracker
from cue_vision.types import (
    CalibrationStatus,
    DecodedFrame,
    FaceDetection,
    ObservationStatus,
    PixelBox,
)
from cue_vision.version import PACKAGE_VERSION, PIPELINE_VERSION, VISION_CONTRACT_VERSION

__all__ = [
    "DEFAULT_IDENTITY_TTL_MS",
    "NO_CALIBRATION",
    "PACKAGE_VERSION",
    "PIPELINE_VERSION",
    "PROVISIONAL_CALIBRATION",
    "VISION_CONTRACT_VERSION",
    "Calibration",
    "CalibrationStatus",
    "DecodedFrame",
    "FaceDetection",
    "GuestReferences",
    "IdentityLedger",
    "LocalTracker",
    "MatchDecision",
    "MatchThresholds",
    "Observation",
    "ObservationStatus",
    "PixelBox",
    "QualityPolicy",
    "QualityVerdict",
    "ReferenceGallery",
    "VisionPipeline",
    "assess",
    "match",
]
