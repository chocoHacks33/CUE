"""Validate a Stage 5 manifest before an explicit annotated release tag."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cue_api.release_preflight import PASS, git_value


@dataclass(frozen=True)
class ReleaseInputs:
    commit: str
    tag: str
    mode: str


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unreadable: {type(error).__name__}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def validate_release_inputs(
    manifest: dict[str, Any], approval: dict[str, Any], expected_commit: str
) -> ReleaseInputs:
    if manifest.get("status") != PASS or manifest.get("releaseReady") is not True:
        raise ValueError("release manifest is not PASS")
    if manifest.get("commit") != expected_commit:
        raise ValueError("release manifest does not name HEAD")
    if approval.get("testedCommit") != expected_commit:
        raise ValueError("release approval does not name HEAD")
    tag = approval.get("releaseTag")
    mode = approval.get("releaseMode")
    if manifest.get("releaseTag") != tag or manifest.get("releaseMode") != mode:
        raise ValueError("manifest and approval release identity differ")
    if not isinstance(tag, str) or not isinstance(mode, str):
        raise ValueError("release tag or mode is missing")
    return ReleaseInputs(expected_commit, tag, mode)


def verify_repository(repo_root: Path, inputs: ReleaseInputs) -> None:
    if git_value(repo_root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("working tree is not clean")
    remote_contains = git_value(repo_root, "branch", "-r", "--contains", inputs.commit)
    if "origin/" not in remote_contains:
        raise ValueError("HEAD is not present on origin")
    existing = git_value(repo_root, "tag", "--list", inputs.tag)
    if existing:
        target = git_value(repo_root, "rev-list", "-n", "1", inputs.tag)
        if target == inputs.commit:
            raise ValueError("release tag already exists on this commit")
        raise ValueError("release tag already exists on a different commit")
