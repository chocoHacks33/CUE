from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from cue_api.contracts import CameraId
from cue_api.control_contracts import (
    ControlLatencyMetrics,
    ControlMode,
    ControlMutationResponse,
    ControlRole,
    ControlSnapshot,
    RenderAckRequest,
    RenderCommand,
    RenderReconcileRequest,
    RenderStatus,
    RenderTarget,
)
from cue_api.control_metrics import ControlLatencyTracker


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

    def __init__(
        self,
        *,
        command_ttl_ms: int = 2_000,
        metrics: ControlLatencyTracker | None = None,
    ) -> None:
        self._generation = secrets.token_hex(12)
        self._command_ttl_ms = command_ttl_ms
        self._events: dict[str, _EventControl] = {}
        self._lock = threading.RLock()
        self._metrics = metrics or ControlLatencyTracker()

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

    def latency_metrics(self, event_id: str) -> ControlLatencyMetrics:
        return self._metrics.snapshot(event_id)

    def end_event(self, event_id: str) -> ControlSnapshot:
        """Fence future commands and invalidate any render awaiting an ACK."""
        with self._lock:
            event = self._event(event_id)
            if event.mode is ControlMode.ENDED:
                return self._snapshot(event)
            if event.pending is not None:
                self._metrics.acknowledged(event.pending.decision_id, RenderStatus.REJECTED)
            event.pending = None
            event.mode = ControlMode.ENDED
            event.mode_revision += 1
            return self._snapshot(event)

    def _expire_pending(self, event: _EventControl, now_ms: int) -> None:
        command = event.pending
        if command is None or now_ms <= command.expires_at_ms:
            return
        event.pending = None
        self._metrics.acknowledged(command.decision_id, RenderStatus.FAILED)

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
            if event.pending is not None:
                self._metrics.acknowledged(event.pending.decision_id, RenderStatus.REJECTED)
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
            if event.pending is not None:
                self._metrics.acknowledged(event.pending.decision_id, RenderStatus.REJECTED)
                event.pending = None

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
            self._metrics.issued(command)
            result = ControlMutationResponse(state=self._snapshot(event), render_command=command)
            event.idempotency[idempotency_key] = _IdempotentMutation(fingerprint, result)
            return result

    def policy_take(
        self,
        event_id: str,
        *,
        camera_id: CameraId,
        stream_epoch: int,
        expected_revision: int,
        decision_key: str,
        reason_code: str,
        now_ms: int | None = None,
    ) -> ControlMutationResponse:
        """Issue an AUTO render without changing the operator's revision."""
        with self._lock:
            event = self._event(event_id)
            idempotency_key = f"policy:{decision_key}"
            fingerprint = (
                "policy_take",
                camera_id.value,
                stream_epoch,
                expected_revision,
                decision_key,
                reason_code,
            )
            replay = event.idempotency.get(idempotency_key)
            if replay is not None:
                if replay.fingerprint != fingerprint:
                    raise ControlError(
                        "IDEMPOTENCY_CONFLICT",
                        "decision key was already used for another policy action",
                    )
                return replay.response
            self._require_revision(event, expected_revision)
            if event.mode is not ControlMode.AUTO:
                raise ControlError("AUTO_NOT_ENABLED", "policy may render only in AUTO mode")
            created_at_ms = now_ms if now_ms is not None else int(time.time() * 1000)
            self._expire_pending(event, created_at_ms)
            if event.pending is not None:
                raise ControlError("RENDER_PENDING", "wait for the current render acknowledgement")
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
            self._metrics.issued(command)
            result = ControlMutationResponse(state=self._snapshot(event), render_command=command)
            event.idempotency[idempotency_key] = _IdempotentMutation(fingerprint, result)
            return result

    def policy_slate(
        self,
        event_id: str,
        *,
        expected_revision: int,
        decision_key: str,
        reason_code: str,
        now_ms: int | None = None,
    ) -> ControlMutationResponse:
        """Issue the deterministic safety slate while AUTO is active."""
        with self._lock:
            event = self._event(event_id)
            idempotency_key = f"policy:{decision_key}"
            fingerprint = (
                "policy_slate",
                expected_revision,
                decision_key,
                reason_code,
            )
            replay = event.idempotency.get(idempotency_key)
            if replay is not None:
                if replay.fingerprint != fingerprint:
                    raise ControlError(
                        "IDEMPOTENCY_CONFLICT",
                        "decision key was already used for another policy action",
                    )
                return replay.response
            self._require_revision(event, expected_revision)
            if event.mode is not ControlMode.AUTO:
                raise ControlError("AUTO_NOT_ENABLED", "policy may render only in AUTO mode")
            created_at_ms = now_ms if now_ms is not None else int(time.time() * 1000)
            self._expire_pending(event, created_at_ms)
            if event.pending is not None:
                raise ControlError("RENDER_PENDING", "wait for the current render acknowledgement")
            event.decision_sequence += 1
            command = RenderCommand(
                decision_id=secrets.token_hex(12),
                event_id=event_id,
                control_generation=event.control_generation,
                decision_sequence=event.decision_sequence,
                mode_revision=event.mode_revision,
                target=RenderTarget.SLATE,
                reason_code=reason_code,
                created_at_ms=created_at_ms,
                expires_at_ms=created_at_ms + self._command_ttl_ms,
            )
            event.pending = command
            self._metrics.issued(command)
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
                self._metrics.acknowledged(command.decision_id, RenderStatus.FAILED)
                raise ControlError(
                    "COMMAND_EXPIRED", "render command expired before acknowledgement"
                )

            if acknowledgement.status is RenderStatus.APPLIED:
                mismatched = acknowledgement.actual_target is not command.target
                if command.target is RenderTarget.CAMERA:
                    mismatched = mismatched or (
                        acknowledgement.actual_camera_id != command.camera_id
                        or acknowledgement.actual_stream_epoch != command.stream_epoch
                    )
                if mismatched:
                    raise ControlError(
                        "TARGET_MISMATCH", "compositor applied a different render target"
                    )

            event.acknowledgements[acknowledgement.decision_id] = acknowledgement
            event.pending = None
            self._metrics.acknowledged(command.decision_id, acknowledgement.status)
            if acknowledgement.status is RenderStatus.APPLIED:
                if acknowledgement.actual_target is RenderTarget.SLATE:
                    event.live_camera_id = None
                    event.live_stream_epoch = None
                else:
                    event.live_camera_id = acknowledgement.actual_camera_id
                    event.live_stream_epoch = acknowledgement.actual_stream_epoch
            return self._snapshot(event)

    def reconcile(
        self,
        event_id: str,
        report: RenderReconcileRequest,
    ) -> ControlSnapshot:
        """Accept the trusted compositor's local state after reconnecting."""
        with self._lock:
            event = self._event(event_id)
            if report.control_generation != event.control_generation:
                raise ControlError("STALE_GENERATION", "reconciliation used an old generation")
            if event.mode is ControlMode.ENDED:
                raise ControlError("EVENT_ENDED", "an ended event cannot be reconciled")
            if event.pending is not None:
                self._metrics.acknowledged(
                    event.pending.decision_id,
                    RenderStatus.REJECTED,
                )
                event.pending = None
                event.mode_revision += 1
            event.live_camera_id = report.actual_camera_id
            event.live_stream_epoch = report.actual_stream_epoch
            return self._snapshot(event)


@dataclass(frozen=True)
class ControlSession:
    event_id: str
    role: ControlRole
    expires_at_monotonic_s: float


class ControlSessionStore:
    """Short-lived role-scoped control socket credentials stored only as hashes."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
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
                expires_at_monotonic_s=self._clock() + self._ttl_seconds,
            )
        return token, self._ttl_seconds

    def validate(self, token: str, event_id: str) -> ControlSession:
        with self._lock:
            session = self._sessions.get(self._digest(token))
            if session is None or session.event_id != event_id:
                raise ControlError("INVALID_SESSION", "invalid control session")
            if session.expires_at_monotonic_s <= self._clock():
                self._sessions.pop(self._digest(token), None)
                raise ControlError("SESSION_EXPIRED", "control session expired")
            return session

    def revoke_event(self, event_id: str) -> int:
        with self._lock:
            digests = [
                digest
                for digest, session in self._sessions.items()
                if session.event_id == event_id
            ]
            for digest in digests:
                del self._sessions[digest]
            return len(digests)
