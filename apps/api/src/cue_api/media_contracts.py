from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum

from cue_api.contracts import CameraId


class PixelFormat(StrEnum):
    RGB24 = "RGB24"
    BGR24 = "BGR24"
    RGBA32 = "RGBA32"

    @property
    def bytes_per_pixel(self) -> int:
        return 4 if self is PixelFormat.RGBA32 else 3


class SampleFormat(StrEnum):
    S16LE = "S16LE"
    F32LE = "F32LE"

    @property
    def bytes_per_sample(self) -> int:
        return 2 if self is SampleFormat.S16LE else 4


@dataclass(frozen=True)
class DecodedVideoFrame:
    event_id: str
    camera_id: CameraId
    stream_epoch: int
    track_sid: str
    sequence: int
    width: int
    height: int
    stride_bytes: int
    pixel_format: PixelFormat
    orientation_degrees: int
    mirrored: bool
    received_at_monotonic_s: float
    capture_time_s: float | None
    data: bytes

    def __post_init__(self) -> None:
        if not self.event_id or not self.track_sid:
            raise ValueError("event_id and track_sid are required")
        if self.stream_epoch < 1 or self.sequence < 0:
            raise ValueError("stream_epoch must be positive and sequence non-negative")
        if self.width < 1 or self.height < 1:
            raise ValueError("frame dimensions must be positive")
        minimum_stride = self.width * self.pixel_format.bytes_per_pixel
        if self.stride_bytes < minimum_stride:
            raise ValueError("stride_bytes is smaller than the packed row size")
        if self.orientation_degrees not in (0, 90, 180, 270):
            raise ValueError("orientation_degrees must be 0, 90, 180 or 270")
        if self.received_at_monotonic_s < 0:
            raise ValueError("received_at_monotonic_s cannot be negative")
        if len(self.data) != self.stride_bytes * self.height:
            raise ValueError("frame payload length does not match stride_bytes * height")


@dataclass(frozen=True)
class DecodedAudioChunk:
    event_id: str
    camera_id: CameraId
    master_track_sid: str
    audio_epoch: int
    sequence: int
    sample_rate_hz: int
    channels: int
    sample_format: SampleFormat
    sample_offset: int
    received_at_monotonic_s: float
    data: bytes

    def __post_init__(self) -> None:
        if self.camera_id != CameraId.HOST:
            raise ValueError("decoded audio must come from CAM-HOST")
        if not self.event_id or not self.master_track_sid:
            raise ValueError("event_id and master_track_sid are required")
        if self.audio_epoch < 1 or self.sequence < 0 or self.sample_offset < 0:
            raise ValueError("epoch must be positive; sequence and offset must be non-negative")
        if self.sample_rate_hz < 8_000 or self.sample_rate_hz > 192_000:
            raise ValueError("sample_rate_hz is outside the supported range")
        if self.channels not in (1, 2):
            raise ValueError("channels must be mono or stereo")
        if self.received_at_monotonic_s < 0:
            raise ValueError("received_at_monotonic_s cannot be negative")
        frame_size = self.channels * self.sample_format.bytes_per_sample
        if not self.data or len(self.data) % frame_size:
            raise ValueError("PCM payload must contain complete, non-empty sample frames")

    @property
    def sample_frame_count(self) -> int:
        return len(self.data) // (self.channels * self.sample_format.bytes_per_sample)

    @property
    def end_sample_offset(self) -> int:
        return self.sample_offset + self.sample_frame_count


class LatestFrameSlot:
    """Capacity-one handoff from media ingest to vision.

    Producers overwrite the previous frame. Consumers therefore analyse the
    freshest available frame instead of draining a latency-growing queue.
    """

    def __init__(self, camera_id: CameraId) -> None:
        self.camera_id = camera_id
        self._lock = threading.Lock()
        self._frame: DecodedVideoFrame | None = None

    def put(self, frame: DecodedVideoFrame) -> bool:
        if frame.camera_id != self.camera_id:
            raise ValueError("frame belongs to a different camera slot")
        with self._lock:
            current = self._frame
            if (
                current is not None
                and frame.stream_epoch == current.stream_epoch
                and frame.track_sid != current.track_sid
            ):
                raise ValueError("track changed without a new stream epoch")
            if current is not None and (
                frame.stream_epoch < current.stream_epoch
                or (
                    frame.stream_epoch == current.stream_epoch
                    and frame.sequence <= current.sequence
                )
            ):
                return False
            self._frame = frame
            return True

    def take(self) -> DecodedVideoFrame | None:
        with self._lock:
            frame = self._frame
            self._frame = None
            return frame

    def peek(self) -> DecodedVideoFrame | None:
        with self._lock:
            return self._frame


@dataclass(frozen=True)
class AudioContinuity:
    accepted: bool
    gap_sample_frames: int = 0
    reason: str | None = None


class PcmContinuityGuard:
    """Reject stale/overlapping PCM and format changes inside an audio epoch."""

    def __init__(self) -> None:
        self._epoch = 0
        self._track_sid: str | None = None
        self._format: tuple[int, int, SampleFormat] | None = None
        self._next_offset = 0
        self._last_sequence = -1

    def accept(self, chunk: DecodedAudioChunk) -> AudioContinuity:
        config = (chunk.sample_rate_hz, chunk.channels, chunk.sample_format)
        if chunk.audio_epoch < self._epoch:
            return AudioContinuity(False, reason="stale audio epoch")

        if chunk.audio_epoch > self._epoch:
            self._epoch = chunk.audio_epoch
            self._track_sid = chunk.master_track_sid
            self._format = config
            self._next_offset = 0
            self._last_sequence = -1

        if self._track_sid != chunk.master_track_sid:
            return AudioContinuity(False, reason="track changed without a new audio epoch")
        if self._format != config:
            return AudioContinuity(False, reason="PCM format changed inside an audio epoch")
        if chunk.sequence <= self._last_sequence:
            return AudioContinuity(False, reason="duplicate or out-of-order audio sequence")
        if chunk.sample_offset < self._next_offset:
            return AudioContinuity(False, reason="overlapping or replayed PCM samples")

        gap = chunk.sample_offset - self._next_offset
        self._next_offset = chunk.end_sample_offset
        self._last_sequence = chunk.sequence
        return AudioContinuity(True, gap_sample_frames=gap)
