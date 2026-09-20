"""End-of-event cleanup, and whether it can prove itself.

The tests that matter here are the ones where the purge **half-succeeds**. A
partial cleanup looks identical to a complete one unless somebody re-reads, so
these drive a backend that lies by omission and check the record catches it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cue_api.guests.cleanup import (
    REQUIRED_CHECKS,
    CleanupRecord,
    cleanup_lines,
    run_cleanup,
)
from cue_api.guests.reference_gallery import GuestReferences, ReferenceGallery, normalise

SARAH = normalise((1.0, 0.0, 0.0, 0.0))


@dataclass
class FakeBackend:
    """A backend whose state after the purge is whatever the test says it is."""

    gallery_after: ReferenceGallery = field(default_factory=ReferenceGallery.empty)
    guests_after: list[dict[str, Any]] = field(default_factory=list)
    cameras_after: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"cameraId": "CAM-HOST", "observation": None},
            {"cameraId": "CAM-GUEST", "observation": None},
            {"cameraId": "CAM-WIDE", "observation": None},
        ]
    )
    receipt: dict[str, Any] = field(
        default_factory=lambda: {
            "eventId": "hackmit-demo",
            "guestIds": ["guest-sarah"],
            "referencesDeleted": 3,
            "observationsDropped": 1,
            "purgedAtMs": 1_700_000_000_000,
        }
    )
    purges: int = 0

    def purge_event(self, event_id: str) -> dict[str, Any]:
        self.purges += 1
        return self.receipt

    def list_guests(self, event_id: str) -> dict[str, Any]:
        return {"guests": self.guests_after}

    def fetch_gallery(self, event_id: str) -> ReferenceGallery:
        return self.gallery_after

    def read_observations(self, event_id: str) -> dict[str, Any]:
        return {"cameras": self.cameras_after}


def withdrawn_stub(guest_id: str = "guest-sarah") -> dict[str, Any]:
    return {
        "guestId": guest_id,
        "status": "WITHDRAWN",
        "referenceCount": 0,
        "consent": {"granted": False, "withdrawnAtMs": 1_700_000_000_000},
    }


# -- the clean case --------------------------------------------------------


def test_a_complete_cleanup_reports_clean_and_shows_its_work() -> None:
    record = run_cleanup(FakeBackend(), "hackmit-demo", purge=True)

    assert record.clean is True
    assert record.remaining == []
    assert record.guests_purged == ["guest-sarah"]
    assert record.references_deleted == 3
    assert record.observations_dropped == 1
    # The record lists the checks that came back empty, not just the verdict.
    assert len(record.verified) == 3


def test_a_withdrawn_stub_with_nothing_attached_is_acceptable() -> None:
    """The record of a withdrawal may remain; what it must not hold is data."""
    backend = FakeBackend(guests_after=[withdrawn_stub()])

    record = run_cleanup(backend, "hackmit-demo", purge=True)

    assert record.clean is True
    assert any("no references and no consent" in check for check in record.verified)


def test_the_purge_happens_exactly_once() -> None:
    backend = FakeBackend()

    run_cleanup(backend, "hackmit-demo", purge=True)

    assert backend.purges == 1


def test_verifying_only_is_the_default_and_deletes_nothing() -> None:
    """After A's /events/{id}/end the data is already gone; do not purge again."""
    backend = FakeBackend()

    record = run_cleanup(backend, "hackmit-demo")

    assert backend.purges == 0
    assert record.purged_here is False
    assert record.clean is True
    assert record.guests_purged == []


def test_verifying_only_still_catches_data_that_survived() -> None:
    backend = FakeBackend(
        gallery_after=ReferenceGallery(
            version=9, guests=(GuestReferences("guest-sarah", "Sarah", 1, (SARAH,)),)
        )
    )

    record = run_cleanup(backend, "hackmit-demo")

    assert backend.purges == 0
    assert record.clean is False
    assert record.remaining[0].where == "worker gallery"


def test_a_verify_only_record_does_not_claim_deletions_it_did_not_make() -> None:
    record = run_cleanup(FakeBackend(), "hackmit-demo")
    document = record.to_document()

    assert document["purgedHere"] is False
    assert document["referencesDeleted"] == 0
    assert document["observationsDropped"] == 0
    assert "verifying only" in chr(10).join(cleanup_lines(record))


# -- the cases that matter: a purge that half-succeeded -------------------


def test_an_embedding_left_in_the_gallery_is_caught() -> None:
    """The gallery is the only route embeddings leave by."""
    backend = FakeBackend(
        gallery_after=ReferenceGallery(
            version=9, guests=(GuestReferences("guest-sarah", "Sarah", 1, (SARAH,)),)
        )
    )

    record = run_cleanup(backend, "hackmit-demo", purge=True)

    assert record.clean is False
    assert record.remaining[0].where == "worker gallery"
    assert "still has 1 embedding" in record.remaining[0].detail


def test_a_guest_still_holding_a_reference_is_caught() -> None:
    backend = FakeBackend(
        guests_after=[{**withdrawn_stub(), "referenceCount": 2}]
    )

    record = run_cleanup(backend, "hackmit-demo", purge=True)

    assert record.clean is False
    assert any("still reports 2 reference" in item.detail for item in record.remaining)


