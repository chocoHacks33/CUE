"""Similarity to confidence calibration.

Stage 2 prep carries the provisional anchor only. Fitting a MEASURED
calibration from held-out labelled pairs is Stage 3 and is not here, so every
confidence this module returns is labelled PROVISIONAL_DEFAULT.

A cosine similarity is not a probability. This module is the only place allowed
to turn one into a confidence, and it labels every answer with how it was
obtained so a provisional anchor is never reported as a measured result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from cue_api.guests.types import CalibrationStatus

#: OpenCV's published SFace cosine reference point. An anchor, not our result.
SFACE_COSINE_REFERENCE = 0.363


def _logistic(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


@dataclass(frozen=True)
class Calibration:
    """Platt-style logistic mapping from raw similarity to confidence."""

    calibration_id: str
    status: CalibrationStatus
    slope: float
    intercept: float
    #: How many labelled pairs produced this mapping. Zero means nobody measured.
    sample_count: int = 0

    def confidence(self, similarity: float | None) -> float | None:
        if similarity is None or self.status is CalibrationStatus.UNCALIBRATED:
            return None
        return _logistic(self.slope * similarity + self.intercept)


#: Used until B fits a measured calibration on the held-out set. The slope puts
#: the 50% point on OpenCV's reference threshold; it is an anchor, not evidence.
PROVISIONAL_CALIBRATION = Calibration(
    calibration_id="sface-cosine-provisional-v1",
    status=CalibrationStatus.PROVISIONAL_DEFAULT,
    slope=12.4,
    intercept=-12.4 * SFACE_COSINE_REFERENCE,
    sample_count=0,
)

#: For runs where no calibration may be claimed at all.
NO_CALIBRATION = Calibration(
    calibration_id="uncalibrated",
    status=CalibrationStatus.UNCALIBRATED,
    slope=0.0,
    intercept=0.0,
    sample_count=0,
)
