import pytest

from cue_api.contracts import CameraId
from cue_api.control import ControlError, ControlStore
from cue_api.control_contracts import (
    ControlMode,
    RenderAckRequest,
    RenderReconcileRequest,
    RenderStatus,
    RenderTarget,
)


def test_restart_rejects_old_ack_then_accepts_explicit_reconciliation() -> None:
    before_restart = ControlStore()
    old = before_restart.manual_take(
        "demo",
        camera_id=CameraId.GUEST,
        stream_epoch=2,
        expected_revision=0,
        idempotency_key="take-before-restart",
        now_ms=1_000,
    ).render_command
    assert old is not None

    after_restart = ControlStore()
    with pytest.raises(ControlError) as caught:
        after_restart.acknowledge(
            "demo",
            RenderAckRequest(
                decision_id=old.decision_id,
                control_generation=old.control_generation,
                decision_sequence=old.decision_sequence,
                status=RenderStatus.APPLIED,
                actual_camera_id=CameraId.GUEST,
                actual_stream_epoch=2,
                applied_at_ms=1_050,
            ),
            now_ms=1_050,
        )
    assert caught.value.code == "STALE_GENERATION"

    current = after_restart.snapshot("demo")
    reconciled = after_restart.reconcile(
        "demo",
        RenderReconcileRequest(
            control_generation=current.control_generation,
            actual_camera_id=CameraId.GUEST,
            actual_stream_epoch=2,
            reported_at_ms=1_100,
        ),
    )
    assert reconciled.live_camera_id is CameraId.GUEST

    slate = after_restart.reconcile(
        "demo",
        RenderReconcileRequest(
            control_generation=current.control_generation,
            actual_target=RenderTarget.SLATE,
            reported_at_ms=1_200,
        ),
    )
    assert slate.live_camera_id is None
    assert slate.live_stream_epoch is None


def test_policy_cannot_render_outside_auto_or_replace_pending_render() -> None:
    store = ControlStore()
    with pytest.raises(ControlError) as caught:
        store.policy_take(
            "demo",
            camera_id=CameraId.GUEST,
            stream_epoch=1,
            expected_revision=0,
            decision_key="policy-1",
            reason_code="INTRODUCTION",
        )
    assert caught.value.code == "AUTO_NOT_ENABLED"

    auto = store.set_mode(
        "demo",
        mode=ControlMode.AUTO,
        expected_revision=0,
        idempotency_key="enable-auto-1",
    )
    store.policy_take(
        "demo",
        camera_id=CameraId.GUEST,
        stream_epoch=1,
        expected_revision=auto.state.mode_revision,
        decision_key="policy-1",
        reason_code="INTRODUCTION",
    )
    with pytest.raises(ControlError) as caught:
        store.policy_take(
            "demo",
            camera_id=CameraId.WIDE,
            stream_epoch=1,
            expected_revision=auto.state.mode_revision,
            decision_key="policy-2",
            reason_code="GROUP",
        )
    assert caught.value.code == "RENDER_PENDING"


def test_expired_policy_render_does_not_block_the_next_decision() -> None:
    store = ControlStore(command_ttl_ms=100)
    auto = store.set_mode(
        "demo",
        mode=ControlMode.AUTO,
        expected_revision=0,
        idempotency_key="enable-auto-1",
    )
    first = store.policy_take(
        "demo",
        camera_id=CameraId.GUEST,
        stream_epoch=1,
        expected_revision=auto.state.mode_revision,
        decision_key="policy-1",
        reason_code="INTRODUCTION",
        now_ms=1_000,
    )
    second = store.policy_take(
        "demo",
        camera_id=CameraId.WIDE,
        stream_epoch=1,
        expected_revision=auto.state.mode_revision,
        decision_key="policy-2",
        reason_code="SAFE_FALLBACK",
        now_ms=1_101,
    )

    assert first.render_command is not None
    assert second.render_command is not None
    assert second.render_command.decision_sequence == 2
    metrics = store.latency_metrics("demo")
    assert metrics.rejected_count == 1
    assert metrics.outstanding_count == 1


def test_trusted_reconciliation_invalidates_an_unrendered_command() -> None:
    store = ControlStore()
    pending = store.manual_take(
        "demo",
        camera_id=CameraId.GUEST,
        stream_epoch=2,
        expected_revision=0,
        idempotency_key="take-before-reconnect",
        now_ms=1_000,
    ).render_command
    assert pending is not None
    revision_before_reconcile = store.snapshot("demo").mode_revision

    reconciled = store.reconcile(
        "demo",
        RenderReconcileRequest(
            control_generation=pending.control_generation,
            actual_camera_id=CameraId.HOST,
            actual_stream_epoch=1,
            reported_at_ms=1_100,
        ),
    )

    assert reconciled.pending_decision_id is None
    assert reconciled.live_camera_id is CameraId.HOST
    assert reconciled.mode_revision == revision_before_reconcile + 1
    assert store.latency_metrics("demo").rejected_count == 1
    with pytest.raises(ControlError) as late:
        store.acknowledge(
            "demo",
            RenderAckRequest(
                decision_id=pending.decision_id,
                control_generation=pending.control_generation,
                decision_sequence=pending.decision_sequence,
                status=RenderStatus.APPLIED,
                actual_camera_id=CameraId.GUEST,
                actual_stream_epoch=2,
                applied_at_ms=1_120,
            ),
            now_ms=1_120,
        )
    assert late.value.code == "UNKNOWN_DECISION"
