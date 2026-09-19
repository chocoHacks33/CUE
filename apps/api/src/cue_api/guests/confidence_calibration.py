"""Similarity to confidence calibration.

`PROVISIONAL_CALIBRATION` is an anchor on OpenCV's published SFace reference
point, not a result. `Calibration.fit()` produces a MEASURED one from held-out
labelled pairs and refuses a one-sided sample, because a mapping learnt from
positives alone would report high confidence for everybody.

A cosine similarity is not a probability. This module is the only place allowed
to turn one into a confidence, and it labels every answer with how it was
obtained so a provisional anchor is never reported as a measured result.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
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


    @classmethod
    def fit(
        cls,
        labelled_similarities: Sequence[tuple[float, bool]],
        *,
        calibration_id: str,
        iterations: int = 2000,
        learning_rate: float = 0.5,
    ) -> Calibration:
        """Fit on held-out labelled pairs of (similarity, same_person).

        Deliberately refuses to fit on a one-sided sample: a mapping learnt from
        positives alone would report high confidence for everybody.
        """
        positives = sum(1 for _, same in labelled_similarities if same)
        negatives = len(labelled_similarities) - positives
        if positives < 5 or negatives < 5:
            raise ValueError(
                "Calibration needs at least 5 positive and 5 negative labelled pairs; "
                f"received {positives} positive and {negatives} negative"
            )

        slope = 10.0
        intercept = -10.0 * SFACE_COSINE_REFERENCE
        count = len(labelled_similarities)
        for _ in range(iterations):
            slope_gradient = 0.0
            intercept_gradient = 0.0
            for similarity, same in labelled_similarities:
                error = _logistic(slope * similarity + intercept) - (1.0 if same else 0.0)
                slope_gradient += error * similarity
                intercept_gradient += error
            slope -= learning_rate * slope_gradient / count
            intercept -= learning_rate * intercept_gradient / count

        return cls(
            calibration_id=calibration_id,
            status=CalibrationStatus.MEASURED,
            slope=slope,
            intercept=intercept,
            sample_count=count,
        )

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
