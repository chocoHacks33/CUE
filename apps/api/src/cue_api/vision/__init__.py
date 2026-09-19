"""Person B — guest visual identity.

Stage 0/1 scope: model provenance and checksums, the capture-quality gate, and
the enrolled reference gallery. It observes; it never directs.

Import the OpenCV adapters from `cue_api.vision.adapters.opencv_models` only
where real pixels exist — the rest of this package has no native dependency, so
it imports and tests on every machine in the team.
"""

from cue_api.vision.gallery import (
    GuestReferences,
    ReferenceGallery,
    cosine_similarity,
    normalise,
)
from cue_api.vision.quality import (
    DEFAULT_QUALITY_POLICY,
    QualityPolicy,
    QualityVerdict,
    assess,
)
from cue_api.vision.types import (
    CalibrationStatus,
    DecodedFrame,
    FaceDetection,
    ObservationStatus,
    PixelBox,
)
from cue_api.vision.version import (
    PACKAGE_VERSION,
    PIPELINE_VERSION,
    VISION_CONTRACT_VERSION,
)

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
