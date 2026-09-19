from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

CONTRACT_VERSION = "0.1.0"


class ContractModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CameraId(StrEnum):
    HOST = "CAM-HOST"
    GUEST = "CAM-GUEST"
    WIDE = "CAM-WIDE"


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


class TopologyResponse(ContractModel):
    contract_version: str = CONTRACT_VERSION
    cameras: list[CameraContract]
    central_runtime: str = "D-MAC"


class HealthResponse(ContractModel):
    status: str
    service: str = "cue-api"
    contract_version: str = CONTRACT_VERSION
    livekit_configured: bool


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
