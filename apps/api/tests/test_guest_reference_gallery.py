"""The worker's view of enrolled references.

Loading the gallery is enrolment's last mile: whatever survives this function is
what the system is willing to put a name to.
"""

from __future__ import annotations

import math

import pytest

from cue_api.guests.reference_gallery import (
    GuestReferences,
    ReferenceGallery,
    cosine_similarity,
    normalise,
)

# Two orthogonal unit vectors stand in for enrolled faces. They are fixtures,
# not recognition: no embedder has ever run on this machine.
SARAH = normalise((1.0, 0.0, 0.0, 0.0))
DANIEL = normalise((0.0, 1.0, 0.0, 0.0))


@pytest.fixture
def gallery() -> ReferenceGallery:
    return ReferenceGallery(
        version=7,
        guests=(
            GuestReferences(
                guest_id="guest-sarah",
                display_name="Sarah",
                reference_version=2,
                embeddings=(SARAH,),
            ),
            GuestReferences(
                guest_id="guest-daniel",
                display_name="Daniel",
                reference_version=1,
                embeddings=(DANIEL,),
            ),
        ),
    )


def payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "galleryVersion": 7,
        "entries": [
            {
                "guestId": "guest-sarah",
                "displayName": "Sarah",
                "referenceVersion": 2,
                "embeddings": [[1.0, 0.0, 0.0, 0.0], [0.6, 0.8, 0.0, 0.0]],
            }
        ],
    }
    base.update(overrides)
    return base


def test_a_loaded_gallery_keeps_its_version() -> None:
    gallery = ReferenceGallery.from_payload(payload())

    assert gallery.version == 7
    assert len(gallery) == 1
    assert gallery.dimension == 4


def test_every_reference_arrives_normalised() -> None:
    gallery = ReferenceGallery.from_payload(
        payload(
            entries=[
                {
                    "guestId": "guest-sarah",
                    "displayName": "Sarah",
                    "referenceVersion": 1,
                    "embeddings": [[3.0, 4.0, 0.0, 0.0]],
                }
            ]
        )
    )

    vector = gallery.guests[0].embeddings[0]

    assert math.hypot(*vector) == pytest.approx(1.0)
    assert vector[0] == pytest.approx(0.6)


def test_a_guest_with_no_usable_reference_is_left_out() -> None:
    # Keeping them would silently widen the gallery with somebody who cannot
    # be matched, and a name that can never be earned is worse than absent.
    gallery = ReferenceGallery.from_payload(
        payload(
            entries=[
                {
                    "guestId": "guest-sarah",
                    "displayName": "Sarah",
                    "referenceVersion": 0,
                    "embeddings": [],
                }
            ]
        )
    )

    assert len(gallery) == 0
    assert gallery.dimension is None


def test_a_gallery_mixing_embedding_widths_is_refused() -> None:
    with pytest.raises(ValueError, match="mixes embedding widths"):
        ReferenceGallery.from_payload(
            payload(
                entries=[
                    {
                        "guestId": "guest-sarah",
                        "displayName": "Sarah",
                        "referenceVersion": 1,
                        "embeddings": [[1.0, 0.0, 0.0, 0.0]],
                    },
                    {
                        "guestId": "guest-daniel",
                        "displayName": "Daniel",
                        "referenceVersion": 1,
                        "embeddings": [[1.0, 0.0]],
                    },
                ]
            )
        )


def test_a_zero_reference_is_refused_rather_than_carried() -> None:
    with pytest.raises(ValueError, match="no magnitude"):
        ReferenceGallery.from_payload(
            payload(
                entries=[
                    {
                        "guestId": "guest-sarah",
                        "displayName": "Sarah",
                        "referenceVersion": 1,
                        "embeddings": [[0.0, 0.0, 0.0, 0.0]],
                    }
                ]
            )
        )


def test_a_payload_without_entries_is_refused() -> None:
    with pytest.raises(ValueError, match="missing its entries"):
        ReferenceGallery.from_payload({"galleryVersion": 1})


def test_an_empty_gallery_has_no_guests_and_no_width() -> None:
    gallery = ReferenceGallery.empty()

    assert len(gallery) == 0
    assert gallery.version == 0
    assert gallery.dimension is None
    assert gallery.get("guest-sarah") is None


def test_a_guest_can_be_looked_up_by_id(gallery: ReferenceGallery) -> None:
    found = gallery.get("guest-daniel")

    assert found is not None
    assert found.display_name == "Daniel"
    assert gallery.get("guest-nobody") is None


def test_similarity_is_a_dot_product_of_unit_vectors() -> None:
    assert cosine_similarity(SARAH, SARAH) == pytest.approx(1.0)
    assert cosine_similarity(SARAH, DANIEL) == pytest.approx(0.0)


def test_comparing_different_widths_is_an_error_not_a_silent_zero() -> None:
    with pytest.raises(ValueError, match="width mismatch"):
        cosine_similarity(SARAH, normalise((1.0, 0.0)))


def test_normalisation_refuses_a_vector_with_no_direction() -> None:
    with pytest.raises(ValueError, match="no magnitude"):
        normalise((0.0, 0.0, 0.0, 0.0))


def test_references_are_stored_as_given_when_already_unit_length() -> None:
    entry = GuestReferences(
        guest_id="guest-sarah",
        display_name="Sarah",
        reference_version=1,
        embeddings=(SARAH,),
    )

    assert entry.embeddings[0] == SARAH
