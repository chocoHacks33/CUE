from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

CONTRACT_VERSION = "0.1.0"


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class CameraId(StrEnum):
    HOST = "CAM-HOST"
    GUEST = "CAM-GUEST"
    WIDE = "CAM-WIDE"


class TransportOutcome(StrEnum):
    ATTACHED = "ATTACHED"
    REPUBLISHED = "REPUBLISHED"
    DETACHED = "DETACHED"
    STALE_DETACH_IGNORED = "STALE_DETACH_IGNORED"


class CameraRole(StrEnum):
    HOST = "HOST"
    GUEST = "GUEST"
    WIDE = "WIDE"


class AudioPolicy(StrEnum):
    MASTER = "MASTER"
    DISABLED = "DISABLED"


class CameraContract(ContractModel):
    camera_id: CameraId
    role: CameraRole
    audio_policy: AudioPolicy
    owner: str = Field(pattern="^[ABC]$")


CAMERA_CONTRACTS: dict[CameraId, CameraContract] = {
    CameraId.HOST: CameraContract(
        camera_id=CameraId.HOST,
        role=CameraRole.HOST,
        audio_policy=AudioPolicy.MASTER,
        owner="A",
    ),
    CameraId.GUEST: CameraContract(
        camera_id=CameraId.GUEST,
        role=CameraRole.GUEST,
        audio_policy=AudioPolicy.DISABLED,
        owner="B",
    ),
    CameraId.WIDE: CameraContract(
        camera_id=CameraId.WIDE,
        role=CameraRole.WIDE,
        audio_policy=AudioPolicy.DISABLED,
        owner="C",
    ),
}


class PublisherTokenRequest(ContractModel):
    event_id: str = Field(min_length=3, max_length=48, pattern=r"^[a-z0-9][a-z0-9-]*$")
    camera_id: CameraId
    display_name: str = Field(min_length=1, max_length=64)


class PublisherTokenResponse(ContractModel):
    contract_version: str = CONTRACT_VERSION
    server_url: str
    participant_token: str
    participant_identity: str
    room_name: str
    camera: CameraContract
    expires_in_seconds: int


class PairingGrantRequest(ContractModel):
    camera_id: CameraId


class PairingGrantResponse(ContractModel):
    contract_version: str = CONTRACT_VERSION
    grant_id: str
    pairing_token: str
    verification_code: str
    camera: CameraContract
    expires_in_seconds: int


class PairingClaimRequest(ContractModel):
    pairing_token: str = Field(min_length=32, max_length=256)
    display_name: str = Field(min_length=1, max_length=64)
    device_label: str = Field(min_length=1, max_length=80)


class PairingClaimResponse(ContractModel):
    contract_version: str = CONTRACT_VERSION
    claim_id: str
    claim_secret: str
    verification_code: str
    camera: CameraContract
    status: str
    expires_in_seconds: int


class PairingDecisionRequest(ContractModel):
    approved: bool


class PairingStatusRequest(ContractModel):
    claim_id: str = Field(min_length=8, max_length=80)
    claim_secret: str = Field(min_length=32, max_length=256)


class PairingStatusResponse(ContractModel):
    contract_version: str = CONTRACT_VERSION
    claim_id: str
    status: str
    verification_code: str
    camera: CameraContract
    expires_in_seconds: int


class ProducerPairingClaimResponse(PairingStatusResponse):
    display_name: str
    device_label: str


class PairingExchangeResponse(PublisherTokenResponse):
    device_session_id: str
    stream_epoch: int = Field(ge=1)


class CameraBindingResponse(ContractModel):
    contract_version: str = CONTRACT_VERSION
    event_id: str
    camera_id: CameraId
    participant_identity: str
    device_session_id: str
    display_name: str
    current_video_track_sid: str | None = None
    stream_epoch: int = Field(ge=1)
    binding_revision: int = Field(ge=0)


