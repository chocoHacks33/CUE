"""End-to-end tests for cue_api.c_lane.CLane.

Replays real Deepgram fixtures through the composed CLane (assembler +
queue + fake parser + session + logger) and asserts the emitted
DecisionRecord stream matches the scripted demo timeline.

Offline only. parse_fn is a fake keyed on transcript text.
"""
from __future__ import annotations

import json
from pathlib import Path

from cue_api.c_lane import CLane
from cue_api.policy.log import DecisionLogger
from cue_api.semantics.parser import Action, Cue, Intent, Scope, TemporalIntent

FIXTURES = Path(__file__).parent / "fixtures" / "deepgram"


# ---- fixture loader + fake parser ------------------------------------------

def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _fake_parse(text: str) -> tuple[Cue, float]:
    """Text -> Cue mapping matching the six fixture utterances."""
    t = text.lower()
    common = dict(evidence_text=text)
    if "after the break" in t or "joins us after" in t:
        return Cue(
            target_guest_ids=["sarah"], scope=Scope.SINGLE,
            intent=Intent.MENTION, temporal_intent=TemporalIntent.FUTURE,
            action=Action.HOLD, **common,
        ), 5.0
    if "actually, daniel" in t:
        return Cue(
            target_guest_ids=["daniel"], scope=Scope.SINGLE,
            intent=Intent.INTRODUCE, temporal_intent=TemporalIntent.NOW,
            action=Action.SHOW, **common,
        ), 5.0
    if ("please welcome sarah" in t or "sarah tan" in t
            or "sarah, please" in t or "sarah please" in t
            or "come up" in t):
        return Cue(
            target_guest_ids=["sarah"], scope=Scope.SINGLE,
            intent=Intent.INTRODUCE, temporal_intent=TemporalIntent.NOW,
            action=Action.SHOW, **common,
        ), 5.0
    return Cue(
        target_guest_ids=[], scope=Scope.NONE, intent=Intent.NONE,
        temporal_intent=TemporalIntent.UNCERTAIN, action=Action.HOLD,
        **common,
    ), 5.0


def _cams(*, guest_healthy: bool = True) -> dict:
    return {
        "CAM-HOST":  {"role": "host",  "healthy": True, "epoch": 1,
                      "confirmed_guest_ids": [], "evidence_age_s": 999.0,
                      "guest_ready": True},
        "CAM-GUEST": {"role": "guest", "healthy": guest_healthy, "epoch": 1,
                      "confirmed_guest_ids": ["sarah"], "evidence_age_s": 0.4,
                      "guest_ready": True},
        "CAM-WIDE":  {"role": "wide",  "healthy": True, "epoch": 1,
                      "confirmed_guest_ids": [], "evidence_age_s": 999.0,
                      "guest_ready": True},
    }


def _make_lane(**kw):
    emitted: list = []
    defaults = {
        "parse_fn": _fake_parse,
        "emit": emitted.append,
        "role_based": True,
        "role_map": {"sarah": "CAM-GUEST", "daniel": "CAM-GUEST"},
        "camera_state_max_age_s": 1.0,
        "initial_camera": "CAM-HOST",
    }
    defaults.update(kw)
    lane = CLane(**defaults)
    return lane, emitted


def _replay(lane: CLane, fixture_name: str, *,
            camera_at: float = 0.0, guest_healthy: bool = True) -> None:
    """Feed every step of a Deepgram fixture through the lane."""
    fix = _load_fixture(fixture_name)
    lane.on_camera_state(_cams(guest_healthy=guest_healthy), now=camera_at)
    for step in fix["steps"]:
        if step.get("kind") == "reset":
            lane.on_reconnect(step["new_epoch"])
            continue
        # Refresh camera state each message so it never goes stale in
        # the fast-fixture tests.
        lane.on_camera_state(_cams(guest_healthy=guest_healthy), now=step["at"])
        lane.on_transcript_message(step["message"], step["at"])


# ---- scripted demo timeline via fixtures -----------------------------------

def test_future_mention_fixture_emits_only_stay():
    lane, emitted = _make_lane()
    _replay(lane, "future_mention")
    actions = [r.action for r in emitted]
    assert emitted, "expected at least one decision"
    assert all(a == "STAY" for a in actions), actions
    reasons = [r.reason for r in emitted]
    assert any("temporal_intent=FUTURE" in r for r in reasons)


