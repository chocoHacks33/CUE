from __future__ import annotations

import pytest

from cue_api.contracts import CameraId
from cue_api.control import ControlError, ControlSessionStore, ControlStore
from cue_api.control_contracts import ControlMode, ControlRole, RenderAckRequest, RenderStatus


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_control_sessions_expire_without_sleeping_and_stay_event_scoped() -> None:
    clock = Clock()
    sessions = ControlSessionStore(ttl_seconds=10, clock=clock)
    token, _ = sessions.issue("event-a", ControlRole.DIRECTOR)
    assert sessions.validate(token, "event-a").role is ControlRole.DIRECTOR
    with pytest.raises(ControlError) as wrong_event:
        sessions.validate(token, "event-b")
    assert wrong_event.value.code == "INVALID_SESSION"

    clock.now += 10
    with pytest.raises(ControlError) as expired:
        sessions.validate(token, "event-a")
    assert expired.value.code == "SESSION_EXPIRED"


def test_take_becomes_live_only_after_matching_render_ack() -> None:
    store = ControlStore(command_ttl_ms=2_000)
    result = store.manual_take(
        "demo",
        camera_id=CameraId.GUEST,
        stream_epoch=3,
        expected_revision=0,
        idempotency_key="manual-take-1",
        now_ms=1_000,
    )
    command = result.render_command
    assert command is not None
    assert result.state.live_camera_id is None
    assert result.state.mode_revision == 1

    state = store.acknowledge(
        "demo",
        RenderAckRequest(
            decision_id=command.decision_id,
            control_generation=command.control_generation,
            decision_sequence=command.decision_sequence,
            status=RenderStatus.APPLIED,
            actual_camera_id=CameraId.GUEST,
            actual_stream_epoch=3,
            applied_at_ms=1_150,
        ),
        now_ms=1_150,
    )
    assert state.live_camera_id is CameraId.GUEST
    assert state.live_stream_epoch == 3
    assert state.pending_decision_id is None


def test_idempotency_replays_the_original_response_before_revision_check() -> None:
    store = ControlStore()
    first = store.set_mode(
        "demo",
        mode=ControlMode.MANUAL_HOLD,
        expected_revision=0,
        idempotency_key="hold-action-1",
    )
    replay = store.set_mode(
        "demo",
        mode=ControlMode.MANUAL_HOLD,
        expected_revision=0,
        idempotency_key="hold-action-1",
    )
    assert replay == first
    assert replay.state.mode_revision == 1


def test_idempotency_key_cannot_be_reused_for_another_action() -> None:
    store = ControlStore()
    store.set_mode(
        "demo",
        mode=ControlMode.MANUAL_HOLD,
        expected_revision=0,
        idempotency_key="shared-key-1",
    )
    with pytest.raises(ControlError) as caught:
        store.set_mode(
            "demo",
            mode=ControlMode.AUTO,
            expected_revision=1,
            idempotency_key="shared-key-1",
        )
    assert caught.value.code == "IDEMPOTENCY_CONFLICT"


def test_new_manual_action_invalidates_a_pending_render() -> None:
    store = ControlStore(command_ttl_ms=2_000)
    take = store.manual_take(
        "demo",
        camera_id=CameraId.HOST,
        stream_epoch=1,
        expected_revision=0,
        idempotency_key="manual-take-1",
        now_ms=1_000,
    )
    command = take.render_command
    assert command is not None

    state = store.set_mode(
        "demo",
        mode=ControlMode.MANUAL_HOLD,
        expected_revision=1,
        idempotency_key="manual-hold-1",
    ).state
    assert state.mode_revision == 2
    assert state.pending_decision_id is None

    with pytest.raises(ControlError, match="not the current pending") as caught:
        store.acknowledge(
            "demo",
            RenderAckRequest(
                decision_id=command.decision_id,
                control_generation=command.control_generation,
                decision_sequence=command.decision_sequence,
                status=RenderStatus.APPLIED,
                actual_camera_id=CameraId.HOST,
                actual_stream_epoch=1,
                applied_at_ms=1_100,
            ),
            now_ms=1_100,
        )
    assert caught.value.code == "UNKNOWN_DECISION"


def test_wrong_target_and_expired_commands_are_never_marked_live() -> None:
    store = ControlStore(command_ttl_ms=100)
    take = store.manual_take(
        "demo",
        camera_id=CameraId.WIDE,
        stream_epoch=4,
        expected_revision=0,
        idempotency_key="manual-take-1",
        now_ms=1_000,
    )
    command = take.render_command
    assert command is not None
    wrong_target = RenderAckRequest(
        decision_id=command.decision_id,
        control_generation=command.control_generation,
        decision_sequence=command.decision_sequence,
        status=RenderStatus.APPLIED,
        actual_camera_id=CameraId.HOST,
        actual_stream_epoch=4,
        applied_at_ms=1_010,
    )
    with pytest.raises(ControlError) as caught:
        store.acknowledge("demo", wrong_target, now_ms=1_010)
    assert caught.value.code == "TARGET_MISMATCH"

    matching = wrong_target.model_copy(update={"actual_camera_id": CameraId.WIDE})
    with pytest.raises(ControlError) as caught:
        store.acknowledge("demo", matching, now_ms=1_101)
    assert caught.value.code == "COMMAND_EXPIRED"
