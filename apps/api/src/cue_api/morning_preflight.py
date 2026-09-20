"""Fail-closed Person A Stage 7 morning preflight.

The report covers A's exact commit, venue/power confirmation and API/auth
reachability. It deliberately does not certify cameras, audio, recording or the
overall release; those require the real four-laptop system and D's checks.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cue_api.release_preflight import FAIL, INCOMPLETE, PASS, Check, git_value

RELEASE_MODES = ("ROLE_BASED_ASSIST", "NAMED_ASSIST", "NAMED_AUTO")
CAMERAS = {"CAM-HOST", "CAM-GUEST", "CAM-WIDE"}
FORBIDDEN_KEY = re.compile(r"(api.?key|secret|password|credential|access.?token)", re.I)
EVENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,47}$")


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: dict[str, Any] | None


Requester = Callable[[str, str, dict[str, str], bytes | None, float], HttpResult]


def _meaningful(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    lowered = value.strip().lower()
    return not any(marker in lowered for marker in ("todo", "replace", "pending", "tbd"))


def _utc_time(value: object) -> bool:
    if not _meaningful(value):
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


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


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"preflight evidence is unreadable: {type(error).__name__}") from error
    if not isinstance(value, dict):
        raise ValueError("preflight evidence must be a JSON object")
    return value


def validate_evidence(value: dict[str, Any], expected_commit: str) -> Check:
    problems: list[str] = []
    if value.get("schemaVersion") != 1:
        problems.append("schemaVersion must be 1")
    if value.get("testedCommit") != expected_commit:
        problems.append("testedCommit does not equal HEAD")
    if value.get("releaseMode") not in RELEASE_MODES:
        problems.append("releaseMode is missing or invalid")
    if value.get("stage6HandoffReviewed") is not True:
        problems.append("stage6HandoffReviewed is not true")

    venue = value.get("venue")
    if not isinstance(venue, dict):
        problems.append("venue is missing")
    else:
        if not _meaningful(venue.get("assignedJudgingLocation")):
            problems.append("venue.assignedJudgingLocation is missing")
        if not _utc_time(venue.get("announcementsCheckedAtUtc")):
            problems.append("venue.announcementsCheckedAtUtc is not a timezone-aware time")
        if not _meaningful(venue.get("evidence")):
            problems.append("venue.evidence is missing")
        for field in (
            "powerAccessConfirmed",
            "allDeviceChargersPresent",
            "cableTripHazardPlanConfirmed",
        ):
            if venue.get(field) is not True:
                problems.append(f"venue.{field} is not true")

    network = value.get("network")
    if not isinstance(network, dict):
        problems.append("network is missing")
    else:
        base_url = network.get("apiBaseUrl")
        parsed = urllib.parse.urlparse(base_url if isinstance(base_url, str) else "")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            problems.append("network.apiBaseUrl must be an http(s) URL")
        if not isinstance(network.get("eventId"), str) or not EVENT_ID.fullmatch(
            network["eventId"]
        ):
            problems.append("network.eventId is missing or invalid")

    reconnect = value.get("reconnect")
    if not isinstance(reconnect, dict):
        problems.append("reconnect is missing")
    else:
        if reconnect.get("cameraHostReconnectObserved") is not True:
            problems.append("reconnect.cameraHostReconnectObserved is not true")
        if reconnect.get("returnsToAssist") is not True:
            problems.append("reconnect.returnsToAssist is not true")
        if not _meaningful(reconnect.get("evidence")):
            problems.append("reconnect.evidence is missing")

    acknowledgements = value.get("acknowledgements")
    for field in (
        "exactCommitConfirmed",
        "noUnverifiedHardwareClaims",
        "limitationsUpdatedIfNeeded",
    ):
        if not isinstance(acknowledgements, dict) or acknowledgements.get(field) is not True:
            problems.append(f"acknowledgements.{field} is not true")

    forbidden = _find_forbidden_key(value)
    if forbidden:
        problems.append(f"preflight evidence contains forbidden secret-like field: {forbidden}")
    if problems:
        return Check("stage7-evidence", INCOMPLETE, "; ".join(problems))
    return Check("stage7-evidence", PASS, "exact commit, venue, power and reconnect are recorded")


def inspect_repository(repo_root: Path) -> tuple[str, str, list[Check]]:
    try:
        commit = git_value(repo_root, "rev-parse", "HEAD")
        branch = git_value(repo_root, "branch", "--show-current")
        dirty = git_value(repo_root, "status", "--porcelain", "--untracked-files=all")
        remote_contains = git_value(repo_root, "branch", "-r", "--contains", commit)
    except RuntimeError as error:
        return "UNKNOWN", "UNKNOWN", [Check("git", FAIL, str(error))]
    return commit, branch, [
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


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> HttpResult:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            parsed = json.loads(payload) if payload else None
            return HttpResult(response.status, parsed if isinstance(parsed, dict) else None)
    except urllib.error.HTTPError as error:
        payload = error.read()
        try:
            parsed = json.loads(payload) if payload else None
        except json.JSONDecodeError:
            parsed = None
        return HttpResult(error.code, parsed if isinstance(parsed, dict) else None)


def _call(
    requester: Requester,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float,
) -> HttpResult | None:
    encoded = json.dumps(payload).encode("utf-8") if payload is not None else None
    merged_headers = {
        "Accept": "application/json",
        "User-Agent": "CUE-Stage7-Preflight/1",
        "ngrok-skip-browser-warning": "cue-stage7-preflight",
        **(headers or {}),
    }
    if encoded is not None:
        merged_headers["Content-Type"] = "application/json"
    try:
        return requester(method, url, merged_headers, encoded, timeout)
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        return None


def probe_live_api(
    base_url: str,
    event_id: str,
    bootstrap_secret: str,
    *,
    requester: Requester = request_json,
    timeout: float = 5.0,
) -> list[Check]:
    base = base_url.rstrip("/")
    checks: list[Check] = []

    live = _call(requester, "GET", f"{base}/health/live", timeout=timeout)
    live_ok = bool(
        live and live.status == 200 and live.body and live.body.get("status") == "ok"
    )
    checks.append(
        Check(
            "api-live",
            PASS if live_ok else FAIL,
            "API answered health/live" if live_ok else "API health/live did not pass",
        )
    )
    ready = _call(requester, "GET", f"{base}/health/ready", timeout=timeout)
    ready_ok = bool(
        ready
        and ready.status == 200
        and ready.body
        and ready.body.get("status") == "ready"
        and ready.body.get("livekitConfigured") is True
    )
    checks.append(
        Check(
            "api-ready",
            PASS if ready_ok else FAIL,
            "API and LiveKit configuration are ready" if ready else "API readiness was unreachable",
        )
    )
    topology = _call(requester, "GET", f"{base}/api/v1/topology", timeout=timeout)
    camera_ids = {
        camera.get("cameraId")
        for camera in (topology.body.get("cameras", []) if topology and topology.body else [])
        if isinstance(camera, dict)
    }
    checks.append(
        Check(
            "camera-topology",
            PASS if topology and topology.status == 200 and camera_ids == CAMERAS else FAIL,
            "three fixed camera IDs are present" if camera_ids == CAMERAS else "camera IDs differ",
        )
    )

    token_url = f"{base}/api/v1/stage0/receiver-token"
    token_request = {
        "eventId": event_id,
        "displayName": "Stage 7 preflight",
        "receiverRole": "DIRECTOR",
    }
    refused = _call(requester, "POST", token_url, payload=token_request, timeout=timeout)
    auth_guard_ok = bool(refused and refused.status == 401)
    checks.append(
        Check(
            "auth-guard",
            PASS if auth_guard_ok else FAIL,
            "missing admission secret was refused"
            if auth_guard_ok
            else "missing admission secret was not refused with 401",
        )
    )
    auth_headers = {"X-CUE-Bootstrap-Secret": bootstrap_secret}
    first = _call(
        requester,
        "POST",
        token_url,
        headers=auth_headers,
        payload=token_request,
        timeout=timeout,
    )
    second = _call(
        requester,
        "POST",
        token_url,
        headers=auth_headers,
        payload=token_request,
        timeout=timeout,
    )

    def valid_token(result: HttpResult | None) -> bool:
        return bool(
            result
            and result.status == 201
            and result.body
            and result.body.get("participantToken")
            and result.body.get("participantIdentity")
            and result.body.get("receiverRole") == "DIRECTOR"
        )

    checks.append(
        Check(
            "auth-success",
            PASS if valid_token(first) else FAIL,
            "valid secret issued a subscribe-only receiver session"
            if valid_token(first)
            else "valid receiver admission failed",
        )
    )
    reissued = bool(
        valid_token(first)
        and valid_token(second)
        and first
        and second
        and first.body
        and second.body
        and first.body.get("participantIdentity") != second.body.get("participantIdentity")
        and first.body.get("roomName") == second.body.get("roomName")
    )
    checks.append(
        Check(
            "receiver-session-reissue",
            PASS if reissued else FAIL,
            "fresh receiver identity issued for the same event"
            if reissued
            else "receiver session was not safely reissued",
        )
    )
    return checks


def make_report(
    commit: str,
    branch: str,
    checks: list[Check],
    evidence: dict[str, Any] | None,
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
        "personAReady": status == PASS,
        "systemValidated": False,
        "hardwareValidated": False,
        "releaseCertified": False,
        "commit": commit,
        "branch": branch,
        "generatedAtUnixMs": int(time.time() * 1_000),
        "releaseMode": evidence.get("releaseMode") if evidence else None,
        "checks": [check.to_mapping() for check in checks],
        "notice": (
            "Person A PASS covers only A's Stage 7 preflight. B/C/D physical checks and "
            "D's final soak/recording gate remain required."
        ),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + os.linesep, encoding="utf-8")
    temporary.replace(path)
