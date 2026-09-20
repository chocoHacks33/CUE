import time

import pytest
from fastapi.testclient import TestClient

from cue_api.contracts import CameraId
from cue_api.control_contracts import ControlRole
from cue_api.main import create_app
from cue_api.settings import Settings


def client() -> TestClient:
    return TestClient(create_app(settings=Settings(cue_producer_secret="producer-test-secret")))


def issue_session(test_client: TestClient, role: ControlRole) -> str:
    response = test_client.post(
        "/api/v1/events/demo/control-sessions",
        headers={"X-CUE-Producer-Secret": "producer-test-secret"},
        json={"role": role.value},
    )
    assert response.status_code == 200
    return response.json()["token"]


def test_control_mutations_require_auth_revision_and_idempotency() -> None:
    test_client = client()
    unauthorised = test_client.post(
        "/api/v1/events/demo/mode",
        json={"mode": "MANUAL_HOLD", "expectedRevision": 0, "idempotencyKey": "hold-0001"},
    )
    assert unauthorised.status_code == 401

    headers = {"X-CUE-Producer-Secret": "producer-test-secret"}
    payload = {"mode": "MANUAL_HOLD", "expectedRevision": 0, "idempotencyKey": "hold-0001"}
    first = test_client.post("/api/v1/events/demo/mode", headers=headers, json=payload)
    replay = test_client.post("/api/v1/events/demo/mode", headers=headers, json=payload)
    assert first.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["state"]["modeRevision"] == 1

    conflict = test_client.post(
        "/api/v1/events/demo/mode",
        headers=headers,
        json={"mode": "AUTO", "expectedRevision": 0, "idempotencyKey": "auto-0001"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "REVISION_CONFLICT"


@pytest.mark.parametrize(
    "message",
    [
        {"type": "render.ack", "ack": {}},
        {"type": "render.reconcile", "report": {}},
        {"type": "receiver.readiness", "readiness": {}},
    ],
)
def test_observer_socket_is_read_only(message: dict[str, object]) -> None:
    test_client = client()
    token = issue_session(test_client, ControlRole.OBSERVER)
    with test_client.websocket_connect("/api/v1/events/demo/control") as socket:
        socket.send_json({"type": "control.authenticate", "token": token})
        assert socket.receive_json()["type"] == "control.authenticated"
        assert socket.receive_json()["type"] == "control.state"
        socket.send_json(message)
        response = socket.receive_json()
        assert response["type"] == "control.error"
        assert response["code"] == "OBSERVER_READ_ONLY"


def test_control_socket_explains_invalid_and_cross_event_sessions() -> None:
    test_client = client()
    token = issue_session(test_client, ControlRole.DIRECTOR)
    for event_id, presented in (("demo", "invalid-token"), ("another-event", token)):
        with test_client.websocket_connect(f"/api/v1/events/{event_id}/control") as socket:
            socket.send_json({"type": "control.authenticate", "token": presented})
            response = socket.receive_json()
            assert response["type"] == "control.error"
            assert response["code"] == "INVALID_SESSION"


def test_director_ack_is_the_only_step_that_sets_the_live_camera() -> None:
    test_client = client()
    token = issue_session(test_client, ControlRole.DIRECTOR)
    store = test_client.app.state.control_store
    result = store.manual_take(
        "demo",
        camera_id=CameraId.GUEST,
        stream_epoch=3,
        expected_revision=0,
        idempotency_key="take-0001",
    )
    command = result.render_command
    assert command is not None

    with test_client.websocket_connect("/api/v1/events/demo/control") as socket:
        socket.send_json({"type": "control.authenticate", "token": token})
        assert socket.receive_json()["type"] == "control.authenticated"
        assert socket.receive_json()["state"]["liveCameraId"] is None
        socket.send_json(
            {
                "type": "render.ack",
                "ack": {
                    "decisionId": command.decision_id,
                    "controlGeneration": command.control_generation,
                    "decisionSequence": command.decision_sequence,
                    "status": "APPLIED",
                    "actualCameraId": "CAM-GUEST",
                    "actualStreamEpoch": 3,
                    "appliedAtMs": int(time.time() * 1000),
                },
            }
        )
        state = socket.receive_json()["state"]
        assert state["liveCameraId"] == "CAM-GUEST"
        assert state["liveStreamEpoch"] == 3

    metrics = test_client.get(
        "/api/v1/events/demo/control-metrics",
        headers={"X-CUE-Producer-Secret": "producer-test-secret"},
    )
    assert metrics.status_code == 200
    assert metrics.json()["appliedCount"] == 1
    assert metrics.json()["outstandingCount"] == 0


def test_director_readiness_is_validated_stored_and_broadcast() -> None:
    test_client = client()
    token = issue_session(test_client, ControlRole.DIRECTOR)
    slots = []
    for camera_id in ("CAM-HOST", "CAM-GUEST", "CAM-WIDE"):
        slots.append(
            {
                "cameraId": camera_id,
                "publisherIdentity": f"publisher:{camera_id}",
                "streamEpoch": 1,
                "videoTrackSid": f"track:{camera_id}",
                "audioTrackSid": "master" if camera_id == "CAM-HOST" else None,
                "decoded": True,
                "renderable": True,
                "lastFrameAgeMs": 20,
                "framesProgressing": True,
                "frameCount": 2,
                "width": 1280,
                "height": 720,
                "state": "video-ready",
            }
        )
    readiness = {
        "contractVersion": "0.1.0",
        "eventId": "demo",
        "rendererId": "renderer-one",
        "rendererGeneration": 1,
        "receiverIdentity": "receiver:demo:director:1",
        "connected": True,
        "clockDomain": "renderer-monotonic",
        "reportedAtMs": 500,
        "currentSource": "CAM-HOST",
        "masterAudio": {
            "cameraId": "CAM-HOST",
            "trackSid": "master",
            "attached": True,
            "playbackAllowed": True,
        },
        "slots": slots,
    }

    with test_client.websocket_connect("/api/v1/events/demo/control") as socket:
        socket.send_json({"type": "control.authenticate", "token": token})
        assert socket.receive_json()["type"] == "control.authenticated"
        assert socket.receive_json()["type"] == "control.state"
        socket.send_json({"type": "receiver.readiness", "readiness": readiness})
        broadcast = socket.receive_json()
        assert broadcast["type"] == "receiver.readiness"
        assert broadcast["readiness"]["rendererId"] == "renderer-one"

    response = test_client.get(
        "/api/v1/events/demo/readiness",
        headers={"X-CUE-Producer-Secret": "producer-test-secret"},
    )
    assert response.status_code == 200
    assert response.json()["currentSource"] == "CAM-HOST"
