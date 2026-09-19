from __future__ import annotations

import threading
from dataclasses import dataclass

from cue_api.contracts import CAMERA_CONTRACTS, CameraId
from cue_api.media_contracts import DecodedVideoFrame, LatestFrameSlot


@dataclass(frozen=True)
class WorkerIngestResult:
    accepted: bool
    replaced_pending_frame: bool = False
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
