"""Unit tests for cue_api.policy.session.DirectorSession."""
from __future__ import annotations

import pytest

from cue_api.policy.director import DecisionAction, Mode
from cue_api.policy.session import DirectorSession, SessionDecision
from cue_api.semantics.parser import Action, Cue, Intent, Scope, TemporalIntent

NOW = 1000.0


def _cams(guest_ready: bool = True, guest_healthy: bool = True,
          host_healthy: bool = True):
    return {
        "CAM-HOST": {
            "role": "host", "healthy": host_healthy, "epoch": 1,
            "confirmed_guest_ids": [], "evidence_age_s": 999.0,
            "guest_ready": True,
        },
        "CAM-GUEST": {
            "role": "guest", "healthy": guest_healthy, "epoch": 1,
            "confirmed_guest_ids": ["sarah"], "evidence_age_s": 0.4,
            "guest_ready": guest_ready,
        },
        "CAM-WIDE": {
            "role": "wide", "healthy": True, "epoch": 1,
            "confirmed_guest_ids": [], "evidence_age_s": 999.0,
            "guest_ready": True,
        },
    }


def _now_cue(**kw):
    d = {
        "target_guest_ids": ["sarah"],
        "scope": Scope.SINGLE,
        "intent": Intent.INTRODUCE,
        "temporal_intent": TemporalIntent.NOW,
        "action": Action.SHOW,
        "evidence_text": "please welcome Sarah",
        "utterance_id": "utt-1",
        "created_at": NOW - 0.2,
        "mode_revision": 0,
    }
    d.update(kw)
    return Cue(**d)


# ---- decision sequencing & mode_revision -----------------------------------

def test_decision_seq_monotonic_and_starts_at_1():
    s = DirectorSession(current_camera="CAM-HOST")
    d1 = s.on_manual("HOLD", NOW)
    d2 = s.on_manual("RESUME_AUTO", NOW + 0.1)
    assert d1.decision_seq == 1
    assert d2.decision_seq == 2
    assert d1.mode_revision == 1  # HOLD bumped 0 -> 1
    assert d2.mode_revision == 2  # RESUME_AUTO bumped 1 -> 2


def test_cue_with_matching_mode_revision_flows_through_decide():
    s = DirectorSession(current_camera="CAM-HOST")
    d = s.on_cue(_now_cue(mode_revision=0), _cams(), NOW)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-GUEST"


def test_cue_from_stale_mode_revision_is_rejected():
    s = DirectorSession(current_camera="CAM-HOST")
    # A manual HOLD bumps the session to rev=1. A cue tagged rev=0 (issued
    # before the HOLD) must be rejected.
    s.on_manual("HOLD", NOW)
    d = s.on_cue(_now_cue(mode_revision=0), _cams(), NOW + 0.1)
    assert d.action == DecisionAction.STAY
    assert "stale mode_revision" in d.reason


def test_late_cue_after_hold_dropped_even_if_it_was_a_named_take():
    s = DirectorSession(current_camera="CAM-HOST")
    # simulate: cue was interpreted before the HOLD, arrives after HOLD.
    cue = _now_cue(mode_revision=0, target_guest_ids=["sarah"])
    s.on_manual("HOLD", NOW)  # rev -> 1
    d = s.on_cue(cue, _cams(), NOW + 0.05)
    assert d.action == DecisionAction.STAY, "late cue must not TAKE"
    assert d.camera_id == "CAM-HOST"


# ---- manual command surface -------------------------------------------------

def test_manual_hold_leaves_camera_and_bumps_mode():
    s = DirectorSession(current_camera="CAM-HOST")
    d = s.on_manual("HOLD", NOW)
    assert d.action == DecisionAction.STAY
    assert d.camera_id == "CAM-HOST"
    assert d.mode_revision == 1
    assert s.state.mode == Mode.HOLD


def test_manual_take_proposes_but_requires_ack_to_commit_current_camera():
    s = DirectorSession(current_camera="CAM-HOST")
    d = s.on_manual("TAKE CAM-GUEST", NOW)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-GUEST"
    # Pending ACK slot open; current_camera has NOT changed yet.
    assert s.state.current_camera == "CAM-HOST"
    assert s.pending_ack is not None
    assert s.pending_ack["seq"] == d.decision_seq


def test_manual_take_requires_camera_id():
    s = DirectorSession(current_camera="CAM-HOST")
    with pytest.raises(ValueError):
        s.on_manual("TAKE", NOW)


