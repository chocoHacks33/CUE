"""Proving that consented data is actually gone.

Stage 5 asks B for "consented-data cleanup". Two things already delete it: A's
`POST /api/v1/events/{id}/end`, which is the authoritative end of an event and
purges guest records and observations along with sessions and bindings, and B's
`DELETE /api/v1/guests`, which purges guest data alone.

Neither reads the event back afterwards, and that is the gap this fills.

"We deleted it" and "we went back and checked it was gone" are different claims,
and the second is the one a guest is owed. A purge that silently half-succeeded
looks identical to one that worked if nobody re-reads. So this reads the event back
through the same public routes and states what it found — either after A's
end-event, or purging guest data itself first.

It **fails loudly**. Anything still present is listed, the record says `clean:
false`, and the command exits non-zero — because a cleanup nobody verified is
indistinguishable from a cleanup that did not happen, and the one outcome that must
never be quiet is data surviving an event it was consented for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from cue_api.guests.reference_gallery import ReferenceGallery


class CleanupTarget(Protocol):
    """What cleanup needs from the backend. `GuestBackendClient` satisfies it."""

    def purge_event(self, event_id: str) -> dict[str, Any]: ...

    def list_guests(self, event_id: str) -> dict[str, Any]: ...

    def fetch_gallery(self, event_id: str) -> ReferenceGallery: ...

    def read_observations(self, event_id: str) -> dict[str, Any]: ...


#: Every place consented data could survive a purge. All three must be read back
#: before a cleanup may be called clean.
REQUIRED_CHECKS = frozenset({"gallery", "guest_records", "live_evidence"})


@dataclass(frozen=True)
class Remaining:
    """One thing that survived the purge."""

    where: str
    detail: str


@dataclass
class CleanupRecord:
    event_id: str
    guests_purged: list[str] = field(default_factory=list)
    references_deleted: int = 0
    observations_dropped: int = 0
    purged_at_ms: int = 0
    #: True when this run did the purging; False when it only verified somebody
    #: else's, which is the normal case after A's end-event.
    purged_here: bool = False
    #: What the re-read found still present. Empty is the only acceptable result.
    remaining: list[Remaining] = field(default_factory=list)
    #: Checks that were performed and came back empty, so the record shows its work.
    verified: list[str] = field(default_factory=list)
    #: Which of the required checks actually ran. A record cannot be clean until
    #: all of them have; otherwise an unverified record would look identical to a
    #: verified one, which is the exact failure this module exists to prevent.
    checks_run: set[str] = field(default_factory=set)

    @property
    def verification_complete(self) -> bool:
        return self.checks_run >= REQUIRED_CHECKS

    @property
    def clean(self) -> bool:
        """Nothing remains **and** every required check was actually performed."""
        return self.verification_complete and not self.remaining

    def to_document(self) -> dict[str, Any]:
        return {
            "eventId": self.event_id,
            "guestsPurged": self.guests_purged,
            "referencesDeleted": self.references_deleted,
            "observationsDropped": self.observations_dropped,
            "purgedAtMs": self.purged_at_ms,
            "purgedHere": self.purged_here,
            "clean": self.clean,
            "verificationComplete": self.verification_complete,
            "checksRun": sorted(self.checks_run),
            "verified": self.verified,
            "remaining": [
                {"where": item.where, "detail": item.detail} for item in self.remaining
            ],
        }


def run_cleanup(
    target: CleanupTarget, event_id: str, *, purge: bool = False
) -> CleanupRecord:
    """Read the event back and report what consented data is left.

    `purge=False`, the default, verifies only. That is the safe default and the one
    to use after A's `POST /api/v1/events/{id}/end`, which has already deleted
    everything and knows about sessions and bindings that this does not.

    `purge=True` purges guest data first, for a guest-only cleanup mid-event.
    """
    record = CleanupRecord(event_id=event_id, purged_here=purge)
    if purge:
        receipt = target.purge_event(event_id)
        record.guests_purged = list(receipt.get("guestIds", []))
        record.references_deleted = int(receipt.get("referencesDeleted", 0))
        record.observations_dropped = int(receipt.get("observationsDropped", 0))
        record.purged_at_ms = int(receipt.get("purgedAtMs", 0))

    _check_gallery(target, event_id, record)
    _check_guest_records(target, event_id, record)
    _check_live_evidence(target, event_id, record)
    return record


def _check_gallery(target: CleanupTarget, event_id: str, record: CleanupRecord) -> None:
    """The gallery is the only route embeddings leave by, so it is checked first."""
    record.checks_run.add("gallery")
    gallery = target.fetch_gallery(event_id)
    if gallery.guests:
        for guest in gallery.guests:
            record.remaining.append(
                Remaining(
                    where="worker gallery",
                    detail=f"{guest.guest_id} still has {len(guest.embeddings)} embedding(s)",
                )
            )
    else:
        record.verified.append("worker gallery holds no embeddings")


def _check_guest_records(
    target: CleanupTarget, event_id: str, record: CleanupRecord
) -> None:
    record.checks_run.add("guest_records")
    listed = target.list_guests(event_id)
    guests = listed.get("guests", [])
    if not guests:
        record.verified.append("no guest records remain")
        return

    # A withdrawn stub with nothing attached is acceptable; anything holding a
    # reference, or still claiming consent, is not.
    for guest in guests:
        guest_id = guest.get("guestId", "?")
        if guest.get("referenceCount"):
            record.remaining.append(
                Remaining(
                    where="guest record",
                    detail=f"{guest_id} still reports {guest['referenceCount']} reference(s)",
                )
            )
        if guest.get("consent", {}).get("granted"):
            record.remaining.append(
                Remaining(
                    where="guest record",
                    detail=f"{guest_id} still claims consent after the event ended",
                )
            )
    if not record.remaining:
        record.verified.append(
            f"{len(guests)} guest record(s) remain, all with no references and no consent"
        )


def _check_live_evidence(
    target: CleanupTarget, event_id: str, record: CleanupRecord
) -> None:
    record.checks_run.add("live_evidence")
    snapshot = target.read_observations(event_id)
    held = [
        view.get("cameraId", "?")
        for view in snapshot.get("cameras", [])
        if view.get("observation") is not None
    ]
    if held:
        for camera_id in held:
            record.remaining.append(
                Remaining(
                    where="live evidence",
                    detail=f"{camera_id} still holds an observation",
                )
            )
    else:
        record.verified.append("no camera holds live evidence")


def cleanup_lines(record: CleanupRecord) -> list[str]:
    """What a human reads, and what goes in the results document."""
    lines = [f"event:        {record.event_id}"]
    if record.purged_here:
        lines += [
            f"guests:       {len(record.guests_purged)} purged",
            f"references:   {record.references_deleted} deleted",
            f"observations: {record.observations_dropped} dropped",
        ]
    else:
        lines.append("purge:        not by this command — verifying only")
    for check in record.verified:
        lines.append(f"verified:     {check}")
    if not record.verification_complete:
        missing = ", ".join(sorted(REQUIRED_CHECKS - record.checks_run))
        lines.append(f"verdict:      UNVERIFIED — these checks never ran: {missing}")
    elif record.clean:
        lines.append("verdict:      clean — re-read found nothing remaining")
    else:
        survived = "survived the purge" if record.purged_here else "is still present"
        lines.append(f"verdict:      NOT CLEAN — consented data {survived}:")
        lines.extend(f"              - {item.where}: {item.detail}" for item in record.remaining)
    return lines
