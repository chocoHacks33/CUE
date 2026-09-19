"""Stage 4's consent/deletion test, driven through the real routes.

The other guest tests check individual rules. This one plays the scenario that
matters if anybody asks the uncomfortable question on the night: a guest consents,
is enrolled, is recognised live, then withdraws — and afterwards **nothing about
them is left anywhere the system can reach**.

Every assertion here goes through the HTTP API rather than poking the registry, so
it covers the paths an operator would actually use under pressure.
"""

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


@pytest.fixture
def client() -> TestClient:
    return TestClient(
        create_app(
            settings=Settings(
                _env_file=None,
                livekit_url="wss://example.livekit.cloud",
                livekit_api_key="test-api-key",
                livekit_api_secret="a-secure-test-secret-that-is-long-enough",
                cue_bootstrap_secret=SECRET,
            )
        )
    )


def embedding(lead: float = 1.0, dimension: int = 128) -> list[float]:
    values = [0.0] * dimension
    values[0] = lead
    values[1] = 1.0 - abs(lead)
    return values


def observation_payload(**overrides: Any) -> dict[str, Any]:
    payload = json.loads((FIXTURES / "visual-observation.confirmed.json").read_text("utf-8"))
    payload.update(overrides)
    return payload


def enrol_and_recognise(client: TestClient, name: str = "Sarah") -> str:
    """Take one guest all the way to being named in live evidence."""
    created = client.post(
        "/api/v1/guests",
        headers=HEADERS,
        json={
            "eventId": EVENT,
            "displayName": name,
            "aliases": [],
            "consentGranted": True,
            "consentPurposes": ["LIVE_IDENTIFICATION", "RECORDING", "CLOUD_RELAY"],
            "recordedBy": "B",
        },
    )
    assert created.status_code == 201
    guest_id = created.json()["guestId"]

    reference = client.post(
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
    assert reference.status_code == 201

    observed = client.post(
        "/api/v1/guests/observations", headers=HEADERS, json=observation_payload()
    )
    assert observed.status_code == 202
    return guest_id


def snapshot(client: TestClient) -> dict[str, Any]:
    return client.get(
        "/api/v1/guests/observations", headers=HEADERS, params={"eventId": EVENT}
    ).json()


def gallery(client: TestClient) -> dict[str, Any]:
    return client.get(
        "/api/v1/guests/gallery", headers=HEADERS, params={"eventId": EVENT}
    ).json()


# -- the scenario ----------------------------------------------------------


def test_a_withdrawal_leaves_nothing_the_system_can_reach(client: TestClient) -> None:
    guest_id = enrol_and_recognise(client)

    # Before: the guest is enrolled, in the worker gallery, and named live.
    assert any(entry["guestId"] == guest_id for entry in gallery(client)["entries"])
    named_before = [
        view["observation"]["subject"]["guestId"]
        for view in snapshot(client)["cameras"]
        if view["observation"] is not None
    ]
    assert guest_id in named_before

    receipt = client.delete(
        f"/api/v1/guests/{guest_id}", headers=HEADERS, params={"eventId": EVENT}
    )

    assert receipt.status_code == 200
    body = receipt.json()
    assert body["guestIds"] == [guest_id]
    assert body["referencesDeleted"] >= 1
    assert body["observationsDropped"] >= 1

    # After: gone from the gallery, gone from live evidence, and still listed only
    # as a withdrawn record with no consent and no references.
    assert all(entry["guestId"] != guest_id for entry in gallery(client)["entries"])
    assert all(view["observation"] is None for view in snapshot(client)["cameras"])

    listed = client.get("/api/v1/guests", headers=HEADERS, params={"eventId": EVENT}).json()
    record = next(guest for guest in listed["guests"] if guest["guestId"] == guest_id)
    assert record["status"] == "WITHDRAWN"
    assert record["consent"]["granted"] is False
    assert record["consent"]["withdrawnAtMs"] is not None
    assert record["referenceCount"] == 0


def test_a_withdrawal_is_observable_not_merely_promised(client: TestClient) -> None:
    """The receipt is the evidence a guest can be shown."""
    guest_id = enrol_and_recognise(client)

    body = client.delete(
        f"/api/v1/guests/{guest_id}", headers=HEADERS, params={"eventId": EVENT}
    ).json()

    assert set(body) >= {
        "eventId",
        "guestIds",
        "referencesDeleted",
        "observationsDropped",
        "purgedAtMs",
    }
    assert body["purgedAtMs"] > 0


def test_a_withdrawn_guest_cannot_be_named_again_by_a_late_observation(
    client: TestClient,
) -> None:
    """Evidence already in flight must not resurrect a name."""
    guest_id = enrol_and_recognise(client)
    client.delete(f"/api/v1/guests/{guest_id}", headers=HEADERS, params={"eventId": EVENT})

    late = client.post(
        "/api/v1/guests/observations",
        headers=HEADERS,
        json=observation_payload(observationId="arrived-after-withdrawal"),
    )

    assert late.status_code == 409
    assert "not an identifiable consenting guest" in late.json()["detail"]
    assert all(view["observation"] is None for view in snapshot(client)["cameras"])


def test_re_enrolment_needs_a_fresh_consent_conversation(client: TestClient) -> None:
    """Adding a reference back is refused; withdrawal is not a pause button."""
    guest_id = enrol_and_recognise(client)
    client.delete(f"/api/v1/guests/{guest_id}", headers=HEADERS, params={"eventId": EVENT})

    retry = client.post(
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

    # 403, not 409: the request is well-formed and the guest exists. What is
    # missing is consent, which is a permission, not a conflict.
    assert retry.status_code == 403
    assert all(entry["guestId"] != guest_id for entry in gallery(client)["entries"])


def test_withdrawing_one_guest_leaves_the_others_alone(client: TestClient) -> None:
    """A deletion that took the room with it would be its own incident."""
    sarah = enrol_and_recognise(client, "Sarah")
    daniel = client.post(
        "/api/v1/guests",
        headers=HEADERS,
        json={
            "eventId": EVENT,
            "displayName": "Daniel",
            "aliases": [],
            "consentGranted": True,
            "consentPurposes": ["LIVE_IDENTIFICATION"],
            "recordedBy": "B",
        },
    ).json()["guestId"]
    client.post(
        f"/api/v1/guests/{daniel}/references",
        headers=HEADERS,
        json={
            "eventId": EVENT,
            "embedding": embedding(lead=0.0),
            "quality": 0.8,
            "embedder": "opencv-sface",
            "embedderVersion": "2021dec",
            "capturedAtMs": 1758293400000,
        },
    )

    client.delete(f"/api/v1/guests/{sarah}", headers=HEADERS, params={"eventId": EVENT})

    remaining = [entry["guestId"] for entry in gallery(client)["entries"]]
    assert daniel in remaining
    assert sarah not in remaining


def test_ending_the_event_purges_everyone_and_all_evidence(client: TestClient) -> None:
    enrol_and_recognise(client)

    receipt = client.delete("/api/v1/guests", headers=HEADERS, params={"eventId": EVENT}).json()

    assert receipt["guestIds"]
    assert client.get(
        "/api/v1/guests", headers=HEADERS, params={"eventId": EVENT}
    ).json()["guests"] == []
    assert gallery(client)["entries"] == []
    assert all(view["observation"] is None for view in snapshot(client)["cameras"])


def test_a_withdrawal_in_one_event_does_not_touch_another(client: TestClient) -> None:
    guest_id = enrol_and_recognise(client)
    other = client.post(
        "/api/v1/guests",
        headers=HEADERS,
        json={
            "eventId": "another-event",
            "displayName": "Sarah",
            "aliases": [],
            "consentGranted": True,
            "consentPurposes": ["LIVE_IDENTIFICATION"],
            "recordedBy": "B",
        },
    ).json()["guestId"]

    client.delete(f"/api/v1/guests/{guest_id}", headers=HEADERS, params={"eventId": EVENT})

    still_there = client.get(
        "/api/v1/guests", headers=HEADERS, params={"eventId": "another-event"}
    ).json()["guests"]
    assert [guest["guestId"] for guest in still_there] == [other]


def test_no_deletion_endpoint_works_without_the_operator_credential(
    client: TestClient,
) -> None:
    """Deletion is destructive; it must not be reachable unauthenticated."""
    guest_id = enrol_and_recognise(client)

    assert client.delete(
        f"/api/v1/guests/{guest_id}", params={"eventId": EVENT}
    ).status_code == 401
    assert client.delete("/api/v1/guests", params={"eventId": EVENT}).status_code == 401
    # And the guest is still there, so the refusal was not a silent deletion.
    assert any(entry["guestId"] == guest_id for entry in gallery(client)["entries"])
