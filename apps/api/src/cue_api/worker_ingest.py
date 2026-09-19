from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

from cue_api.contracts import CAMERA_CONTRACTS, CameraId
from cue_api.guests.types import DecodedFrame
from cue_api.media_contracts import (
    DecodedAudioChunk,
    DecodedVideoFrame,
    LatestFrameSlot,
    PcmContinuityGuard,
    PixelFormat,
)


@dataclass(frozen=True)
class WorkerIngestResult:
    accepted: bool
    replaced_pending_frame: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class WorkerAudioIngestResult:
    accepted: bool
    gap_sample_frames: int = 0
    reason: str | None = None


class WorkerFrameIngestor:
    """In-process, latest-frame-only bridge from media decode to the worker.

    Raw frames never cross REST or the control WebSocket. Each camera has one
    replaceable slot, so an overloaded worker gets freshness instead of delay.
    """

    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        self._slots = {camera_id: LatestFrameSlot(camera_id) for camera_id in CAMERA_CONTRACTS}
        self._epochs = {camera_id: 0 for camera_id in CAMERA_CONTRACTS}
        self._lock = threading.Lock()

    def ingest(self, frame: DecodedVideoFrame) -> WorkerIngestResult:
        if frame.event_id != self.event_id:
            return WorkerIngestResult(False, reason="frame belongs to a different event")
        with self._lock:
            current_epoch = self._epochs[frame.camera_id]
            if frame.stream_epoch < current_epoch:
                return WorkerIngestResult(False, reason="stale stream epoch")
            if frame.stream_epoch > current_epoch:
                self._slots[frame.camera_id] = LatestFrameSlot(frame.camera_id)
                self._epochs[frame.camera_id] = frame.stream_epoch

            slot = self._slots[frame.camera_id]
            replaced = slot.peek() is not None
            try:
                accepted = slot.put(frame)
            except ValueError as error:
                return WorkerIngestResult(False, reason=str(error))
            if not accepted:
                return WorkerIngestResult(False, reason="duplicate or out-of-order frame")
            return WorkerIngestResult(True, replaced_pending_frame=replaced)

    def take(self, camera_id: CameraId) -> DecodedVideoFrame | None:
        with self._lock:
            return self._slots[camera_id].take()

    def current_epoch(self, camera_id: CameraId) -> int:
        with self._lock:
            return self._epochs[camera_id]


class WorkerAudioIngestor:
    """Bounded, loss-visible PCM handoff for C's streaming speech adapter."""

    def __init__(self, *, max_chunks: int = 100) -> None:
        if max_chunks < 1:
            raise ValueError("max_chunks must be positive")
        self._max_chunks = max_chunks
        self._chunks: deque[DecodedAudioChunk] = deque()
        self._continuity = PcmContinuityGuard()
        self._lock = threading.Lock()

    def ingest(self, chunk: DecodedAudioChunk) -> WorkerAudioIngestResult:
        with self._lock:
            if len(self._chunks) >= self._max_chunks:
                return WorkerAudioIngestResult(False, reason="audio worker queue is full")
            continuity = self._continuity.accept(chunk)
            if not continuity.accepted:
                return WorkerAudioIngestResult(False, reason=continuity.reason)
            self._chunks.append(chunk)
            return WorkerAudioIngestResult(
                True,
                gap_sample_frames=continuity.gap_sample_frames,
            )

    def take(self) -> DecodedAudioChunk | None:
        with self._lock:
            return self._chunks.popleft() if self._chunks else None

    def pending_chunks(self) -> int:
        with self._lock:
            return len(self._chunks)


def to_vision_frame(frame: DecodedVideoFrame) -> DecodedFrame:
    """Convert A's validated bytes to B's upright, unmirrored BGR frame."""
    try:
        import numpy  # noqa: PLC0415 - optional live-vision dependency
    except ImportError as error:  # pragma: no cover - depends on the Mac environment
        raise RuntimeError('Live frame conversion needs the API "vision" extra') from error

    bytes_per_pixel = frame.pixel_format.bytes_per_pixel
    rows = numpy.frombuffer(frame.data, dtype=numpy.uint8).reshape(frame.height, frame.stride_bytes)
    packed = rows[:, : frame.width * bytes_per_pixel].reshape(
        frame.height, frame.width, bytes_per_pixel
    )
    if frame.pixel_format is PixelFormat.RGB24:
        image: Any = packed[:, :, ::-1]
    elif frame.pixel_format is PixelFormat.RGBA32:
        image = packed[:, :, [2, 1, 0]]
    else:
        image = packed

    if frame.mirrored:
        image = image[:, ::-1]
    if frame.orientation_degrees:
        image = numpy.rot90(image, k=-(frame.orientation_degrees // 90))
    image = numpy.ascontiguousarray(image)
    height, width = image.shape[:2]
    return DecodedFrame(
        camera_id=frame.camera_id.value,
        stream_epoch=frame.stream_epoch,
        sequence=frame.sequence,
        width=width,
        height=height,
        received_at_ms=round(frame.received_at_monotonic_s * 1000),
        image=image,
        pixel_format="BGR24",
        orientation_degrees=0,
        captured_at_ms=(
            round(frame.capture_time_s * 1000) if frame.capture_time_s is not None else None
        ),
    )