def test_simple_intro_fixture_emits_take_guest():
    lane, emitted = _make_lane()
    _replay(lane, "simple_intro")
    # A single named TAKE at the end; no earlier TAKE.
    takes = [r for r in emitted if r.action == "TAKE"]
    assert len(takes) == 1, [r.action for r in emitted]
    assert takes[0].camera_id == "CAM-GUEST"
    assert takes[0].mode_revision == 0
    assert takes[0].decision_seq >= 1


def test_correction_fixture_emits_take_daniel_not_sarah():
    lane, emitted = _make_lane()
    _replay(lane, "correction_split")
    takes = [r for r in emitted if r.action == "TAKE"]
    # Exactly ONE final target from the whole utterance.
    assert len(takes) == 1
    # And it's the corrected one (daniel maps to CAM-GUEST via role_map).
    assert "daniel" in takes[0].reason
    assert takes[0].camera_id == "CAM-GUEST"


def test_long_pause_endpoint_fixture_emits_take_sarah():
    lane, emitted = _make_lane()
    _replay(lane, "long_pause_endpoint")
    takes = [r for r in emitted if r.action == "TAKE"]
    assert len(takes) == 1
    assert takes[0].camera_id == "CAM-GUEST"


def test_reconnect_fixture_drops_pre_reset_utterance():
    lane, emitted = _make_lane()
    _replay(lane, "reconnect_epoch_change")
    # on_reconnect sets auto_paused=True (RESUME_AUTO is explicit). So the
    # post-reset "Daniel, welcome." utterance produces a STAY, not a TAKE.
    # The assertion for this test is: no TAKE happens across the whole
    # replay -- the pre-reset assembly is discarded, the post-reset one
    # is held pending explicit resume.
    assert all(r.action != "TAKE" for r in emitted), [r.action for r in emitted]
    # And every emitted decision under mode_revision >= 1 (bumped by
    # on_reconnect).
    assert emitted and any(r.mode_revision >= 1 for r in emitted)


# ---- explicit rules the user called out ------------------------------------

def test_provisional_text_never_emits_a_take():
    lane, emitted = _make_lane()
    # Only interim (is_final=false) messages, no endpoint.
    lane.on_camera_state(_cams(), now=0.0)
    lane.on_transcript_message({
        "audio_epoch": 1, "type": "Results",
        "start": 0.0, "duration": 0.4,
        "is_final": False, "speech_final": False,
        "channel": {"alternatives": [{"transcript": "please welcome Sarah"}]},
    }, now=0.4)
    lane.on_transcript_message({
        "audio_epoch": 1, "type": "Results",
        "start": 0.0, "duration": 0.8,
        "is_final": False, "speech_final": False,
        "channel": {"alternatives": [{"transcript": "please welcome Sarah Tan"}]},
    }, now=0.8)
    assert emitted == [], "provisional-only must not emit a decision"


def test_camera_state_older_than_expiry_blocks_named_take():
    lane, emitted = _make_lane(camera_state_max_age_s=0.5)
    # Stage a stale camera snapshot 2 seconds before the utterance.
    lane.on_camera_state(_cams(), now=0.0)
    # Now push a full utterance whose semantic action would be a named
    # TAKE. Camera state has expired (2.0s > 0.5s).
    lane.on_transcript_message({
        "audio_epoch": 1, "type": "Results",
        "start": 0.0, "duration": 1.5,
        "is_final": True, "speech_final": True,
        "channel": {"alternatives": [{
            "transcript": "Please welcome Sarah Tan.",
        }]},
    }, now=2.0)
    assert len(emitted) == 1
    rec = emitted[0]
    assert rec.action == "STAY"
    assert "camera state expired" in rec.reason
    assert rec.camera_id == "CAM-HOST"  # kept, not swapped


def test_tick_flushes_missing_endpoint():
    lane, emitted = _make_lane(assembler_timeout_s=1.0)
    lane.on_camera_state(_cams(), now=0.0)
    # Send an is_final=true segment but NO speech_final and NO
    # UtteranceEnd. Deepgram just goes quiet.
    lane.on_transcript_message({
        "audio_epoch": 1, "type": "Results",
        "start": 0.0, "duration": 0.9,
        "is_final": True, "speech_final": False,
        "channel": {"alternatives": [{"transcript": "Please welcome Sarah Tan."}]},
    }, now=0.9)
    assert emitted == [], "no endpoint yet, so no decision yet"
    # Refresh cameras, then tick past the assembler timeout.
    lane.on_camera_state(_cams(), now=2.5)
    lane.tick(now=2.5)
    takes = [r for r in emitted if r.action == "TAKE"]
    assert len(takes) == 1
    assert takes[0].camera_id == "CAM-GUEST"


# ---- integration with logger + emit + session state ------------------------

