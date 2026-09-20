from __future__ import annotations

import threading
import time
from collections.abc import Callable

from cue_api.admission import AdmissionStore
from cue_api.contracts import EventEndReceipt
from cue_api.control import ControlSessionStore, ControlStore
from cue_api.guests.observation_store import ObservationStore
from cue_api.guests.registry import GuestRegistry
from cue_api.readiness import ReadinessStore


class EventLifecycleCoordinator:
    """One idempotent end-of-event cleanup transaction for in-memory state."""

    def __init__(
        self,
        *,
        admissions: AdmissionStore,
        control: ControlStore,
        sessions: ControlSessionStore,
        readiness: ReadinessStore,
        guests: GuestRegistry,
        observations: ObservationStore,
        clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        self._admissions = admissions
        self._control = control
        self._sessions = sessions
        self._readiness = readiness
        self._guests = guests
        self._observations = observations
        self._clock_ms = clock_ms
        self._receipts: dict[str, EventEndReceipt] = {}
        self._lock = threading.RLock()

    def require_active(self, event_id: str) -> None:
        self._admissions.require_active(event_id)

    def end_event(self, event_id: str) -> EventEndReceipt:
        with self._lock:
            previous = self._receipts.get(event_id)
            if previous is not None:
                return previous.model_copy(update={"already_ended": True})

            control_state = self._control.end_event(event_id)
            sessions_revoked = self._sessions.revoke_event(event_id)
            admission = self._admissions.end_event(event_id)
            guest_ids, references_deleted = self._guests.purge_event(event_id=event_id)
            observations_dropped = self._observations.drop_event(event_id=event_id)
            readiness_removed = self._readiness.drop_event(event_id)
            receipt = EventEndReceipt(
                event_id=event_id,
                already_ended=False,
                mode=control_state.mode.value,
                control_sessions_revoked=sessions_revoked,
                grants_deleted=admission.grants_deleted,
                claims_deleted=admission.claims_deleted,
                bindings_deleted=admission.bindings_deleted,
                guest_ids_deleted=guest_ids,
                references_deleted=references_deleted,
                observations_dropped=observations_dropped,
                readiness_removed=readiness_removed,
                ended_at_ms=self._clock_ms(),
            )
            self._receipts[event_id] = receipt
            return receipt
