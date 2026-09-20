from __future__ import annotations

import pytest

from cue_api.admission import AdmissionError, AdmissionStore
from cue_api.contracts import CameraId


def test_twenty_republishes_keep_the_physical_publisher_in_its_fixed_slot() -> None:
    """Automated stress check only; it does not replace the 20 LIVE trials."""
    store = AdmissionStore()
    grant = store.create_grant("stage4", CameraId.GUEST)
    claim = store.claim(grant.pairing_token, "Person B", "B laptop")
    store.decide("stage4", claim.claim.claim_id, approved=True)
    store.begin_exchange(claim.claim.claim_id, claim.claim_secret)
    original = store.complete_exchange(claim.claim.claim_id)

    for index in range(1, 21):
        track_sid = f"TR_republish_{index:02}"
        binding = store.record_video_track(
            "stage4",
            CameraId.GUEST,
            original.participant_identity,
            track_sid,
        )
        assert binding.camera_id is CameraId.GUEST
        assert binding.participant_identity == original.participant_identity
        assert binding.current_video_track_sid == track_sid
        assert binding.stream_epoch == index
        with pytest.raises(AdmissionError):
            store.record_video_track(
                "stage4",
                CameraId.GUEST,
                "publisher:stage4:CAM-WIDE:attacker",
                f"TR_attacker_{index:02}",
            )

    (current,) = store.list_bindings("stage4")
    assert current.camera_id is CameraId.GUEST
    assert current.participant_identity == original.participant_identity
    assert current.stream_epoch == 20
