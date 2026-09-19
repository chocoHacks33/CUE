"""Synthetic Stage 2 loop used before the real Mac compositor is attached.

Nothing here is presented as live recognition or a real camera cut. It joins
C's pure policy to A's control state and a deterministic mock of D's ACK path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cue_api.contracts import CameraId
from cue_api.control import ControlStore
from cue_api.control_contracts import (
    ControlMode,
    ControlSnapshot,
    RenderAckRequest,
    RenderCommand,
    RenderReconcileRequest,
    RenderStatus,
    RenderTarget,
)
from cue_api.policy.director import Decision, DecisionAction, Mode, State, decide


@dataclass(frozen=True)
class FixtureRunResult:
    decision: Decision
    command: RenderCommand | None
    acknowledgement: RenderAckRequest | None
    state: ControlSnapshot


class MockCompositor:
    def __init__(self, ready_epochs: dict[CameraId, int]) -> None:
        self.ready_epochs = ready_epochs

    def apply(self, command: RenderCommand, *, now_ms: int) -> RenderAckRequest:
        if command.target is RenderTarget.SLATE:
            return RenderAckRequest(
                decision_id=command.decision_id,
                control_generation=command.control_generation,
                decision_sequence=command.decision_sequence,
                status=RenderStatus.APPLIED,
                actual_target=RenderTarget.SLATE,
                applied_at_ms=now_ms,
            )
        ready = (
            command.camera_id is not None
            and command.stream_epoch is not None
            and self.ready_epochs.get(command.camera_id) == command.stream_epoch
        )
        return RenderAckRequest(
            decision_id=command.decision_id,
            control_generation=command.control_generation,
            decision_sequence=command.decision_sequence,
            status=RenderStatus.APPLIED if ready else RenderStatus.REJECTED,
            actual_target=RenderTarget.CAMERA,
            actual_camera_id=command.camera_id if ready else None,
            actual_stream_epoch=command.stream_epoch if ready else None,
            applied_at_ms=now_ms,
            detail=None if ready else "fixture track is not renderable",
        )


class Stage2FixtureRunner:
    def __init__(
        self,
        *,
        event_id: str,
        store: ControlStore,
        compositor: MockCompositor,
        current_camera: CameraId,
        current_stream_epoch: int,
    ) -> None:
        self.event_id = event_id
        self.store = store
        self.compositor = compositor
        snapshot = store.snapshot(event_id)
        self.state = State(current_camera=current_camera.value, last_cut_time=0.0)
        store.reconcile(
            event_id,
            RenderReconcileRequest(
                control_generation=snapshot.control_generation,
                actual_camera_id=current_camera,
                actual_stream_epoch=current_stream_epoch,
                reported_at_ms=0,
            ),
        )

    @staticmethod
    def _policy_mode(mode: ControlMode) -> Mode:
        if mode is ControlMode.AUTO:
            return Mode.AUTO
        if mode is ControlMode.MANUAL_HOLD:
            return Mode.HOLD
        return Mode.ASSIST

    def run(
        self,
        *,
        cue: Any,
        cameras: dict[str, dict[str, Any]],
        decision_key: str,
        now_s: float,
    ) -> FixtureRunResult:
        control = self.store.snapshot(self.event_id)
        self.state.mode = self._policy_mode(control.mode)
        self.state.current_camera = (
            control.live_camera_id.value if control.live_camera_id is not None else None
        )
        decision = decide(cue, cameras, self.state, now_s)
        if decision.action is DecisionAction.STAY:
            return FixtureRunResult(decision, None, None, control)

        now_ms = int(now_s * 1000)
        reason_code = "FIXTURE_" + decision.action.value
        if decision.action is DecisionAction.SLATE:
            mutation = self.store.policy_slate(
                self.event_id,
                expected_revision=control.mode_revision,
                decision_key=decision_key,
                reason_code=reason_code,
                now_ms=now_ms,
            )
        else:
            if decision.camera_id is None:
                raise ValueError("TAKE decision did not name a camera")
            camera_id = CameraId(decision.camera_id)
            stream_epoch = int(cameras[decision.camera_id]["epoch"])
            mutation = self.store.policy_take(
                self.event_id,
                camera_id=camera_id,
                stream_epoch=stream_epoch,
                expected_revision=control.mode_revision,
                decision_key=decision_key,
                reason_code=reason_code,
                now_ms=now_ms,
            )
        command = mutation.render_command
        assert command is not None
        acknowledgement = self.compositor.apply(command, now_ms=now_ms + 25)
        state = self.store.acknowledge(
            self.event_id,
            acknowledgement,
            now_ms=now_ms + 25,
        )
        if acknowledgement.status is RenderStatus.APPLIED:
            self.state.current_camera = (
                state.live_camera_id.value if state.live_camera_id is not None else None
            )
            self.state.last_cut_time = now_s
            self.state.last_utterance_id = getattr(cue, "utterance_id", "") or ""
        return FixtureRunResult(decision, command, acknowledgement, state)
