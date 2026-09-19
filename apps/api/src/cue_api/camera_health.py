from __future__ import annotations

import threading
from dataclasses import dataclass

from cue_api.contracts import CAMERA_CONTRACTS, CameraId


@dataclass(frozen=True)
class CameraHealth:
    connected: bool
    publishing: bool
    receiving: bool
    decoding: bool
    renderable: bool
    visually_usable: bool
    stalled: bool
    recovering: bool
    last_frame_age_ms: int | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CameraHealthReport:
    camera_id: CameraId
    stream_epoch: int
    health: CameraHealth


class CameraHealthTracker:
    """Frame-progression health with a one-second stall and two-second recovery gate."""

    def __init__(self, *, stall_after_ms: int = 1_000, recover_after_ms: int = 2_000) -> None:
        self.stall_after_ms = stall_after_ms
        self.recover_after_ms = recover_after_ms
        self.connected = False
        self.publishing = False
        self.receiving = False
        self._transport_renderable = False
        self._visual_quality_usable = False
        self._warnings: tuple[str, ...] = ()
        self._last_sequence = -1
        self._last_frame_at_ms: int | None = None
        self._stalled = False
        self._recovery_started_at_ms: int | None = None

    def update_transport(
        self,
        *,
        connected: bool,
        publishing: bool,
        receiving: bool,
        renderable: bool,
        visually_usable: bool,
        warnings: tuple[str, ...] = (),
    ) -> None:
        self.connected = connected
        self.publishing = publishing
        self.receiving = receiving
        self._transport_renderable = renderable
        self._visual_quality_usable = visually_usable
        self._warnings = warnings

    def observe_frame(self, sequence: int, now_ms: int) -> bool:
        if sequence <= self._last_sequence:
            return False
        previous_at = self._last_frame_at_ms
        self._last_sequence = sequence
        self._last_frame_at_ms = now_ms

        if self._stalled:
            if previous_at is None or now_ms - previous_at > self.stall_after_ms:
                self._recovery_started_at_ms = now_ms
            elif self._recovery_started_at_ms is None:
                self._recovery_started_at_ms = now_ms
            elif now_ms - self._recovery_started_at_ms >= self.recover_after_ms:
                self._stalled = False
                self._recovery_started_at_ms = None
        return True

    def snapshot(self, now_ms: int) -> CameraHealth:
        age = None if self._last_frame_at_ms is None else max(0, now_ms - self._last_frame_at_ms)
        if age is not None and age > self.stall_after_ms:
            self._stalled = True
            self._recovery_started_at_ms = None

        decoding = self.receiving and age is not None and not self._stalled
        renderable = decoding and self._transport_renderable
        visually_usable = renderable and self._visual_quality_usable
        return CameraHealth(
            connected=self.connected,
            publishing=self.publishing,
            receiving=self.receiving,
            decoding=decoding,
            renderable=renderable,
            visually_usable=visually_usable,
            stalled=self._stalled,
            recovering=self._stalled and self._recovery_started_at_ms is not None,
            last_frame_age_ms=age,
            warnings=self._warnings,
        )


class CameraHealthRegistry:
    """Event-local health keyed by stable camera ID and current stream epoch."""

    def __init__(self) -> None:
        self._trackers = {camera_id: CameraHealthTracker() for camera_id in CAMERA_CONTRACTS}
        self._epochs = {camera_id: 0 for camera_id in CAMERA_CONTRACTS}
        self._lock = threading.RLock()

    def activate_epoch(self, camera_id: CameraId, stream_epoch: int) -> bool:
        if stream_epoch < 1:
            raise ValueError("stream_epoch must be positive")
        with self._lock:
            if stream_epoch < self._epochs[camera_id]:
                return False
            if stream_epoch > self._epochs[camera_id]:
                self._epochs[camera_id] = stream_epoch
                self._trackers[camera_id] = CameraHealthTracker()
            return True

    def update_transport(
        self,
        camera_id: CameraId,
        stream_epoch: int,
        *,
        connected: bool,
        publishing: bool,
        receiving: bool,
        renderable: bool,
        visually_usable: bool,
        warnings: tuple[str, ...] = (),
    ) -> bool:
        with self._lock:
            if not self.activate_epoch(camera_id, stream_epoch):
                return False
            self._trackers[camera_id].update_transport(
                connected=connected,
                publishing=publishing,
                receiving=receiving,
                renderable=renderable,
                visually_usable=visually_usable,
                warnings=warnings,
            )
            return True

    def observe_frame(
        self,
        camera_id: CameraId,
        stream_epoch: int,
        sequence: int,
        now_ms: int,
    ) -> bool:
        with self._lock:
            if not self.activate_epoch(camera_id, stream_epoch):
                return False
            return self._trackers[camera_id].observe_frame(sequence, now_ms)

    def snapshot(self, camera_id: CameraId, now_ms: int) -> CameraHealthReport:
        with self._lock:
            return CameraHealthReport(
                camera_id=camera_id,
                stream_epoch=self._epochs[camera_id],
                health=self._trackers[camera_id].snapshot(now_ms),
            )

    def current_epoch(self, camera_id: CameraId) -> int:
        with self._lock:
            return self._epochs[camera_id]

    def snapshot_all(self, now_ms: int) -> tuple[CameraHealthReport, ...]:
        return tuple(self.snapshot(camera_id, now_ms) for camera_id in CAMERA_CONTRACTS)
