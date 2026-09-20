"""The submission document's factual claims, checked against the code.

Stage 5 is freeze. A freeze that nobody enforces is not a freeze — it is a hope
that nobody edits a threshold on Sunday morning.

`docs/b-limitations-and-licences.md` is what a judge reads. It states model
digests, licences, thresholds and the current naming policy as facts. Every one of
those could be made false by a one-line change somewhere else, silently, and the
document would go on claiming it.

So these tests **read the document** and compare what it says with what the code
does. They deliberately parse the markdown rather than restating the numbers here:
a test that hard-codes `0.363` twice proves only that I can copy, and would go on
passing while the document told a judge something untrue.

If one of these fails, the code and the submission disagree. Fix whichever is
wrong — but do not delete the test, because then nothing is frozen.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cue_api.guests.confidence_calibration import PROVISIONAL_CALIBRATION
from cue_api.guests.face_matching import MatchThresholds
from cue_api.guests.face_models import MODEL_FILES, SFACE, YUNET
from cue_api.guests.identity_ledger import DEFAULT_IDENTITY_TTL_MS
from cue_api.guests.identity_readiness import NamingPolicy, assess_identity_readiness
from cue_api.guests.types import CalibrationStatus

DOCS = Path(__file__).resolve().parents[3] / "docs"
SUBMISSION = DOCS / "b-limitations-and-licences.md"


@pytest.fixture(scope="module")
def document() -> str:
    assert SUBMISSION.exists(), f"{SUBMISSION} is what a judge reads; it must exist"
    return SUBMISSION.read_text(encoding="utf-8")


# -- model provenance ------------------------------------------------------


def test_the_digests_in_the_document_are_the_digests_the_code_pins(document: str) -> None:
    """A pinned digest is provenance. A stale one in the document is a false claim."""
    digests = set(re.findall(r"\b[0-9a-f]{64}\b", document))

    assert digests, "the document quotes no digests at all"
    for model in MODEL_FILES:
        assert model.expected_sha256 in digests, (
            f"{model.key} pins {model.expected_sha256} but the submission document "
            "does not quote it"
        )


def test_the_document_quotes_no_digest_the_code_does_not_pin(document: str) -> None:
    """A digest in the document that nothing verifies is worse than none."""
    pinned = {model.expected_sha256 for model in MODEL_FILES}
    quoted = set(re.findall(r"\b[0-9a-f]{64}\b", document))

    assert quoted <= pinned, f"unpinned digest(s) quoted: {sorted(quoted - pinned)}"


def test_the_model_filenames_match(document: str) -> None:
    for model in MODEL_FILES:
        assert model.filename in document, f"{model.filename} is not named in the document"


def test_the_licences_the_document_claims_are_the_ones_the_code_records(
    document: str,
) -> None:
    """Both were read from upstream; the document and the registry must agree."""
    assert "MIT" in YUNET.declared_licence
    assert "Apache-2.0" in SFACE.declared_licence
    # And the document says the same about each file, on the same table row.
    for model, licence in ((YUNET, "MIT"), (SFACE, "Apache-2.0")):
        row = next(
            line for line in document.splitlines() if model.filename in line and "|" in line
        )
        assert licence in row, f"{model.filename} row does not claim {licence}"


def test_the_document_still_says_the_licences_were_verified(document: str) -> None:
    assert YUNET.licence_verified and SFACE.licence_verified
    assert "read rather than assumed" in document or "LICENSE" in document


# -- thresholds ------------------------------------------------------------


def test_the_thresholds_the_document_quotes_are_the_thresholds_in_force(
    document: str,
) -> None:
    """Retuning a threshold must not leave the submission quoting the old one."""
    thresholds = MatchThresholds()
    line = next(
        line for line in document.splitlines() if "Thresholds are unmeasured" in line
    )
    # The sentence continues onto the following lines, so take the paragraph.
    start = document.index(line)
    paragraph = document[start : start + 400]

    assert str(thresholds.accept_similarity) in paragraph
    assert str(thresholds.margin) in paragraph
    assert str(thresholds.confirmations_required) in paragraph
    assert f"{thresholds.confirmation_window_ms / 1000:g} s" in paragraph
    assert f"{DEFAULT_IDENTITY_TTL_MS / 1000:g} s" in paragraph


def test_the_accept_threshold_is_still_the_published_reference_point() -> None:
    """The document calls 0.363 an anchor, not our result. It must stay an anchor."""
    from cue_api.guests.confidence_calibration import SFACE_COSINE_REFERENCE

    assert MatchThresholds().accept_similarity == SFACE_COSINE_REFERENCE


# -- the claim that matters most -------------------------------------------


def test_the_document_claim_that_naming_is_switched_off_is_true(document: str) -> None:
    """The load-bearing sentence a judge will test. If it goes false, CI says so."""
    readiness = assess_identity_readiness(calibration=PROVISIONAL_CALIBRATION)

    assert readiness.policy is NamingPolicy.ROLE_BASED
    assert readiness.role_based is True
    assert readiness.unattended_naming_permitted is False
    assert "ROLE_BASED" in document
    assert "switched off" in document


def test_the_document_points_at_a_route_that_exists(document: str) -> None:
    """It invites a judge to check the claim, so the route had better be there."""
    import os

    assert "GET /api/v1/guests/readiness" in document

    os.environ.setdefault("LIVEKIT_URL", "wss://example.livekit.cloud")
    os.environ.setdefault("LIVEKIT_API_KEY", "k")
    os.environ.setdefault("LIVEKIT_API_SECRET", "s" * 32)
    os.environ.setdefault("CUE_BOOTSTRAP_SECRET", "t")
    from cue_api.main import create_app

    paths = create_app().openapi()["paths"]
    assert "/api/v1/guests/readiness" in paths
    assert "get" in paths["/api/v1/guests/readiness"]


def test_no_calibration_means_the_disclosed_status_is_provisional(document: str) -> None:
    assert PROVISIONAL_CALIBRATION.status is CalibrationStatus.PROVISIONAL_DEFAULT
    assert PROVISIONAL_CALIBRATION.sample_count == 0
    assert "PROVISIONAL_DEFAULT" in document


# -- the document must keep saying what is missing -------------------------


def test_the_document_still_admits_no_real_face_has_been_seen(document: str) -> None:
    """The single most important sentence in the file. It stays until it is false."""
    assert "No real human face has ever been through this system" in document


def test_the_document_still_admits_it_has_not_run_on_the_mac(document: str) -> None:
    assert "Never run on the Mac" in document


def test_the_document_refuses_to_quote_an_accuracy_figure(document: str) -> None:
    """A percentage in this file would almost certainly be a claim we cannot support."""
    section = document[document.index("Will not say") :]
    assert "Any accuracy, precision, recall or confidence figure" in section

    forbidden = re.findall(r"\b\d{1,3}(?:\.\d+)?\s*%", document)
    assert not forbidden, f"the submission quotes a percentage: {forbidden}"


def test_the_identity_report_on_disk_still_records_no_trials() -> None:
    """If somebody fills it in, these freeze tests must be revisited together."""
    report = (DOCS / "results" / "b-identity-report.md").read_text(encoding="utf-8")

    assert "Status: NOT RUN" in report
    assert "Trials run: **0**" in report
