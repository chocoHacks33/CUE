import pytest

from cue_api.contracts import CameraId
from cue_api.control_contracts import RenderCommand, RenderStatus
from cue_api.control_metrics import ControlLatencyTracker


def command(decision_id: str, event_id: str = "demo") -> RenderCommand:
    return RenderCommand(
        decision_id=decision_id,
        event_id=event_id,
        control_generation="generation-1",
        decision_sequence=1,
        mode_revision=1,
        camera_id=CameraId.HOST,
        stream_epoch=1,
        reason_code="TEST",
        created_at_ms=1_000,
        expires_at_ms=3_000,
    )


def test_latency_window_reports_nearest_rank_p50_and_p95_per_event() -> None:
    tracker = ControlLatencyTracker(window_size=20)
    for index, latency_ms in enumerate(range(10, 110, 10), start=1):
        item = command(f"decision-{index}")
        tracker.issued(item, now_s=1.0)
        tracker.acknowledged(
            item.decision_id,
            RenderStatus.APPLIED,
            now_s=1.0 + latency_ms / 1000,
        )

    metrics = tracker.snapshot("demo")
    assert metrics.applied_count == 10
    assert metrics.p50_ms == pytest.approx(50)
    assert metrics.p95_ms == pytest.approx(100)
    assert metrics.maximum_ms == pytest.approx(100)
    assert tracker.snapshot("another-event").applied_count == 0


def test_rejected_and_outstanding_commands_are_counted_separately() -> None:
    tracker = ControlLatencyTracker()
    rejected = command("rejected")
    pending = command("pending")
    tracker.issued(rejected, now_s=1.0)
    tracker.issued(pending, now_s=1.0)
    tracker.acknowledged("rejected", RenderStatus.REJECTED, now_s=1.1)

    metrics = tracker.snapshot("demo")
    assert metrics.applied_count == 0
    assert metrics.rejected_count == 1
    assert metrics.outstanding_count == 1