def test_manual_slate_issues_slate_and_needs_ack():
    s = DirectorSession(current_camera="CAM-HOST")
    d = s.on_manual("SLATE", NOW)
    assert d.action == DecisionAction.SLATE
    assert d.camera_id is None
    assert s.pending_ack is not None


def test_unknown_manual_raises():
    s = DirectorSession()
    with pytest.raises(ValueError):
        s.on_manual("SNAP", NOW)


# ---- ACK handling -----------------------------------------------------------

def test_ack_applied_true_commits_current_camera():
    s = DirectorSession(current_camera="CAM-HOST")
    d = s.on_manual("TAKE CAM-GUEST", NOW)
    s.on_ack(d.decision_seq, applied=True, now=NOW + 0.05)
    assert s.state.current_camera == "CAM-GUEST"
    assert s.pending_ack is None


def test_ack_applied_false_leaves_current_camera_unchanged():
    s = DirectorSession(current_camera="CAM-HOST")
    d = s.on_manual("TAKE CAM-GUEST", NOW)
    s.on_ack(d.decision_seq, applied=False, now=NOW + 0.05)
    assert s.state.current_camera == "CAM-HOST"
    assert s.pending_ack is None


def test_ack_for_superseded_seq_is_ignored():
    s = DirectorSession(current_camera="CAM-HOST")
    s.on_manual("TAKE CAM-GUEST", NOW)     # seq=1
    d2 = s.on_manual("TAKE CAM-WIDE", NOW)  # seq=2 (supersedes)
    # ACK for seq=1 arrives late
    s.on_ack(decision_seq=1, applied=True, now=NOW + 0.1)
    assert s.state.current_camera == "CAM-HOST", "stale ACK must not commit"
    # ACK for seq=2 works.
    s.on_ack(d2.decision_seq, applied=True, now=NOW + 0.2)
    assert s.state.current_camera == "CAM-WIDE"


# ---- speech pipeline & reconnect --------------------------------------------

def test_speech_down_blocks_automatic_take():
    s = DirectorSession(current_camera="CAM-HOST")
    s.on_speech_down()
    d = s.on_cue(_now_cue(), _cams(), NOW)
    assert d.action == DecisionAction.STAY, "auto TAKE must be blocked while paused"


def test_manual_take_still_works_when_speech_is_down():
    s = DirectorSession(current_camera="CAM-HOST")
    s.on_speech_down()
    d = s.on_manual("TAKE CAM-GUEST", NOW)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-GUEST"
    # Also unpauses auto per manual override.
    assert s.auto_paused is False


def test_speech_up_alone_does_not_resume_auto():
    s = DirectorSession(current_camera="CAM-HOST")
    s.on_speech_down()
    s.on_speech_up()
    assert s.auto_paused is True, "RESUME_AUTO must be explicit"
    d = s.on_cue(_now_cue(mode_revision=s.mode_revision), _cams(), NOW)
    assert d.action == DecisionAction.STAY


def test_resume_auto_after_speech_up_reenables_takes():
    s = DirectorSession(current_camera="CAM-HOST")
    s.on_speech_down()
    s.on_speech_up()
    s.on_manual("RESUME_AUTO", NOW)      # bumps mode
    d = s.on_cue(_now_cue(mode_revision=s.mode_revision), _cams(), NOW + 0.1)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-GUEST"


def test_reconnect_pauses_auto_and_bumps_mode():
    s = DirectorSession(current_camera="CAM-HOST")
    rev0 = s.mode_revision
    s.on_reconnect()
    assert s.mode_revision == rev0 + 1
    assert s.auto_paused is True
    # A pre-reconnect cue is rejected as stale.
    d = s.on_cue(_now_cue(mode_revision=rev0), _cams(), NOW)
    assert d.action == DecisionAction.STAY
    assert "stale mode_revision" in d.reason


# ---- safety failover survives HOLD -----------------------------------------

def test_unhealthy_current_during_hold_still_failovers_to_wide():
    s = DirectorSession(current_camera="CAM-HOST")
    s.on_manual("HOLD", NOW)  # rev -> 1
    d = s.on_cue(_now_cue(mode_revision=s.mode_revision),
                 _cams(host_healthy=False), NOW + 0.05)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-WIDE"


# ---- record shape sanity ----------------------------------------------------

def test_session_decision_is_dataclass_with_expected_fields():
    s = DirectorSession()
    d = s.on_manual("HOLD", NOW)
    assert isinstance(d, SessionDecision)
    for f in ("action", "camera_id", "reason", "decision_seq", "mode_revision"):
        assert hasattr(d, f)