def test_a_guest_still_claiming_consent_after_the_event_is_caught() -> None:
    """Consent is event-scoped; surviving it is a finding, not a convenience."""
    backend = FakeBackend(
        guests_after=[{**withdrawn_stub(), "consent": {"granted": True}}]
    )

    record = run_cleanup(backend, "hackmit-demo", purge=True)

    assert record.clean is False
    assert any("still claims consent" in item.detail for item in record.remaining)


def test_live_evidence_left_on_a_camera_is_caught() -> None:
    backend = FakeBackend(
        cameras_after=[
            {"cameraId": "CAM-HOST", "observation": None},
            {"cameraId": "CAM-GUEST", "observation": {"observationId": "left-behind"}},
            {"cameraId": "CAM-WIDE", "observation": None},
        ]
    )

    record = run_cleanup(backend, "hackmit-demo", purge=True)

    assert record.clean is False
    assert record.remaining[0].where == "live evidence"
    assert "CAM-GUEST" in record.remaining[0].detail


def test_every_surviving_item_is_listed_not_just_the_first() -> None:
    """An operator fixing one leak should not discover the others one at a time."""
    backend = FakeBackend(
        gallery_after=ReferenceGallery(
            version=9, guests=(GuestReferences("guest-sarah", "Sarah", 1, (SARAH,)),)
        ),
        guests_after=[{**withdrawn_stub(), "referenceCount": 2}],
        cameras_after=[{"cameraId": "CAM-GUEST", "observation": {"observationId": "x"}}],
    )

    record = run_cleanup(backend, "hackmit-demo", purge=True)

    assert record.clean is False
    assert {item.where for item in record.remaining} == {
        "worker gallery",
        "guest record",
        "live evidence",
    }


def test_a_receipt_claiming_deletions_does_not_make_a_run_clean() -> None:
    """The receipt is the backend's word; the re-read is the evidence."""
    backend = FakeBackend(
        receipt={
            "eventId": "hackmit-demo",
            "guestIds": ["guest-sarah"],
            "referencesDeleted": 99,
            "observationsDropped": 99,
            "purgedAtMs": 1,
        },
        gallery_after=ReferenceGallery(
            version=9, guests=(GuestReferences("guest-sarah", "Sarah", 1, (SARAH,)),)
        ),
    )

    record = run_cleanup(backend, "hackmit-demo", purge=True)

    assert record.references_deleted == 99
    assert record.clean is False


# -- the record a human reads and files -----------------------------------


def test_the_document_is_filed_with_a_verdict() -> None:
    document = run_cleanup(FakeBackend(), "hackmit-demo", purge=True).to_document()

    assert document["clean"] is True
    assert document["eventId"] == "hackmit-demo"
    assert document["guestsPurged"] == ["guest-sarah"]
    assert document["remaining"] == []
    assert document["verified"]


def test_a_failed_cleanup_says_what_survived() -> None:
    backend = FakeBackend(
        cameras_after=[{"cameraId": "CAM-GUEST", "observation": {"observationId": "x"}}]
    )

    text = "\n".join(cleanup_lines(run_cleanup(backend, "hackmit-demo", purge=True)))

    assert "NOT CLEAN" in text
    assert "survived the purge" in text  # this run did purge
    assert "CAM-GUEST still holds an observation" in text


def test_a_verify_only_failure_does_not_blame_a_purge_it_never_made() -> None:
    backend = FakeBackend(
        cameras_after=[{"cameraId": "CAM-GUEST", "observation": {"observationId": "x"}}]
    )

    text = chr(10).join(cleanup_lines(run_cleanup(backend, "hackmit-demo")))

    assert "NOT CLEAN" in text
    assert "is still present" in text
    assert "survived the purge" not in text


def test_a_clean_cleanup_says_it_was_re_read() -> None:
    text = "\n".join(cleanup_lines(run_cleanup(FakeBackend(), "hackmit-demo", purge=True)))

    assert "clean — re-read found nothing remaining" in text
    assert "NOT CLEAN" not in text


def test_a_record_with_no_checks_run_is_not_clean() -> None:
    """"Nothing remains" is not the same claim as "we looked and nothing remains".

    An unverified record must not be indistinguishable from a verified one, which
    is the exact failure this module exists to prevent.
    """
    record = CleanupRecord(event_id="hackmit-demo")

    assert record.remaining == []
    assert record.verification_complete is False
    assert record.clean is False


def test_a_partial_verification_is_not_clean_either() -> None:
    record = CleanupRecord(event_id="hackmit-demo")
    record.checks_run.update({"gallery", "guest_records"})

    assert record.clean is False
    assert "live_evidence" in "".join(cleanup_lines(record))


def test_a_run_cleanup_record_has_run_every_required_check() -> None:
    record = run_cleanup(FakeBackend(), "hackmit-demo", purge=True)

    assert record.checks_run == REQUIRED_CHECKS
    assert record.verification_complete is True
    assert record.to_document()["checksRun"] == sorted(REQUIRED_CHECKS)


def test_an_unverified_record_says_which_checks_never_ran() -> None:
    text = chr(10).join(cleanup_lines(CleanupRecord(event_id="hackmit-demo")))

    assert "UNVERIFIED" in text
    assert "gallery" in text
    assert "live_evidence" in text
