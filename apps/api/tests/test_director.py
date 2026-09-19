"""Unit tests for cue_api.policy.director (deterministic directing).

Every rule from the v3 plan "Directing logic C owns" is exercised:
- manual HOLD beats late AI decisions but still permits safety failover
- only NOW + single resolved target may TAKE a named guest camera
- named TAKE requires fresh confirmed identity (<=IDENTITY_MAX_AGE_S)
- otherwise healthy wide, else SLATE
- role_based flag skips identity check and uses a roster map
- scope=group -> wide; FUTURE/PAST/NEGATED/UNCERTAIN -> stay
- minimum shot MIN_SHOT_S, with a same-utterance correction exception
- cue older than CUE_LIFETIME_S rejected as stale
- every Decision carries a non-empty reason string
"""
from __future__ import annotations

import pytest

from cue_api.policy.director import (
    CUE_LIFETIME_S,
    IDENTITY_MAX_AGE_S,
    MIN_SHOT_S,
    Decision,
    DecisionAction,
    Mode,
    State,
    decide,
)
from cue_api.semantics.parser import Action, Cue, Intent, Scope, TemporalIntent

NOW = 1000.0


def cams(**overrides):
    """Three-camera stack: HOST/GUEST/WIDE. Override any field per camera."""
    base = {
        "CAM-HOST": {
            "role": "host", "healthy": True, "epoch": 1,
            "confirmed_guest_ids": [], "evidence_age_s": 999.0,
        },
        "CAM-GUEST": {
            "role": "guest", "healthy": True, "epoch": 1,
            "confirmed_guest_ids": ["sarah"], "evidence_age_s": 0.4,
        },
        "CAM-WIDE": {
            "role": "wide", "healthy": True, "epoch": 1,
            "confirmed_guest_ids": [], "evidence_age_s": 999.0,
        },
    }
    for cid, patch in overrides.items():
        base[cid] = {**base[cid], **patch}
    return base


def now_cue(**kw):
    defaults = {
        "target_guest_ids": ["sarah"],
        "scope": Scope.SINGLE,
        "intent": Intent.INTRODUCE,
        "temporal_intent": TemporalIntent.NOW,
        "action": Action.SHOW,
        "evidence_text": "please welcome Sarah",
        "utterance_id": "utt-1",
        "created_at": NOW - 0.2,
    }
    defaults.update(kw)
    return Cue(**defaults)


def base_state(**kw):
    defaults = {
        "current_camera": "CAM-HOST",
        "last_cut_time": NOW - 10.0,
        "mode": Mode.AUTO,
        "hold_until": None,
        "last_utterance_id": "prior-utt",
    }
    defaults.update(kw)
    return State(**defaults)


# --- named TAKE path ---------------------------------------------------------

def test_now_single_healthy_fresh_identity_takes_guest():
    d = decide(now_cue(), cams(), base_state(), NOW)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-GUEST"


def test_stale_identity_falls_back_to_wide():
    d = decide(
        now_cue(),
        cams(**{"CAM-GUEST": {"evidence_age_s": IDENTITY_MAX_AGE_S + 0.1}}),
        base_state(),
        NOW,
    )
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-WIDE"


def test_target_not_visible_falls_back_to_wide():
    d = decide(
        now_cue(),
        cams(**{"CAM-GUEST": {"confirmed_guest_ids": []}}),
        base_state(),
        NOW,
    )
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-WIDE"


def test_target_unusable_and_no_wide_returns_slate():
    stack = cams(**{
        "CAM-GUEST": {"confirmed_guest_ids": []},
        "CAM-WIDE": {"healthy": False},
        "CAM-HOST": {"healthy": False},
    })
    d = decide(now_cue(), stack, base_state(current_camera=None), NOW)
    assert d.action == DecisionAction.SLATE
    assert d.camera_id is None


# --- manual HOLD -------------------------------------------------------------

def test_manual_hold_mode_blocks_named_take():
    st = base_state(mode=Mode.HOLD, current_camera="CAM-HOST")
    d = decide(now_cue(), cams(), st, NOW)
    assert d.action == DecisionAction.STAY
    assert d.camera_id == "CAM-HOST"
    assert "HOLD" in d.reason


def test_manual_hold_still_failovers_when_current_unhealthy():
    st = base_state(mode=Mode.HOLD, current_camera="CAM-HOST")
    d = decide(now_cue(), cams(**{"CAM-HOST": {"healthy": False}}), st, NOW)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-WIDE"


def test_hold_until_in_future_blocks_take():
    st = base_state(hold_until=NOW + 2.0)
    d = decide(now_cue(), cams(), st, NOW)
    assert d.action == DecisionAction.STAY


def test_hold_until_expired_allows_take():
    st = base_state(hold_until=NOW - 0.1)
    d = decide(now_cue(), cams(), st, NOW)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-GUEST"


# --- non-NOW temporal intents ------------------------------------------------

@pytest.mark.parametrize("ti", [
    TemporalIntent.FUTURE,
    TemporalIntent.PAST,
    TemporalIntent.NEGATED,
    TemporalIntent.UNCERTAIN,
])
def test_non_now_temporal_intent_stays(ti):
    cue = now_cue(temporal_intent=ti, action=Action.HOLD)
    d = decide(cue, cams(), base_state(), NOW)
    assert d.action == DecisionAction.STAY
    assert d.camera_id == "CAM-HOST"


