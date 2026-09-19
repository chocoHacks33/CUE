import pytest

from cue_api.contracts import CameraId
from cue_api.media_contracts import (
    DecodedAudioChunk,
    DecodedVideoFrame,
    PixelFormat,
    SampleFormat,
)
from cue_api.worker_ingest import WorkerAudioIngestor, WorkerFrameIngestor, to_vision_frame


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


def audio(sequence: int, offset: int) -> DecodedAudioChunk:
    return DecodedAudioChunk(
        event_id="demo",
        camera_id=CameraId.HOST,
        master_track_sid="master-audio",
        audio_epoch=1,
        sequence=sequence,
        sample_rate_hz=16_000,
        channels=1,
        sample_format=SampleFormat.S16LE,
        sample_offset=offset,
        received_at_monotonic_s=float(sequence),
        data=b"\0\0" * 2,
    )


def test_audio_ingest_preserves_order_and_reports_overload_gap() -> None:
    ingestor = WorkerAudioIngestor(max_chunks=1)
    assert ingestor.ingest(audio(0, 0)).accepted is True
    assert ingestor.ingest(audio(1, 2)).reason == "audio worker queue is full"
    assert ingestor.take() == audio(0, 0)
    after_drop = ingestor.ingest(audio(2, 4))
    assert after_drop.accepted is True
    assert after_drop.gap_sample_frames == 2


def test_vision_adapter_outputs_upright_contiguous_bgr() -> None:
    numpy = pytest.importorskip("numpy")
    source = DecodedVideoFrame(
        event_id="demo",
        camera_id=CameraId.GUEST,
        stream_epoch=2,
        track_sid="track-2",
        sequence=1,
        width=2,
        height=1,
        stride_bytes=6,
        pixel_format=PixelFormat.RGB24,
        orientation_degrees=90,
        mirrored=False,
        received_at_monotonic_s=1.25,
        capture_time_s=1.0,
        data=bytes([255, 0, 0, 0, 255, 0]),
    )
    converted = to_vision_frame(source)
    assert (converted.width, converted.height) == (1, 2)
    assert converted.pixel_format == "BGR24"
    assert converted.orientation_degrees == 0
    assert converted.received_at_ms == 1_250
    assert converted.captured_at_ms == 1_000
    assert converted.image.flags["C_CONTIGUOUS"]
    assert numpy.array_equal(converted.image[0, 0], [0, 0, 255])
