"""Offline pipeline test: fixture -> Assembler -> fake parser -> decide().

No network, no LLM, no timers. Each scenario replays a Deepgram fixture
through the assembler, hand-maps the resulting FinalUtterance text to a
Cue (a stand-in for cue_api.semantics.parser.parse), and asserts on the
Decision returned by cue_api.policy.director.decide.

Six scenarios (per stage-1 prep):
  1. future mention                     -> STAY
  2. named intro, guest camera healthy  -> TAKE CAM-GUEST
  3. named intro, guest camera down     -> TAKE CAM-WIDE
  4. named intro under manual HOLD      -> STAY (late cue defeated)
  5. correction across two finals       -> exactly one final target, TAKE
  6. stale cue                          -> STAY (rejected)
"""
from __future__ import annotations

import json
from pathlib import Path

from cue_api.policy.director import (
    CUE_LIFETIME_S,
    Decision,
    DecisionAction,
    Mode,
    State,
    decide,
)
from cue_api.semantics.parser import Action, Cue, Intent, Scope, TemporalIntent
from cue_api.speech.assembler import Assembler, Event, FinalUtterance

FIXTURES = Path(__file__).parent / "fixtures" / "deepgram"


def run_fixture(name: str) -> list[Event]:
    fix = json.loads((FIXTURES / f"{name}.json").read_text())
    asm = Assembler(timeout_s=fix.get("timeout_s", 1.2),
                    audio_epoch=fix.get("audio_epoch", 1))
    events: list[Event] = []
    for step in fix["steps"]:
        if step.get("kind") == "reset":
            asm.reset(step["new_epoch"])
            continue
        events.extend(asm.feed(step["message"], step["at"]))
    return events


def only_final(events: list[Event]) -> FinalUtterance:
    finals = [e for e in events if isinstance(e, FinalUtterance)]
    assert len(finals) == 1, f"expected exactly one final, got {len(finals)}"
    return finals[0]


def fake_parse(final: FinalUtterance) -> Cue:
    """Stand-in for the real OpenAI parser. Pattern-matches fixture texts."""
    t = final.text.lower()
    common = {
        "utterance_id": final.utterance_id,
        "created_at": final.ended_at or 0.0,
        "evidence_text": final.text,
    }
    if "after the break" in t or "joins us after" in t:
        return Cue(target_guest_ids=["sarah"], scope=Scope.SINGLE,
                   intent=Intent.MENTION, temporal_intent=TemporalIntent.FUTURE,
                   action=Action.HOLD, **common)
    if "actually, daniel" in t:
        # Correction: final target is Daniel; earlier "Sarah" mention is dropped.
        return Cue(target_guest_ids=["daniel"], scope=Scope.SINGLE,
                   intent=Intent.INTRODUCE, temporal_intent=TemporalIntent.NOW,
                   action=Action.SHOW, **common)
    if "please welcome sarah" in t or "come up" in t or "sarah tan" in t:
        return Cue(target_guest_ids=["sarah"], scope=Scope.SINGLE,
                   intent=Intent.INTRODUCE, temporal_intent=TemporalIntent.NOW,
                   action=Action.SHOW, **common)
    return Cue(target_guest_ids=[], scope=Scope.NONE, intent=Intent.NONE,
               temporal_intent=TemporalIntent.UNCERTAIN, action=Action.HOLD,
               **common)


def cams(*, guest_healthy: bool = True, guest_targets: tuple[str, ...] = ("sarah",),
         host_targets: tuple[str, ...] = ()) -> dict[str, dict]:
    return {
        "CAM-HOST": {"role": "host", "healthy": True, "epoch": 1,
                     "confirmed_guest_ids": list(host_targets),
                     "evidence_age_s": 0.4 if host_targets else 999.0},
        "CAM-GUEST": {"role": "guest", "healthy": guest_healthy, "epoch": 1,
                      "confirmed_guest_ids": list(guest_targets),
                      "evidence_age_s": 0.4},
        "CAM-WIDE": {"role": "wide", "healthy": True, "epoch": 1,
                     "confirmed_guest_ids": [], "evidence_age_s": 999.0},
    }


def base_state(**kw) -> State:
    # last_cut_time set well in the past so the 2.5 s min-shot gate is not
    # what these scenarios are exercising -- the director's other tests
    # already cover it in test_director.py.
    defaults = {"current_camera": "CAM-HOST",
                "last_cut_time": -100.0,
                "mode": Mode.AUTO,
                "hold_until": None,
                "last_utterance_id": ""}
    defaults.update(kw)
    return State(**defaults)


# --- scenarios ----------------------------------------------------------------

def test_future_mention_stays():
    final = only_final(run_fixture("future_mention"))
    cue = fake_parse(final)
    assert cue.temporal_intent == TemporalIntent.FUTURE
    d = decide(cue, cams(), base_state(), now=final.ended_at + 0.1)
    assert d.action == DecisionAction.STAY
    assert isinstance(d, Decision)


def test_named_intro_takes_guest_camera_when_healthy():
    final = only_final(run_fixture("simple_intro"))
    cue = fake_parse(final)
    assert cue.temporal_intent == TemporalIntent.NOW
    assert cue.target_guest_ids == ["sarah"]
    d = decide(cue, cams(), base_state(), now=final.ended_at + 0.1)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-GUEST"


def test_named_intro_falls_back_to_wide_when_guest_camera_down():
    final = only_final(run_fixture("simple_intro"))
    cue = fake_parse(final)
    d = decide(cue, cams(guest_healthy=False), base_state(),
               now=final.ended_at + 0.1)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-WIDE"


def test_manual_hold_defeats_late_named_cue():
    final = only_final(run_fixture("simple_intro"))
    cue = fake_parse(final)
    state = base_state(mode=Mode.HOLD, current_camera="CAM-HOST")
    d = decide(cue, cams(), state, now=final.ended_at + 0.1)
    assert d.action == DecisionAction.STAY
    assert d.camera_id == "CAM-HOST"
    assert "HOLD" in d.reason


def test_correction_gives_exactly_one_final_target():
    events = run_fixture("correction_split")
    finals = [e for e in events if isinstance(e, FinalUtterance)]
    assert len(finals) == 1, "correction must not produce two premature finals"
    cue = fake_parse(finals[0])
    assert cue.target_guest_ids == ["daniel"], "final target must be the correction"
    # And directing takes the camera that actually shows Daniel.
    stack = cams(guest_targets=("daniel",))
    d = decide(cue, stack, base_state(), now=finals[0].ended_at + 0.1)
    assert d.action == DecisionAction.TAKE
    assert d.camera_id == "CAM-GUEST"


def test_stale_cue_is_rejected_by_director():
    final = only_final(run_fixture("simple_intro"))
    cue = fake_parse(final)
    # Simulate the cue arriving well after CUE_LIFETIME_S.
    now = (final.ended_at or 0.0) + CUE_LIFETIME_S + 1.0
    d = decide(cue, cams(), base_state(), now=now)
    assert d.action == DecisionAction.STAY
    assert "stale" in d.reason.lower()
