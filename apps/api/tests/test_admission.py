from __future__ import annotations

import pytest

from cue_api.admission import AdmissionCode, AdmissionError, AdmissionStore, ClaimStatus
from cue_api.contracts import CameraId


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_single_use_pairing_cannot_be_replayed_or_change_slot() -> None:
    store = AdmissionStore()
    created = store.create_grant("demo-event", CameraId.GUEST)

    claim = store.claim(created.pairing_token, "Person B", "B laptop")

    assert claim.claim.camera_id is CameraId.GUEST
    assert claim.claim.status is ClaimStatus.PENDING
    with pytest.raises(AdmissionError) as replay:
        store.claim(created.pairing_token, "Attacker", "other device")
    assert replay.value.code is AdmissionCode.ALREADY_USED


def test_slot_is_reserved_until_rejection_then_can_be_repaired() -> None:
    store = AdmissionStore()
    grant = store.create_grant("demo-event", CameraId.HOST)
    claim = store.claim(grant.pairing_token, "Person A", "A laptop")

    with pytest.raises(AdmissionError) as conflict:
        store.create_grant("demo-event", CameraId.HOST)
    assert conflict.value.code is AdmissionCode.CONFLICT

    store.decide("demo-event", claim.claim.claim_id, approved=False)
    replacement = store.create_grant("demo-event", CameraId.HOST)
    assert replacement.grant.camera_id is CameraId.HOST


def test_claim_secret_is_required_and_approval_precedes_exchange() -> None:
    store = AdmissionStore()
    grant = store.create_grant("demo-event", CameraId.WIDE)
    created = store.claim(grant.pairing_token, "Person C", "C laptop")

    with pytest.raises(AdmissionError) as wrong_secret:
        store.status(created.claim.claim_id, "cueclaim_wrong-secret-that-is-long-enough")
    assert wrong_secret.value.code is AdmissionCode.NOT_FOUND

    with pytest.raises(AdmissionError) as pending:
        store.begin_exchange(created.claim.claim_id, created.claim_secret)
    assert pending.value.code is AdmissionCode.NOT_APPROVED

    approved = store.decide("demo-event", created.claim.claim_id, approved=True)
    assert approved.status is ClaimStatus.APPROVED
    issuing = store.begin_exchange(created.claim.claim_id, created.claim_secret)
    assert issuing.status is ClaimStatus.ISSUING
    binding = store.complete_exchange(created.claim.claim_id)
    assert binding.camera_id is CameraId.WIDE
    assert binding.stream_epoch == 1

    with pytest.raises(AdmissionError) as replay:
        store.begin_exchange(created.claim.claim_id, created.claim_secret)
    assert replay.value.code is AdmissionCode.ALREADY_USED


def test_expired_grant_and_claim_fail_closed() -> None:
    clock = Clock()
    store = AdmissionStore(grant_ttl_seconds=30, claim_ttl_seconds=60, clock=clock)
    expired_grant = store.create_grant("demo-event", CameraId.HOST)
    clock.now += 31
    with pytest.raises(AdmissionError) as grant_error:
        store.claim(expired_grant.pairing_token, "A", "laptop")
    assert grant_error.value.code is AdmissionCode.NOT_FOUND

    fresh = store.create_grant("demo-event", CameraId.HOST)
    claim = store.claim(fresh.pairing_token, "A", "laptop")
    clock.now += 61
    with pytest.raises(AdmissionError) as claim_error:
        store.status(claim.claim.claim_id, claim.claim_secret)
    assert claim_error.value.code is AdmissionCode.EXPIRED


def test_track_republish_advances_epoch_without_changing_camera_binding() -> None:
    store = AdmissionStore()
    grant = store.create_grant("demo-event", CameraId.HOST)
    claim = store.claim(grant.pairing_token, "Person A", "A laptop")
    store.decide("demo-event", claim.claim.claim_id, approved=True)
    store.begin_exchange(claim.claim.claim_id, claim.claim_secret)
    binding = store.complete_exchange(claim.claim.claim_id)

    first = store.record_video_track(
        "demo-event", CameraId.HOST, binding.participant_identity, "TR_first"
    )
    duplicate = store.record_video_track(
        "demo-event", CameraId.HOST, binding.participant_identity, "TR_first"
    )
    republished = store.record_video_track(
        "demo-event", CameraId.HOST, binding.participant_identity, "TR_second"
    )

    assert first.stream_epoch == duplicate.stream_epoch == 1
    assert republished.stream_epoch == 2
    assert republished.camera_id is CameraId.HOST
    with pytest.raises(AdmissionError):
        store.record_video_track("demo-event", CameraId.HOST, "wrong identity", "TR_third")
