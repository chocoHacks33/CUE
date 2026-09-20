from __future__ import annotations

import json

import pytest

from cue_api.stage4_gate import (
    EvidenceKind,
    GateStatus,
    ProbeArea,
    TrialResult,
    assess_stage4,
)
from cue_api.stage4_gate_cli import main


def trial(
    trial_id: str,
    area: ProbeArea,
    *,
    passed: bool = True,
    evidence: EvidenceKind = EvidenceKind.LIVE,
    latency_ms: float | None = None,
    detail: str = "",
) -> TrialResult:
    return TrialResult(trial_id, area, passed, evidence, latency_ms, detail)


def passing_trials() -> list[TrialResult]:
    results = [
        trial(f"route-{index:02}", ProbeArea.ROUTING_RECONNECT)
        for index in range(1, 21)
    ]
    results.extend(
        trial(
            f"loss-{index:02}",
            ProbeArea.SOURCE_LOSS,
            latency_ms=900 + index * 10,
        )
        for index in range(1, 11)
    )
    results.extend(
        [
            trial("backend-01", ProbeArea.BACKEND_FAILURE),
            trial("speech-01", ProbeArea.SPEECH_PROVIDER_FAILURE),
            trial("semantic-01", ProbeArea.SEMANTIC_PROVIDER_FAILURE),
            trial(
                "event-access-01",
                ProbeArea.EVENT_ACCESS,
                evidence=EvidenceKind.AUTOMATED,
            ),
        ]
    )
    results.extend(
        trial(
            f"observer-{index:02}",
            ProbeArea.OBSERVER_CONTROL,
            evidence=EvidenceKind.AUTOMATED,
        )
        for index in range(1, 4)
    )
    return results


def test_empty_evidence_fails_closed_as_incomplete() -> None:
    assessment = assess_stage4([])
    assert assessment.status is GateStatus.INCOMPLETE
    assert assessment.auto_eligible is False
    assert len(assessment.blocking_reasons) == len(ProbeArea)


def test_replay_cannot_satisfy_a_live_requirement() -> None:
    trials = [
        trial(
            f"route-{index:02}",
            ProbeArea.ROUTING_RECONNECT,
            evidence=EvidenceKind.REPLAY,
        )
        for index in range(1, 21)
    ]
    assessment = assess_stage4(trials)
    routing = assessment.areas[0]
    assert routing.status is GateStatus.INCOMPLETE
    assert routing.qualifying_trials == 0


def test_every_operational_requirement_passes() -> None:
    assessment = assess_stage4(passing_trials())
    assert assessment.status is GateStatus.PASS
    assert assessment.auto_eligible is True
    assert assessment.blocking_reasons == ()
    assert "B's identity gate" in assessment.disclosure


def test_one_camera_swap_fails_the_gate() -> None:
    trials = passing_trials()
    trials[7] = trial(
        "route-08",
        ProbeArea.ROUTING_RECONNECT,
        passed=False,
        detail="CAM-GUEST rejoined as CAM-WIDE",
    )
    assessment = assess_stage4(trials)
    assert assessment.status is GateStatus.FAIL
    assert assessment.auto_eligible is False
    assert any("CAM-GUEST rejoined" in reason for reason in assessment.blocking_reasons)


def test_source_loss_requires_latency_and_enforces_p95() -> None:
    missing = passing_trials()
    missing[20] = trial("loss-01", ProbeArea.SOURCE_LOSS)
    assessment = assess_stage4(missing)
    source = next(area for area in assessment.areas if area.area is ProbeArea.SOURCE_LOSS)
    assert source.status is GateStatus.INCOMPLETE
    assert "missing latency" in " ".join(source.blocking_reasons)

    slow = passing_trials()
    slow[29] = trial("loss-10", ProbeArea.SOURCE_LOSS, latency_ms=1_501)
    source = next(
        area for area in assess_stage4(slow).areas if area.area is ProbeArea.SOURCE_LOSS
    )
    assert source.status is GateStatus.FAIL
    assert source.p95_latency_ms == 1_501


def test_duplicate_ids_and_unexplained_failures_are_rejected() -> None:
    with pytest.raises(ValueError, match="explain"):
        trial("bad", ProbeArea.EVENT_ACCESS, passed=False)
    with pytest.raises(ValueError, match="unique"):
        assess_stage4(
            [
                trial("duplicate", ProbeArea.EVENT_ACCESS),
                trial("duplicate", ProbeArea.OBSERVER_CONTROL),
            ]
        )


def test_cli_returns_nonzero_for_incomplete_report(tmp_path, capsys) -> None:
    path = tmp_path / "stage4.json"
    path.write_text(json.dumps({"trials": []}), encoding="utf-8")
    assert main([str(path)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "INCOMPLETE"
    assert payload["autoEligible"] is False


def test_cli_returns_zero_for_a_passing_report(tmp_path, capsys) -> None:
    values = [
        {
            "trialId": item.trial_id,
            "area": item.area.value,
            "passed": item.passed,
            "evidenceKind": item.evidence_kind.value,
            "latencyMs": item.latency_ms,
            "detail": item.detail,
        }
        for item in passing_trials()
    ]
    path = tmp_path / "stage4.json"
    path.write_text(json.dumps({"trials": values}), encoding="utf-8")
    assert main([str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