def test_emit_and_logger_receive_the_same_records(tmp_path):
    log = DecisionLogger(tmp_path / "d.jsonl")
    emitted: list = []
    lane = CLane(
        parse_fn=_fake_parse,
        emit=emitted.append,
        logger=log,
        role_based=True,
        role_map={"sarah": "CAM-GUEST"},
        initial_camera="CAM-HOST",
    )
    _replay(lane, "simple_intro")
    rows = log.read_all()
    assert len(rows) == len(emitted)
    for r, rec in zip(rows, emitted, strict=True):
        assert r["decision_seq"] == rec.decision_seq
        assert r["action"] == rec.action
        assert r["camera_id"] == rec.camera_id


def test_manual_hold_bumps_mode_and_late_cue_is_rejected():
    lane, emitted = _make_lane()
    lane.on_camera_state(_cams(), now=1.0)
    # Producer HOLDs (rev -> 1).
    lane.on_manual("HOLD", now=1.0)
    # A message stream that would produce a named TAKE arrives after HOLD.
    # Its utterance is submitted at the CURRENT mode_revision, so it
    # would not be "stale" -- but the session is in HOLD mode and will
    # STAY (safety failover still runs). This is the "manual HOLD beats
    # AI" rule in action.
    lane.on_camera_state(_cams(), now=1.1)
    lane.on_transcript_message({
        "audio_epoch": 1, "type": "Results",
        "start": 0.0, "duration": 1.0,
        "is_final": True, "speech_final": True,
        "channel": {"alternatives": [{"transcript": "Please welcome Sarah Tan."}]},
    }, now=1.1)
    actions = [r.action for r in emitted]
    assert "TAKE" not in actions
    # The manual HOLD line is present.
    assert any(r.reason == "manual HOLD" for r in emitted)


def test_ack_applied_true_commits_current_camera():
    lane, emitted = _make_lane()
    lane.on_camera_state(_cams(), now=0.0)
    lane.on_manual("TAKE CAM-GUEST", now=0.0)
    take = emitted[-1]
    assert take.action == "TAKE"
    lane.on_ack(take.decision_seq, applied=True, now=0.05)
    # The next STAY / on_cue path should now show CAM-GUEST as current.
    lane.on_transcript_message({
        "audio_epoch": 1, "type": "Results",
        "start": 0.0, "duration": 0.5,
        "is_final": True, "speech_final": True,
        "channel": {"alternatives": [{"transcript": "Sarah joins us after the break."}]},
    }, now=1.0)
    # Latest emitted is a STAY (FUTURE), keeping CAM-GUEST.
    stays = [r for r in emitted if r.action == "STAY"]
    assert stays and stays[-1].camera_id == "CAM-GUEST"


def test_on_reconnect_clears_queue_and_bumps_mode():
    lane, emitted = _make_lane()
    lane.on_camera_state(_cams(), now=0.0)
    rev0 = lane.mode_revision
    # Submit a half-baked utterance (only interim), then reconnect.
    lane.on_transcript_message({
        "audio_epoch": 1, "type": "Results",
        "start": 0.0, "duration": 0.3,
        "is_final": False, "speech_final": False,
        "channel": {"alternatives": [{"transcript": "please"}]},
    }, now=0.3)
    assert emitted == []
    lane.on_reconnect(new_epoch=2)
    assert lane.mode_revision == rev0 + 1
    assert lane.audio_epoch == 2
    # A new utterance under the new epoch still produces STAY: reconnect
    # pauses AUTO until RESUME_AUTO is explicitly issued.
    lane.on_camera_state(_cams(), now=1.5)
    lane.on_transcript_message({
        "audio_epoch": 2, "type": "Results",
        "start": 0.0, "duration": 1.0,
        "is_final": True, "speech_final": True,
        "channel": {"alternatives": [{"transcript": "Please welcome Sarah Tan."}]},
    }, now=1.5)
    assert all(r.action != "TAKE" for r in emitted)
    # After RESUME_AUTO, the next utterance can TAKE.
    lane.on_manual("RESUME_AUTO", now=1.6)
    lane.on_camera_state(_cams(), now=2.0)
    lane.on_transcript_message({
        "audio_epoch": 2, "type": "Results",
        "start": 0.0, "duration": 1.0,
        "is_final": True, "speech_final": True,
        "channel": {"alternatives": [{"transcript": "Please welcome Sarah Tan."}]},
    }, now=2.0)
    takes = [r for r in emitted if r.action == "TAKE"]
    assert takes and takes[-1].camera_id == "CAM-GUEST"
