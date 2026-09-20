from __future__ import annotations

from fastapi.testclient import TestClient

from cue_api.contracts import CameraId
from cue_api.livekit_tokens import IssuedPublisherToken
from cue_api.main import create_app
from cue_api.settings import Settings


class Issuer:
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
        del display_name, stream_epoch, device_session_id
        return IssuedPublisherToken(
            token="test-token",
            participant_identity=participant_identity or f"publisher:{event_id}:{camera_id.value}",
            room_name=f"cue-{event_id}",
            expires_in_seconds=600,
        )


def client() -> TestClient:
    settings = Settings(
        _env_file=None,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="key",
        livekit_api_secret="secret",
        cue_bootstrap_secret="legacy-secret",
        cue_producer_secret="producer-secret",
    )
    return TestClient(create_app(settings=settings, token_issuer=Issuer()))


PRODUCER = {"X-CUE-Producer-Secret": "producer-secret"}
BOOTSTRAP = {"X-CUE-Bootstrap-Secret": "legacy-secret"}


def pair_host(test_client: TestClient) -> str:
    grant = test_client.post(
        "/api/v1/events/demo-event/pairing",
        headers=PRODUCER,
        json={"cameraId": "CAM-HOST"},
    ).json()
    claim = test_client.post(
        "/api/v1/pairing/claim",
        json={
            "pairingToken": grant["pairingToken"],
            "displayName": "Person A",
            "deviceLabel": "A laptop",
        },
    ).json()
    test_client.post(
        f"/api/v1/events/demo-event/devices/{claim['claimId']}/approve",
        headers=PRODUCER,
        json={"approved": True},
    )
    exchange = test_client.post(
        "/api/v1/pairing/exchange",
        json={"claimId": claim["claimId"], "claimSecret": claim["claimSecret"]},
    )
    assert exchange.status_code == 201
    return exchange.json()["participantIdentity"]


def test_transport_endpoints_advance_epoch_and_ignore_late_detach() -> None:
    test_client = client()
    identity = pair_host(test_client)
    payload = {
        "cameraId": "CAM-HOST",
        "participantIdentity": identity,
        "trackSid": "TR-first",
    }
    first = test_client.post(
        "/api/v1/events/demo-event/transport/video-attached",
        headers=PRODUCER,
        json=payload,
    )
    second = test_client.post(
        "/api/v1/events/demo-event/transport/video-attached",
        headers=PRODUCER,
        json={**payload, "trackSid": "TR-second"},
    )
    late = test_client.post(
        "/api/v1/events/demo-event/transport/video-detached",
        headers=PRODUCER,
        json=payload,
    )

    assert first.json()["binding"]["streamEpoch"] == 1
    assert first.json()["binding"]["bindingRevision"] == 1
    assert second.json()["outcome"] == "REPUBLISHED"
    assert second.json()["binding"]["streamEpoch"] == 2
    assert second.json()["binding"]["bindingRevision"] == 2
    assert late.json()["outcome"] == "STALE_DETACH_IGNORED"
    assert late.json()["binding"]["currentVideoTrackSid"] == "TR-second"


def test_transport_endpoints_advance_epoch_after_clean_disconnect() -> None:
    test_client = client()
    identity = pair_host(test_client)
    base = {
        "cameraId": "CAM-HOST",
        "participantIdentity": identity,
    }
    first = test_client.post(
        "/api/v1/events/demo-event/transport/video-attached",
        headers=PRODUCER,
        json={**base, "trackSid": "TR-first"},
    )
    detached = test_client.post(
        "/api/v1/events/demo-event/transport/video-detached",
        headers=PRODUCER,
        json={**base, "trackSid": "TR-first"},
    )
    reconnected = test_client.post(
        "/api/v1/events/demo-event/transport/video-attached",
        headers=PRODUCER,
        json={**base, "trackSid": "TR-reconnected"},
    )

    assert first.json()["binding"]["streamEpoch"] == 1
    assert detached.json()["outcome"] == "DETACHED"
    assert detached.json()["binding"]["currentVideoTrackSid"] is None
    assert detached.json()["binding"]["bindingRevision"] == 2
    assert reconnected.json()["outcome"] == "REPUBLISHED"
    assert reconnected.json()["binding"]["streamEpoch"] == 2
    assert reconnected.json()["binding"]["bindingRevision"] == 3


def test_end_event_fences_tokens_pairing_guests_control_and_transport() -> None:
    test_client = client()
    identity = pair_host(test_client)
    session = test_client.post(
        "/api/v1/events/demo-event/control-sessions",
        headers=PRODUCER,
        json={"role": "DIRECTOR"},
    )
    assert session.status_code == 200

    ended = test_client.post("/api/v1/events/demo-event/end", headers=PRODUCER)
    replay = test_client.post("/api/v1/events/demo-event/end", headers=PRODUCER)
    assert ended.status_code == 200
    assert ended.json()["mode"] == "ENDED"
    assert ended.json()["bindingsDeleted"] == 1
    assert ended.json()["controlSessionsRevoked"] == 1
    assert replay.json()["alreadyEnded"] is True

    blocked = [
        test_client.post(
            "/api/v1/events/demo-event/pairing",
            headers=PRODUCER,
            json={"cameraId": "CAM-GUEST"},
        ),
        test_client.post(
            "/api/v1/events/demo-event/control-sessions",
            headers=PRODUCER,
            json={"role": "OBSERVER"},
        ),
        test_client.post(
            "/api/v1/events/demo-event/transport/video-attached",
            headers=PRODUCER,
            json={
                "cameraId": "CAM-HOST",
                "participantIdentity": identity,
                "trackSid": "TR-late",
            },
        ),
        test_client.post(
            "/api/v1/stage0/publisher-token",
            headers=BOOTSTRAP,
            json={
                "eventId": "demo-event",
                "cameraId": "CAM-HOST",
                "displayName": "A",
            },
        ),
        test_client.post(
            "/api/v1/guests",
            headers=BOOTSTRAP,
            json={
                "eventId": "demo-event",
                "displayName": "Late guest",
                "aliases": [],
                "consentGranted": True,
                "consentPurposes": ["LIVE_IDENTIFICATION"],
                "recordedBy": "B",
            },
        ),
    ]
    assert [response.status_code for response in blocked] == [410, 410, 410, 410, 410]
