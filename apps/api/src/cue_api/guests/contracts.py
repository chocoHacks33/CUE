"""Person B — guest consent and visual observation contracts.

Mirrors `packages/contracts/src/guests.ts`. Both runtimes validate the fixtures
in `packages/contracts/fixtures/`; a rule that only one side enforces is not a
shared contract.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from cue_api.contracts import CameraId, ContractModel

GUEST_CONTRACT_VERSION = "0.1.0"

#: PRD starting value. Measure and tune; this is not a proven outcome.
IDENTITY_TTL_MS = 1500


class StrictContractModel(ContractModel):
    """Unknown fields are a contract drift signal, not something to ignore."""

    model_config = ConfigDict(extra="forbid")


class ObservationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    PROVISIONAL = "PROVISIONAL"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"
    LOW_QUALITY = "LOW_QUALITY"
    NO_FACE = "NO_FACE"


#: Only these two statuses may carry a guest identity.
NAMEABLE_STATUSES = frozenset({ObservationStatus.CONFIRMED, ObservationStatus.PROVISIONAL})


class CalibrationStatus(StrEnum):
    MEASURED = "MEASURED"
    PROVISIONAL_DEFAULT = "PROVISIONAL_DEFAULT"
    UNCALIBRATED = "UNCALIBRATED"


class ClockDomain(StrEnum):
    WORKER_MONOTONIC_MAPPED = "WORKER_MONOTONIC_MAPPED"
    BACKEND_WALL = "BACKEND_WALL"


class GuestStatus(StrEnum):
    ENROLLING = "ENROLLING"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class ConsentPurpose(StrEnum):
    LIVE_IDENTIFICATION = "LIVE_IDENTIFICATION"
    RECORDING = "RECORDING"
    CLOUD_RELAY = "CLOUD_RELAY"


class NormalisedBox(StrictContractModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(ge=0, le=1)
    height: float = Field(ge=0, le=1)


class ObservationQuality(StrictContractModel):
    passed: bool
    score: float = Field(ge=0, le=1)
    face_width_ratio: float = Field(ge=0, le=1)
    sharpness: float = Field(ge=0, le=1)
    brightness: float = Field(ge=0, le=1)
    detector_score: float = Field(ge=0, le=1)
    failed_checks: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _failed_checks_match_verdict(self) -> ObservationQuality:
        if self.passed and self.failed_checks:
            raise ValueError("A passing quality verdict cannot list failed checks")
        if not self.passed and not self.failed_checks:
            raise ValueError("A failing quality verdict must name the failed checks")
        return self


class ObservationMatch(StrictContractModel):
    calibrated_confidence: float | None = Field(default=None, ge=0, le=1)
    calibration_id: str
    calibration_status: CalibrationStatus
    margin: float | None = None
    similarity: float | None = None
    runner_up_guest_id: str | None = None
    consecutive_confirmations: int = Field(ge=0)

    @model_validator(mode="after")
    def _no_confidence_without_calibration(self) -> ObservationMatch:
        uncalibrated = self.calibration_status is CalibrationStatus.UNCALIBRATED
        if uncalibrated and self.calibrated_confidence is not None:
            raise ValueError("An uncalibrated match cannot report a calibrated confidence")
        return self


class ObservationSubject(StrictContractModel):
    guest_id: str | None = None
    display_name: str | None = None
    reference_version: int | None = None

    @model_validator(mode="after")
    def _name_requires_identity(self) -> ObservationSubject:
        if self.display_name is not None and self.guest_id is None:
            raise ValueError("A display name without a guest ID is a seat label, not an identity")
        return self


class ObservationProvenance(StrictContractModel):
    pipeline_version: str
    detector: str
    detector_version: str
    embedder: str
    embedder_version: str
    gallery_version: int = Field(ge=0)


class ObservationTiming(StrictContractModel):
    captured_at_ms: int | None = None
    observed_at_ms: int
    expires_at_ms: int
    clock_domain: ClockDomain
    clock_uncertainty_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _expiry_follows_observation(self) -> ObservationTiming:
        if self.expires_at_ms < self.observed_at_ms:
            raise ValueError("An observation cannot expire before it was observed")
        return self


class VisualObservation(StrictContractModel):
    guest_contract_version: Literal["0.1.0"] = GUEST_CONTRACT_VERSION
    observation_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=3, max_length=48, pattern=r"^[a-z0-9][a-z0-9-]*$")
    camera_id: CameraId
    stream_epoch: int = Field(ge=1)
    track_key: str = Field(min_length=1, max_length=128)
    frame_sequence: int = Field(ge=0)
    status: ObservationStatus
    subject: ObservationSubject
    box: NormalisedBox | None = None
    quality: ObservationQuality
    match: ObservationMatch | None = None
    provenance: ObservationProvenance
    timing: ObservationTiming
    usable_for_named_take: bool

    @model_validator(mode="after")
    def _identity_rules(self) -> VisualObservation:
        if self.subject.guest_id is not None and self.status not in NAMEABLE_STATUSES:
            raise ValueError(f"{self.status.value} observations must not name a guest")
        if self.usable_for_named_take:
            if self.status is not ObservationStatus.CONFIRMED:
                raise ValueError("Only a CONFIRMED observation may support a named take")
            if self.subject.guest_id is None:
                raise ValueError("A named take needs a named guest")
            if not self.quality.passed:
                raise ValueError("A named take needs an observation that passed the quality gate")
        return self

    def is_fresh(self, now_ms: int) -> bool:
        return now_ms <= self.timing.expires_at_ms


class GuestConsent(StrictContractModel):
    granted: bool
    granted_at_ms: int
    scope: Literal["EVENT"] = "EVENT"
    purposes: list[ConsentPurpose] = Field(min_length=1)
    withdrawn_at_ms: int | None = None
    recorded_by: str = Field(min_length=1, max_length=64)


class GuestRecord(StrictContractModel):
    """The public view of a guest. Reference embeddings never appear here."""

    guest_contract_version: Literal["0.1.0"] = GUEST_CONTRACT_VERSION
    guest_id: str
    event_id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    status: GuestStatus
    consent: GuestConsent
    reference_version: int = Field(ge=0)
    reference_count: int = Field(ge=0)
    mean_reference_quality: float | None = None
    storage: Literal["MEMORY_ONLY"] = "MEMORY_ONLY"
    updated_at_ms: int

    @model_validator(mode="after")
    def _withdrawal_is_complete(self) -> GuestRecord:
        if self.status is GuestStatus.WITHDRAWN:
            if self.consent.granted or self.consent.withdrawn_at_ms is None:
                raise ValueError("A withdrawn guest must record the withdrawal and drop consent")
            if self.reference_count != 0:
                raise ValueError("A withdrawn guest must hold no references")
        return self


class GuestEnrolmentRequest(ContractModel):
    event_id: str = Field(min_length=3, max_length=48, pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str = Field(min_length=1, max_length=64)
    aliases: list[str] = Field(default_factory=list, max_length=8)
    guest_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{1,47}$")
    consent_granted: bool
    consent_purposes: list[ConsentPurpose] = Field(min_length=1)
    recorded_by: str = Field(min_length=1, max_length=64)


class ReferenceSubmission(ContractModel):
    """One enrolment reference, already reduced to an embedding by the worker.

    Reference images are never uploaded to or stored by the backend.
    """

    event_id: str = Field(min_length=3, max_length=48, pattern=r"^[a-z0-9][a-z0-9-]*$")
    embedding: list[float] = Field(min_length=2, max_length=1024)
    quality: float = Field(ge=0, le=1)
    embedder: str = Field(min_length=1, max_length=64)
    embedder_version: str = Field(min_length=1, max_length=64)
    captured_at_ms: int


class GalleryEntry(ContractModel):
    """Worker-facing view. Carries embeddings, so it is never sent to a browser."""

    guest_id: str
    display_name: str
    reference_version: int
    embeddings: list[list[float]]


class GalleryResponse(ContractModel):
    guest_contract_version: Literal["0.1.0"] = GUEST_CONTRACT_VERSION
    event_id: str
    gallery_version: int
    entries: list[GalleryEntry]


class GuestListResponse(ContractModel):
    guest_contract_version: Literal["0.1.0"] = GUEST_CONTRACT_VERSION
    event_id: str
    gallery_version: int
    guests: list[GuestRecord]


class PurgeReceipt(ContractModel):
    """Deletion has to be observable, or it is only a promise."""

    event_id: str
    guest_ids: list[str]
    references_deleted: int
    observations_dropped: int
    purged_at_ms: int


class CameraObservationView(ContractModel):
    camera_id: CameraId
    observation: VisualObservation | None = None
    fresh: bool = False
    age_ms: int | None = None


class ObservationSnapshot(ContractModel):
    guest_contract_version: Literal["0.1.0"] = GUEST_CONTRACT_VERSION
    event_id: str
    now_ms: int
    gallery_version: int
    cameras: list[CameraObservationView]


class InvalidationRequest(ContractModel):
    """A's epoch or reframe signal arriving at B's evidence store."""

    event_id: str = Field(min_length=3, max_length=48, pattern=r"^[a-z0-9][a-z0-9-]*$")
    camera_id: CameraId
    current_stream_epoch: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=120)
