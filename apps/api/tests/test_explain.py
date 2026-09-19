"""Every reason string the C-lane emits maps to a plain sentence."""
from __future__ import annotations

from cue_api.policy.explain import plain_reason
from cue_api.policy.log import DecisionRecord


def _rec(
    *,
    action: str = "STAY",
    camera_id: str | None = "CAM-HOST",
    reason: str = "",
    targets: list[str] | None = None,
    temporal_intent: str = "",
    scope: str = "single",
    source: str = "LIVE",
) -> DecisionRecord:
    return DecisionRecord(
        at=0.0,
        decision_seq=1,
        mode_revision=0,
        action=action,
        camera_id=camera_id,
        reason=reason,
        transcript_span=None,
        cue_summary=({
            "target_guest_ids": list(targets or []),
            "scope": scope,
            "temporal_intent": temporal_intent,
            "action_pre_validate": "SHOW",
        } if targets is not None or temporal_intent else None),
        cameras_considered=[],
        latencies_ms={},
        source=source,
    )


# ---- manual commands -------------------------------------------------------

def test_manual_hold():
    s = plain_reason(_rec(reason="manual HOLD"))
    assert s == "You took over. CUE is waiting."


def test_manual_resume_auto():
    s = plain_reason(_rec(reason="manual RESUME_AUTO"))
    assert s == "CUE is directing again."


def test_manual_take_camera():
    s = plain_reason(_rec(action="TAKE", camera_id="CAM-GUEST",
                          reason="manual TAKE CAM-GUEST"))
    assert s == "You cut to the guest camera."


def test_manual_slate():
    s = plain_reason(_rec(action="SLATE", camera_id=None, reason="manual SLATE"))
    assert s == "You cut to the slate."


# ---- late-cue rejection ----------------------------------------------------

def test_stale_mode_revision():
    s = plain_reason(_rec(reason="cue from stale mode_revision 0 (current 1)"))
    assert s == "Ignoring a late suggestion. Your last command wins."


# ---- camera-state gates ----------------------------------------------------

def test_camera_state_missing():
    s = plain_reason(_rec(reason="camera state missing"))
    assert "camera check" in s.lower()


def test_camera_state_expired():
    s = plain_reason(_rec(reason="camera state expired (2.00s > 1.00s)"))
    assert "fresh camera check" in s.lower()


# ---- guest_ready gate ------------------------------------------------------

def test_guest_not_ready_falls_back_to_wide():
    s = plain_reason(_rec(action="TAKE", camera_id="CAM-WIDE",
                          reason="guest not ready"))
    assert s == "Guest isn't ready yet, so showing the wide shot."


def test_guest_not_ready_no_wide_slate():
    s = plain_reason(_rec(action="SLATE", camera_id=None,
                          reason="guest not ready; no healthy wide -> slate"))
    assert "no safe view" in s.lower()


# ---- temporal-intent stays -------------------------------------------------

def test_future_mention_names_the_guest():
    s = plain_reason(_rec(reason="temporal_intent=FUTURE, not NOW",
                          targets=["sarah"], temporal_intent="FUTURE"))
    assert s == "Staying on the host. Sarah is joining later."


def test_past_reference():
    s = plain_reason(_rec(reason="temporal_intent=PAST, not NOW",
                          targets=["daniel"], temporal_intent="PAST"))
    assert "past" in s.lower() and "Daniel" in s


def test_negated():
    s = plain_reason(_rec(reason="temporal_intent=NEGATED, not NOW",
                          targets=["sarah"], temporal_intent="NEGATED"))
    assert "said not to" in s.lower()


def test_uncertain():
    s = plain_reason(_rec(reason="temporal_intent=UNCERTAIN, not NOW",
                          targets=[], temporal_intent="UNCERTAIN"))
    assert "not sure" in s.lower()


# ---- cue lifecycle ---------------------------------------------------------

def test_cue_stale():
    s = plain_reason(_rec(reason="cue stale (4.20s > 3.0s)"))
    assert "too long" in s.lower()


def test_no_cue_wide_fallback():
    s = plain_reason(_rec(action="TAKE", camera_id="CAM-WIDE",
                          reason="no cue; current unhealthy -> wide fallback"))
    assert s == "Nothing to cut on. Showing the wide shot."


def test_no_cue_slate():
    s = plain_reason(_rec(action="SLATE", camera_id=None,
                          reason="no cue; no healthy view -> slate"))
    assert "nothing to cut on" in s.lower() and "slate" in s.lower()


