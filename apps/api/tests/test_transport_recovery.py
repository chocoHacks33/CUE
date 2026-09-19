from __future__ import annotations

import pytest

from cue_api.admission import AdmissionError, AdmissionStore
from cue_api.contracts import CameraId, TransportOutcome
from cue_api.guests.observations import ObservationStore
from cue_api.transport import TransportCoordinator


def bound_store() -> tuple[AdmissionStore, str]:
    store = AdmissionStore()
    grant = store.create_grant("demo-event", CameraId.HOST)
    claim = store.claim(grant.pairing_token, "Person A", "A laptop")
    store.decide("demo-event", claim.claim.claim_id, approved=True)
    store.begin_exchange(claim.claim.claim_id, claim.claim_secret)
    binding = store.complete_exchange(claim.claim.claim_id)
    return store, binding.participant_identity


def test_republish_advances_epoch_and_late_detach_cannot_clear_new_track() -> None:
    admissions, identity = bound_store()
    observations = ObservationStore()
    transport = TransportCoordinator(admissions, observations)

    first = transport.attach_video(
        event_id="demo-event",
        camera_id=CameraId.HOST,
        participant_identity=identity,
        track_sid="TR-first",
    )
    republished = transport.attach_video(
        event_id="demo-event",
        camera_id=CameraId.HOST,
        participant_identity=identity,
        track_sid="TR-second",
    )
    late = transport.detach_video(
        event_id="demo-event",
        camera_id=CameraId.HOST,
        participant_identity=identity,
        track_sid="TR-first",
    )

    assert first.outcome is TransportOutcome.ATTACHED
    assert first.binding.stream_epoch == 1
    assert republished.outcome is TransportOutcome.REPUBLISHED
    assert republished.binding.stream_epoch == 2
    assert observations.current_epoch(
        event_id="demo-event", camera_id=CameraId.HOST
    ) == 2
    assert late.outcome is TransportOutcome.STALE_DETACH_IGNORED
    assert late.binding.current_video_track_sid == "TR-second"


def test_exact_detach_clears_track_without_rewinding_epoch() -> None:
    admissions, identity = bound_store()
    transport = TransportCoordinator(admissions, ObservationStore())
    transport.attach_video(
        event_id="demo-event",
        camera_id=CameraId.HOST,
        participant_identity=identity,
        track_sid="TR-first",
    )
    transport.attach_video(
        event_id="demo-event",
        camera_id=CameraId.HOST,
        participant_identity=identity,
        track_sid="TR-second",
    )

    detached = transport.detach_video(
        event_id="demo-event",
        camera_id=CameraId.HOST,
        participant_identity=identity,
        track_sid="TR-second",
    )

    assert detached.outcome is TransportOutcome.DETACHED
    assert detached.binding.current_video_track_sid is None
    assert detached.binding.stream_epoch == 2


def test_attach_after_clean_detach_gets_a_fresh_epoch() -> None:
    admissions, identity = bound_store()
    transport = TransportCoordinator(admissions, ObservationStore())
    first = transport.attach_video(
        event_id="demo-event",
        camera_id=CameraId.HOST,
        participant_identity=identity,
        track_sid="TR-first",
    )
    transport.detach_video(
        event_id="demo-event",
        camera_id=CameraId.HOST,
        participant_identity=identity,
        track_sid="TR-first",
    )

    reconnected = transport.attach_video(
        event_id="demo-event",
        camera_id=CameraId.HOST,
        participant_identity=identity,
        track_sid="TR-reconnected",
    )

    assert first.binding.stream_epoch == 1
    assert reconnected.outcome is TransportOutcome.REPUBLISHED
    assert reconnected.binding.stream_epoch == 2


def test_transport_event_cannot_take_over_another_bound_identity() -> None:
    admissions, _identity = bound_store()
    transport = TransportCoordinator(admissions, ObservationStore())
    with pytest.raises(AdmissionError):
        transport.attach_video(
            event_id="demo-event",
            camera_id=CameraId.HOST,
            participant_identity="publisher:demo-event:CAM-HOST:impostor",
            track_sid="TR-evil",
        )
