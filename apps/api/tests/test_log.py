"""Unit tests for cue_api.policy.log."""
from __future__ import annotations

import json

from cue_api.policy.director import DecisionAction
from cue_api.policy.log import (
    CameraConsideration,
    DecisionLogger,
    record_from_session_decision,
)
from cue_api.policy.session import SessionDecision
from cue_api.semantics.parser import Action, Cue, Intent, Scope, TemporalIntent


def _sd(**overrides) -> SessionDecision:
    d = {
        "action": DecisionAction.TAKE,
        "camera_id": "CAM-GUEST",
        "reason": "fresh identity sarah on CAM-GUEST (age 0.40s)",
        "decision_seq": 42,
        "mode_revision": 3,
    }
    d.update(overrides)
    return SessionDecision(**d)


def _cue() -> Cue:
    return Cue(
        target_guest_ids=["sarah"],
        scope=Scope.SINGLE,
        intent=Intent.INTRODUCE,
        temporal_intent=TemporalIntent.NOW,
        action=Action.SHOW,
        evidence_text="please welcome Sarah Tan.",
        utterance_id="utt-99",
        created_at=1000.0,
        mode_revision=3,
    )


# ---- DecisionLogger --------------------------------------------------------

def test_append_writes_one_json_line(tmp_path):
    log = DecisionLogger(tmp_path / "decisions.jsonl")
    rec = record_from_session_decision(_sd(), at=1000.0, cue=_cue())
    log.append(rec)
    text = (tmp_path / "decisions.jsonl").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["action"] == "TAKE"
    assert parsed["camera_id"] == "CAM-GUEST"
    assert parsed["decision_seq"] == 42
    assert parsed["mode_revision"] == 3


def test_appends_preserve_order_across_calls(tmp_path):
    log = DecisionLogger(tmp_path / "decisions.jsonl")
    log.append(record_from_session_decision(_sd(decision_seq=1), at=1.0, cue=_cue()))
    log.append(record_from_session_decision(_sd(decision_seq=2), at=2.0, cue=_cue()))
    log.append(record_from_session_decision(_sd(decision_seq=3), at=3.0, cue=_cue()))
    rows = log.read_all()
    assert [r["decision_seq"] for r in rows] == [1, 2, 3]


def test_record_contains_transcript_span_and_cue_summary(tmp_path):
    log = DecisionLogger(tmp_path / "d.jsonl")
    log.append(record_from_session_decision(_sd(), at=1000.0, cue=_cue()))
    row = log.read_all()[0]
    span = row["transcript_span"]
    assert span["utterance_id"] == "utt-99"
    assert span["text"] == "please welcome Sarah Tan."
    summary = row["cue_summary"]
    assert summary["target_guest_ids"] == ["sarah"]
    assert summary["temporal_intent"] == "NOW"
    assert summary["scope"] == "single"


def test_cameras_considered_are_serialised(tmp_path):
    log = DecisionLogger(tmp_path / "d.jsonl")
    considered = [
        CameraConsideration(
            camera_id="CAM-HOST", role="host", healthy=True,
            guest_ready=True, evidence_age_s=999.0, picked=False,
            rejection_reason="target sarah not in confirmed_guest_ids",
        ),
        CameraConsideration(
            camera_id="CAM-GUEST", role="guest", healthy=True,
            guest_ready=True, evidence_age_s=0.4, picked=True,
        ),
    ]
    log.append(record_from_session_decision(
        _sd(), at=1000.0, cue=_cue(), cameras_considered=considered,
    ))
    row = log.read_all()[0]
    assert len(row["cameras_considered"]) == 2
    assert row["cameras_considered"][1]["picked"] is True
    assert row["cameras_considered"][0]["rejection_reason"].startswith("target sarah")


def test_latencies_and_source_default_and_override(tmp_path):
    log = DecisionLogger(tmp_path / "d.jsonl")
    log.append(record_from_session_decision(
        _sd(), at=1000.0, cue=_cue(),
        latencies_ms={"asr": 320, "cue": 850, "decide": 1, "total": 1171},
        source="FIXTURE",
    ))
    row = log.read_all()[0]
    assert row["latencies_ms"]["total"] == 1171
    assert row["source"] == "FIXTURE"


def test_directory_is_created_for_logger(tmp_path):
    log_path = tmp_path / "nested" / "dir" / "d.jsonl"
    log = DecisionLogger(log_path)
    log.append(record_from_session_decision(_sd(), at=1.0, cue=_cue()))
    assert log_path.exists()


def test_record_no_model_chain_of_thought(tmp_path):
    """Sanity: reason is only the short observable string, not model output."""
    log = DecisionLogger(tmp_path / "d.jsonl")
    log.append(record_from_session_decision(_sd(), at=1.0, cue=_cue()))
    row = log.read_all()[0]
    for f in ("chain_of_thought", "reasoning", "logits", "logprobs"):
        assert f not in row
