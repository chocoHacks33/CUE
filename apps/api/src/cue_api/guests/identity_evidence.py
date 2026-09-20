"""Where the readiness gate gets its four facts from.

`identity_readiness.assess_identity_readiness` decides what identity may do. It
needs four inputs, and two of them cannot be verified by any code: whether the Mac
runtime gate passed, and whether B's media checks ran. Those are human
attestations.

An unverifiable claim that flips a safety gate is exactly the thing to make
awkward to assert, so an attestation here is not a bare boolean. It has to name
who made it and which results document backs it, the same way a stored calibration
has to name its dataset. A flag nobody signed is not evidence, and an attestation
that points at no document cannot be checked by anyone later.

The default, with nothing supplied, is that none of it has happened — which is
where the project is, and which the gate turns into `ROLE_BASED`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cue_api.guests.calibration_store import load_or_provisional
from cue_api.guests.confidence_calibration import Calibration
from cue_api.guests.identity_eval import IdentityReport

#: Default location of a calibration fitted by `cue-guests calibrate`.
DEFAULT_CALIBRATION_PATH = Path("calibration.json")


class AttestationError(ValueError):
    """An attestation that nobody signed, or that points at no evidence."""


@dataclass(frozen=True)
class Attestation:
    """A human saying a hardware check passed, on the record."""

    #: Who ran it. A person, not a service.
    attested_by: str
    #: The results document anyone can go and read.
    evidence_document: str

    def __post_init__(self) -> None:
        if not self.attested_by.strip():
            raise AttestationError("An attestation must name who ran the check")
        if not self.evidence_document.strip():
            raise AttestationError(
                "An attestation must name the results document that backs it; "
                "a claim with nothing to read is not evidence"
            )


@dataclass(frozen=True)
class IdentityEvidence:
    """Everything the readiness gate is allowed to consider."""

    calibration: Calibration
    report: IdentityReport | None = None
    mac_runtime_gate: Attestation | None = None
    media_checks: Attestation | None = None

    @property
    def mac_runtime_gate_passed(self) -> bool:
        return self.mac_runtime_gate is not None

    @property
    def media_checks_passed(self) -> bool:
        return self.media_checks is not None

    def attestations(self) -> dict[str, str]:
        """Who signed what, for the producer panel and the run sheet."""
        signed: dict[str, str] = {}
        if self.mac_runtime_gate is not None:
            signed["macRuntimeGate"] = (
                f"{self.mac_runtime_gate.attested_by} — {self.mac_runtime_gate.evidence_document}"
            )
        if self.media_checks is not None:
            signed["mediaChecks"] = (
                f"{self.media_checks.attested_by} — {self.media_checks.evidence_document}"
            )
        return signed


def gather(
    *,
    calibration_path: Path = DEFAULT_CALIBRATION_PATH,
    report: IdentityReport | None = None,
    mac_runtime_gate: Attestation | None = None,
    media_checks: Attestation | None = None,
) -> IdentityEvidence:
    """Read what is on disk, and take the rest as supplied.

    A missing calibration file is normal and yields the provisional anchor. A file
    that is present but invalid raises out of `load_or_provisional`, which is
    correct: somebody put it there and will assume it is in use.
    """
    return IdentityEvidence(
        calibration=load_or_provisional(calibration_path).calibration,
        report=report,
        mac_runtime_gate=mac_runtime_gate,
        media_checks=media_checks,
    )
