"""The Python half of the shared fixture check.

`packages/contracts/src/vision.test.ts` asserts the same rules on the same
files. If only one runtime rejects a payload, it is not a shared contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cue_api.guests.contracts import (
    IDENTITY_TTL_MS,
    GuestRecord,
    ObservationStatus,
    VisualObservation,
)
from cue_api.guests.observations import ObservationStore
from cue_api.guests.registry import GuestRegistry, normalise_embedding

FIXTURES = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "fixtures"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def confirmed(**overrides: Any) -> dict[str, Any]:
    payload = load("visual-observation.confirmed.json")
    payload.update(overrides)
    return payload


def test_the_confirmed_fixture_validates() -> None:
    observation = VisualObservation.model_validate(confirmed())

    assert observation.status is ObservationStatus.CONFIRMED
    assert observation.subject.guest_id == "guest-sarah"
    assert observation.timing.expires_at_ms - observation.timing.observed_at_ms == IDENTITY_TTL_MS


def test_the_ambiguous_fixture_stays_anonymous() -> None:
    observation = VisualObservation.model_validate(load("visual-observation.ambiguous.json"))

    assert observation.subject.guest_id is None
    assert observation.usable_for_named_take is False
    assert observation.match is not None
    assert observation.match.calibrated_confidence is None


def test_an_unknown_observation_may_not_name_a_guest() -> None:
    with pytest.raises(ValidationError, match="must not name a guest"):
        VisualObservation.model_validate(confirmed(status="UNKNOWN", usableForNamedTake=False))


def test_only_a_confirmed_observation_supports_a_named_take() -> None:
    with pytest.raises(ValidationError, match="Only a CONFIRMED observation"):
        VisualObservation.model_validate(confirmed(status="PROVISIONAL"))


def test_an_uncalibrated_match_may_not_report_a_confidence() -> None:
    payload = confirmed()
    payload["match"] = {**payload["match"], "calibrationStatus": "UNCALIBRATED"}

    with pytest.raises(ValidationError, match="uncalibrated match"):
        VisualObservation.model_validate(payload)


def test_an_observation_cannot_expire_before_it_was_observed() -> None:
    payload = confirmed()
    payload["timing"] = {
        **payload["timing"],
        "expiresAtMs": payload["timing"]["observedAtMs"] - 1,
    }

    with pytest.raises(ValidationError, match="cannot expire before"):
        VisualObservation.model_validate(payload)


def test_a_box_outside_the_frame_is_rejected() -> None:
    payload = confirmed()
    payload["box"] = {**payload["box"], "width": 1.4}

    with pytest.raises(ValidationError):
        VisualObservation.model_validate(payload)


def test_a_quality_failure_must_name_its_checks() -> None:
    payload = confirmed(status="LOW_QUALITY", usableForNamedTake=False)
    payload["subject"] = {"guestId": None, "displayName": None, "referenceVersion": None}
    payload["quality"] = {**payload["quality"], "passed": False, "failedChecks": []}

    with pytest.raises(ValidationError, match="must name the failed checks"):
        VisualObservation.model_validate(payload)


def test_a_display_name_without_an_identity_is_a_seat_label() -> None:
    payload = confirmed()
    payload["subject"] = {"guestId": None, "displayName": "Sarah", "referenceVersion": None}

    with pytest.raises(ValidationError, match="seat label"):
        VisualObservation.model_validate(payload)


def test_the_guest_fixture_validates() -> None:
    guest = GuestRecord.model_validate(load("guest-record.json"))

    assert guest.consent.scope == "EVENT"
    assert guest.storage == "MEMORY_ONLY"


def test_a_guest_record_may_not_carry_embeddings() -> None:
    payload = load("guest-record.json")
    payload["embeddings"] = [[0.1, 0.2]]

    with pytest.raises(ValidationError):
        GuestRecord.model_validate(payload)


def test_a_withdrawn_guest_may_not_still_claim_consent() -> None:
    payload = load("guest-record.json")
    payload["status"] = "WITHDRAWN"

    with pytest.raises(ValidationError, match="withdrawn guest"):
        GuestRecord.model_validate(payload)


def test_freshness_is_evaluated_against_the_expiry_not_the_arrival() -> None:
    observation = VisualObservation.model_validate(confirmed())
    expires = observation.timing.expires_at_ms

    assert observation.is_fresh(expires)
    assert not observation.is_fresh(expires + 1)


def test_a_late_observation_does_not_become_fresh_by_arriving_late() -> None:
    store = ObservationStore()
    registry = GuestRegistry()
    observation = VisualObservation.model_validate(confirmed())
    store.record(observation)

    snapshot = store.snapshot(
        event_id=observation.event_id,
        now_ms=observation.timing.expires_at_ms + 5_000,
        gallery_version=registry.gallery_version,
    )

    view = next(item for item in snapshot.cameras if item.camera_id == observation.camera_id)
    assert view.observation is not None
    assert view.fresh is False
    assert view.age_ms is not None and view.age_ms > IDENTITY_TTL_MS


def test_an_embedding_is_normalised_on_the_way_in() -> None:
    vector = normalise_embedding([3.0, 4.0] + [0.0] * 126, 128)

    assert pytest.approx(sum(value * value for value in vector)) == 1.0
    assert vector[0] == pytest.approx(0.6)


def test_a_zero_embedding_is_refused() -> None:
    with pytest.raises(ValueError, match="no magnitude"):
        normalise_embedding([0.0] * 128, 128)
