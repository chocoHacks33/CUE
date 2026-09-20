"""`GET /api/v1/guests/readiness` — the exit gate as the product sees it.

Stage 4's gate says the ASSIST fallback must be *disclosed*. A disclosure that
lives only in a document is not disclosed to anyone watching, so it has to be
reachable by D's panel. These tests cover that surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cue_api.guests.calibration_store import save
from cue_api.guests.confidence_calibration import PROVISIONAL_CALIBRATION, Calibration
from cue_api.guests.identity_eval import NegativeTrial, PositiveTrial, summarise
from cue_api.guests.identity_evidence import Attestation, AttestationError, IdentityEvidence, gather
from cue_api.guests.types import CalibrationStatus
from cue_api.main import create_app
from cue_api.settings import Settings

SECRET = "stage-zero-secret"
HEADERS = {"X-CUE-Bootstrap-Secret": SECRET}
EVENT = "hackmit-demo"

MEASURED = Calibration(
    calibration_id="held-out-2026-09-19",
    status=CalibrationStatus.MEASURED,
    slope=11.4,
    intercept=-4.2,
    sample_count=60,
)


def settings() -> Settings:
    return Settings(
        _env_file=None,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="test-api-key",
        livekit_api_secret="a-secure-test-secret-that-is-long-enough",
        cue_bootstrap_secret=SECRET,
    )


def clean_report(wrong_person: int = 0):
    good = [
        PositiveTrial("guest-sarah", "guest-sarah", "CONFIRMED", 600)
        for _ in range(30 - wrong_person)
    ]
    bad = [
        PositiveTrial("guest-sarah", "guest-daniel", "CONFIRMED", 600)
        for _ in range(wrong_person)
    ]
    return summarise(
        good + bad,
        [NegativeTrial(f"unenrolled-{i}", None, "UNKNOWN") for i in range(30)],
    )


def client_with(evidence: IdentityEvidence | None = None) -> TestClient:
    supplied = evidence or IdentityEvidence(calibration=PROVISIONAL_CALIBRATION)
    return TestClient(
        create_app(settings=settings(), identity_evidence=lambda: supplied)
    )


def readiness(client: TestClient) -> dict:
    response = client.get(
        "/api/v1/guests/readiness", headers=HEADERS, params={"eventId": EVENT}
    )
    assert response.status_code == 200
    return response.json()


def everything() -> IdentityEvidence:
    return IdentityEvidence(
        calibration=MEASURED,
        report=clean_report(),
        mac_runtime_gate=Attestation("D", "docs/results/b-media-check.md"),
        media_checks=Attestation("B", "docs/results/b-media-check.md"),
    )


# -- what the route says today --------------------------------------------


def test_with_no_evidence_the_route_reports_role_based() -> None:
    body = readiness(client_with())

    assert body["namingPolicy"] == "ROLE_BASED"
    assert body["roleBased"] is True
    assert body["unattendedNamingPermitted"] is False
    assert body["calibrationStatus"] == "PROVISIONAL_DEFAULT"
    assert "Nothing on screen is identified by face" in body["disclosure"]
    assert len(body["blockingReasons"]) == 4
    assert body["attestations"] == {}


def test_the_disclosure_is_never_empty_in_any_state() -> None:
    for evidence in (
        IdentityEvidence(calibration=PROVISIONAL_CALIBRATION),
        IdentityEvidence(calibration=PROVISIONAL_CALIBRATION, report=clean_report()),
        everything(),
    ):
        assert readiness(client_with(evidence))["disclosure"].strip()


def test_the_payload_is_camel_case_for_the_browser() -> None:
    body = readiness(client_with())

    assert "namingPolicy" in body
    assert "naming_policy" not in body
    assert body["guestContractVersion"] == "0.1.0"


def test_readiness_needs_the_operator_credential() -> None:
    response = client_with().get("/api/v1/guests/readiness", params={"eventId": EVENT})

    assert response.status_code == 401


# -- the gate, through the route ------------------------------------------


def test_full_evidence_reports_named_auto_with_its_attestations() -> None:
    body = readiness(client_with(everything()))

    assert body["namingPolicy"] == "NAMED_AUTO"
    assert body["roleBased"] is False
    assert body["unattendedNamingPermitted"] is True
    assert body["blockingReasons"] == []
    assert body["attestations"]["macRuntimeGate"].startswith("D — ")
    assert "b-media-check.md" in body["attestations"]["mediaChecks"]


def test_one_wrong_name_reports_role_based_through_the_route() -> None:
    evidence = IdentityEvidence(
        calibration=MEASURED,
        report=clean_report(wrong_person=1),
        mac_runtime_gate=Attestation("D", "docs/results/b-media-check.md"),
        media_checks=Attestation("B", "docs/results/b-media-check.md"),
    )

    body = readiness(client_with(evidence))

    assert body["namingPolicy"] == "ROLE_BASED"
    assert any("wrong name" in reason for reason in body["blockingReasons"])


def test_a_missing_attestation_downgrades_to_assist() -> None:
    evidence = IdentityEvidence(
        calibration=MEASURED,
        report=clean_report(),
        mac_runtime_gate=Attestation("D", "docs/results/b-media-check.md"),
        media_checks=None,
    )

    body = readiness(client_with(evidence))

    assert body["namingPolicy"] == "NAMED_ASSIST"
    assert body["unattendedNamingPermitted"] is False
    assert "operator confirms" in body["disclosure"]
    assert "macRuntimeGate" in body["attestations"]
    assert "mediaChecks" not in body["attestations"]


def test_the_route_never_reports_unattended_naming_outside_named_auto() -> None:
    """The contradiction D's parser refuses must never be produced here."""
    for evidence in (
        IdentityEvidence(calibration=PROVISIONAL_CALIBRATION),
        IdentityEvidence(calibration=MEASURED, report=clean_report()),
        IdentityEvidence(calibration=PROVISIONAL_CALIBRATION, report=clean_report()),
    ):
        body = readiness(client_with(evidence))
        if body["namingPolicy"] != "NAMED_AUTO":
            assert body["unattendedNamingPermitted"] is False


# -- attestations are not bare booleans -----------------------------------


def test_an_attestation_must_name_who_ran_the_check() -> None:
    with pytest.raises(AttestationError, match="who ran the check"):
        Attestation("  ", "docs/results/b-media-check.md")


def test_an_attestation_must_point_at_something_readable() -> None:
    with pytest.raises(AttestationError, match="nothing to read"):
        Attestation("D", "")


# -- reading the calibration off disk -------------------------------------


def test_gather_falls_back_to_the_provisional_anchor(tmp_path: Path) -> None:
    evidence = gather(calibration_path=tmp_path / "absent.json")

    assert evidence.calibration.status is CalibrationStatus.PROVISIONAL_DEFAULT
    assert evidence.mac_runtime_gate_passed is False
    assert evidence.media_checks_passed is False


def test_gather_picks_up_a_calibration_that_is_on_disk(tmp_path: Path) -> None:
    path = tmp_path / "calibration.json"
    save(MEASURED, path, dataset_note="held-out set A")

    evidence = gather(calibration_path=path)

    assert evidence.calibration.status is CalibrationStatus.MEASURED
    assert evidence.calibration.sample_count == 60
