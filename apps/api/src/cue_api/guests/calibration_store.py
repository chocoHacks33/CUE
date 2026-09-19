"""Persisting a fitted calibration, and refusing a dishonest one.

`Calibration.fit()` can produce a `MEASURED` mapping, but until now nothing could
carry one from the machine that fitted it to the machine that runs the show. This
is that carrier, and it is the point where a false claim would be easiest to make:
a hand-edited JSON file saying `MEASURED` would make every observation downstream
report a measured confidence that nobody measured.

So loading validates the claim rather than trusting it. `MEASURED` has to look
like something `fit()` could actually have produced — a real sample count, finite
parameters, a mapping that is not flat. A file that fails any of those is refused
outright instead of being quietly downgraded, because a calibration file that
exists but is wrong is worse than none: somebody put it there on purpose and will
assume it is in use.

When no file exists at all, the runtime falls back to `PROVISIONAL_CALIBRATION`.
That is a disclosure, not a default: every observation then says
`PROVISIONAL_DEFAULT` and the demo cannot imply otherwise.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

from cue_api.guests.confidence_calibration import (
    PROVISIONAL_CALIBRATION,
    Calibration,
)
from cue_api.guests.types import CalibrationStatus

#: `fit()` needs at least 5 positives and 5 negatives, so nothing it produces can
#: honestly report fewer than this many samples.
MINIMUM_MEASURED_SAMPLES = 10

FILE_VERSION = 1


class CalibrationFileError(ValueError):
    """The file does not describe a calibration anyone could have measured."""


@dataclass(frozen=True)
class StoredCalibration:
    """A calibration plus the provenance needed to judge it later."""

    calibration: Calibration
    #: Where the labelled pairs came from. Free text, written by whoever fitted it.
    dataset_note: str
    fitted_at_ms: int

    def to_document(self) -> dict[str, object]:
        return {
            "fileVersion": FILE_VERSION,
            "calibrationId": self.calibration.calibration_id,
            "status": self.calibration.status.value,
            "slope": self.calibration.slope,
            "intercept": self.calibration.intercept,
            "sampleCount": self.calibration.sample_count,
            "datasetNote": self.dataset_note,
            "fittedAtMs": self.fitted_at_ms,
        }


def save(
    calibration: Calibration,
    path: Path,
    *,
    dataset_note: str,
    fitted_at_ms: int | None = None,
) -> StoredCalibration:
    """Write a calibration, refusing to record a claim it cannot support."""
    if not dataset_note.strip():
        raise CalibrationFileError(
            "A calibration must record where its labelled pairs came from; "
            "an unattributed calibration cannot be reviewed"
        )
    stored = StoredCalibration(
        calibration=calibration,
        dataset_note=dataset_note.strip(),
        fitted_at_ms=fitted_at_ms if fitted_at_ms is not None else int(time.time() * 1000),
    )
    _validate(stored.calibration)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stored.to_document(), indent=2) + "\n", encoding="utf-8")
    return stored


def load(path: Path) -> StoredCalibration:
    """Read and validate a calibration file. Raises rather than downgrading."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise CalibrationFileError(f"No calibration file at {path}") from error

    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CalibrationFileError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise CalibrationFileError(f"{path} does not contain a calibration object")

    version = document.get("fileVersion")
    if version != FILE_VERSION:
        raise CalibrationFileError(
            f"{path} declares fileVersion {version!r}; this build reads {FILE_VERSION}"
        )

    missing = [
        key
        for key in ("calibrationId", "status", "slope", "intercept", "sampleCount", "datasetNote")
        if key not in document
    ]
    if missing:
        raise CalibrationFileError(f"{path} is missing {', '.join(sorted(missing))}")

    status_value = document["status"]
    try:
        status = CalibrationStatus(status_value)
    except ValueError as error:
        raise CalibrationFileError(f"Unknown calibration status {status_value!r}") from error

    calibration_id = document["calibrationId"]
    if not isinstance(calibration_id, str) or not calibration_id.strip():
        raise CalibrationFileError("calibrationId must be a non-empty string")

    dataset_note = document["datasetNote"]
    if not isinstance(dataset_note, str) or not dataset_note.strip():
        raise CalibrationFileError(
            "datasetNote must say where the labelled pairs came from"
        )

    calibration = Calibration(
        calibration_id=calibration_id,
        status=status,
        slope=_finite(document["slope"], "slope"),
        intercept=_finite(document["intercept"], "intercept"),
        sample_count=_whole(document["sampleCount"], "sampleCount"),
    )
    _validate(calibration)

    fitted_at = document.get("fittedAtMs", 0)
    return StoredCalibration(
        calibration=calibration,
        dataset_note=dataset_note.strip(),
        fitted_at_ms=_whole(fitted_at, "fittedAtMs"),
    )


def load_or_provisional(path: Path) -> StoredCalibration:
    """The runtime entry point: a stored calibration, or an honest fallback.

    A missing file is normal and falls back to `PROVISIONAL_DEFAULT`. A file that
    is present but invalid is **not** normal and raises: somebody deliberately put
    it there and will assume it is in use.
    """
    if not path.exists():
        return StoredCalibration(
            calibration=PROVISIONAL_CALIBRATION,
            dataset_note=(
                "No calibration file; using the provisional anchor on OpenCV's "
                "published SFace reference point. Not a measured result."
            ),
            fitted_at_ms=0,
        )
    return load(path)


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CalibrationFileError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise CalibrationFileError(f"{field} must be finite, received {value!r}")
    return number


def _whole(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CalibrationFileError(f"{field} must be a whole number")
    if value < 0:
        raise CalibrationFileError(f"{field} cannot be negative")
    return value


def _validate(calibration: Calibration) -> None:
    """The rules a calibration has to satisfy to be believed."""
    if calibration.status is CalibrationStatus.MEASURED:
        if calibration.sample_count < MINIMUM_MEASURED_SAMPLES:
            raise CalibrationFileError(
                f"A MEASURED calibration claims {calibration.sample_count} samples; "
                f"fitting needs at least {MINIMUM_MEASURED_SAMPLES}, so this was not "
                "produced by a fit"
            )
        if calibration.slope == 0.0:
            raise CalibrationFileError(
                "A MEASURED calibration with zero slope reports the same confidence "
                "for everybody, which is not a measurement"
            )
    if calibration.status is CalibrationStatus.UNCALIBRATED and calibration.sample_count:
        raise CalibrationFileError(
            "An UNCALIBRATED calibration cannot claim a sample count; it reports no "
            "confidence at all"
        )
