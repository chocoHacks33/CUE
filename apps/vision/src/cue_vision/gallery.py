"""The enrolled reference gallery held by the worker.

Only consenting, enrolled guests ever enter this structure. Nothing here infers
a name from a seat, a camera role or a join order.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from cue_vision.types import Embedding


def normalise(values: Sequence[float]) -> Embedding:
    norm = math.sqrt(sum(float(value) * float(value) for value in values))
    if not math.isfinite(norm) or norm <= 1e-9:
        raise ValueError("Embedding has no magnitude and cannot be matched")
    return tuple(float(value) / norm for value in values)


def cosine_similarity(left: Embedding, right: Embedding) -> float:
    """Dot product of two unit vectors. Both sides are normalised on entry."""
    if len(left) != len(right):
        raise ValueError(f"Embedding width mismatch: {len(left)} vs {len(right)}")
    return sum(a * b for a, b in zip(left, right, strict=True))


@dataclass(frozen=True)
class GuestReferences:
    guest_id: str
    display_name: str
    reference_version: int
    embeddings: tuple[Embedding, ...]


@dataclass(frozen=True)
class ReferenceGallery:
    version: int
    guests: tuple[GuestReferences, ...]

    @property
    def dimension(self) -> int | None:
        for guest in self.guests:
            for embedding in guest.embeddings:
                return len(embedding)
        return None

    def __len__(self) -> int:
        return len(self.guests)

    def get(self, guest_id: str) -> GuestReferences | None:
        for guest in self.guests:
            if guest.guest_id == guest_id:
                return guest
        return None

    @classmethod
    def empty(cls) -> ReferenceGallery:
        return cls(version=0, guests=())

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> ReferenceGallery:
        """Build from the backend's `/api/v1/vision/gallery` response."""
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, Iterable):
            raise ValueError("Gallery payload is missing its entries")

        guests: list[GuestReferences] = []
        for entry in raw_entries:
            if not isinstance(entry, Mapping):
                raise ValueError("Gallery entry must be an object")
            embeddings = entry.get("embeddings")
            if not isinstance(embeddings, Iterable):
                raise ValueError("Gallery entry is missing its embeddings")
            vectors = tuple(normalise(vector) for vector in embeddings)  # type: ignore[arg-type]
            if not vectors:
                # A guest with no usable reference cannot be matched, and
                # pretending otherwise would silently widen the gallery.
                continue
            guests.append(
                GuestReferences(
                    guest_id=str(entry["guestId"]),
                    display_name=str(entry["displayName"]),
                    reference_version=int(entry["referenceVersion"]),  # type: ignore[call-overload]
                    embeddings=vectors,
                )
            )

        widths = {len(vector) for guest in guests for vector in guest.embeddings}
        if len(widths) > 1:
            raise ValueError(f"Gallery mixes embedding widths {sorted(widths)}")

        return cls(version=int(payload.get("galleryVersion", 0)), guests=tuple(guests))
