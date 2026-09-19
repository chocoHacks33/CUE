from __future__ import annotations

import pytest

from cue_api.contracts import CameraId
from cue_api.media_contracts import (
    DecodedAudioChunk,
    DecodedVideoFrame,
    LatestFrameSlot,
    PcmContinuityGuard,
    PixelFormat,
    SampleFormat,
)


def frame(sequence: int, *, epoch: int = 1, camera: CameraId = CameraId.HOST):
    return DecodedVideoFrame(
        event_id="demo-event",
        camera_id=camera,
        stream_epoch=epoch,
        track_sid=f"TR_video_{epoch}",
        sequence=sequence,
        width=2,
        height=2,
        stride_bytes=6,
        pixel_format=PixelFormat.RGB24,
        orientation_degrees=0,
        mirrored=False,
        received_at_monotonic_s=12.5,
        capture_time_s=None,
        data=bytes(12),
    )


def audio(
    sequence: int,
    offset: int,
    *,
    epoch: int = 1,
    track_sid: str = "TR_audio_1",
    rate: int = 48_000,
):
    return DecodedAudioChunk(
        event_id="demo-event",
        camera_id=CameraId.HOST,
        master_track_sid=track_sid,
        audio_epoch=epoch,
        sequence=sequence,
        sample_rate_hz=rate,
        channels=1,
        sample_format=SampleFormat.S16LE,
        sample_offset=offset,
        received_at_monotonic_s=20.0,
        data=bytes(960),  # 480 mono int16 sample frames
    )


def test_video_frame_validates_layout_and_orientation() -> None:
    assert frame(1).data == bytes(12)
    with pytest.raises(ValueError, match="payload length"):
        DecodedVideoFrame(
            **{**frame(1).__dict__, "data": bytes(11)},
        )
    with pytest.raises(ValueError, match="orientation"):
        DecodedVideoFrame(
            **{**frame(1).__dict__, "orientation_degrees": 45},
        )


def test_latest_frame_slot_never_builds_a_backlog() -> None:
    slot = LatestFrameSlot(CameraId.HOST)
    assert slot.put(frame(1))
    assert slot.put(frame(2))
    assert not slot.put(frame(1))
    assert slot.take() == frame(2)
    assert slot.take() is None


def test_new_stream_epoch_supersedes_any_old_frame_sequence() -> None:
    slot = LatestFrameSlot(CameraId.HOST)
    assert slot.put(frame(99, epoch=1))
    assert slot.put(frame(0, epoch=2))
    assert not slot.put(frame(100, epoch=1))
    assert slot.peek() == frame(0, epoch=2)
    with pytest.raises(ValueError, match="different camera"):
        slot.put(frame(1, epoch=3, camera=CameraId.GUEST))
    with pytest.raises(ValueError, match="track changed"):
        slot.put(DecodedVideoFrame(**{**frame(1, epoch=2).__dict__, "track_sid": "TR_other"}))


def test_audio_contract_counts_real_pcm_sample_frames() -> None:
    chunk = audio(0, 0)
    assert chunk.sample_frame_count == 480
    assert chunk.end_sample_offset == 480
    with pytest.raises(ValueError, match="CAM-HOST"):
        DecodedAudioChunk(**{**chunk.__dict__, "camera_id": CameraId.GUEST})
    with pytest.raises(ValueError, match="complete"):
        DecodedAudioChunk(**{**chunk.__dict__, "data": bytes(959)})


def test_pcm_guard_rejects_replays_and_format_changes_without_epoch_bump() -> None:
    guard = PcmContinuityGuard()
    assert guard.accept(audio(0, 0)).accepted
    assert guard.accept(audio(1, 480)).accepted
    assert not guard.accept(audio(1, 480)).accepted
    assert not guard.accept(audio(2, 960, rate=16_000)).accepted
    assert not guard.accept(audio(2, 960, track_sid="TR_audio_2")).accepted


def test_pcm_guard_reports_gaps_and_resets_on_new_epoch() -> None:
    guard = PcmContinuityGuard()
    assert guard.accept(audio(0, 0)).accepted
    gap = guard.accept(audio(1, 600))
    assert gap.accepted
    assert gap.gap_sample_frames == 120
    next_epoch = guard.accept(audio(0, 0, epoch=2, track_sid="TR_audio_2", rate=16_000))
    assert next_epoch.accepted
    assert next_epoch.gap_sample_frames == 0
