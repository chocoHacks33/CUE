from __future__ import annotations

import pytest

from cue_api.admission import AdmissionCode, AdmissionError, AdmissionStore
from cue_api.contracts import CameraId
from cue_api.control import ControlError, ControlSessionStore, ControlStore
from cue_api.control_contracts import ControlRole
from cue_api.guests.contracts import ConsentPurpose
from cue_api.guests.observations import ObservationStore
from cue_api.guests.registry import GuestRegistry
from cue_api.lifecycle import EventLifecycleCoordinator
from cue_api.readiness import ReadinessStore


def test_end_event_revokes_state_and_is_idempotent() -> None:
    admissions = AdmissionStore()
    grant = admissions.create_grant("demo-event", CameraId.HOST)
    claim = admissions.claim(grant.pairing_token, "Person A", "A laptop")
    admissions.decide("demo-event", claim.claim.claim_id, approved=True)
    admissions.begin_exchange(claim.claim.claim_id, claim.claim_secret)
    admissions.complete_exchange(claim.claim.claim_id)

    control = ControlStore()
    sessions = ControlSessionStore()
    token, _ttl = sessions.issue("demo-event", ControlRole.DIRECTOR)
    guests = GuestRegistry()
    guests.enrol(
        event_id="demo-event",
        display_name="Sarah",
        aliases=[],
        consent_granted=True,
        consent_purposes=[ConsentPurpose.LIVE_IDENTIFICATION],
        recorded_by="B",
        now_ms=1_000,
    )
    lifecycle = EventLifecycleCoordinator(
        admissions=admissions,
        control=control,
        sessions=sessions,
        readiness=ReadinessStore(),
        guests=guests,
        observations=ObservationStore(),
        clock_ms=lambda: 2_000,
    )

    receipt = lifecycle.end_event("demo-event")
    replay = lifecycle.end_event("demo-event")

    assert receipt.mode == "ENDED"
    assert receipt.control_sessions_revoked == 1
    assert receipt.bindings_deleted == 1
    assert receipt.guest_ids_deleted == ["guest-sarah"]
    assert replay.already_ended is True
    assert replay.ended_at_ms == receipt.ended_at_ms
    with pytest.raises(ControlError):
        sessions.validate(token, "demo-event")
    with pytest.raises(AdmissionError) as ended:
        admissions.create_grant("demo-event", CameraId.GUEST)
    assert ended.value.code is AdmissionCode.EVENT_ENDED
