from __future__ import annotations

import pytest

from cue_api.guests.confidence_calibration import (
    NO_CALIBRATION,
    PROVISIONAL_CALIBRATION,
    SFACE_COSINE_REFERENCE,
    Calibration,
)
from cue_api.guests.types import CalibrationStatus


def test_the_provisional_mapping_is_labelled_as_provisional() -> None:
    assert PROVISIONAL_CALIBRATION.status is CalibrationStatus.PROVISIONAL_DEFAULT
    assert PROVISIONAL_CALIBRATION.sample_count == 0


def test_the_provisional_mapping_sits_on_the_published_reference_point() -> None:
    assert PROVISIONAL_CALIBRATION.confidence(SFACE_COSINE_REFERENCE) == pytest.approx(0.5)


def test_confidence_rises_with_similarity() -> None:
    low = PROVISIONAL_CALIBRATION.confidence(0.2)
    high = PROVISIONAL_CALIBRATION.confidence(0.7)

    assert low is not None and high is not None
    assert low < 0.2 < 0.8 < high


def test_an_uncalibrated_run_reports_no_confidence_at_all() -> None:
    assert NO_CALIBRATION.confidence(0.9) is None
    assert NO_CALIBRATION.status is CalibrationStatus.UNCALIBRATED


def test_a_missing_similarity_yields_no_confidence() -> None:
    assert PROVISIONAL_CALIBRATION.confidence(None) is None


def test_fitting_refuses_a_one_sided_sample() -> None:
    positives_only = [(0.7 + index * 0.01, True) for index in range(20)]

    with pytest.raises(ValueError, match="positive and 5 negative"):
        Calibration.fit(positives_only, calibration_id="bad")


def test_a_measured_calibration_separates_the_two_populations() -> None:
    labelled = [(0.65 + index * 0.01, True) for index in range(20)]
    labelled += [(0.05 + index * 0.01, False) for index in range(20)]

    calibration = Calibration.fit(labelled, calibration_id="held-out-v1")

    assert calibration.status is CalibrationStatus.MEASURED
    assert calibration.sample_count == 40
    positive = calibration.confidence(0.70)
    negative = calibration.confidence(0.10)
    assert positive is not None and negative is not None
    assert positive > 0.8
    assert negative < 0.2
