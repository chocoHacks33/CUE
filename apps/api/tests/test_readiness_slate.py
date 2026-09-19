"""D: the compositor reports "SLATE" as current_source when on the safe picture."""

import pytest

from cue_api.readiness import ReceiverReadiness


def _report(current_source: object) -> dict[str, object]:
    return {
        "contractVersion": "0.1.0",
        "eventId": "hackmit-demo",
        "rendererId": "renderer-abcdef12",
        "rendererGeneration": 1,
        "receiverIdentity": "receiver:hackmit-demo:director:abcd1234",
        "connected": True,
        "clockDomain": "renderer-monotonic",
        "reportedAtMs": 1234.5,
        "currentSource": current_source,
        "masterAudio": {
            "cameraId": "CAM-HOST",
            "trackSid": None,
            "attached": False,
            "playbackAllowed": True,
        },
        "slots": [
            {
                "cameraId": camera_id,
                "publisherIdentity": None,
                "streamEpoch": None,
                "videoTrackSid": None,
                "audioTrackSid": None,
                "decoded": False,
                "renderable": False,
                "lastFrameAgeMs": None,
                "framesProgressing": False,
                "frameCount": 0,
                "width": 0,
                "height": 0,
                "state": "waiting",
            }
            for camera_id in ("CAM-HOST", "CAM-GUEST", "CAM-WIDE")
        ],
    }


def test_current_source_accepts_camera_slate_and_null() -> None:
    assert ReceiverReadiness.model_validate(_report("CAM-WIDE")).current_source == "CAM-WIDE"
    assert ReceiverReadiness.model_validate(_report("SLATE")).current_source == "SLATE"
    assert ReceiverReadiness.model_validate(_report(None)).current_source is None


def test_current_source_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        ReceiverReadiness.model_validate(_report("CAM-4"))
