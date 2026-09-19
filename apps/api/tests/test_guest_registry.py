"""Person B — the consent registry itself, not the HTTP shell around it.

`test_guests.py` drives these rules through the API. These cases drive the
registry directly, because consent, reference versioning and deletion are where
a quiet mistake costs a guest their privacy rather than a 500.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from cue_api.guests.contracts import (
    ConsentPurpose,
    GuestEnrolmentRequest,
    GuestRecord,
    GuestStatus,
    ReferenceSubmission,
)
from cue_api.guests.registry import (
    DEFAULT_EMBEDDING_DIMENSION,
    ConsentError,
    GuestNotFoundError,
    GuestRegistry,
    normalise_embedding,
)

EVENT = "hackmit-demo"
NOW = 1_758_293_400_000
FIXTURES = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "fixtures"

FULL_CONSENT = [
    ConsentPurpose.LIVE_IDENTIFICATION,
    ConsentPurpose.RECORDING,
    ConsentPurpose.CLOUD_RELAY,
]


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def embedding(*leading: float) -> list[float]:
    values = [0.0] * DEFAULT_EMBEDDING_DIMENSION
    for index, value in enumerate(leading):
        values[index] = value
    return values


def enrol(
    registry: GuestRegistry,
    name: str = "Sarah",
    *,
    purposes: list[ConsentPurpose] | None = None,
    granted: bool = True,
    guest_id: str | None = None,
    event_id: str = EVENT,
    now_ms: int = NOW,
) -> GuestRecord:
    return registry.enrol(
        event_id=event_id,
        display_name=name,
        aliases=[],
        consent_granted=granted,
        consent_purposes=purposes if purposes is not None else list(FULL_CONSENT),
        recorded_by="B",
        guest_id=guest_id,
        now_ms=now_ms,
    )


def add_reference(
    registry: GuestRegistry,
    guest_id: str,
    *,
    vector: list[float] | None = None,
    quality: float = 0.8,
    event_id: str = EVENT,
    now_ms: int = NOW,
) -> GuestRecord:
    return registry.add_reference(
        event_id=event_id,
        guest_id=guest_id,
        embedding=vector if vector is not None else embedding(1.0),
        quality=quality,
        embedder="opencv-sface",
        embedder_version="2021dec",
        captured_at_ms=now_ms,
        now_ms=now_ms,
    )


@pytest.fixture
def registry() -> GuestRegistry:
    return GuestRegistry()


# --- consent ---------------------------------------------------------------


def test_a_refused_consent_never_creates_a_guest(registry: GuestRegistry) -> None:
    with pytest.raises(ConsentError, match="without granted consent"):
        enrol(registry, granted=False)

    assert registry.list_guests(EVENT) == []


def test_consent_to_filming_is_not_consent_to_being_matched(registry: GuestRegistry) -> None:
    with pytest.raises(ConsentError, match="Live identification consent"):
        enrol(registry, purposes=[ConsentPurpose.RECORDING, ConsentPurpose.CLOUD_RELAY])

    assert registry.list_guests(EVENT) == []


def test_the_refusal_fixtures_are_well_formed_and_still_refused(
    registry: GuestRegistry,
) -> None:
    # Both payloads validate against the contract. The schema cannot express a
    # consent decision, so the registry has to be the one that says no.
    for name in (
        "guest-enrolment-request.consent-refused.json",
        "guest-enrolment-request.recording-only.json",
    ):
        request = GuestEnrolmentRequest.model_validate(load(name))

        with pytest.raises(ConsentError):
            registry.enrol(
                event_id=request.event_id,
                display_name=request.display_name,
                aliases=request.aliases,
                consent_granted=request.consent_granted,
                consent_purposes=request.consent_purposes,
                recorded_by=request.recorded_by,
                guest_id=request.guest_id,
                now_ms=NOW,
            )

    assert registry.list_guests(EVENT) == []


def test_the_valid_enrolment_fixture_produces_a_consenting_guest(
    registry: GuestRegistry,
) -> None:
    request = GuestEnrolmentRequest.model_validate(load("guest-enrolment-request.json"))

    record = registry.enrol(
        event_id=request.event_id,
        display_name=request.display_name,
        aliases=request.aliases,
        consent_granted=request.consent_granted,
        consent_purposes=request.consent_purposes,
        recorded_by=request.recorded_by,
        guest_id=request.guest_id,
        now_ms=NOW,
    )

    assert record.guest_id == "guest-sarah"
    assert record.status is GuestStatus.ENROLLING
    assert record.consent.granted is True
    assert record.consent.scope == "EVENT"
    assert record.consent.granted_at_ms == NOW
    assert record.consent.withdrawn_at_ms is None


def test_consent_records_who_took_it(registry: GuestRegistry) -> None:
    record = enrol(registry)

    assert record.consent.recorded_by == "B"


# --- identifiers -----------------------------------------------------------


def test_a_guest_id_is_derived_from_the_name_not_a_seat(registry: GuestRegistry) -> None:
    assert enrol(registry, "Sarah Lee").guest_id == "guest-sarah-lee"


def test_punctuation_collapses_into_one_separator(registry: GuestRegistry) -> None:
    assert enrol(registry, "Ana-Maria  O'Brien").guest_id == "guest-ana-maria-o-brien"


def test_a_name_with_nothing_usable_still_gets_an_id(registry: GuestRegistry) -> None:
    assert enrol(registry, "!!!").guest_id == "guest-guest"


def test_two_guests_with_the_same_name_stay_distinct(registry: GuestRegistry) -> None:
    first = enrol(registry, "Sarah")
    second = enrol(registry, "Sarah")
    third = enrol(registry, "Sarah")

    assert [first.guest_id, second.guest_id, third.guest_id] == [
        "guest-sarah",
        "guest-sarah-2",
        "guest-sarah-3",
    ]


def test_an_explicit_id_is_honoured(registry: GuestRegistry) -> None:
    assert enrol(registry, "Sarah", guest_id="guest-host-partner").guest_id == "guest-host-partner"


def test_reusing_an_explicit_id_is_refused(registry: GuestRegistry) -> None:
    enrol(registry, "Sarah", guest_id="guest-sarah")

    with pytest.raises(ValueError, match="already exists"):
        enrol(registry, "Someone else", guest_id="guest-sarah")


def test_the_same_id_in_another_event_is_a_different_person(registry: GuestRegistry) -> None:
    enrol(registry, "Sarah", guest_id="guest-sarah")
    enrol(registry, "Sarah", guest_id="guest-sarah", event_id="another-event")

    assert len(registry.list_guests(EVENT)) == 1
    assert len(registry.list_guests("another-event")) == 1


# --- references ------------------------------------------------------------


def test_an_embedding_is_stored_at_unit_length(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id
    add_reference(registry, guest_id, vector=embedding(3.0, 4.0))

    _, entries = registry.gallery(EVENT)
    vector = entries[0][3][0]

    assert math.hypot(*vector) == pytest.approx(1.0)
    assert vector[0] == pytest.approx(0.6)
    assert vector[1] == pytest.approx(0.8)


def test_the_reference_fixture_is_accepted_and_normalised(registry: GuestRegistry) -> None:
    submission = ReferenceSubmission.model_validate(load("reference-submission.json"))
    guest_id = enrol(registry).guest_id

    record = registry.add_reference(
        event_id=submission.event_id,
        guest_id=guest_id,
        embedding=submission.embedding,
        quality=submission.quality,
        embedder=submission.embedder,
        embedder_version=submission.embedder_version,
        captured_at_ms=submission.captured_at_ms,
        now_ms=NOW,
    )

    assert record.reference_count == 1
    assert record.mean_reference_quality == pytest.approx(submission.quality)
    _, entries = registry.gallery(EVENT)
    assert math.hypot(*entries[0][3][0]) == pytest.approx(1.0)


def test_the_first_reference_activates_the_guest(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id
    assert registry.get(EVENT, guest_id).status is GuestStatus.ENROLLING

    record = add_reference(registry, guest_id)

    assert record.status is GuestStatus.ACTIVE
    assert record.reference_version == 1


def test_each_reference_advances_the_version(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id

    add_reference(registry, guest_id, vector=embedding(1.0))
    add_reference(registry, guest_id, vector=embedding(0.0, 1.0))
    record = add_reference(registry, guest_id, vector=embedding(0.0, 0.0, 1.0))

    assert record.reference_version == 3
    assert record.reference_count == 3


def test_mean_reference_quality_covers_every_reference(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id

    add_reference(registry, guest_id, vector=embedding(1.0), quality=0.6)
    record = add_reference(registry, guest_id, vector=embedding(0.0, 1.0), quality=0.8)

    assert record.mean_reference_quality == pytest.approx(0.7)


def test_a_wrong_width_embedding_names_the_expected_width(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id

    with pytest.raises(ValueError, match="Expected a 128-d embedding, received 3"):
        add_reference(registry, guest_id, vector=[0.1, 0.2, 0.3])


def test_a_non_finite_embedding_is_refused(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id

    with pytest.raises(ValueError, match="non-finite"):
        add_reference(registry, guest_id, vector=embedding(float("nan")))


def test_a_zero_embedding_is_refused(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id

    with pytest.raises(ValueError, match="no magnitude"):
        add_reference(registry, guest_id, vector=embedding())


def test_a_reference_for_an_unenrolled_guest_is_refused(registry: GuestRegistry) -> None:
    with pytest.raises(GuestNotFoundError, match="not enrolled"):
        add_reference(registry, "guest-nobody")


def test_the_embedding_dimension_is_configurable(registry: GuestRegistry) -> None:
    small = GuestRegistry(embedding_dimension=4)
    guest_id = enrol(small).guest_id

    record = small.add_reference(
        event_id=EVENT,
        guest_id=guest_id,
        embedding=[0.0, 3.0, 4.0, 0.0],
        quality=0.7,
        embedder="fixture",
        embedder_version="test",
        captured_at_ms=NOW,
        now_ms=NOW,
    )

    assert record.reference_count == 1
    assert small.embedding_dimension == 4


# --- identifiability and the worker gallery --------------------------------


def test_a_guest_without_references_is_not_identifiable(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id

    assert registry.is_identifiable(EVENT, guest_id) is False
    assert registry.gallery(EVENT)[1] == []


def test_a_guest_with_references_is_identifiable(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id
    add_reference(registry, guest_id)

    assert registry.is_identifiable(EVENT, guest_id) is True


def test_an_unknown_guest_is_never_identifiable(registry: GuestRegistry) -> None:
    assert registry.is_identifiable(EVENT, "guest-nobody") is False


def test_the_gallery_hands_out_copies_not_its_own_storage(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id
    add_reference(registry, guest_id, vector=embedding(3.0, 4.0))

    _, entries = registry.gallery(EVENT)
    entries[0][3][0][0] = 99.0

    _, again = registry.gallery(EVENT)
    assert again[0][3][0][0] == pytest.approx(0.6)


def test_the_gallery_is_scoped_to_one_event(registry: GuestRegistry) -> None:
    here = enrol(registry, "Sarah").guest_id
    there = enrol(registry, "Daniel", event_id="another-event").guest_id
    add_reference(registry, here)
    add_reference(registry, there, event_id="another-event")

    _, entries = registry.gallery(EVENT)

    assert [entry[0] for entry in entries] == ["guest-sarah"]


def test_the_gallery_version_advances_on_every_change(registry: GuestRegistry) -> None:
    start = registry.gallery_version

    guest_id = enrol(registry).guest_id
    after_enrol = registry.gallery_version
    add_reference(registry, guest_id)
    after_reference = registry.gallery_version

    assert after_enrol > start
    assert after_reference > after_enrol
    assert registry.gallery_version == after_reference  # reading does not bump it


# --- withdrawal and deletion ----------------------------------------------


def test_withdrawal_deletes_the_references_and_says_how_many(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id
    add_reference(registry, guest_id, vector=embedding(1.0))
    add_reference(registry, guest_id, vector=embedding(0.0, 1.0))

    record, deleted = registry.withdraw(event_id=EVENT, guest_id=guest_id, now_ms=NOW + 1000)

    assert deleted == 2
    assert record.status is GuestStatus.WITHDRAWN
    assert record.reference_count == 0
    assert record.reference_version == 0
    assert record.mean_reference_quality is None
    assert record.consent.granted is False
    assert record.consent.withdrawn_at_ms == NOW + 1000


def test_a_withdrawn_guest_leaves_the_gallery_immediately(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id
    add_reference(registry, guest_id)

    registry.withdraw(event_id=EVENT, guest_id=guest_id, now_ms=NOW + 1000)

    assert registry.gallery(EVENT)[1] == []
    assert registry.is_identifiable(EVENT, guest_id) is False


def test_a_withdrawn_guest_cannot_quietly_regain_a_reference(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id
    add_reference(registry, guest_id)
    registry.withdraw(event_id=EVENT, guest_id=guest_id, now_ms=NOW + 1000)

    with pytest.raises(ConsentError, match="withdrawn consent"):
        add_reference(registry, guest_id)


def test_the_withdrawn_record_still_satisfies_the_contract(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id
    add_reference(registry, guest_id)
    record, _ = registry.withdraw(event_id=EVENT, guest_id=guest_id, now_ms=NOW + 1000)

    # The contract refuses a withdrawal that kept consent or references, so a
    # round trip proves the registry left the record in a consistent state.
    assert GuestRecord.model_validate(record.model_dump(by_alias=True)) == record


def test_withdrawing_twice_reports_nothing_left_to_delete(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id
    add_reference(registry, guest_id)

    registry.withdraw(event_id=EVENT, guest_id=guest_id, now_ms=NOW + 1000)
    _, deleted = registry.withdraw(event_id=EVENT, guest_id=guest_id, now_ms=NOW + 2000)

    assert deleted == 0


def test_withdrawing_an_unknown_guest_is_an_error_not_a_silent_success(
    registry: GuestRegistry,
) -> None:
    with pytest.raises(GuestNotFoundError):
        registry.withdraw(event_id=EVENT, guest_id="guest-nobody", now_ms=NOW)


def test_ending_the_event_removes_the_records_themselves(registry: GuestRegistry) -> None:
    sarah = enrol(registry, "Sarah").guest_id
    daniel = enrol(registry, "Daniel").guest_id
    add_reference(registry, sarah)
    add_reference(registry, daniel)

    guest_ids, deleted = registry.purge_event(event_id=EVENT)

    assert sorted(guest_ids) == ["guest-daniel", "guest-sarah"]
    assert deleted == 2
    assert registry.list_guests(EVENT) == []


def test_ending_one_event_leaves_another_alone(registry: GuestRegistry) -> None:
    enrol(registry, "Sarah")
    enrol(registry, "Daniel", event_id="another-event")

    registry.purge_event(event_id=EVENT)

    assert [guest.guest_id for guest in registry.list_guests("another-event")] == ["guest-daniel"]


def test_purging_an_empty_event_changes_nothing(registry: GuestRegistry) -> None:
    before = registry.gallery_version

    guest_ids, deleted = registry.purge_event(event_id="never-happened")

    assert (guest_ids, deleted) == ([], 0)
    assert registry.gallery_version == before


# --- records are snapshots -------------------------------------------------


def test_a_returned_record_never_carries_an_embedding(registry: GuestRegistry) -> None:
    guest_id = enrol(registry).guest_id
    record = add_reference(registry, guest_id)

    keys = record.model_dump(by_alias=True).keys()

    assert "embeddings" not in keys
    assert "references" not in keys


def test_a_returned_record_does_not_change_underneath_the_caller(
    registry: GuestRegistry,
) -> None:
    guest_id = enrol(registry).guest_id
    before = registry.get(EVENT, guest_id)

    add_reference(registry, guest_id)

    assert before.reference_count == 0
    assert registry.get(EVENT, guest_id).reference_count == 1


def test_guests_are_listed_in_a_stable_order(registry: GuestRegistry) -> None:
    enrol(registry, "Sarah")
    enrol(registry, "Daniel")
    enrol(registry, "Ana")

    assert [guest.guest_id for guest in registry.list_guests(EVENT)] == [
        "guest-ana",
        "guest-daniel",
        "guest-sarah",
    ]


# --- the normalisation helper ---------------------------------------------


def test_normalisation_preserves_direction(registry: GuestRegistry) -> None:
    vector = normalise_embedding([0.0, 3.0, 0.0, 4.0], 4)

    assert vector == pytest.approx((0.0, 0.6, 0.0, 0.8))


def test_normalisation_refuses_a_vector_of_the_wrong_width() -> None:
    with pytest.raises(ValueError, match="received 3"):
        normalise_embedding([1.0, 0.0, 0.0], 4)


def test_normalisation_refuses_an_infinite_value() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        normalise_embedding([float("inf"), 0.0, 0.0, 0.0], 4)


def test_normalisation_refuses_a_vector_too_small_to_have_a_direction() -> None:
    with pytest.raises(ValueError, match="no magnitude"):
        normalise_embedding([1e-12, 0.0, 0.0, 0.0], 4)
