"""Person B — guest consent, enrolment and observation routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cue_api.main import create_app
from cue_api.settings import Settings

SECRET = "stage-zero-secret"
HEADERS = {"X-CUE-Bootstrap-Secret": SECRET}
EVENT = "hackmit-demo"
FIXTURES = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "fixtures"


def settings() -> Settings:
    return Settings(
        _env_file=None,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="test-api-key",
        livekit_api_secret="a-secure-test-secret-that-is-long-enough",
        cue_bootstrap_secret=SECRET,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=settings()))


def embedding(*, lead: float = 1.0, dimension: int = 128) -> list[float]:
    values = [0.0] * dimension
    values[0] = lead
    values[1] = 1.0 - abs(lead)
    return values


def enrol(client: TestClient, name: str = "Sarah", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "eventId": EVENT,
        "displayName": name,
        "aliases": [],
        "consentGranted": True,
        "consentPurposes": ["LIVE_IDENTIFICATION", "RECORDING", "CLOUD_RELAY"],
        "recordedBy": "B",
    }
    payload.update(overrides)
    response = client.post("/api/v1/guests", headers=HEADERS, json=payload)
    return {"status": response.status_code, "body": response.json()}


def enrolled_sarah(client: TestClient) -> str:
    created = enrol(client)
    guest_id = created["body"]["guestId"]
    client.post(
        f"/api/v1/guests/{guest_id}/references",
        headers=HEADERS,
        json={
            "eventId": EVENT,
            "embedding": embedding(),
            "quality": 0.8,
            "embedder": "opencv-sface",
            "embedderVersion": "2021dec",
            "capturedAtMs": 1758293400000,
        },
    )
    return guest_id


def test_guest_routes_require_the_operator_credential(client: TestClient) -> None:
    assert client.get("/api/v1/guests", params={"eventId": EVENT}).status_code == 401
    assert client.get("/api/v1/vision/gallery", params={"eventId": EVENT}).status_code == 401


def test_enrolment_without_consent_is_refused(client: TestClient) -> None:
    result = enrol(client, consentGranted=False)

    assert result["status"] == 403
    assert "consent" in result["body"]["detail"].lower()


def test_enrolment_needs_identification_consent_specifically(client: TestClient) -> None:
    result = enrol(client, consentPurposes=["RECORDING"])

    assert result["status"] == 403


def test_a_new_guest_starts_with_no_references(client: TestClient) -> None:
    result = enrol(client)

    assert result["status"] == 201
    assert result["body"]["status"] == "ENROLLING"
    assert result["body"]["referenceCount"] == 0
    assert result["body"]["storage"] == "MEMORY_ONLY"
    assert result["body"]["guestId"] == "guest-sarah"


def test_a_reference_activates_the_guest(client: TestClient) -> None:
    guest_id = enrolled_sarah(client)

    body = client.get("/api/v1/guests", headers=HEADERS, params={"eventId": EVENT}).json()
    guest = body["guests"][0]

    assert guest["guestId"] == guest_id
    assert guest["status"] == "ACTIVE"
    assert guest["referenceVersion"] == 1
    assert guest["meanReferenceQuality"] == pytest.approx(0.8)


def test_the_guest_list_never_carries_embeddings(client: TestClient) -> None:
    enrolled_sarah(client)

    raw = client.get("/api/v1/guests", headers=HEADERS, params={"eventId": EVENT}).text

    assert "embedding" not in raw.lower()


def test_a_mismatched_embedding_width_is_refused(client: TestClient) -> None:
    created = enrol(client)
    guest_id = created["body"]["guestId"]

    response = client.post(
        f"/api/v1/guests/{guest_id}/references",
        headers=HEADERS,
        json={
            "eventId": EVENT,
            "embedding": [0.1, 0.2, 0.3],
            "quality": 0.8,
            "embedder": "opencv-sface",
            "embedderVersion": "2021dec",
            "capturedAtMs": 1758293400000,
        },
    )

    assert response.status_code == 422
    assert "128-d" in response.json()["detail"]


def test_the_worker_gallery_only_holds_consenting_active_guests(client: TestClient) -> None:
    enrolled_sarah(client)
    enrol(client, name="Daniel")  # enrolled, but no reference yet

    gallery = client.get("/api/v1/vision/gallery", headers=HEADERS, params={"eventId": EVENT})
    body = gallery.json()

    assert [entry["guestId"] for entry in body["entries"]] == ["guest-sarah"]
    assert len(body["entries"][0]["embeddings"][0]) == 128


def test_withdrawal_deletes_the_references_and_reports_what_went(client: TestClient) -> None:
    guest_id = enrolled_sarah(client)

    receipt = client.delete(
        f"/api/v1/guests/{guest_id}",
        headers=HEADERS,
        params={"eventId": EVENT},
    ).json()

    assert receipt["referencesDeleted"] == 1
    assert receipt["guestIds"] == [guest_id]

    guest = client.get("/api/v1/guests", headers=HEADERS, params={"eventId": EVENT}).json()
    assert guest["guests"][0]["status"] == "WITHDRAWN"
    assert guest["guests"][0]["consent"]["granted"] is False
    assert guest["guests"][0]["referenceCount"] == 0

    gallery = client.get("/api/v1/vision/gallery", headers=HEADERS, params={"eventId": EVENT})
    assert gallery.json()["entries"] == []


def test_a_withdrawn_guest_cannot_be_re_enrolled_by_adding_a_reference(
    client: TestClient,
) -> None:
    guest_id = enrolled_sarah(client)
    client.delete(f"/api/v1/guests/{guest_id}", headers=HEADERS, params={"eventId": EVENT})

    response = client.post(
        f"/api/v1/guests/{guest_id}/references",
        headers=HEADERS,
        json={
            "eventId": EVENT,
            "embedding": embedding(),
            "quality": 0.9,
            "embedder": "opencv-sface",
            "embedderVersion": "2021dec",
            "capturedAtMs": 1758293400000,
        },
    )

    assert response.status_code == 403


def test_ending_the_event_purges_every_guest(client: TestClient) -> None:
    enrolled_sarah(client)
    enrol(client, name="Daniel")

    receipt = client.delete("/api/v1/guests", headers=HEADERS, params={"eventId": EVENT}).json()

    assert sorted(receipt["guestIds"]) == ["guest-daniel", "guest-sarah"]
    listed = client.get("/api/v1/guests", headers=HEADERS, params={"eventId": EVENT}).json()
    assert listed["guests"] == []


def test_events_are_isolated_from_one_another(client: TestClient) -> None:
    enrolled_sarah(client)

    other = client.get(
        "/api/v1/guests",
        headers=HEADERS,
        params={"eventId": "another-event"},
    ).json()

    assert other["guests"] == []


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text("utf-8"))


def test_the_enrolment_fixture_is_accepted_verbatim(client: TestClient) -> None:
    response = client.post(
        "/api/v1/guests",
        headers=HEADERS,
        json=fixture("guest-enrolment-request.json"),
    )

    assert response.status_code == 201
    assert response.json()["guestId"] == "guest-sarah"


def test_a_refused_consent_is_rejected_over_the_wire(client: TestClient) -> None:
    response = client.post(
        "/api/v1/guests",
        headers=HEADERS,
        json=fixture("guest-enrolment-request.consent-refused.json"),
    )

    assert response.status_code == 403
    assert client.get("/api/v1/guests", headers=HEADERS, params={"eventId": EVENT}).json()[
        "guests"
    ] == []


def test_consent_to_filming_alone_is_rejected_over_the_wire(client: TestClient) -> None:
    response = client.post(
        "/api/v1/guests",
        headers=HEADERS,
        json=fixture("guest-enrolment-request.recording-only.json"),
    )

    assert response.status_code == 403
    assert "Live identification" in response.json()["detail"]


def test_the_reference_fixture_is_accepted_and_normalised(client: TestClient) -> None:
    client.post("/api/v1/guests", headers=HEADERS, json=fixture("guest-enrolment-request.json"))

    response = client.post(
        "/api/v1/guests/guest-sarah/references",
        headers=HEADERS,
        json=fixture("reference-submission.json"),
    )

    assert response.status_code == 201
    assert response.json()["status"] == "ACTIVE"

    gallery = client.get(
        "/api/v1/vision/gallery",
        headers=HEADERS,
        params={"eventId": EVENT},
    ).json()
    vector = gallery["entries"][0]["embeddings"][0]
    assert sum(value * value for value in vector) == pytest.approx(1.0)
    assert vector[0] == pytest.approx(0.6)
