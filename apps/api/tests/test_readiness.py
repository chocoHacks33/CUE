import pytest
from pydantic import ValidationError

from cue_api.contracts import CameraId
from cue_api.readiness import ReadinessError, ReadinessStore, ReceiverReadiness


def readiness_payload(
    *,
    renderer_id: str = "renderer-one",
    generation: int = 1,
    frame_count: int = 1,
    progressing: bool = False,
) -> dict[str, object]:
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
                "framesProgressing": progressing,
                "frameCount": frame_count,
                "width": 1280,
                "height": 720,
                "state": "video-ready",
            }
        )
    return {
        "contractVersion": "0.1.0",
        "eventId": "demo",
        "rendererId": renderer_id,
        "rendererGeneration": generation,
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


def test_readiness_requires_exact_camera_order_and_renderable_decoded_track() -> None:
    payload = readiness_payload()
    payload["contractVersion"] = "9.9.9"
    with pytest.raises(ValidationError, match="0.1.0"):
        ReceiverReadiness.model_validate(payload)

    payload = readiness_payload()
    payload["slots"] = list(reversed(payload["slots"]))  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="CAM-HOST"):
        ReceiverReadiness.model_validate(payload)

    payload = readiness_payload()
    payload["slots"][0]["decoded"] = False  # type: ignore[index]
    with pytest.raises(ValidationError, match="decoded current video track"):
        ReceiverReadiness.model_validate(payload)


def test_server_health_needs_progress_not_only_renderer_connection() -> None:
    store = ReadinessStore()
    first = ReceiverReadiness.model_validate(readiness_payload())
    store.ingest("demo", first, received_at_ms=1_000)
    assert store.health("demo").snapshot(CameraId.HOST, 1_000).health.decoding is False

    second = ReceiverReadiness.model_validate(readiness_payload(frame_count=2, progressing=True))
    store.ingest("demo", second, received_at_ms=1_100)
    health = store.health("demo").snapshot(CameraId.HOST, 1_100).health
    assert health.decoding is True
    assert health.renderable is True
    assert health.visually_usable is False
    assert health.warnings == ("visual_quality_unknown",)


def test_stale_generation_and_competing_renderer_are_rejected() -> None:
    store = ReadinessStore()
    store.ingest(
        "demo",
        ReceiverReadiness.model_validate(readiness_payload(generation=2)),
        received_at_ms=1_000,
    )
    with pytest.raises(ReadinessError) as stale:
        store.ingest(
            "demo",
            ReceiverReadiness.model_validate(readiness_payload(generation=1)),
            received_at_ms=1_100,
        )
    assert stale.value.code == "STALE_RENDERER"

    with pytest.raises(ReadinessError) as conflict:
        store.ingest(
            "demo",
            ReceiverReadiness.model_validate(
                readiness_payload(renderer_id="renderer-two", generation=1)
            ),
            received_at_ms=1_100,
        )
    assert conflict.value.code == "RENDERER_CONFLICT"


def test_old_timestamp_is_rejected_and_new_generation_resets_frame_health() -> None:
    store = ReadinessStore()
    current = ReceiverReadiness.model_validate(
        readiness_payload(generation=1, frame_count=5, progressing=True)
    )
    store.ingest("demo", current, received_at_ms=1_000)

    older_payload = readiness_payload(generation=1, frame_count=6, progressing=True)
    older_payload["reportedAtMs"] = 499
    with pytest.raises(ReadinessError) as stale:
        store.ingest(
            "demo",
            ReceiverReadiness.model_validate(older_payload),
            received_at_ms=1_100,
        )
    assert stale.value.code == "STALE_READINESS"

    restarted = ReceiverReadiness.model_validate(
        readiness_payload(generation=2, frame_count=0, progressing=False)
    )
    store.ingest("demo", restarted, received_at_ms=1_200)
    health = store.health("demo").snapshot(CameraId.HOST, 1_200)
    assert health.stream_epoch == 1
    assert health.health.decoding is False


def test_disconnected_slot_cannot_remain_renderable() -> None:
    store = ReadinessStore()
    connected = ReceiverReadiness.model_validate(
        readiness_payload(frame_count=2, progressing=True)
    )
    store.ingest("demo", connected, received_at_ms=1_000)

    payload = readiness_payload(frame_count=2, progressing=False)
    payload["connected"] = False
    disconnected = ReceiverReadiness.model_validate(payload)
    store.ingest("demo", disconnected, received_at_ms=1_100)
    health = store.health("demo").snapshot(CameraId.HOST, 1_100).health
    assert health.connected is False
    assert health.decoding is False
    assert health.renderable is False
