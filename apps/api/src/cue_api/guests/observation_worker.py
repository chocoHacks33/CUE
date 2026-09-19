"""The loop that turns A's frames into live observations.

Stage 2 wiring. Everything it needs already exists: A's `LatestFrameSlot` hands
over frames, `frame_intake.adapt` reshapes them, `VisionPipeline` decides what it
can honestly say, and the backend routes store it. This module is only the driver.

Three rules shape it:

1. **Never block the camera.** The slot is capacity-one by design, so the worker
   analyses the freshest frame and lets older ones go rather than draining a queue
   whose latency only grows.
2. **Never crash the loop.** A backend that is down, slow or returning 409 is an
   expected condition during a live show, not an exception worth stopping for. The
   worker counts failures and keeps looking at frames.
3. **Withdrawal wins immediately.** A refreshed gallery is the authority on who
   may be named. Anyone who disappears from it loses their identity in the same
   call, without waiting for the next enrolment cycle.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from cue_api.guests.frame_intake import FrameRejected, WorkerClock, adapt
from cue_api.guests.observation_pipeline import Observation, VisionPipeline
from cue_api.guests.reference_gallery import ReferenceGallery
from cue_api.media_contracts import LatestFrameSlot


class ObservationSink(Protocol):
    """What the worker needs from the backend. `GuestBackendClient` satisfies it."""

    def fetch_gallery(self, event_id: str) -> ReferenceGallery: ...

    def post_observation(self, observation: dict[str, object]) -> dict[str, object]: ...

    def invalidate(
        self,
        *,
        event_id: str,
        camera_id: str,
        current_stream_epoch: int,
        reason: str,
    ) -> dict[str, object]: ...


@dataclass
class WorkerCounters:
    """What happened, in numbers B can put in the identity report."""

    frames_analysed: int = 0
    frames_rejected: int = 0
    observations_posted: int = 0
    epochs_invalidated: int = 0
    gallery_refreshes: int = 0
    backend_failures: int = 0


@dataclass
class ObservationWorker:
    event_id: str
    pipeline: VisionPipeline
    sink: ObservationSink
    clock: WorkerClock
    counters: WorkerCounters = field(default_factory=WorkerCounters)
    #: Last epoch seen per camera, so a republish is noticed exactly once.
    _epochs: dict[str, int] = field(default_factory=dict, init=False)
    #: Why the most recent frames were refused, for the operator panel.
    last_rejection: str | None = field(default=None, init=False)

    # -- gallery -----------------------------------------------------------

    def refresh_gallery(self) -> bool:
        """Adopt the backend's gallery. Returns False if the backend was unreachable.

        `VisionPipeline.set_gallery` forgets anyone missing from the new gallery,
        so a withdrawal that happened between refreshes takes effect here.
        """
        try:
            gallery = self.sink.fetch_gallery(self.event_id)
        except Exception:  # noqa: BLE001 - a refresh failure must not stop the loop
            self.counters.backend_failures += 1
            return False
        self.pipeline.set_gallery(gallery)
        self.counters.gallery_refreshes += 1
        return True

    # -- frames ------------------------------------------------------------

    def poll(self, slots: Iterable[LatestFrameSlot]) -> list[Observation]:
        """Analyse the freshest frame from each slot and publish what it supports."""
        observations: list[Observation] = []
        for slot in slots:
            frame = slot.take()
            if frame is None:
                continue
            observations.extend(self._analyse(frame))
        return observations

    def _analyse(self, raw) -> list[Observation]:
        try:
            frame = adapt(raw, self.clock)
        except FrameRejected as error:
            self.counters.frames_rejected += 1
            self.last_rejection = str(error)
            return []

        self._note_epoch(frame.camera_id, frame.stream_epoch)

        observations = self.pipeline.observe(frame)
        self.counters.frames_analysed += 1
        self._publish(observations)
        return observations

    def _note_epoch(self, camera_id: str, stream_epoch: int) -> None:
        """A republish voids every identity the old epoch supported."""
        previous = self._epochs.get(camera_id)
        if previous is not None and stream_epoch == previous:
            return
        self._epochs[camera_id] = stream_epoch
        if previous is None:
            return

        reason = f"{camera_id} republished: epoch {previous} -> {stream_epoch}"
        self.pipeline.invalidate_camera(camera_id, reason)
        self.counters.epochs_invalidated += 1
        try:
            self.sink.invalidate(
                event_id=self.event_id,
                camera_id=camera_id,
                current_stream_epoch=stream_epoch,
                reason=reason,
            )
        except Exception:  # noqa: BLE001 - local evidence is already void
            self.counters.backend_failures += 1

    def _publish(self, observations: Sequence[Observation]) -> None:
        for observation in observations:
            try:
                self.sink.post_observation(observation.to_contract())
            except Exception:  # noqa: BLE001 - a dropped post is not a wrong cut
                self.counters.backend_failures += 1
            else:
                self.counters.observations_posted += 1

    # -- explicit signals from A -------------------------------------------

    def reframed(self, camera_id: str, stream_epoch: int, reason: str) -> int:
        """A reframe voids identity even when the stream epoch has not moved."""
        dropped = self.pipeline.invalidate_camera(camera_id, reason)
        self._epochs[camera_id] = stream_epoch
        try:
            self.sink.invalidate(
                event_id=self.event_id,
                camera_id=camera_id,
                current_stream_epoch=stream_epoch,
                reason=reason,
            )
        except Exception:  # noqa: BLE001
            self.counters.backend_failures += 1
        return dropped

    def forget_guest(self, guest_id: str) -> int:
        """Immediate withdrawal, without waiting for the next gallery refresh."""
        return self.pipeline.forget_guest(guest_id)
