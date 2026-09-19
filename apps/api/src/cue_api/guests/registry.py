"""In-memory, event-scoped consent and reference store.

Deliberately not persisted. A restart clears every embedding and requires
re-enrolment; that is the privacy default, not a missing feature.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

from cue_api.guests.contracts import (
    ConsentPurpose,
    GuestConsent,
    GuestRecord,
    GuestStatus,
)

#: SFace produces 128-d embeddings. Any other width means a mismatched model.
DEFAULT_EMBEDDING_DIMENSION = 128


class ConsentError(RuntimeError):
    """Raised when an operation would use data the guest has not consented to."""


class GuestNotFoundError(LookupError):
    pass


def normalise_embedding(values: list[float], dimension: int) -> tuple[float, ...]:
    """Validate and L2-normalise so cosine similarity is a plain dot product."""
    if len(values) != dimension:
        raise ValueError(f"Expected a {dimension}-d embedding, received {len(values)}")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("Embedding contains a non-finite value")
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-9:
        raise ValueError("Embedding has no magnitude and cannot be matched")
    return tuple(value / norm for value in values)


@dataclass
class _Reference:
    version: int
    vector: list[float]
    quality: float
    embedder: str
    embedder_version: str
    captured_at_ms: int


@dataclass
class _Guest:
    guest_id: str
    event_id: str
    display_name: str
    aliases: list[str]
    consent: GuestConsent
    status: GuestStatus
    updated_at_ms: int
    references: list[_Reference] = field(default_factory=list)
    reference_version: int = 0

    def to_record(self) -> GuestRecord:
        qualities = [reference.quality for reference in self.references]
        return GuestRecord(
            guest_id=self.guest_id,
            event_id=self.event_id,
            display_name=self.display_name,
            aliases=list(self.aliases),
            status=self.status,
            consent=self.consent,
            reference_version=self.reference_version,
            reference_count=len(self.references),
            mean_reference_quality=(sum(qualities) / len(qualities)) if qualities else None,
            updated_at_ms=self.updated_at_ms,
        )

    def purge_references(self) -> int:
        """Drop every embedding, overwriting the vectors we still hold a ref to.

        Python cannot guarantee the bytes leave the process, so this is a
        best-effort scrub plus an immediate unlink, and the limitation is stated
        in the privacy notes rather than glossed over.
        """
        deleted = len(self.references)
        for reference in self.references:
            for index in range(len(reference.vector)):
                reference.vector[index] = 0.0
            reference.vector.clear()
        self.references.clear()
        return deleted


def _slugify(display_name: str) -> str:
    kept = [char if char.isalnum() else "-" for char in display_name.lower()]
    slug = "".join(kept).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:40] or "guest"


class GuestRegistry:
    """Event-scoped guest roster. Every mutation advances the gallery version."""

    def __init__(self, embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION) -> None:
        self._embedding_dimension = embedding_dimension
        self._guests: dict[tuple[str, str], _Guest] = {}
        self._gallery_version = 0
        self._lock = threading.Lock()

    @property
    def embedding_dimension(self) -> int:
        return self._embedding_dimension

    @property
    def gallery_version(self) -> int:
        with self._lock:
            return self._gallery_version

    def enrol(
        self,
        *,
        event_id: str,
        display_name: str,
        aliases: list[str],
        consent_granted: bool,
        consent_purposes: list[ConsentPurpose],
        recorded_by: str,
        now_ms: int,
        guest_id: str | None = None,
    ) -> GuestRecord:
        if not consent_granted:
            raise ConsentError("A guest cannot be enrolled without granted consent")
        if ConsentPurpose.LIVE_IDENTIFICATION not in consent_purposes:
            raise ConsentError("Live identification consent is required to enrol a face reference")

        with self._lock:
            resolved_id = guest_id or self._unique_id(event_id, f"guest-{_slugify(display_name)}")
            key = (event_id, resolved_id)
            if key in self._guests:
                raise ValueError(f"Guest {resolved_id} already exists for event {event_id}")

            guest = _Guest(
                guest_id=resolved_id,
                event_id=event_id,
                display_name=display_name,
                aliases=list(aliases),
                consent=GuestConsent(
                    granted=True,
                    granted_at_ms=now_ms,
                    purposes=list(consent_purposes),
                    withdrawn_at_ms=None,
                    recorded_by=recorded_by,
                ),
                status=GuestStatus.ENROLLING,
                updated_at_ms=now_ms,
            )
            self._guests[key] = guest
            self._gallery_version += 1
            return guest.to_record()

    def add_reference(
        self,
        *,
        event_id: str,
        guest_id: str,
        embedding: list[float],
        quality: float,
        embedder: str,
        embedder_version: str,
        captured_at_ms: int,
        now_ms: int,
    ) -> GuestRecord:
        vector = normalise_embedding(embedding, self._embedding_dimension)

        with self._lock:
            guest = self._require(event_id, guest_id)
            if guest.status is GuestStatus.WITHDRAWN or not guest.consent.granted:
                raise ConsentError(f"Guest {guest_id} has withdrawn consent")

            guest.reference_version += 1
            guest.references.append(
                _Reference(
                    version=guest.reference_version,
                    vector=list(vector),
                    quality=quality,
                    embedder=embedder,
                    embedder_version=embedder_version,
                    captured_at_ms=captured_at_ms,
                )
            )
            guest.status = GuestStatus.ACTIVE
            guest.updated_at_ms = now_ms
            self._gallery_version += 1
            return guest.to_record()

    def withdraw(self, *, event_id: str, guest_id: str, now_ms: int) -> tuple[GuestRecord, int]:
        with self._lock:
            guest = self._require(event_id, guest_id)
            deleted = guest.purge_references()
            guest.reference_version = 0
            guest.status = GuestStatus.WITHDRAWN
            guest.consent = guest.consent.model_copy(
                update={"granted": False, "withdrawn_at_ms": now_ms}
            )
            guest.updated_at_ms = now_ms
            self._gallery_version += 1
            return guest.to_record(), deleted

    def purge_event(self, *, event_id: str) -> tuple[list[str], int]:
        """End-of-event deletion: identities and embeddings both go."""
        with self._lock:
            keys = [key for key in self._guests if key[0] == event_id]
            deleted = 0
            for key in keys:
                deleted += self._guests[key].purge_references()
                del self._guests[key]
            if keys:
                self._gallery_version += 1
            return [key[1] for key in keys], deleted

    def get(self, event_id: str, guest_id: str) -> GuestRecord:
        with self._lock:
            return self._require(event_id, guest_id).to_record()

    def list_guests(self, event_id: str) -> list[GuestRecord]:
        with self._lock:
            guests = [guest for key, guest in self._guests.items() if key[0] == event_id]
        return [guest.to_record() for guest in sorted(guests, key=lambda item: item.guest_id)]

    def is_identifiable(self, event_id: str, guest_id: str) -> bool:
        """True only while the guest consents and still has usable references."""
        with self._lock:
            guest = self._guests.get((event_id, guest_id))
            return bool(
                guest
                and guest.status is GuestStatus.ACTIVE
                and guest.consent.granted
                and guest.references
            )

    def gallery(self, event_id: str) -> tuple[int, list[tuple[str, str, int, list[list[float]]]]]:
        """Worker-facing embeddings for consenting, active guests only."""
        with self._lock:
            entries = []
            for key, guest in sorted(self._guests.items()):
                if key[0] != event_id:
                    continue
                if guest.status is not GuestStatus.ACTIVE or not guest.consent.granted:
                    continue
                entries.append(
                    (
                        guest.guest_id,
                        guest.display_name,
                        guest.reference_version,
                        [list(reference.vector) for reference in guest.references],
                    )
                )
            return self._gallery_version, entries

    def _require(self, event_id: str, guest_id: str) -> _Guest:
        guest = self._guests.get((event_id, guest_id))
        if guest is None:
            raise GuestNotFoundError(f"Guest {guest_id} is not enrolled for event {event_id}")
        return guest

    def _unique_id(self, event_id: str, base: str) -> str:
        candidate = base
        suffix = 2
        while (event_id, candidate) in self._guests:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate
