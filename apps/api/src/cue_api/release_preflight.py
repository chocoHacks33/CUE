"""Fail-closed Stage 5 release preflight.

This module prepares a release manifest but never creates a Git tag. A human
must review the manifest before tagging the exact tested commit.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PASS = "PASS"
FAIL = "FAIL"
INCOMPLETE = "INCOMPLETE"
OWNER_NAMES = ("A", "B", "C", "D")
REQUIRED_ENV = (
    "OPENAI_API_KEY",
    "DEEPGRAM_API_KEY",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "CUE_MODEL",
    "CUE_BOOTSTRAP_SECRET",
    "CUE_PRODUCER_SECRET",
    "VITE_API_BASE_URL",
)
REQUIRED_FILES = (
    "package.json",
    "package-lock.json",
    "apps/api/pyproject.toml",
    "apps/api/src/cue_api/main.py",
    "apps/web/package.json",
    "docs/CUE_HackMIT_2026_Plan_v3_Laptop_Cameras_Mac_Server.md",
)
PLACEHOLDER_MARKERS = ("replace", "todo", "example", "your-project", "<", ">")


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str

    def to_mapping(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values


def check_environment(path: Path) -> Check:
    values = parse_env_file(path)
    if not values:
        return Check("environment", INCOMPLETE, f"missing configuration file: {path}")
    missing = [name for name in REQUIRED_ENV if not values.get(name, "").strip()]
    placeholders = [
        name
        for name in REQUIRED_ENV
        if values.get(name)
        and any(marker in values[name].lower() for marker in PLACEHOLDER_MARKERS)
    ]
    problems: list[str] = []
    if missing:
        problems.append("missing " + ", ".join(missing))
    if placeholders:
        problems.append("placeholder value in " + ", ".join(placeholders))
    if values.get("CUE_PROVIDER", "openai").strip().lower() != "openai":
        problems.append("CUE_PROVIDER must be openai for this release")
    bootstrap = values.get("CUE_BOOTSTRAP_SECRET", "")
    producer = values.get("CUE_PRODUCER_SECRET", "")
    if bootstrap and producer and bootstrap == producer:
        problems.append("bootstrap and producer secrets must differ")
    if problems:
        return Check("environment", FAIL, "; ".join(problems))
    return Check("environment", PASS, "required variables are populated; values were not logged")


def check_approval(path: Path, expected_commit: str) -> Check:
    if not path.is_file():
        return Check("release-approval", INCOMPLETE, f"missing approval file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return Check(
            "release-approval",
            FAIL,
            f"approval file is unreadable: {type(error).__name__}",
        )
    if not isinstance(value, dict):
        return Check("release-approval", FAIL, "approval document must be a JSON object")

    problems: list[str] = []
    if value.get("schemaVersion") != 1:
        problems.append("schemaVersion must be 1")
    if value.get("testedCommit") != expected_commit:
        problems.append("testedCommit does not equal HEAD")
    tag = value.get("releaseTag")
    if not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,63}", tag):
        problems.append("releaseTag is missing or invalid")

    gates = value.get("stage4Gates")
    if not isinstance(gates, dict):
        problems.append("stage4Gates is missing")
    else:
        for owner in OWNER_NAMES:
            gate = gates.get(owner)
            if not isinstance(gate, dict) or gate.get("status") != PASS:
                problems.append(f"Stage 4 owner {owner} is not PASS")
            elif not _meaningful_text(gate.get("evidence")):
                problems.append(f"Stage 4 owner {owner} has no evidence reference")

    _require_true_fields(
        value.get("macValidation"),
        "macValidation",
        ("cleanStartup", "threeFeeds", "recordingPlayback", "runbookVerified"),
        problems,
    )
    _require_true_fields(
        value.get("submission"),
        "submission",
        ("saved", "reopenedAndVerified", "allMembersVerified", "trackVerified"),
        problems,
    )
    _require_true_fields(value.get("ownerSignoffs"), "ownerSignoffs", OWNER_NAMES, problems)
    if value.get("limitationsReviewed") is not True:
        problems.append("limitationsReviewed is not true")

    if problems:
        return Check("release-approval", INCOMPLETE, "; ".join(problems))
    return Check(
        "release-approval",
        PASS,
        "all gates, Mac checks, submission checks and sign-offs pass",
    )


def _meaningful_text(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    lowered = value.strip().lower()
    return not any(marker in lowered for marker in ("todo", "replace", "pending"))


def _require_true_fields(
    value: object,
    section: str,
    fields: tuple[str, ...],
    problems: list[str],
) -> None:
    if not isinstance(value, dict):
        problems.append(f"{section} is missing")
        return
    for field in fields:
        if value.get(field) is not True:
            problems.append(f"{section}.{field} is not true")


def run_command(
    command: list[str], cwd: Path, timeout: int = 300
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def git_value(repo_root: Path, *arguments: str) -> str:
    result = run_command(["git", *arguments], repo_root, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def inspect_git(repo_root: Path) -> tuple[str, list[Check]]:
    try:
        commit = git_value(repo_root, "rev-parse", "HEAD")
        branch = git_value(repo_root, "branch", "--show-current")
        dirty = git_value(repo_root, "status", "--porcelain", "--untracked-files=all")
        remote_contains = git_value(repo_root, "branch", "-r", "--contains", commit)
        tracked = git_value(repo_root, "ls-files").splitlines()
    except RuntimeError as error:
        return "UNKNOWN", [Check("git", FAIL, str(error))]

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
            "HEAD exists on origin"
            if "origin/" in remote_contains
            else "push the tested HEAD first",
        ),
    ]
    unsafe = [
        path
        for path in tracked
        if path == ".env"
        or path.startswith(("recordings/", "artifacts/", "models/"))
        or path.endswith(".onnx")
    ]
    checks.append(
        Check(
            "tracked-private-files",
            PASS if not unsafe else FAIL,
            "no private runtime artifacts are tracked"
            if not unsafe
            else "unsafe tracked paths: " + ", ".join(unsafe[:8]),
        )
    )
    return commit, checks


def inspect_runtime(repo_root: Path) -> list[Check]:
    checks: list[Check] = []
    python_ok = sys.version_info >= (3, 11)
    checks.append(
        Check(
            "python-version",
            PASS if python_ok else FAIL,
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
    )
    node = shutil.which("node")
    if not node:
        checks.append(Check("node-version", FAIL, "node executable not found"))
    else:
        result = run_command([node, "--version"], repo_root, timeout=30)
        match = re.fullmatch(r"v(\d+)\.\d+\.\d+", result.stdout.strip())
        major = int(match.group(1)) if match else 0
        supported = major in (20, 22) or major >= 24
        checks.append(
            Check(
                "node-version",
                PASS if result.returncode == 0 and supported else FAIL,
                result.stdout.strip() or "could not read Node.js version",
            )
        )
    missing = [path for path in REQUIRED_FILES if not (repo_root / path).is_file()]
    checks.append(
        Check(
            "release-files",
            PASS if not missing else FAIL,
            "required source and lock files exist"
            if not missing
            else "missing " + ", ".join(missing),
        )
    )
    return checks


def run_validation_suite(repo_root: Path) -> list[Check]:
    npm = shutil.which("npm") or shutil.which("npm.cmd") or "npm"
    commands = (
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
    checks: list[Check] = []
    for name, command, cwd in commands:
        started = time.perf_counter()
        try:
            result = run_command(command, cwd)
            elapsed = time.perf_counter() - started
            detail = f"exit {result.returncode} in {elapsed:.1f}s"
            checks.append(Check(name, PASS if result.returncode == 0 else FAIL, detail))
        except (OSError, subprocess.TimeoutExpired) as error:
            checks.append(Check(name, FAIL, type(error).__name__))
    return checks


def run_provider_smoke(repo_root: Path) -> Check:
    try:
        result = run_command([sys.executable, "scripts/smoke_api.py"], repo_root, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        return Check("provider-smoke", FAIL, type(error).__name__)
    return Check(
        "provider-smoke",
        PASS if result.returncode == 0 else FAIL,
        "OpenAI and Deepgram authenticated" if result.returncode == 0 else "provider smoke failed",
    )


def run_api_startup_smoke(repo_root: Path, timeout_s: float = 15.0) -> Check:
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "cue_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=repo_root / "apps/api",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return Check("api-clean-start", FAIL, f"API exited with {process.returncode}")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health/ready", timeout=1
                ) as response:
                    if response.status == 200:
                        return Check("api-clean-start", PASS, "fresh process reached ready")
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.2)
        return Check("api-clean-start", FAIL, "API did not become ready before timeout")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def make_manifest(commit: str, checks: list[Check]) -> dict[str, Any]:
    if any(check.status == FAIL for check in checks):
        status = FAIL
    elif any(check.status == INCOMPLETE for check in checks):
        status = INCOMPLETE
    else:
        status = PASS
    return {
        "schemaVersion": 1,
        "status": status,
        "releaseReady": status == PASS,
        "commit": commit,
        "generatedAtUnixMs": int(time.time() * 1_000),
        "platform": sys.platform,
        "checks": [check.to_mapping() for check in checks],
        "notice": (
            "Review this manifest before manually tagging the exact commit. "
            "The preflight never creates or pushes a tag."
        ),
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + os.linesep, encoding="utf-8")
    temporary.replace(path)
