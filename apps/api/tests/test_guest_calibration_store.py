"""Carrying a fitted calibration between machines, and refusing a false one.

This file is the place a demo could most cheaply claim a measured result: a
hand-written JSON saying `MEASURED` would make every observation downstream report
a confidence nobody measured. So most of these tests are refusals.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cue_api.guests.calibration_store import (
    FILE_VERSION,
    MINIMUM_MEASURED_SAMPLES,
    CalibrationFileError,
    load,
    load_or_provisional,
    save,
)
from cue_api.guests.confidence_calibration import (
    NO_CALIBRATION,
    PROVISIONAL_CALIBRATION,
    Calibration,
)
from cue_api.guests.types import CalibrationStatus


def measured(**overrides) -> Calibration:
    values = {
        "calibration_id": "held-out-2026-09-19",
        "status": CalibrationStatus.MEASURED,
        "slope": 11.4,
        "intercept": -4.2,
        "sample_count": 60,
    }
    values.update(overrides)
    return Calibration(**values)


def write_document(path: Path, **overrides) -> Path:
    document = {
        "fileVersion": FILE_VERSION,
        "calibrationId": "held-out-2026-09-19",
        "status": "MEASURED",
        "slope": 11.4,
        "intercept": -4.2,
        "sampleCount": 60,
        "datasetNote": "30 positive and 30 negative pairs, held-out set A",
        "fittedAtMs": 1_700_000_000_000,
    }
    document.update(overrides)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


# -- round trip ------------------------------------------------------------


def test_a_fitted_calibration_survives_a_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "calibration.json"

    save(measured(), path, dataset_note="held-out set A", fitted_at_ms=1_700_000_000_000)
    stored = load(path)

    assert stored.calibration == measured()
    assert stored.dataset_note == "held-out set A"
    assert stored.fitted_at_ms == 1_700_000_000_000


def test_a_calibration_must_say_where_its_pairs_came_from(tmp_path: Path) -> None:
    """An unattributed calibration cannot be reviewed, so it cannot be saved."""
    with pytest.raises(CalibrationFileError, match="where its labelled pairs came from"):
        save(measured(), tmp_path / "c.json", dataset_note="   ")


def test_saving_creates_the_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "calibration.json"

    save(measured(), path, dataset_note="held-out set A")

    assert path.exists()


# -- the fallback ----------------------------------------------------------


def test_a_missing_file_falls_back_to_the_provisional_anchor(tmp_path: Path) -> None:
    stored = load_or_provisional(tmp_path / "absent.json")

    assert stored.calibration is PROVISIONAL_CALIBRATION
    assert stored.calibration.status is CalibrationStatus.PROVISIONAL_DEFAULT
    assert "Not a measured result" in stored.dataset_note


def test_a_present_but_invalid_file_raises_rather_than_downgrading(tmp_path: Path) -> None:
    """Somebody put that file there on purpose and will assume it is in use."""
    path = write_document(tmp_path / "calibration.json", sampleCount=0)

    with pytest.raises(CalibrationFileError):
        load_or_provisional(path)


# -- refusing a claim nobody could have measured ---------------------------


def test_measured_with_no_samples_is_refused(tmp_path: Path) -> None:
    path = write_document(tmp_path / "c.json", sampleCount=0)

    with pytest.raises(CalibrationFileError, match="not.*produced by a fit"):
        load(path)


def test_measured_with_fewer_samples_than_a_fit_needs_is_refused(tmp_path: Path) -> None:
    path = write_document(tmp_path / "c.json", sampleCount=MINIMUM_MEASURED_SAMPLES - 1)

    with pytest.raises(CalibrationFileError, match="at least"):
        load(path)


def test_a_measured_calibration_that_reports_one_confidence_for_everybody_is_refused(
    tmp_path: Path,
) -> None:
    path = write_document(tmp_path / "c.json", slope=0.0)

    with pytest.raises(CalibrationFileError, match="same confidence"):
        load(path)


def test_an_uncalibrated_file_may_not_claim_samples(tmp_path: Path) -> None:
    path = write_document(tmp_path / "c.json", status="UNCALIBRATED", sampleCount=40)

    with pytest.raises(CalibrationFileError, match="cannot claim a sample count"):
        load(path)


def test_saving_is_validated_too_so_a_bad_claim_never_reaches_disk(tmp_path: Path) -> None:
    path = tmp_path / "c.json"

    with pytest.raises(CalibrationFileError):
        save(measured(sample_count=2), path, dataset_note="held-out set A")

    assert not path.exists()


# -- malformed files -------------------------------------------------------


def test_an_unknown_status_is_refused(tmp_path: Path) -> None:
    path = write_document(tmp_path / "c.json", status="EXCELLENT")

    with pytest.raises(CalibrationFileError, match="Unknown calibration status"):
        load(path)


def test_a_future_file_version_is_refused(tmp_path: Path) -> None:
    path = write_document(tmp_path / "c.json", fileVersion=FILE_VERSION + 1)

    with pytest.raises(CalibrationFileError, match="fileVersion"):
        load(path)


def test_missing_fields_are_named(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"fileVersion": FILE_VERSION, "status": "MEASURED"}), "utf-8")

    with pytest.raises(CalibrationFileError, match="calibrationId"):
        load(path)


def test_a_non_finite_slope_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    # json.dumps writes bare Infinity, which json.loads accepts back as a float.
    write_document(path, slope=float("inf"))

    with pytest.raises(CalibrationFileError, match="finite"):
        load(path)


def test_a_slope_that_is_not_a_number_is_refused(tmp_path: Path) -> None:
    path = write_document(tmp_path / "c.json", slope="steep")

    with pytest.raises(CalibrationFileError, match="slope must be a number"):
        load(path)


def test_a_fractional_sample_count_is_refused(tmp_path: Path) -> None:
    path = write_document(tmp_path / "c.json", sampleCount=60.5)

    with pytest.raises(CalibrationFileError, match="whole number"):
        load(path)


def test_an_empty_dataset_note_is_refused_on_load(tmp_path: Path) -> None:
    path = write_document(tmp_path / "c.json", datasetNote="")

    with pytest.raises(CalibrationFileError, match="where the labelled pairs came from"):
        load(path)


def test_a_file_that_is_not_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text("slope: 11.4", encoding="utf-8")

    with pytest.raises(CalibrationFileError, match="not valid JSON"):
        load(path)


def test_an_absent_file_named_directly_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CalibrationFileError, match="No calibration file"):
        load(tmp_path / "absent.json")


# -- what the honest statuses still allow ----------------------------------


def test_the_provisional_anchor_round_trips_without_claiming_samples(tmp_path: Path) -> None:
    path = tmp_path / "c.json"

    save(PROVISIONAL_CALIBRATION, path, dataset_note="OpenCV published reference point")
    stored = load(path)

    assert stored.calibration.status is CalibrationStatus.PROVISIONAL_DEFAULT
    assert stored.calibration.sample_count == 0


def test_an_uncalibrated_run_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "c.json"

    save(NO_CALIBRATION, path, dataset_note="deliberately claiming nothing")

    assert load(path).calibration.confidence(0.9) is None


# -- the loop, closed ------------------------------------------------------


def test_a_loaded_calibration_reaches_the_observation_contract(tmp_path: Path) -> None:
    """Without this, a fitted calibration could never affect what is published."""
    from conftest import SARAH, KeyedEmbedder, ScriptedDetector, make_detection, make_frame

    from cue_api.guests.calibration_store import load_or_provisional
    from cue_api.guests.observation_pipeline import VisionPipeline
    from cue_api.guests.reference_gallery import GuestReferences, ReferenceGallery

    path = tmp_path / "calibration.json"
    save(measured(), path, dataset_note="held-out set A")

    detector = ScriptedDetector()
    detector.queue([make_detection(x=500.0)])
    pipeline = VisionPipeline(
        event_id="hackmit-demo",
        detector=detector,
        embedder=KeyedEmbedder(vectors={500.0: SARAH}),
        gallery=ReferenceGallery(
            version=1, guests=(GuestReferences("guest-sarah", "Sarah", 1, (SARAH,)),)
        ),
        calibration=load_or_provisional(path).calibration,
    )

    observation = pipeline.observe(make_frame(received_at_ms=1_000_000))[0]

    assert observation.calibration_status is CalibrationStatus.MEASURED
    assert observation.calibration_id == "held-out-2026-09-19"
    assert observation.to_contract()["match"]["calibrationStatus"] == "MEASURED"


def test_without_a_file_the_observation_discloses_the_provisional_anchor(
    tmp_path: Path,
) -> None:
    from conftest import SARAH, KeyedEmbedder, ScriptedDetector, make_detection, make_frame

    from cue_api.guests.calibration_store import load_or_provisional
    from cue_api.guests.observation_pipeline import VisionPipeline
    from cue_api.guests.reference_gallery import GuestReferences, ReferenceGallery

    detector = ScriptedDetector()
    detector.queue([make_detection(x=500.0)])
    pipeline = VisionPipeline(
        event_id="hackmit-demo",
        detector=detector,
        embedder=KeyedEmbedder(vectors={500.0: SARAH}),
        gallery=ReferenceGallery(
            version=1, guests=(GuestReferences("guest-sarah", "Sarah", 1, (SARAH,)),)
        ),
        calibration=load_or_provisional(tmp_path / "absent.json").calibration,
    )

    observation = pipeline.observe(make_frame(received_at_ms=1_000_000))[0]

    assert observation.calibration_status is CalibrationStatus.PROVISIONAL_DEFAULT
    assert observation.to_contract()["match"]["calibrationStatus"] == "PROVISIONAL_DEFAULT"
