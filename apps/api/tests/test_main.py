from __future__ import annotations

import json

import jwt
from fastapi.testclient import TestClient

from cue_api.contracts import CameraId, ReceiverRole
from cue_api.livekit_tokens import (
    IssuedPublisherToken,
    IssuedReceiverToken,
    LiveKitPublisherTokenIssuer,
    LiveKitReceiverTokenIssuer,
)
from cue_api.main import create_app
from cue_api.settings import Settings


class FakeIssuer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, CameraId, str]] = []

    def issue(self, event_id: str, camera_id: CameraId, display_name: str) -> IssuedPublisherToken:
        self.calls.append((event_id, camera_id, display_name))
        return IssuedPublisherToken(
            token="signed-token",
            participant_identity=f"publisher:{event_id}:{camera_id.value}",
            room_name=f"cue-{event_id}",
            expires_in_seconds=600,
        )


def configured_settings() -> Settings:
    return Settings(
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="test-api-key",
        livekit_api_secret="a-secure-test-secret-that-is-long-enough",
        cue_bootstrap_secret="stage-zero-secret",
        cue_cors_origins="http://localhost:5173",
    )


def test_health_distinguishes_liveness_from_readiness() -> None:
    client = TestClient(create_app(settings=Settings(_env_file=None)))

    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert ready.status_code == 503
    assert ready.json()["livekitConfigured"] is False


def test_topology_has_one_and_only_one_master_microphone() -> None:
    client = TestClient(create_app(settings=Settings(_env_file=None)))

    response = client.get("/api/v1/topology")

    assert response.status_code == 200
    cameras = response.json()["cameras"]
    masters = [camera["cameraId"] for camera in cameras if camera["audioPolicy"] == "MASTER"]
    assert masters == ["CAM-HOST"]
    assert {camera["cameraId"] for camera in cameras} == {
        "CAM-HOST",
        "CAM-GUEST",
        "CAM-WIDE",
    }


def test_token_endpoint_rejects_missing_bootstrap_secret() -> None:
    client = TestClient(create_app(settings=configured_settings(), token_issuer=FakeIssuer()))

    response = client.post(
        "/api/v1/stage0/publisher-token",
        json={"eventId": "hackmit-demo", "cameraId": "CAM-HOST", "displayName": "Person A"},
    )

    assert response.status_code == 401


def test_token_endpoint_uses_server_owned_contract() -> None:
    issuer = FakeIssuer()
    client = TestClient(create_app(settings=configured_settings(), token_issuer=issuer))

    response = client.post(
        "/api/v1/stage0/publisher-token",
        headers={"X-CUE-Bootstrap-Secret": "stage-zero-secret"},
        json={"eventId": "hackmit-demo", "cameraId": "CAM-HOST", "displayName": "Person A"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["participantIdentity"] == "publisher:hackmit-demo:CAM-HOST"
    assert body["camera"]["audioPolicy"] == "MASTER"
    assert issuer.calls == [("hackmit-demo", CameraId.HOST, "Person A")]


def test_livekit_grants_enforce_camera_specific_audio_policy() -> None:
    issuer = LiveKitPublisherTokenIssuer(configured_settings())

    host = issuer.issue("hackmit-demo", CameraId.HOST, "Person A")
    guest = issuer.issue("hackmit-demo", CameraId.GUEST, "Person B")
    host_claims = jwt.decode(host.token, options={"verify_signature": False})
    guest_claims = jwt.decode(guest.token, options={"verify_signature": False})

    assert host_claims["video"]["canPublishSources"] == ["camera", "microphone"]
    assert guest_claims["video"]["canPublishSources"] == ["camera"]
    assert host_claims["video"]["canSubscribe"] is False
    assert host_claims["video"]["canPublishData"] is False
    metadata = json.loads(host_claims["metadata"])
    assert metadata["cameraId"] == "CAM-HOST"
    assert metadata["streamEpoch"] == 1


def test_invalid_event_slug_is_rejected_before_issuer() -> None:
    issuer = FakeIssuer()
    client = TestClient(create_app(settings=configured_settings(), token_issuer=issuer))

    response = client.post(
        "/api/v1/stage0/publisher-token",
        headers={"X-CUE-Bootstrap-Secret": "stage-zero-secret"},
        json={"eventId": "../../other-room", "cameraId": "CAM-HOST", "displayName": "A"},
    )

    assert response.status_code == 422
    assert issuer.calls == []


class FakeReceiverIssuer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ReceiverRole, str]] = []

    def issue(
        self, event_id: str, receiver_role: ReceiverRole, display_name: str
    ) -> IssuedReceiverToken:
        self.calls.append((event_id, receiver_role, display_name))
        return IssuedReceiverToken(
            token="signed-receiver-token",
            participant_identity=f"receiver:{event_id}:{receiver_role.value.lower()}:abcd1234",
            room_name=f"cue-{event_id}",
            expires_in_seconds=600,
        )


def test_receiver_token_endpoint_rejects_missing_bootstrap_secret() -> None:
    client = TestClient(
        create_app(settings=configured_settings(), receiver_token_issuer=FakeReceiverIssuer())
    )

    response = client.post(
        "/api/v1/stage0/receiver-token",
        json={"eventId": "hackmit-demo", "displayName": "Person D", "receiverRole": "DIRECTOR"},
    )

    assert response.status_code == 401


def test_receiver_token_endpoint_joins_the_same_room_as_publishers() -> None:
    issuer = FakeReceiverIssuer()
    client = TestClient(create_app(settings=configured_settings(), receiver_token_issuer=issuer))

    response = client.post(
        "/api/v1/stage0/receiver-token",
        headers={"X-CUE-Bootstrap-Secret": "stage-zero-secret"},
        json={"eventId": "hackmit-demo", "displayName": "Person D", "receiverRole": "DIRECTOR"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["roomName"] == "cue-hackmit-demo"
    assert body["participantIdentity"].startswith("receiver:hackmit-demo:director:")
    assert body["receiverRole"] == "DIRECTOR"
    assert issuer.calls == [("hackmit-demo", ReceiverRole.DIRECTOR, "Person D")]


def test_receiver_token_endpoint_defaults_to_director_role() -> None:
    issuer = FakeReceiverIssuer()
    client = TestClient(create_app(settings=configured_settings(), receiver_token_issuer=issuer))

    response = client.post(
        "/api/v1/stage0/receiver-token",
        headers={"X-CUE-Bootstrap-Secret": "stage-zero-secret"},
        json={"eventId": "hackmit-demo", "displayName": "Person D"},
    )

    assert response.status_code == 201
    assert issuer.calls == [("hackmit-demo", ReceiverRole.DIRECTOR, "Person D")]


def test_livekit_receiver_grants_can_subscribe_but_never_publish() -> None:
    issuer = LiveKitReceiverTokenIssuer(configured_settings())

    first = issuer.issue("hackmit-demo", ReceiverRole.DIRECTOR, "Person D")
    second = issuer.issue("hackmit-demo", ReceiverRole.OBSERVER, "Observer")
    claims = jwt.decode(first.token, options={"verify_signature": False})

    assert claims["video"]["room"] == "cue-hackmit-demo"
    assert claims["video"]["canSubscribe"] is True
    assert claims["video"]["canPublish"] is False
    assert claims["video"]["canPublishData"] is False
    assert first.participant_identity != second.participant_identity
    assert second.participant_identity.startswith("receiver:hackmit-demo:observer:")
    metadata = json.loads(claims["metadata"])
    assert metadata["receiverRole"] == "DIRECTOR"
    assert "cameraId" not in metadata
