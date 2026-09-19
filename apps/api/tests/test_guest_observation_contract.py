"""The pipeline's output must match the fixture the other runtimes validate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conftest import SARAH, KeyedEmbedder, ScriptedDetector, make_detection, make_frame

from cue_api.guests.observation_pipeline import VisionPipeline
from cue_api.guests.reference_gallery import GuestReferences, ReferenceGallery

FIXTURES = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "fixtures"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def shape(value: Any) -> Any:
    """The key structure of a payload, ignoring the values."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return "list"
    return type(value).__name__ if value is not None else "null"


def emit_confirmed() -> dict[str, Any]:
    detector = ScriptedDetector()
    detector.queue([make_detection()])
    pipeline = VisionPipeline(
        event_id="hackmit-demo",
        detector=detector,
        embedder=KeyedEmbedder(vectors={500: SARAH}),
        gallery=ReferenceGallery(
            version=7,
            guests=(
                GuestReferences(
                    guest_id="guest-sarah",
                    display_name="Sarah",
                    reference_version=2,
                    embeddings=(SARAH,),
                ),
            ),
        ),
    )
    emitted: dict[str, Any] = {}
    for index in range(3):
        frame = make_frame(sequence=index, received_at_ms=1_000_000 + index * 80)
        emitted = pipeline.observe(frame)[0].to_contract()
    return emitted


def test_the_emitted_payload_has_the_fixture_key_structure() -> None:
    emitted = emit_confirmed()
    fixture = load("visual-observation.confirmed.json")

    assert set(emitted) == set(fixture)
    for section in ("subject", "quality", "match", "provenance", "timing"):
        assert set(emitted[section]) == set(fixture[section]), section
    assert set(emitted["box"]) == set(fixture["box"])


def test_a_null_field_stays_nullable_in_both_directions() -> None:
    emitted = emit_confirmed()
    ambiguous = load("visual-observation.ambiguous.json")

    assert shape(emitted["subject"]).keys() == shape(ambiguous["subject"]).keys()
    assert emitted["status"] == "CONFIRMED"
    assert ambiguous["subject"]["guestId"] is None


def test_the_emitted_payload_carries_the_declared_contract_version() -> None:
    emitted = emit_confirmed()
    fixture = load("visual-observation.confirmed.json")

    assert emitted["guestContractVersion"] == fixture["guestContractVersion"]
    assert emitted["provenance"]["pipelineVersion"].startswith("cue-guests/")


def test_the_identity_expiry_is_the_declared_ttl() -> None:
    emitted = emit_confirmed()

    timing = emitted["timing"]
    assert timing["expiresAtMs"] - timing["observedAtMs"] == 1500
    assert timing["clockDomain"] == "WORKER_MONOTONIC_MAPPED"
    assert timing["clockUncertaintyMs"] > 0
