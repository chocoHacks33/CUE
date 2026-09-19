from __future__ import annotations

import threading
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from cue_api.camera_health import CameraHealthRegistry
from cue_api.contracts import CAMERA_CONTRACTS, CONTRACT_VERSION, CameraId, ContractModel


class SlotReadinessState(StrEnum):
    WAITING = "waiting"
    PUBLISHER_CONNECTED = "publisher-connected"
    SUBSCRIBING = "subscribing"
    VIDEO_READY = "video-ready"
    STALLED = "stalled"


class SlotReadiness(ContractModel):
    camera_id: CameraId
    publisher_identity: str | None = None
    stream_epoch: int | None = Field(default=None, ge=1)
    video_track_sid: str | None = None
    audio_track_sid: str | None = None
    decoded: bool
    renderable: bool
    last_frame_age_ms: float | None = Field(default=None, ge=0)
    frames_progressing: bool
    frame_count: int = Field(ge=0)
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    state: SlotReadinessState

    @model_validator(mode="after")
    def renderable_needs_current_decoded_track(self) -> SlotReadiness:
        if self.renderable and (
            not self.decoded
            or self.video_track_sid is None
            or self.stream_epoch is None
            or self.state is not SlotReadinessState.VIDEO_READY
        ):
            raise ValueError("renderable slot needs a decoded current video track")
        return self


class MasterAudioReadiness(ContractModel):
    camera_id: CameraId
    track_sid: str | None = None
    attached: bool
    playback_allowed: bool

    @model_validator(mode="after")
    def only_host_can_be_master(self) -> MasterAudioReadiness:
        if self.camera_id is not CameraId.HOST:
            raise ValueError("master audio must be CAM-HOST")
        if self.attached and self.track_sid is None:
            raise ValueError("attached master audio needs a track SID")
        return self


class ReceiverReadiness(ContractModel):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    event_id: str
    renderer_id: str = Field(min_length=8, max_length=128)
    renderer_generation: int = Field(ge=1)
    receiver_identity: str | None = None
    connected: bool
    clock_domain: str
    reported_at_ms: float = Field(ge=0)
    current_source: CameraId | None = None
    master_audio: MasterAudioReadiness
    slots: list[SlotReadiness]

    @model_validator(mode="after")
    def validate_shape(self) -> ReceiverReadiness:
        if self.clock_domain != "renderer-monotonic":
            raise ValueError("readiness clock must be renderer-monotonic")
        if [slot.camera_id for slot in self.slots] != list(CAMERA_CONTRACTS):
            raise ValueError("readiness must contain CAM-HOST, CAM-GUEST and CAM-WIDE in order")
        return self


class ReadinessError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReadinessStore:
    """Latest renderer report plus server-clock health derived from progression."""

    def __init__(self) -> None:
        self._reports: dict[str, ReceiverReadiness] = {}
        self._health: dict[str, CameraHealthRegistry] = {}
        self._lock = threading.RLock()

    def ingest(
        self,
        event_id: str,
        report: ReceiverReadiness,
        *,
        received_at_ms: int,
    ) -> ReceiverReadiness:
        if report.event_id != event_id:
            raise ReadinessError("EVENT_MISMATCH", "readiness belongs to another event")
        with self._lock:
            previous = self._reports.get(event_id)
            if previous is not None:
                if (
                    report.renderer_id == previous.renderer_id
                    and report.renderer_generation < previous.renderer_generation
                ):
                    raise ReadinessError("STALE_RENDERER", "renderer generation moved backwards")
                if (
                    report.renderer_id != previous.renderer_id
                    and previous.connected
                    and report.connected
                ):
                    raise ReadinessError(
                        "RENDERER_CONFLICT",
                        "another connected renderer already owns the programme output",
                    )

                same_renderer_generation = (
                    report.renderer_id == previous.renderer_id
                    and report.renderer_generation == previous.renderer_generation
                )
                if same_renderer_generation and report.reported_at_ms < previous.reported_at_ms:
                    raise ReadinessError(
                        "STALE_READINESS", "renderer readiness timestamp moved backwards"
                    )

            renderer_changed = previous is not None and (
                report.renderer_id != previous.renderer_id
                or report.renderer_generation != previous.renderer_generation
            )
            if renderer_changed or event_id not in self._health:
                self._health[event_id] = CameraHealthRegistry()
            registry = self._health[event_id]
            for slot in report.slots:
                if slot.stream_epoch is None:
                    current_epoch = registry.current_epoch(slot.camera_id)
                    if current_epoch > 0:
                        registry.update_transport(
                            slot.camera_id,
                            current_epoch,
                            connected=False,
                            publishing=False,
                            receiving=False,
                            renderable=False,
                            visually_usable=False,
                            warnings=("renderer_disconnected",),
                        )
                    continue
                registry.update_transport(
                    slot.camera_id,
                    slot.stream_epoch,
                    connected=report.connected and slot.publisher_identity is not None,
                    publishing=slot.video_track_sid is not None,
                    receiving=report.connected and slot.decoded,
                    renderable=report.connected and slot.renderable,
                    visually_usable=False,
                    warnings=(
                        ("renderer_stalled",)
                        if slot.state is SlotReadinessState.STALLED
                        else ("visual_quality_unknown",)
                    ),
                )
                if slot.frames_progressing:
                    registry.observe_frame(
                        slot.camera_id,
                        slot.stream_epoch,
                        slot.frame_count,
                        received_at_ms,
                    )
            self._reports[event_id] = report
            return report

    def current(self, event_id: str) -> ReceiverReadiness | None:
        with self._lock:
            return self._reports.get(event_id)

    def health(self, event_id: str) -> CameraHealthRegistry:
        with self._lock:
            return self._health.setdefault(event_id, CameraHealthRegistry())
