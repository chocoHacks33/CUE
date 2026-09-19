from cue_api.contracts import CameraId
from cue_api.control import ControlStore
from cue_api.control_contracts import ControlMode, RenderStatus, RenderTarget
from cue_api.integration_fixture import MockCompositor, Stage2FixtureRunner
from cue_api.semantics.parser import Action, Cue, Intent, Scope, TemporalIntent


def cue(temporal: TemporalIntent = TemporalIntent.NOW) -> Cue:
    return Cue(
        target_guest_ids=["sarah"],
        scope=Scope.SINGLE,
        intent=Intent.INTRODUCE,
        temporal_intent=temporal,
        action=Action.SHOW if temporal is TemporalIntent.NOW else Action.HOLD,
        evidence_text="Sarah, please join us now",
        utterance_id="fixture-utterance-1",
        created_at=10.0,
    )


def cameras(*, all_unhealthy: bool = False) -> dict[str, dict[str, object]]:
    return {
        "CAM-HOST": {"role": "host", "healthy": not all_unhealthy, "epoch": 2},
        "CAM-GUEST": {
            "role": "guest",
            "healthy": not all_unhealthy,
            "epoch": 3,
            "confirmed_guest_ids": ["sarah"],
            "evidence_age_s": 0.2,
        },
        "CAM-WIDE": {"role": "wide", "healthy": not all_unhealthy, "epoch": 1},
    }


def runner(store: ControlStore) -> Stage2FixtureRunner:
    return Stage2FixtureRunner(
        event_id="fixture-stage2",
        store=store,
        compositor=MockCompositor({CameraId.HOST: 2, CameraId.GUEST: 3, CameraId.WIDE: 1}),
        current_camera=CameraId.HOST,
        current_stream_epoch=2,
    )


def test_fixture_cue_policy_render_ack_updates_live_state() -> None:
    store = ControlStore()
    fixture = runner(store)
    store.set_mode(
        "fixture-stage2",
        mode=ControlMode.AUTO,
        expected_revision=0,
        idempotency_key="enable-auto-1",
    )

    result = fixture.run(
        cue=cue(),
        cameras=cameras(),
        decision_key="decision-intro-1",
        now_s=10.0,
    )

    assert result.command is not None
    assert result.command.target is RenderTarget.CAMERA
    assert result.command.camera_id is CameraId.GUEST
    assert result.acknowledgement is not None
    assert result.acknowledgement.status is RenderStatus.APPLIED
    assert result.state.live_camera_id is CameraId.GUEST
    assert store.latency_metrics("fixture-stage2").applied_count == 1


def test_future_mention_produces_no_render_command() -> None:
    store = ControlStore()
    fixture = runner(store)
    store.set_mode(
        "fixture-stage2",
        mode=ControlMode.AUTO,
        expected_revision=0,
        idempotency_key="enable-auto-1",
    )
    result = fixture.run(
        cue=cue(TemporalIntent.FUTURE),
        cameras=cameras(),
        decision_key="decision-future-1",
        now_s=10.0,
    )
    assert result.command is None
    assert result.state.live_camera_id is CameraId.HOST


def test_no_healthy_camera_renders_and_acknowledges_slate() -> None:
    store = ControlStore()
    fixture = runner(store)
    store.set_mode(
        "fixture-stage2",
        mode=ControlMode.AUTO,
        expected_revision=0,
        idempotency_key="enable-auto-1",
    )
    result = fixture.run(
        cue=cue(),
        cameras=cameras(all_unhealthy=True),
        decision_key="decision-slate-1",
        now_s=10.0,
    )
    assert result.command is not None
    assert result.command.target is RenderTarget.SLATE
    assert result.acknowledgement is not None
    assert result.acknowledgement.actual_target is RenderTarget.SLATE
    assert result.state.live_camera_id is None
