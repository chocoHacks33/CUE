from __future__ import annotations

from cue_api.guests.face_matching import MatchThresholds
from cue_api.guests.identity_ledger import IdentityLedger
from cue_api.guests.types import ObservationStatus

TRACK = "CAM-GUEST:1:face-1"


def build() -> IdentityLedger:
    return IdentityLedger(
        thresholds=MatchThresholds(confirmations_required=3, confirmation_window_ms=1200),
        identity_ttl_ms=1500,
    )


def test_one_frame_is_not_an_identity() -> None:
    ledger = build()

    first = ledger.observe_candidate(TRACK, "guest-sarah", 1000)
    second = ledger.observe_candidate(TRACK, "guest-sarah", 1080)

    assert first.status is ObservationStatus.PROVISIONAL
    assert second.status is ObservationStatus.PROVISIONAL
    assert second.consecutive_confirmations == 2


def test_repeated_agreement_confirms() -> None:
    ledger = build()

    for offset in (0, 80, 160):
        assertion = ledger.observe_candidate(TRACK, "guest-sarah", 1000 + offset)

    assert assertion.status is ObservationStatus.CONFIRMED
    assert assertion.expires_at_ms == 1160 + 1500


def test_a_flicker_between_two_guests_confirms_neither() -> None:
    ledger = build()

    ledger.observe_candidate(TRACK, "guest-sarah", 1000)
    ledger.observe_candidate(TRACK, "guest-sarah", 1080)
    switched = ledger.observe_candidate(TRACK, "guest-daniel", 1160)

    assert switched.consecutive_confirmations == 1
    assert switched.status is ObservationStatus.PROVISIONAL


def test_a_long_gap_restarts_the_count() -> None:
    ledger = build()

    ledger.observe_candidate(TRACK, "guest-sarah", 1000)
    ledger.observe_candidate(TRACK, "guest-sarah", 1080)
    resumed = ledger.observe_candidate(TRACK, "guest-sarah", 1080 + 1300)

    assert resumed.consecutive_confirmations == 1


def test_an_unreadable_frame_drops_the_identity() -> None:
    ledger = build()
    for offset in (0, 80, 160):
        ledger.observe_candidate(TRACK, "guest-sarah", 1000 + offset)

    ledger.observe_non_identity(TRACK)

    assert ledger.current(TRACK, 1200) is None


def test_identity_expires_with_its_last_supporting_frame() -> None:
    ledger = build()
    for offset in (0, 80, 160):
        ledger.observe_candidate(TRACK, "guest-sarah", 1000 + offset)

    assert ledger.current(TRACK, 1160 + 1499) is not None
    assert ledger.current(TRACK, 1160 + 1501) is None


def test_prune_removes_only_the_stale_tracks() -> None:
    ledger = build()
    ledger.observe_candidate("CAM-GUEST:1:face-1", "guest-sarah", 1000)
    ledger.observe_candidate("CAM-WIDE:1:face-1", "guest-daniel", 4000)

    removed = ledger.prune(4100)

    assert removed == 1
    assert len(ledger) == 1


def test_a_republished_camera_loses_every_identity_it_held() -> None:
    ledger = build()
    ledger.observe_candidate("CAM-GUEST:1:face-1", "guest-sarah", 1000)
    ledger.observe_candidate("CAM-GUEST:1:face-2", "guest-daniel", 1000)
    ledger.observe_candidate("CAM-WIDE:1:face-1", "guest-daniel", 1000)

    forgotten = ledger.forget_camera("CAM-GUEST")

    assert forgotten == 2
    assert ledger.current("CAM-WIDE:1:face-1", 1100) is not None


def test_withdrawn_consent_removes_the_guest_everywhere() -> None:
    ledger = build()
    ledger.observe_candidate("CAM-GUEST:1:face-1", "guest-sarah", 1000)
    ledger.observe_candidate("CAM-WIDE:1:face-3", "guest-sarah", 1000)

    forgotten = ledger.forget_guest("guest-sarah")

    assert forgotten == 2
    assert len(ledger) == 0
