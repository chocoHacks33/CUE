from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from cue_api.contracts import CameraId, ContractModel


class ControlMode(StrEnum):
    SETUP = "SETUP"
    READY = "READY"
    ASSIST = "ASSIST"
    AUTO = "AUTO"
    MANUAL_HOLD = "MANUAL_HOLD"
    DEGRADED = "DEGRADED"
    ENDED = "ENDED"


class ControlRole(StrEnum):
    DIRECTOR = "DIRECTOR"
    OBSERVER = "OBSERVER"


class RenderStatus(StrEnum):
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class ControlSessionRequest(ContractModel):
    role: ControlRole


class ControlSessionResponse(ContractModel):
    token: str
    role: ControlRole
    expires_in_seconds: int


class ControlSnapshot(ContractModel):
    event_id: str
    control_generation: str
    mode: ControlMode
    mode_revision: int = Field(ge=0)
    decision_sequence: int = Field(ge=0)
    live_camera_id: CameraId | None = None
    live_stream_epoch: int | None = Field(default=None, ge=1)
    pending_decision_id: str | None = None


class ModeCommandRequest(ContractModel):
    mode: ControlMode
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=96, pattern=r"^[A-Za-z0-9._:-]+$")


class ManualTakeRequest(ContractModel):
    camera_id: CameraId
    stream_epoch: int = Field(ge=1)
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=96, pattern=r"^[A-Za-z0-9._:-]+$")
    reason_code: str = Field(default="MANUAL_TAKE", min_length=1, max_length=64)


class RenderCommand(ContractModel):
    decision_id: str
    event_id: str
    control_generation: str
    decision_sequence: int = Field(ge=1)
    mode_revision: int = Field(ge=0)
    camera_id: CameraId
    stream_epoch: int = Field(ge=1)
    reason_code: str
    created_at_ms: int = Field(ge=0)
    expires_at_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def expiry_follows_creation(self) -> RenderCommand:
        if self.expires_at_ms <= self.created_at_ms:
            raise ValueError("expires_at_ms must be later than created_at_ms")
        return self


class RenderAckRequest(ContractModel):
    decision_id: str
    control_generation: str
    decision_sequence: int = Field(ge=1)
    status: RenderStatus
    actual_camera_id: CameraId | None = None
    actual_stream_epoch: int | None = Field(default=None, ge=1)
    applied_at_ms: int = Field(ge=0)
    detail: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def applied_ack_has_actual_target(self) -> RenderAckRequest:
        if self.status is RenderStatus.APPLIED and (
            self.actual_camera_id is None or self.actual_stream_epoch is None
        ):
            raise ValueError("an APPLIED acknowledgement needs the actual camera and stream epoch")
        return self


class ControlMutationResponse(ContractModel):
    state: ControlSnapshot
    render_command: RenderCommand | None = None

