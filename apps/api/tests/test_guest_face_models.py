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
    """How `cue-guests models --record` behaves for a model nobody has pinned yet."""
    path = write_model(tmp_path, YUNET.filename)
    unpinned = replace(YUNET, expected_sha256=None)

    assert verify(unpinned, tmp_path) == sha256_of(path)


def test_a_pinned_model_rejects_a_different_file(tmp_path: Path) -> None:
    write_model(tmp_path, YUNET.filename)
    pinned = replace(YUNET, expected_sha256="0" * 64)

    with pytest.raises(ModelVerificationError, match="expected"):
        verify(pinned, tmp_path)


def test_a_pinned_model_accepts_the_recorded_file(tmp_path: Path) -> None:
    path = write_model(tmp_path, SFACE.filename)
    pinned = replace(SFACE, expected_sha256=sha256_of(path))

    assert verify(pinned, tmp_path) == sha256_of(path)


def test_the_status_report_flags_a_file_that_does_not_match_its_pin(tmp_path: Path) -> None:
    # A file is present, but it is not the file that was pinned.
    write_model(tmp_path, YUNET.filename, payload=b"not the real weights")

    report = {entry["key"]: entry for entry in status_report(tmp_path)}

    assert report["yunet"]["present"] is True
    assert report["yunet"]["pinned"] is True
    assert report["yunet"]["matchesPin"] is False
    assert report["sface"]["present"] is False


def test_every_model_is_pinned_and_its_licence_read() -> None:
    """The pins are digests of files actually downloaded and hashed locally.

    This test replaces the earlier "nothing is claimed before download" one, which
    was correct while the weights were undownloaded and became wrong the moment
    they were. YuNet's pin independently matches the `oid sha256` in upstream's
    git-lfs pointer.
    """
    for model in MODEL_FILES:
        assert model.expected_sha256 is not None, f"{model.key} is unpinned"
        assert len(model.expected_sha256) == 64
        assert model.licence_verified, f"{model.key} licence unverified"


def test_a_pin_is_a_real_digest_not_a_placeholder() -> None:
    for model in MODEL_FILES:
        digest = model.expected_sha256
        assert digest is not None
        assert set(digest) <= set("0123456789abcdef")
        assert len(set(digest)) > 4, "a digest of one repeated character is a placeholder"
