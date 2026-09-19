from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field

from cue_api.contracts import CameraId
from cue_api.control_contracts import (
    ControlMode,
    ControlMutationResponse,
    ControlRole,
    ControlSnapshot,
    RenderAckRequest,
    RenderCommand,
    RenderStatus,
)


class ControlError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class _EventControl:
    event_id: str
    control_generation: str
    mode: ControlMode = ControlMode.ASSIST
    mode_revision: int = 0
    decision_sequence: int = 0
    live_camera_id: CameraId | None = None
    live_stream_epoch: int | None = None
    pending: RenderCommand | None = None
    idempotency: dict[str, _IdempotentMutation] = field(default_factory=dict)
    acknowledgements: dict[str, RenderAckRequest] = field(default_factory=dict)


@dataclass(frozen=True)
class _IdempotentMutation:
    fingerprint: tuple[object, ...]
    response: ControlMutationResponse


class ControlStore:
    """Authoritative in-memory control state with stale-command guards.

    It deliberately does not depend on LiveKit, the compositor or the Stage 1
    integration branch. The adapters can be attached after all three feeds are
    physically verified.
    """

    def __init__(self, *, command_ttl_ms: int = 2_000) -> None:
        self._generation = secrets.token_hex(12)
        self._command_ttl_ms = command_ttl_ms
        self._events: dict[str, _EventControl] = {}
        self._lock = threading.RLock()

    def _event(self, event_id: str) -> _EventControl:
        return self._events.setdefault(
            event_id,
            _EventControl(event_id=event_id, control_generation=self._generation),
        )

    @staticmethod
    def _snapshot(event: _EventControl) -> ControlSnapshot:
        return ControlSnapshot(
            event_id=event.event_id,
            control_generation=event.control_generation,
            mode=event.mode,
            mode_revision=event.mode_revision,
            decision_sequence=event.decision_sequence,
            live_camera_id=event.live_camera_id,
            live_stream_epoch=event.live_stream_epoch,
            pending_decision_id=event.pending.decision_id if event.pending else None,
        )

    def snapshot(self, event_id: str) -> ControlSnapshot:
        with self._lock:
            return self._snapshot(self._event(event_id))

    @staticmethod
    def _require_revision(event: _EventControl, expected_revision: int) -> None:
        if expected_revision != event.mode_revision:
            raise ControlError(
                "REVISION_CONFLICT",
                f"expected mode revision {expected_revision}, current is {event.mode_revision}",
            )

    def set_mode(
        self,
        event_id: str,
        *,
        mode: ControlMode,
        expected_revision: int,
        idempotency_key: str,
    ) -> ControlMutationResponse:
        with self._lock:
            event = self._event(event_id)
            fingerprint = ("mode", mode.value, expected_revision)
            replay = event.idempotency.get(idempotency_key)
            if replay is not None:
                if replay.fingerprint != fingerprint:
                    raise ControlError(
                        "IDEMPOTENCY_CONFLICT",
                        "idempotency key was already used for a different action",
                    )
                return replay.response
            self._require_revision(event, expected_revision)
            if event.mode is ControlMode.ENDED:
                raise ControlError("EVENT_ENDED", "an ended event cannot change mode")

            event.mode = mode
            event.mode_revision += 1
            event.pending = None
            result = ControlMutationResponse(state=self._snapshot(event))
            event.idempotency[idempotency_key] = _IdempotentMutation(fingerprint, result)
            return result

    def manual_take(
        self,
        event_id: str,
        *,
        camera_id: CameraId,
        stream_epoch: int,
        expected_revision: int,
        idempotency_key: str,
        reason_code: str = "MANUAL_TAKE",
        now_ms: int | None = None,
    ) -> ControlMutationResponse:
        with self._lock:
            event = self._event(event_id)
            fingerprint = (
                "take",
                camera_id.value,
                stream_epoch,
                expected_revision,
                reason_code,
            )
            replay = event.idempotency.get(idempotency_key)
            if replay is not None:
                if replay.fingerprint != fingerprint:
                    raise ControlError(
                        "IDEMPOTENCY_CONFLICT",
                        "idempotency key was already used for a different action",
                    )
                return replay.response
            self._require_revision(event, expected_revision)
            if event.mode is ControlMode.ENDED:
                raise ControlError("EVENT_ENDED", "an ended event cannot take a camera")

            created_at_ms = now_ms if now_ms is not None else int(time.time() * 1000)
            event.mode_revision += 1
            event.decision_sequence += 1
            command = RenderCommand(
                decision_id=secrets.token_hex(12),
                event_id=event_id,
                control_generation=event.control_generation,
                decision_sequence=event.decision_sequence,
                mode_revision=event.mode_revision,
                camera_id=camera_id,
                stream_epoch=stream_epoch,
                reason_code=reason_code,
                created_at_ms=created_at_ms,
                expires_at_ms=created_at_ms + self._command_ttl_ms,
            )
            event.pending = command
            result = ControlMutationResponse(state=self._snapshot(event), render_command=command)
            event.idempotency[idempotency_key] = _IdempotentMutation(fingerprint, result)
            return result

    def acknowledge(
        self,
        event_id: str,
        acknowledgement: RenderAckRequest,
        *,
        now_ms: int | None = None,
    ) -> ControlSnapshot:
        with self._lock:
            event = self._event(event_id)
            previous = event.acknowledgements.get(acknowledgement.decision_id)
            if previous is not None:
                if previous != acknowledgement:
                    raise ControlError(
                        "ACK_CONFLICT", "decision already has a different acknowledgement"
                    )
                return self._snapshot(event)

            command = event.pending
            if acknowledgement.control_generation != event.control_generation:
                raise ControlError(
                    "STALE_GENERATION", "acknowledgement is from an old control generation"
                )
            if command is None or command.decision_id != acknowledgement.decision_id:
                raise ControlError("UNKNOWN_DECISION", "decision is not the current pending render")
            if command.decision_sequence != acknowledgement.decision_sequence:
                raise ControlError("SEQUENCE_MISMATCH", "decision sequence does not match")
            if command.mode_revision != event.mode_revision:
                raise ControlError(
                    "STALE_REVISION", "a newer manual action invalidated this render"
                )

            observed_at_ms = now_ms if now_ms is not None else int(time.time() * 1000)
            if observed_at_ms > command.expires_at_ms:
                event.pending = None
                raise ControlError(
                    "COMMAND_EXPIRED", "render command expired before acknowledgement"
                )

            if acknowledgement.status is RenderStatus.APPLIED and (
                acknowledgement.actual_camera_id != command.camera_id
                or acknowledgement.actual_stream_epoch != command.stream_epoch
            ):
                raise ControlError(
                    "TARGET_MISMATCH", "compositor applied a different camera or epoch"
                )

            event.acknowledgements[acknowledgement.decision_id] = acknowledgement
            event.pending = None
            if acknowledgement.status is RenderStatus.APPLIED:
                event.live_camera_id = acknowledgement.actual_camera_id
                event.live_stream_epoch = acknowledgement.actual_stream_epoch
            return self._snapshot(event)


@dataclass(frozen=True)
class ControlSession:
    event_id: str
    role: ControlRole
    expires_at_monotonic_s: float


class ControlSessionStore:
    """Short-lived role-scoped control socket credentials stored only as hashes."""

    def __init__(self, *, ttl_seconds: int = 300) -> None:
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, ControlSession] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def issue(self, event_id: str, role: ControlRole) -> tuple[str, int]:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[self._digest(token)] = ControlSession(
                event_id=event_id,
                role=role,
                expires_at_monotonic_s=time.monotonic() + self._ttl_seconds,
            )
        return token, self._ttl_seconds

    def validate(self, token: str, event_id: str) -> ControlSession:
        with self._lock:
            session = self._sessions.get(self._digest(token))
            if session is None or session.event_id != event_id:
                raise ControlError("INVALID_SESSION", "invalid control session")
            if session.expires_at_monotonic_s <= time.monotonic():
                self._sessions.pop(self._digest(token), None)
                raise ControlError("SESSION_EXPIRED", "control session expired")
            return session
