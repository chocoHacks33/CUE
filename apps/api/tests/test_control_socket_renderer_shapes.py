"""D: A's control socket driven with the payload shapes D's compositor adapters emit.

Guards the A/D seam: readiness with currentSource "SLATE", reconciliation, a
backend-routed TAKE, an APPLIED acknowledgement in wall-clock milliseconds, and
HOLD invalidating a pending command. No LiveKit, no browser.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from cue_api.main import create_app
from cue_api.settings import Settings

EVENT = "hackmit-demo"
PRODUCER = {"X-CUE-Producer-Secret": "prod-secret-456"}


def _app() -> TestClient:
    settings = Settings(
        _env_file=None,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="key",
        livekit_api_secret="s" * 32,
        cue_bootstrap_secret="boot-secret-123",
        cue_producer_secret="prod-secret-456",
    )
    return TestClient(create_app(settings=settings))


def _slot(camera_id: str, ready: bool) -> dict[str, object]:
    return {
        "cameraId": camera_id,
        "publisherIdentity": f"publisher:{EVENT}:{camera_id}" if ready else None,
        "streamEpoch": 1 if ready else None,
        "videoTrackSid": f"TR_{camera_id}" if ready else None,
        "audioTrackSid": "TR_A" if camera_id == "CAM-HOST" and ready else None,
        "decoded": ready,
        "renderable": ready,
        "lastFrameAgeMs": 20 if ready else None,
        "framesProgressing": ready,
        "frameCount": 100 if ready else 0,
        "width": 1280,
        "height": 720,
        "state": "video-ready" if ready else "waiting",
    }


def _readiness(current_source: object) -> dict[str, object]:
    return {
        "contractVersion": "0.1.0",
        "eventId": EVENT,
        "rendererId": "renderer-abcdef12",
        "rendererGeneration": 1,
        "receiverIdentity": f"receiver:{EVENT}:director:1234",
        "connected": True,
        "clockDomain": "renderer-monotonic",
        "reportedAtMs": 5000.0,
        "currentSource": current_source,
        "masterAudio": {
            "cameraId": "CAM-HOST",
            "trackSid": "TR_A",
            "attached": True,
            "playbackAllowed": True,
        },
        "slots": [_slot("CAM-HOST", True), _slot("CAM-GUEST", False), _slot("CAM-WIDE", False)],
    }


def _until(ws, wanted: str, limit: int = 12):
    seen: list[str] = []
    for _ in range(limit):
        message = ws.receive_json()
        seen.append(message["type"])
        if message["type"] == wanted:
            return message, seen
    raise AssertionError(f"no {wanted} in {seen}")


def test_renderer_shapes_round_trip_through_the_control_socket() -> None:
    client = _app()
    session = client.post(
        f"/api/v1/events/{EVENT}/control-sessions", headers=PRODUCER, json={"role": "DIRECTOR"}
    ).json()

    with client.websocket_connect(f"/api/v1/events/{EVENT}/control") as ws:
        ws.send_json({"type": "control.authenticate", "token": session["token"]})
        _until(ws, "control.authenticated")
        state, _ = _until(ws, "control.state")
        generation = state["state"]["controlGeneration"]

        # Readiness with the compositor on the slate is accepted and stored verbatim.
        ws.send_json({"type": "receiver.readiness", "readiness": _readiness("SLATE")})
        _, seen = _until(ws, "receiver.readiness")
        assert "control.error" not in seen
        stored = client.get(f"/api/v1/events/{EVENT}/readiness", headers=PRODUCER).json()
        assert stored["currentSource"] == "SLATE"

        # Reconcile the actual output on connect.
        ws.send_json(
            {
                "type": "render.reconcile",
                "report": {
                    "controlGeneration": generation,
                    "actualTarget": "SLATE",
                    "actualCameraId": None,
                    "actualStreamEpoch": None,
                    "reportedAtMs": int(time.time() * 1000),
                },
            }
        )
        reconciled, _ = _until(ws, "control.state")
        assert reconciled["state"]["liveCameraId"] is None

        # Manual TAKE through the backend arrives as a render command on the director socket.
        take = client.post(
            f"/api/v1/events/{EVENT}/take",
            headers=PRODUCER,
            json={
                "cameraId": "CAM-HOST",
                "streamEpoch": 1,
                "expectedRevision": reconciled["state"]["modeRevision"],
                "idempotencyKey": "take:1:renderer-1",
            },
        ).json()
        command = take["renderCommand"]
        pushed, _ = _until(ws, "render.command")
        assert pushed["command"]["decisionId"] == command["decisionId"]

        # APPLIED acknowledgement, as ackToAcknowledgement() shapes it, moves the backend's live camera.
        acknowledgement = {
            "decisionId": command["decisionId"],
            "controlGeneration": command["controlGeneration"],
            "decisionSequence": command["decisionSequence"],
            "status": "APPLIED",
            "actualTarget": "CAMERA",
            "actualCameraId": "CAM-HOST",
            "actualStreamEpoch": 1,
            "appliedAtMs": int(time.time() * 1000),
            "detail": None,
        }
        ws.send_json({"type": "render.ack", "ack": acknowledgement})
        live, _ = _until(ws, "control.state")
        while live["state"]["liveCameraId"] is None:
            live, _ = _until(ws, "control.state")
        assert live["state"]["liveCameraId"] == "CAM-HOST"
        assert live["state"]["pendingDecisionId"] is None

        # HOLD clears a pending command; its late acknowledgement is refused.
        second = client.post(
            f"/api/v1/events/{EVENT}/take",
            headers=PRODUCER,
            json={
                "cameraId": "CAM-HOST",
                "streamEpoch": 1,
                "expectedRevision": live["state"]["modeRevision"],
                "idempotencyKey": "take:2:renderer-1",
            },
        ).json()
        _until(ws, "render.command")
        hold = client.post(
            f"/api/v1/events/{EVENT}/mode",
            headers=PRODUCER,
            json={
                "mode": "MANUAL_HOLD",
                "expectedRevision": second["state"]["modeRevision"],
                "idempotencyKey": "mode:1:renderer-1",
            },
        ).json()
        assert hold["state"]["mode"] == "MANUAL_HOLD"
        assert hold["state"]["pendingDecisionId"] is None
        late = {
            **acknowledgement,
            "decisionId": second["renderCommand"]["decisionId"],
            "decisionSequence": second["renderCommand"]["decisionSequence"],
            "appliedAtMs": int(time.time() * 1000),
        }
        ws.send_json({"type": "render.ack", "ack": late})
        refused, _ = _until(ws, "control.error")
        assert refused["code"] in {"UNKNOWN_DECISION", "STALE_REVISION"}

        # Malformed readiness is refused, not stored.
        ws.send_json({"type": "receiver.readiness", "readiness": _readiness("CAM-4")})
        bad, _ = _until(ws, "control.error")
        assert bad["code"] == "INVALID_CONTROL_MESSAGE"

    metrics = client.get(f"/api/v1/events/{EVENT}/control-metrics", headers=PRODUCER).json()
    assert metrics["appliedCount"] == 1
    assert metrics["rejectedCount"] == 1
    assert metrics["outstandingCount"] == 0
