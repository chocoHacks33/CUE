"""Bounded, offline-only Stage 6 regression and handoff reporting."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PASS = "PASS"
FAIL = "FAIL"
INCOMPLETE = "INCOMPLETE"
OWNERS = ("A", "B", "C", "D")
RELEASE_MODES = ("ROLE_BASED_ASSIST", "NAMED_ASSIST", "NAMED_AUTO")
FORBIDDEN_KEY = re.compile(r"(api.?key|secret|password|credential|access.?token)", re.I)


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str

    def to_mapping(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def _meaningful(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    lowered = value.strip().lower()
    return not any(marker in lowered for marker in ("todo", "replace", "pending"))


def _find_forbidden_key(value: object, prefix: str = "") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            location = f"{prefix}.{key}" if prefix else str(key)
            if FORBIDDEN_KEY.search(str(key)):
                return location
            found = _find_forbidden_key(child, location)
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _find_forbidden_key(child, f"{prefix}[{index}]")
            if found:
                return found
    return None


def load_handoff(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"handoff is unreadable: {type(error).__name__}") from error
    if not isinstance(value, dict):
        raise ValueError("handoff must be a JSON object")
    return value


def validate_handoff(value: dict[str, Any], expected_commit: str) -> Check:
    problems: list[str] = []
    if value.get("schemaVersion") != 1:
        problems.append("schemaVersion must be 1")
    if value.get("commit") != expected_commit:
        problems.append("commit does not equal HEAD")
    from_owner = value.get("fromOwner")
    to_owner = value.get("toOwner")
    if from_owner not in OWNERS or to_owner not in OWNERS or from_owner == to_owner:
        problems.append("fromOwner/toOwner must be two different A-D owners")
    if value.get("releaseMode") not in RELEASE_MODES:
        problems.append("releaseMode is missing or invalid")
    if value.get("hardwareStatus") != "NEEDS_REVALIDATION":
        problems.append("hardwareStatus must remain NEEDS_REVALIDATION overnight")
    if not _meaningful(value.get("resumeAtUtc")):
        problems.append("resumeAtUtc is missing")

    for field in ("knownBlockers", "morningFirstActions", "completedOfflineWork"):
        rows = value.get(field)
        if not isinstance(rows, list) or not rows or not all(_meaningful(row) for row in rows):
            problems.append(f"{field} must contain at least one concrete item")

    acknowledgements = value.get("acknowledgements")
    required_acknowledgements = (
        "noNewMediaArchitecture",
        "noModelMigration",
        "noHardwareClaim",
        "venueRulesChecked",
        "handoffAgreed",
    )
    if not isinstance(acknowledgements, dict):
        problems.append("acknowledgements is missing")
    else:
        for field in required_acknowledgements:
            if acknowledgements.get(field) is not True:
                problems.append(f"acknowledgements.{field} is not true")

    forbidden = _find_forbidden_key(value)
    if forbidden:
        problems.append(f"handoff contains forbidden secret-like field: {forbidden}")
    if problems:
        return Check("handoff", INCOMPLETE, "; ".join(problems))
    return Check("handoff", PASS, f"agreed {from_owner}-to-{to_owner} offline handoff")


def run_command(
    command: list[str], cwd: Path, timeout: int, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def git_value(repo_root: Path, *arguments: str) -> str:
    result = run_command(
        ["git", *arguments],
        repo_root,
        30,
        dict(os.environ),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def inspect_repository(repo_root: Path) -> tuple[str, str, list[Check]]:
    try:
        commit = git_value(repo_root, "rev-parse", "HEAD")
        branch = git_value(repo_root, "branch", "--show-current")
        dirty = git_value(repo_root, "status", "--porcelain", "--untracked-files=all")
        remote_contains = git_value(repo_root, "branch", "-r", "--contains", commit)
    except RuntimeError as error:
        return "UNKNOWN", "UNKNOWN", [Check("git", FAIL, str(error))]
    checks = [
        Check("git-branch", PASS if branch else FAIL, branch or "detached HEAD"),
        Check(
            "git-clean",
            PASS if not dirty else FAIL,
            "working tree is clean" if not dirty else "working tree has uncommitted files",
        ),
        Check(
            "git-pushed",
            PASS if "origin/" in remote_contains else INCOMPLETE,
            "HEAD exists on origin" if "origin/" in remote_contains else "push HEAD first",
        ),
    ]
    return commit, branch, checks


def offline_commands(repo_root: Path) -> tuple[tuple[str, list[str], Path], ...]:
    npm = shutil.which("npm") or shutil.which("npm.cmd") or "npm"
    return (
        ("api-tests", [sys.executable, "-m", "pytest", "-q"], repo_root / "apps/api"),
        (
            "api-lint",
            [sys.executable, "-m", "ruff", "check", "src", "tests"],
            repo_root / "apps/api",
        ),
        ("web-tests", [npm, "test"], repo_root),
        ("typecheck", [npm, "run", "typecheck"], repo_root),
        ("production-build", [npm, "run", "build"], repo_root),
    )


Runner = Callable[[list[str], Path, int, dict[str, str]], subprocess.CompletedProcess[str]]


def run_offline_suite(
    repo_root: Path,
    *,
    maximum_seconds: int = 600,
    runner: Runner = run_command,
    clock: Callable[[], float] = time.monotonic,
) -> list[Check]:
    started = clock()
    environment = dict(os.environ)
    for name in (
        "OPENAI_API_KEY",
        "DEEPGRAM_API_KEY",
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "CUE_MODEL",
        "CUE_BOOTSTRAP_SECRET",
        "CUE_PRODUCER_SECRET",
    ):
        environment.pop(name, None)
    environment["CUE_OFFLINE"] = "1"
    checks: list[Check] = []
    for name, command, cwd in offline_commands(repo_root):
        remaining = maximum_seconds - int(clock() - started)
        if remaining <= 0:
            checks.append(Check(name, INCOMPLETE, "offline time budget exhausted"))
            continue
        command_started = clock()
        try:
            result = runner(command, cwd, remaining, environment)
            elapsed = clock() - command_started
            checks.append(
                Check(
                    name,
                    PASS if result.returncode == 0 else FAIL,
                    f"exit {result.returncode} in {elapsed:.1f}s",
                )
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            checks.append(Check(name, FAIL, type(error).__name__))
    return checks


def make_report(
    commit: str,
    branch: str,
    checks: list[Check],
    handoff: dict[str, Any] | None,
) -> dict[str, Any]:
    if any(check.status == FAIL for check in checks):
        status = FAIL
    elif any(check.status == INCOMPLETE for check in checks):
        status = INCOMPLETE
    else:
        status = PASS
    return {
        "schemaVersion": 1,
        "status": status,
        "offlineRegressionPassed": status == PASS,
        "hardwareValidated": False,
        "releaseCertified": False,
        "commit": commit,
        "branch": branch,
        "generatedAtUnixMs": int(time.time() * 1_000),
        "handoff": {
            "fromOwner": handoff.get("fromOwner"),
            "toOwner": handoff.get("toOwner"),
            "resumeAtUtc": handoff.get("resumeAtUtc"),
            "releaseMode": handoff.get("releaseMode"),
            "knownBlockers": handoff.get("knownBlockers"),
            "morningFirstActions": handoff.get("morningFirstActions"),
            "completedOfflineWork": handoff.get("completedOfflineWork"),
        }
        if handoff
        else None,
        "checks": [check.to_mapping() for check in checks],
        "notice": (
            "Offline PASS is not a hardware, provider, recording or release certification. "
            "Revalidate the physical system after the venue reopens."
        ),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + os.linesep, encoding="utf-8")
    temporary.replace(path)
