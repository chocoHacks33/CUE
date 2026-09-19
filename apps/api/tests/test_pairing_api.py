from __future__ import annotations

from fastapi.testclient import TestClient

from cue_api.contracts import CameraId
from cue_api.livekit_tokens import IssuedPublisherToken
from cue_api.main import create_app
from cue_api.settings import Settings


class PairingIssuer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def issue(
        self,
        event_id: str,
        camera_id: CameraId,
        display_name: str,
        *,
        participant_identity: str | None = None,
        stream_epoch: int = 1,
        device_session_id: str | None = None,
    ) -> IssuedPublisherToken:
        self.calls.append(
            {
                "event_id": event_id,
                "camera_id": camera_id,
                "display_name": display_name,
                "participant_identity": participant_identity,
                "stream_epoch": stream_epoch,
                "device_session_id": device_session_id,
            }
        )
        return IssuedPublisherToken(
            token="stage-one-livekit-token",
            participant_identity=participant_identity or "missing",
            room_name=f"cue-{event_id}",
            expires_in_seconds=600,
        )


def settings() -> Settings:
    return Settings(
        _env_file=None,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="key",
        livekit_api_secret="secret",
        cue_bootstrap_secret="legacy-secret",
        cue_producer_secret="producer-only-secret",
    )


def producer_headers() -> dict[str, str]:
    return {"X-CUE-Producer-Secret": "producer-only-secret"}


def create_claim(client: TestClient, camera_id: str = "CAM-HOST") -> tuple[dict, dict]:
    grant_response = client.post(
        "/api/v1/events/demo-event/pairing",
        headers=producer_headers(),
        json={"cameraId": camera_id},
    )
    assert grant_response.status_code == 201
    grant = grant_response.json()
    claim_response = client.post(
        "/api/v1/pairing/claim",
        json={
            "pairingToken": grant["pairingToken"],
            "displayName": "Person A",
            "deviceLabel": "A Windows laptop",
        },
    )
    assert claim_response.status_code == 201
    return grant, claim_response.json()


def test_pairing_grant_requires_producer_secret_and_valid_event_slug() -> None:
    client = TestClient(create_app(settings=settings(), token_issuer=PairingIssuer()))

    missing = client.post("/api/v1/events/demo-event/pairing", json={"cameraId": "CAM-HOST"})
    invalid_event = client.post(
        "/api/v1/events/..bad/pairing",
        headers=producer_headers(),
        json={"cameraId": "CAM-HOST"},
    )

    assert missing.status_code == 401
    assert invalid_event.status_code == 422


def test_pairing_token_assigns_camera_server_side_and_is_single_use() -> None:
    client = TestClient(create_app(settings=settings(), token_issuer=PairingIssuer()))
    grant, claim = create_claim(client, "CAM-GUEST")

    assert claim["camera"]["cameraId"] == "CAM-GUEST"
    assert claim["camera"]["audioPolicy"] == "DISABLED"
    assert claim["verificationCode"] == grant["verificationCode"]
    replay = client.post(
        "/api/v1/pairing/claim",
        json={
            "pairingToken": grant["pairingToken"],
            "displayName": "Other",
            "deviceLabel": "Other laptop",
        },
    )
    assert replay.status_code == 409


def test_pending_claim_cannot_exchange_until_producer_approval() -> None:
    issuer = PairingIssuer()
    client = TestClient(create_app(settings=settings(), token_issuer=issuer))
    _grant, claim = create_claim(client)
    capability = {"claimId": claim["claimId"], "claimSecret": claim["claimSecret"]}

    pending = client.post("/api/v1/pairing/exchange", json=capability)
    listed = client.get("/api/v1/events/demo-event/pairing-claims", headers=producer_headers())

    assert pending.status_code == 409
    assert issuer.calls == []
    assert listed.status_code == 200
    assert listed.json()[0]["deviceLabel"] == "A Windows laptop"
    assert listed.json()[0]["status"] == "PENDING"


def test_approved_claim_exchanges_once_and_creates_stable_binding() -> None:
    issuer = PairingIssuer()
    client = TestClient(create_app(settings=settings(), token_issuer=issuer))
    _grant, claim = create_claim(client)
    capability = {"claimId": claim["claimId"], "claimSecret": claim["claimSecret"]}

    approval = client.post(
        f"/api/v1/events/demo-event/devices/{claim['claimId']}/approve",
        headers=producer_headers(),
        json={"approved": True},
    )
    exchange = client.post("/api/v1/pairing/exchange", json=capability)
    replay = client.post("/api/v1/pairing/exchange", json=capability)
    bindings = client.get("/api/v1/events/demo-event/bindings", headers=producer_headers())

    assert approval.status_code == 200
    assert approval.json()["status"] == "APPROVED"
    assert exchange.status_code == 201
    body = exchange.json()
    assert body["camera"]["cameraId"] == "CAM-HOST"
    assert body["streamEpoch"] == 1
    assert body["participantIdentity"].startswith("publisher:demo-event:CAM-HOST:")
    assert body["deviceSessionId"] in body["participantIdentity"]
    assert replay.status_code == 409
    assert len(issuer.calls) == 1
    assert bindings.status_code == 200
    assert bindings.json()[0]["participantIdentity"] == body["participantIdentity"]


def test_claim_secret_is_not_a_producer_credential() -> None:
    client = TestClient(create_app(settings=settings(), token_issuer=PairingIssuer()))
    _grant, claim = create_claim(client)

    response = client.get(
        "/api/v1/events/demo-event/bindings",
        headers={"X-CUE-Producer-Secret": claim["claimSecret"]},
    )

    assert response.status_code == 401
