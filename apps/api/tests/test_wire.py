"""Tests for cue_api.policy.wire — DecisionRecord -> A-shape transport."""
from __future__ import annotations

import json

from cue_api.contracts import CONTRACT_VERSION
from cue_api.policy.director import DecisionAction
from cue_api.policy.log import CameraConsideration, record_from_session_decision
from cue_api.policy.session import SessionDecision
from cue_api.policy.wire import DecisionEvent, to_wire, to_wire_json
from cue_api.semantics.parser import Action, Cue, Intent, Scope, TemporalIntent


def _sd(**kw) -> SessionDecision:
    d = {
        "action": DecisionAction.TAKE,
        "camera_id": "CAM-GUEST",
        "reason": "role_based: sarah -> CAM-GUEST",
        "decision_seq": 3,
        "mode_revision": 1,
    }
    d.update(kw)
    return SessionDecision(**d)


def _cue() -> Cue:
    return Cue(
        target_guest_ids=["sarah"],
        scope=Scope.SINGLE,
        intent=Intent.INTRODUCE,
        temporal_intent=TemporalIntent.NOW,
        action=Action.SHOW,
        evidence_text="Please welcome Sarah Tan.",
        utterance_id="utt-42",
        created_at=1000.0,
    )


def test_to_wire_produces_event_with_contract_version():
    rec = record_from_session_decision(_sd(), at=1000.5, cue=_cue(),
                                       source="LIVE")
    ev = to_wire(rec)
    assert isinstance(ev, DecisionEvent)
    assert ev.contract_version == CONTRACT_VERSION
    assert ev.kind == "decision"


def test_to_wire_json_uses_camelcase_and_camel_field_names():
    rec = record_from_session_decision(_sd(), at=1000.5, cue=_cue(),
                                       source="LIVE")
    js = to_wire_json(rec)
    d = json.loads(js)
    # camelCase keys (A's convention via to_camel alias generator)
    assert "contractVersion" in d
    assert "decisionSeq" in d
    assert "modeRevision" in d
    assert "cameraId" in d
    assert "plainReason" in d
    # snake_case keys must NOT be on the wire.
    assert "contract_version" not in d
    assert "decision_seq" not in d
    assert "mode_revision" not in d


def test_to_wire_plain_reason_reflects_sentence_style():
    # For a role_based cue-driven TAKE, plain_reason should be
    # "CUE cut to Sarah. She was just invited up."
    rec = record_from_session_decision(_sd(), at=0.0, cue=_cue())
    ev = to_wire(rec)
    assert ev.plain_reason.startswith("CUE cut to Sarah")


def test_source_override_forces_fixture_tag():
    rec = record_from_session_decision(_sd(), at=0.0, cue=_cue(),
                                       source="LIVE")
    ev = to_wire(rec, source_override="FIXTURE")
    assert ev.source == "FIXTURE"


def test_source_override_defends_against_garbage_values():
    rec = record_from_session_decision(_sd(), at=0.0, cue=_cue(),
                                       source="LIVE")
    ev = to_wire(rec, source_override="unknown-bad-value")  # type: ignore[arg-type]
    assert ev.source == "LIVE"


def test_transcript_span_and_cue_summary_camel_case_on_wire():
    rec = record_from_session_decision(_sd(), at=0.0, cue=_cue())
    d = json.loads(to_wire_json(rec))
    assert "transcriptSpan" in d
    ts = d["transcriptSpan"]
    assert set(ts.keys()) == {"utteranceId", "text", "startedAt", "endedAt"}
    cs = d["cueSummary"]
    assert set(cs.keys()) == {
        "targetGuestIds", "scope", "temporalIntent", "actionPreValidate",
    }


def test_cameras_considered_carry_rejection_reason_on_wire():
    considered = [
        CameraConsideration(
            camera_id="CAM-HOST", role="host", healthy=True,
            evidence_age_s=999.0, picked=False,
            rejection_reason="target not in confirmed_guest_ids",
        ),
        CameraConsideration(
            camera_id="CAM-GUEST", role="guest", healthy=True,
            guest_ready=True, evidence_age_s=0.4, picked=True,
        ),
    ]
    rec = record_from_session_decision(
        _sd(), at=0.0, cue=_cue(),
        cameras_considered=considered,
    )
    d = json.loads(to_wire_json(rec))
    assert len(d["camerasConsidered"]) == 2
    assert d["camerasConsidered"][0]["rejectionReason"].startswith("target not")
    assert d["camerasConsidered"][1]["picked"] is True


def test_stay_and_slate_actions_survive_wire_round_trip():
    stay = record_from_session_decision(
        _sd(action=DecisionAction.STAY, camera_id="CAM-HOST",
            reason="temporal_intent=FUTURE, not NOW"),
        at=0.0, cue=_cue(),
    )
    slate = record_from_session_decision(
        _sd(action=DecisionAction.SLATE, camera_id=None,
            reason="target sarah unusable; no healthy wide -> slate"),
        at=0.0, cue=_cue(),
    )
    d_stay = json.loads(to_wire_json(stay))
    d_slate = json.loads(to_wire_json(slate))
    assert d_stay["action"] == "STAY"
    assert d_stay["cameraId"] == "CAM-HOST"
    assert d_slate["action"] == "SLATE"
    assert d_slate["cameraId"] is None


def test_wire_event_is_pydantic_and_validates_new_instance_from_wire_json():
    rec = record_from_session_decision(_sd(), at=1.0, cue=_cue())
    js = to_wire_json(rec, source_override="FIXTURE")
    round_trip = DecisionEvent.model_validate_json(js)
    assert round_trip.decision_seq == rec.decision_seq
    assert round_trip.source == "FIXTURE"
    assert round_trip.plain_reason.startswith("CUE cut to")


def test_identity_defaults_to_role_based_and_survives_wire():
    rec = record_from_session_decision(_sd(), at=0.0, cue=_cue())
    ev = to_wire(rec)
    assert rec.identity == "ROLE_BASED"
    assert ev.identity == "ROLE_BASED"
    d = json.loads(to_wire_json(rec))
    assert d["identity"] == "ROLE_BASED"


def test_identity_verified_survives_wire_round_trip():
    rec = record_from_session_decision(
        _sd(), at=0.0, cue=_cue(), identity="VERIFIED",
    )
    ev = to_wire(rec)
    assert rec.identity == "VERIFIED"
    assert ev.identity == "VERIFIED"


def test_identity_garbage_clamps_to_role_based_on_wire():
    """A rogue caller that sets an unknown identity must not break the wire."""
    rec = record_from_session_decision(_sd(), at=0.0, cue=_cue())
    rec.identity = "SOMETHING_ELSE"  # type: ignore[assignment]
    ev = to_wire(rec)
    assert ev.identity == "ROLE_BASED"
