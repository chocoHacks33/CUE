"""Latest-observation store for Person B's visual evidence.

Holds one current observation per camera, never a history of faces. Evidence is
dropped when its epoch is superseded, when it expires, and when the guest it
names withdraws consent.
"""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass, field

from cue_api.contracts import CameraId
from cue_api.guests.contracts import (
    CameraObservationView,
    ObservationSnapshot,
    ObservationStatus,
    VisualObservation,
)


class StaleEpochError(RuntimeError):
    """The observation describes a camera epoch that has already been replaced."""


@dataclass
class _CameraSlot:
    current_epoch: int = 0
    latest: VisualObservation | None = None
    invalidation_reason: str | None = None
    tallies: Counter[str] = field(default_factory=Counter)


class ObservationStore:
    def __init__(self) -> None:
        self._slots: dict[tuple[str, CameraId], _CameraSlot] = {}
        self._lock = threading.Lock()

    def record(self, observation: VisualObservation) -> VisualObservation:
        key = (observation.event_id, observation.camera_id)
        with self._lock:
            slot = self._slots.setdefault(key, _CameraSlot())
            if observation.stream_epoch < slot.current_epoch:
                raise StaleEpochError(
                    f"{observation.camera_id.value} is on epoch {slot.current_epoch}; "
                    f"observation claims epoch {observation.stream_epoch}"
                )
            if observation.stream_epoch > slot.current_epoch:
                slot.current_epoch = observation.stream_epoch
                slot.invalidation_reason = None
            slot.latest = observation
            slot.tallies[observation.status.value] += 1
            return observation

    def invalidate(
        self,
        *,
        event_id: str,
        camera_id: CameraId,
        current_stream_epoch: int,
        reason: str,
    ) -> bool:
        """Apply an epoch or reframe signal. Returns True if evidence was dropped.

        An explicit invalidation always clears the stored evidence, including on
        an unchanged epoch: a reframe or a lost track invalidates identity even
        when the publisher keeps the same stream.
        """
        key = (event_id, camera_id)
        with self._lock:
            slot = self._slots.setdefault(key, _CameraSlot())
            slot.current_epoch = max(slot.current_epoch, current_stream_epoch)
            slot.invalidation_reason = reason
            dropped = slot.latest is not None
            slot.latest = None
            return dropped

    def drop_guest(self, *, event_id: str, guest_id: str) -> int:
        """Consent withdrawal removes the guest from live evidence immediately."""
        dropped = 0
        with self._lock:
            for (stored_event, _), slot in self._slots.items():
                if stored_event != event_id or slot.latest is None:
                    continue
                if slot.latest.subject.guest_id == guest_id:
                    slot.latest = None
                    dropped += 1
        return dropped

    def drop_event(self, *, event_id: str) -> int:
        dropped = 0
        with self._lock:
            for key in [key for key in self._slots if key[0] == event_id]:
                if self._slots[key].latest is not None:
                    dropped += 1
                del self._slots[key]
        return dropped

    def current_epoch(self, *, event_id: str, camera_id: CameraId) -> int:
        with self._lock:
            slot = self._slots.get((event_id, camera_id))
            return slot.current_epoch if slot else 0

    def tallies(self, *, event_id: str) -> dict[str, int]:
        """Status counts for the identity report. No per-face history is kept."""
        totals: Counter[str] = Counter()
        with self._lock:
            for (stored_event, _), slot in self._slots.items():
                if stored_event == event_id:
                    totals.update(slot.tallies)
        return {status.value: totals.get(status.value, 0) for status in ObservationStatus}

    def snapshot(self, *, event_id: str, now_ms: int, gallery_version: int) -> ObservationSnapshot:
        views: list[CameraObservationView] = []
        with self._lock:
            for camera_id in CameraId:
                slot = self._slots.get((event_id, camera_id))
                latest = slot.latest if slot else None
                if latest is None:
                    views.append(CameraObservationView(camera_id=camera_id))
                    continue
                views.append(
                    CameraObservationView(
                        camera_id=camera_id,
                        observation=latest,
                        fresh=latest.is_fresh(now_ms),
                        age_ms=max(0, now_ms - latest.timing.observed_at_ms),
                    )
                )
        return ObservationSnapshot(
            event_id=event_id,
            now_ms=now_ms,
            gallery_version=gallery_version,
            cameras=views,
        )