# ---- min-shot / correction -------------------------------------------------

def test_min_shot_held():
    s = plain_reason(_rec(reason="min shot 2.5s not met (1.20s); "
                                 "held CAM-GUEST. Would have taken: fresh identity"))
    assert "beat longer" in s.lower()


def test_correction_recut_names_new_target():
    s = plain_reason(_rec(
        action="TAKE", camera_id="CAM-GUEST",
        reason="role_based: daniel -> CAM-GUEST (correction re-cut at 0.95s)",
        targets=["daniel"], temporal_intent="NOW",
    ))
    assert s == "Correction. CUE cut to Daniel instead."


# ---- named TAKEs -----------------------------------------------------------

def test_named_take_role_based_says_cue_and_flips_pronoun_for_female_guest():
    s = plain_reason(_rec(
        action="TAKE", camera_id="CAM-GUEST",
        reason="role_based: sarah -> CAM-GUEST",
        targets=["sarah"], temporal_intent="NOW",
    ))
    assert s == "CUE cut to Sarah. She was just invited up."


def test_named_take_role_based_uses_male_pronoun_for_daniel():
    s = plain_reason(_rec(
        action="TAKE", camera_id="CAM-GUEST",
        reason="role_based: daniel -> CAM-GUEST",
        targets=["daniel"], temporal_intent="NOW",
    ))
    assert s == "CUE cut to Daniel. He was just invited up."


def test_named_take_fresh_identity():
    s = plain_reason(_rec(
        action="TAKE", camera_id="CAM-GUEST",
        reason="fresh identity sarah on CAM-GUEST (age 0.40s)",
        targets=["sarah"], temporal_intent="NOW",
    ))
    assert s == "CUE cut to Sarah. She was just invited up."


def test_manual_take_never_says_cue_and_always_says_you():
    s_manual = plain_reason(_rec(
        action="TAKE", camera_id="CAM-GUEST",
        reason="manual TAKE CAM-GUEST",
    ))
    s_cue    = plain_reason(_rec(
        action="TAKE", camera_id="CAM-GUEST",
        reason="role_based: sarah -> CAM-GUEST",
        targets=["sarah"], temporal_intent="NOW",
    ))
    assert s_manual.startswith("You cut to")
    assert s_cue.startswith("CUE cut to")
    assert "You" not in s_cue.split()  # never mixed
    assert "CUE" not in s_manual.split()


def test_target_unusable_wide():
    s = plain_reason(_rec(
        action="TAKE", camera_id="CAM-WIDE",
        reason="target sarah unusable -> wide",
        targets=["sarah"], temporal_intent="NOW",
    ))
    assert s == "Sarah's camera isn't usable, so showing the wide shot."


def test_target_unusable_slate():
    s = plain_reason(_rec(
        action="SLATE", camera_id=None,
        reason="target sarah unusable; no healthy wide -> slate",
        targets=["sarah"], temporal_intent="NOW",
    ))
    assert "no usable view" in s.lower()


def test_safety_failover_wide():
    s = plain_reason(_rec(
        action="TAKE", camera_id="CAM-WIDE",
        reason="target sarah unusable -> wide; current unhealthy, safety failover",
        targets=["sarah"], temporal_intent="NOW",
    ))
    # "unusable" already matched first, so we get the more informative sentence.
    assert "wide shot" in s.lower()


# ---- group scope -----------------------------------------------------------

def test_group_scope_wide():
    s = plain_reason(_rec(
        action="TAKE", camera_id="CAM-WIDE",
        reason="group scope -> wide",
        targets=["sarah", "daniel"], temporal_intent="NOW", scope="group",
    ))
    assert s == "Two people up. Showing the wide shot."


def test_group_scope_no_wide_stays():
    s = plain_reason(_rec(
        action="STAY", camera_id="CAM-HOST",
        reason="group scope but no healthy wide",
        targets=["sarah", "daniel"], temporal_intent="NOW", scope="group",
    ))
    assert "group" in s.lower()


# ---- unknown reason falls back gracefully ---------------------------------

def test_unknown_stay_falls_back_to_generic():
    s = plain_reason(_rec(action="STAY", reason="some future reason C hasn't seen"))
    assert s == "Staying on the current shot."


def test_unknown_take_falls_back_to_camera_word():
    s = plain_reason(_rec(action="TAKE", camera_id="CAM-HOST",
                          reason="entirely new reason string"))
    assert s == "Cutting to the host."