class VideoTrackMutationRequest(ContractModel):
    camera_id: CameraId
    participant_identity: str = Field(min_length=8, max_length=180)
    track_sid: str = Field(min_length=1, max_length=180)


class TransportMutationResponse(ContractModel):
    binding: CameraBindingResponse
    outcome: TransportOutcome
    epoch_advanced: bool
    observation_dropped: bool


class EventEndReceipt(ContractModel):
    event_id: str
    already_ended: bool
    mode: Literal["ENDED"]
    control_sessions_revoked: int = Field(ge=0)
    grants_deleted: int = Field(ge=0)
    claims_deleted: int = Field(ge=0)
    bindings_deleted: int = Field(ge=0)
    guest_ids_deleted: list[str]
    references_deleted: int = Field(ge=0)
    observations_dropped: int = Field(ge=0)
    readiness_removed: bool
    ended_at_ms: int = Field(ge=0)


class TopologyResponse(ContractModel):
    contract_version: str = CONTRACT_VERSION
    cameras: list[CameraContract]
    central_runtime: str = "D-MAC"


class HealthResponse(ContractModel):
    status: str
    service: str = "cue-api"
    contract_version: str = CONTRACT_VERSION
    livekit_configured: bool


Stage4ProbeArea = Literal[
    "ROUTING_RECONNECT",
    "SOURCE_LOSS",
    "BACKEND_FAILURE",
    "SPEECH_PROVIDER_FAILURE",
    "SEMANTIC_PROVIDER_FAILURE",
    "EVENT_ACCESS",
    "OBSERVER_CONTROL",
]
Stage4EvidenceKind = Literal["AUTOMATED", "REPLAY", "LIVE"]


class Stage4TrialRequest(ContractModel):
    trial_id: str = Field(
        min_length=3,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    area: Stage4ProbeArea
    passed: bool
    evidence_kind: Stage4EvidenceKind
    latency_ms: float | None = Field(default=None, ge=0, le=600_000)
    detail: str = Field(min_length=3, max_length=1_000)

    @model_validator(mode="after")
    def require_source_loss_latency(self) -> Stage4TrialRequest:
        if self.area == "SOURCE_LOSS" and self.evidence_kind == "LIVE":
            if self.latency_ms is None:
                raise ValueError("a live SOURCE_LOSS trial requires latencyMs")
        return self


class Stage4TrialResponse(Stage4TrialRequest):
    pass


class Stage4AreaAssessmentResponse(ContractModel):
    area: Stage4ProbeArea
    status: Literal["PASS", "FAIL", "INCOMPLETE"]
    qualifying_trials: int = Field(ge=0)
    required_trials: int = Field(ge=1)
    p95_latency_ms: float | None = Field(default=None, ge=0)
    blocking_reasons: list[str]


class Stage4AssessmentResponse(ContractModel):
    status: Literal["PASS", "FAIL", "INCOMPLETE"]
    auto_eligible: bool
    disclosure: str
    blocking_reasons: list[str]
    areas: list[Stage4AreaAssessmentResponse]


class Stage4EvidenceReportResponse(ContractModel):
    contract_version: str = CONTRACT_VERSION
    event_id: str
    trials: list[Stage4TrialResponse]
    assessment: Stage4AssessmentResponse


class Stage4TrialMutationResponse(ContractModel):
    created: bool
    report: Stage4EvidenceReportResponse


class ReceiverRole(StrEnum):
    DIRECTOR = "DIRECTOR"
    OBSERVER = "OBSERVER"


class ReceiverTokenRequest(ContractModel):
    event_id: str = Field(min_length=3, max_length=48, pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str = Field(min_length=1, max_length=64)
    receiver_role: ReceiverRole = ReceiverRole.DIRECTOR


class ReceiverTokenResponse(ContractModel):
    contract_version: str = CONTRACT_VERSION
    server_url: str
    participant_token: str
    participant_identity: str
    room_name: str
    receiver_role: ReceiverRole
    expires_in_seconds: int
