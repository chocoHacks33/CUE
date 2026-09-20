from __future__ import annotations

import json

from cue_api.morning_preflight import (
    FAIL,
    INCOMPLETE,
    PASS,
    Check,
    HttpResult,
    make_report,
    probe_live_api,
    validate_evidence,
)


def valid_evidence(commit: str = "abc123") -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "testedCommit": commit,
        "releaseMode": "ROLE_BASED_ASSIST",
        "stage6HandoffReviewed": True,
        "venue": {
            "assignedJudgingLocation": "Room 32-123",
            "announcementsCheckedAtUtc": "2026-09-20T12:00:00Z",
            "evidence": "private/stage7/venue.png",
            "powerAccessConfirmed": True,
            "allDeviceChargersPresent": True,
            "cableTripHazardPlanConfirmed": True,
        },
        "network": {
            "apiBaseUrl": "https://cue.example.invalid",
            "eventId": "hackmit-2026",
        },
        "reconnect": {
            "cameraHostReconnectObserved": True,
            "returnsToAssist": True,
            "evidence": "private/stage7/reconnect.json",
        },
        "acknowledgements": {
            "exactCommitConfirmed": True,
            "noUnverifiedHardwareClaims": True,
            "limitationsUpdatedIfNeeded": True,
        },
    }


def test_valid_evidence_is_bound_to_head() -> None:
    assert validate_evidence(valid_evidence(), "abc123").status == PASS
    mismatch = validate_evidence(valid_evidence(), "different")
    assert mismatch.status == INCOMPLETE
    assert "does not equal HEAD" in mismatch.detail


def test_stage6_venue_power_and_physical_reconnect_are_required() -> None:
    value = valid_evidence()
    value["stage6HandoffReviewed"] = False
    value["venue"]["powerAccessConfirmed"] = False  # type: ignore[index]
    value["reconnect"]["cameraHostReconnectObserved"] = False  # type: ignore[index]
    result = validate_evidence(value, "abc123")
    assert result.status == INCOMPLETE
    assert "stage6HandoffReviewed" in result.detail
    assert "powerAccessConfirmed" in result.detail
    assert "cameraHostReconnectObserved" in result.detail


def test_evidence_rejects_secret_like_fields() -> None:
    value = valid_evidence()
    value["apiKey"] = "must-not-be-recorded"
    result = validate_evidence(value, "abc123")
    assert result.status == INCOMPLETE
    assert "forbidden" in result.detail


def test_live_probe_checks_health_topology_auth_and_session_reissue() -> None:
    calls: list[tuple[str, str, dict[str, str], dict[str, object] | None]] = []
    issued = 0

    def requester(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResult:
        nonlocal issued
        del timeout
        payload = json.loads(body) if body else None
        calls.append((method, url, headers, payload))
        if url.endswith("/health/live"):
            return HttpResult(200, {"status": "ok", "livekitConfigured": True})
        if url.endswith("/health/ready"):
            return HttpResult(200, {"status": "ready", "livekitConfigured": True})
        if url.endswith("/api/v1/topology"):
            return HttpResult(
                200,
                {
                    "cameras": [
                        {"cameraId": "CAM-HOST"},
                        {"cameraId": "CAM-GUEST"},
                        {"cameraId": "CAM-WIDE"},
                    ]
                },
            )
        if "X-CUE-Bootstrap-Secret" not in headers:
            return HttpResult(401, {"detail": "unauthorized"})
        issued += 1
        return HttpResult(
            201,
            {
                "participantToken": f"private-token-{issued}",
                "participantIdentity": f"receiver:director:{issued}",
                "receiverRole": "DIRECTOR",
                "roomName": "cue-hackmit-2026",
            },
        )

    secret = "a-private-bootstrap-secret"
    results = probe_live_api(
        "https://cue.example.invalid/",
        "hackmit-2026",
        secret,
        requester=requester,
    )
    assert len(results) == 6
    assert all(result.status == PASS for result in results)
    assert all(secret not in result.detail for result in results)
    assert all("private-token" not in result.detail for result in results)
    assert len(calls) == 6
    assert all(
        headers["ngrok-skip-browser-warning"] == "cue-stage7-preflight"
        for _, _, headers, _ in calls
    )


def test_live_probe_fails_when_missing_auth_is_accepted() -> None:
    def requester(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResult:
        del method, headers, body, timeout
        if url.endswith("/health/live"):
            return HttpResult(200, {"status": "ok"})
        if url.endswith("/health/ready"):
            return HttpResult(200, {"status": "ready", "livekitConfigured": True})
        if url.endswith("/api/v1/topology"):
            return HttpResult(
                200,
                {"cameras": [{"cameraId": camera} for camera in sorted((
                    "CAM-HOST", "CAM-GUEST", "CAM-WIDE"
                ))]},
            )
        return HttpResult(201, {})

    results = probe_live_api(
        "https://cue.invalid",
        "hackmit-2026",
        "long-enough-secret",
        requester=requester,
    )
    assert next(result for result in results if result.name == "auth-guard").status == FAIL


def test_report_never_certifies_the_whole_system() -> None:
    report = make_report(
        "abc123",
        "codex/person-a-stage-7-prep",
        [Check("A", PASS, "done")],
        valid_evidence(),
    )
    assert report["status"] == PASS
    assert report["personAReady"] is True
    assert report["systemValidated"] is False
    assert report["hardwareValidated"] is False
    assert report["releaseCertified"] is False


def test_failure_takes_priority_over_incomplete() -> None:
    report = make_report(
        "abc123",
        "branch",
        [Check("physical", INCOMPLETE, "not run"), Check("auth", FAIL, "failed")],
        None,
    )
    assert report["status"] == FAIL
