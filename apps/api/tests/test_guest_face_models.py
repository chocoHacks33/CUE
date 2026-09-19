from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from cue_api.guests.face_models import (
    MODEL_FILES,
    SFACE,
    YUNET,
    ModelVerificationError,
    sha256_of,
    status_report,
    verify,
)


def write_model(directory: Path, filename: str, payload: bytes = b"weights") -> Path:
    path = directory / filename
    path.write_bytes(payload)
    return path


def test_a_missing_model_file_names_where_to_get_it(tmp_path: Path) -> None:
    with pytest.raises(ModelVerificationError, match="opencv_zoo"):
        verify(YUNET, tmp_path)


def test_an_unpinned_model_reports_its_digest(tmp_path: Path) -> None:
    path = write_model(tmp_path, YUNET.filename)

    assert verify(YUNET, tmp_path) == sha256_of(path)


def test_a_pinned_model_rejects_a_different_file(tmp_path: Path) -> None:
    write_model(tmp_path, YUNET.filename)
    pinned = replace(YUNET, expected_sha256="0" * 64)

    with pytest.raises(ModelVerificationError, match="expected"):
        verify(pinned, tmp_path)


def test_a_pinned_model_accepts_the_recorded_file(tmp_path: Path) -> None:
    path = write_model(tmp_path, SFACE.filename)
    pinned = replace(SFACE, expected_sha256=sha256_of(path))

    assert verify(pinned, tmp_path) == sha256_of(path)


def test_the_status_report_is_honest_about_what_is_unverified(tmp_path: Path) -> None:
    write_model(tmp_path, YUNET.filename)

    report = {entry["key"]: entry for entry in status_report(tmp_path)}

    assert report["yunet"]["present"] is True
    assert report["yunet"]["pinned"] is False
    assert report["sface"]["present"] is False
    assert report["yunet"]["licenceVerified"] is False


def test_no_checksum_is_claimed_before_anyone_downloaded_the_file() -> None:
    # A fabricated digest would pass review and prove nothing. These stay empty
    # until B pins the digest of the file actually downloaded.
    assert all(model.expected_sha256 is None for model in MODEL_FILES)
    assert all(not model.licence_verified for model in MODEL_FILES)
