from cue_api.contracts import CameraId
from cue_api.media_contracts import DecodedVideoFrame, PixelFormat
from cue_api.worker_ingest import WorkerFrameIngestor


def frame(sequence: int, *, event_id: str = "demo", epoch: int = 1) -> DecodedVideoFrame:
    return DecodedVideoFrame(
        event_id=event_id,
        camera_id=CameraId.HOST,
        stream_epoch=epoch,
        track_sid=f"track-{epoch}",
        sequence=sequence,
        width=2,
        height=2,
        stride_bytes=6,
        pixel_format=PixelFormat.RGB24,
        orientation_degrees=0,
        mirrored=False,
        received_at_monotonic_s=float(sequence),
        capture_time_s=None,
        data=b"\0" * 12,
    )


def test_worker_slot_replaces_old_work_instead_of_building_latency() -> None:
    ingestor = WorkerFrameIngestor("demo")
    assert ingestor.ingest(frame(1)).accepted is True
    second = ingestor.ingest(frame(2))
    assert second.accepted is True
    assert second.replaced_pending_frame is True
    assert ingestor.take(CameraId.HOST) == frame(2)
    assert ingestor.take(CameraId.HOST) is None


def test_worker_rejects_other_events_stale_epochs_and_old_sequences() -> None:
    ingestor = WorkerFrameIngestor("demo")
    assert ingestor.ingest(frame(1, event_id="other")).accepted is False
    assert ingestor.ingest(frame(5, epoch=2)).accepted is True
    assert ingestor.current_epoch(CameraId.HOST) == 2
    assert ingestor.ingest(frame(6, epoch=1)).reason == "stale stream epoch"
    assert ingestor.ingest(frame(5, epoch=2)).reason == "duplicate or out-of-order frame"