# --- scope -------------------------------------------------------------------

def test_scope_group_takes_wide():
    cue = now_cue(
        scope=Scope.GROUP,
        target_guest_ids=["sarah", "daniel"],
        action=Action.WIDE,
    )
    d = decide(cue, cams(), base_state(), NOW)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-WIDE"


def test_scope_group_no_wide_stays_on_healthy_current():
    cue = now_cue(
        scope=Scope.GROUP,
        target_guest_ids=["sarah", "daniel"],
        action=Action.WIDE,
    )
    d = decide(
        cue,
        cams(**{"CAM-WIDE": {"healthy": False}}),
        base_state(current_camera="CAM-HOST"),
        NOW,
    )
    assert d.action == DecisionAction.STAY
    assert d.camera_id == "CAM-HOST"


# --- staleness ---------------------------------------------------------------

def test_stale_cue_rejected():
    cue = now_cue(created_at=NOW - (CUE_LIFETIME_S + 0.5))
    d = decide(cue, cams(), base_state(), NOW)
    assert d.action == DecisionAction.STAY
    assert "stale" in d.reason.lower()


def test_fresh_cue_within_lifetime_allows_take():
    cue = now_cue(created_at=NOW - 1.0)
    d = decide(cue, cams(), base_state(), NOW)
    assert d.action == DecisionAction.TAKE


# --- minimum shot & correction override --------------------------------------

def _two_guest_cams():
    return cams(**{
        "CAM-HOST": {"confirmed_guest_ids": ["daniel"], "evidence_age_s": 0.4},
        "CAM-GUEST": {"confirmed_guest_ids": ["sarah"], "evidence_age_s": 0.4},
    })


def test_min_shot_blocks_recut_within_window():
    st = base_state(
        current_camera="CAM-GUEST",
        last_cut_time=NOW - 1.0,
        last_utterance_id="prior-utt",
    )
    cue = now_cue(target_guest_ids=["daniel"], utterance_id="utt-new")
    d = decide(cue, _two_guest_cams(), st, NOW)
    assert d.action == DecisionAction.STAY
    assert d.camera_id == "CAM-GUEST"
    assert "min shot" in d.reason.lower()


def test_same_utterance_correction_allows_recut_within_window():
    st = base_state(
        current_camera="CAM-GUEST",
        last_cut_time=NOW - 1.0,
        last_utterance_id="utt-same",
    )
    cue = now_cue(target_guest_ids=["daniel"], utterance_id="utt-same")
    d = decide(cue, _two_guest_cams(), st, NOW)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-HOST"
    assert "correction" in d.reason.lower()


def test_recut_after_min_shot_window_allowed():
    st = base_state(
        current_camera="CAM-GUEST",
        last_cut_time=NOW - (MIN_SHOT_S + 0.1),
        last_utterance_id="prior-utt",
    )
    cue = now_cue(target_guest_ids=["daniel"], utterance_id="utt-new")
    d = decide(cue, _two_guest_cams(), st, NOW)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-HOST"


# --- role-based fallback -----------------------------------------------------

def test_role_based_skips_identity_check():
    stack = cams(**{"CAM-GUEST": {"confirmed_guest_ids": [], "evidence_age_s": 999.0}})
    d = decide(
        now_cue(),
        stack,
        base_state(),
        NOW,
        role_based=True,
        role_map={"sarah": "CAM-GUEST"},
    )
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-GUEST"
    assert "role_based" in d.reason


def test_role_based_mapped_camera_unhealthy_falls_back_to_wide():
    d = decide(
        now_cue(),
        cams(**{"CAM-GUEST": {"healthy": False}}),
        base_state(),
        NOW,
        role_based=True,
        role_map={"sarah": "CAM-GUEST"},
    )
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-WIDE"


# --- misc --------------------------------------------------------------------

def test_no_cue_stays_on_healthy_current():
    d = decide(None, cams(), base_state(current_camera="CAM-HOST"), NOW)
    assert d.action == DecisionAction.STAY
    assert d.camera_id == "CAM-HOST"


# --- guest_ready gate --------------------------------------------------------

def test_guest_not_ready_falls_back_to_wide_with_named_reason():
    stack = cams(**{"CAM-GUEST": {"guest_ready": False}})
    d = decide(now_cue(), stack, base_state(), NOW)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-WIDE"
    assert "guest not ready" in d.reason.lower()


def test_guest_ready_true_still_takes_guest_camera():
    stack = cams(**{"CAM-GUEST": {"guest_ready": True}})
    d = decide(now_cue(), stack, base_state(), NOW)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-GUEST"


def test_guest_ready_absent_defaults_true():
    stack = cams()  # no guest_ready key at all
    for cam in stack.values():
        assert "guest_ready" not in cam
    d = decide(now_cue(), stack, base_state(), NOW)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-GUEST"


def test_every_decision_carries_reason():
    outputs = [
        decide(now_cue(), cams(), base_state(), NOW),
        decide(None, cams(), base_state(), NOW),
        decide(now_cue(), cams(), base_state(mode=Mode.HOLD), NOW),
        decide(
            now_cue(temporal_intent=TemporalIntent.FUTURE, action=Action.HOLD),
            cams(),
            base_state(),
            NOW,
        ),
    ]
    for d in outputs:
        assert isinstance(d, Decision)
        assert isinstance(d.reason, str) and d.reason.strip()
