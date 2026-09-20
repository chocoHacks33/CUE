from __future__ import annotations

import pytest

from cue_api.release_finalize import validate_release_inputs
from cue_api.release_finalize_cli import main


def approval(commit: str = "abc123") -> dict[str, object]:
    return {
        "testedCommit": commit,
        "releaseTag": "cue-hackmit-2026-demo",
        "releaseMode": "ROLE_BASED_ASSIST",
    }


def manifest(commit: str = "abc123") -> dict[str, object]:
    return {
        "status": "PASS",
        "releaseReady": True,
        "commit": commit,
        "releaseTag": "cue-hackmit-2026-demo",
        "releaseMode": "ROLE_BASED_ASSIST",
    }


def test_passing_manifest_and_approval_are_bound_to_head() -> None:
    inputs = validate_release_inputs(manifest(), approval(), "abc123")
    assert inputs.tag == "cue-hackmit-2026-demo"
    assert inputs.mode == "ROLE_BASED_ASSIST"


@pytest.mark.parametrize(
    ("manifest_update", "approval_update", "message"),
    [
        ({"status": "INCOMPLETE", "releaseReady": False}, {}, "not PASS"),
        ({"commit": "old"}, {}, "does not name HEAD"),
        ({}, {"testedCommit": "old"}, "does not name HEAD"),
        ({"releaseTag": "other"}, {}, "identity differ"),
        ({"releaseMode": "NAMED_AUTO"}, {}, "identity differ"),
    ],
)
def test_release_identity_mismatches_are_refused(
    manifest_update: dict[str, object],
    approval_update: dict[str, object],
    message: str,
) -> None:
    manifest_value = {**manifest(), **manifest_update}
    approval_value = {**approval(), **approval_update}
    with pytest.raises(ValueError, match=message):
        validate_release_inputs(manifest_value, approval_value, "abc123")


def test_push_cannot_be_requested_without_explicit_tag_creation(capsys) -> None:
    assert main(["--push"]) == 2
    assert "--push requires --create-tag" in capsys.readouterr().out
