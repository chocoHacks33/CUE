"""Split-utterance correction and mode-revision rejection through CLane.

Deepgram is not called. We feed the assembler two ``Results`` frames
with ``speech_final=True`` on the second, mirroring what Deepgram would
produce for "Please welcome Sarah... actually, Daniel". Assembler joins
them into one FinalUtterance; SemanticQueue calls the injected parse_fn
which returns a Cue targeting only the final subject (Daniel). Result:
exactly one TAKE, exactly one decision_seq bump.

For the mode-revision rejection test, we simulate the producer pressing
HOLD, then a late cue coming in tagged with the *old* mode_revision.
DirectorSession must reject the late cue by mode_revision — the plan
calls this out as a non-negotiable safety property.
"""
from __future__ import annotations

import pytest

from cue_api.c_lane import CLane
from cue_api.policy.log import DecisionRecord
from cue_api.semantics.parser import (
    Action,
    Cue,
    Intent,
    Scope,
    TemporalIntent,
)

ROLE_MAP = {"sarah": "CAM-GUEST", "daniel": "CAM-GUEST"}


def _healthy_cams(*, guest_ready: bool = True) -> dict:
    return {
        "CAM-HOST":  {"role": "host",  "healthy": True, "epoch": 1,
                      "confirmed_guest_ids": [], "evidence_age_s": 999.0,
                      "guest_ready": True},
        "CAM-GUEST": {"role": "guest", "healthy": True, "epoch": 1,
                      "confirmed_guest_ids": ["sarah", "daniel"],
                      "evidence_age_s": 0.4, "guest_ready": guest_ready},
        "CAM-WIDE":  {"role": "wide",  "healthy": True, "epoch": 1,
                      "confirmed_guest_ids": [], "evidence_age_s": 999.0,
                      "guest_ready": True},
    }


def _final_daniel_parse_fn():
    """Parser that always returns 'Daniel NOW' — the corrected target."""
    def _p(text: str):
        return Cue(
            target_guest_ids=["daniel"], scope=Scope.SINGLE,
            intent=Intent.INTRODUCE, temporal_intent=TemporalIntent.NOW,
            action=Action.SHOW, evidence_text=text,
        ), 1.0
    return _p


def _stale_parse_fn():
    """Parser that always returns 'Sarah NOW'; used with a stale mode_revision."""
    def _p(text: str):
        return Cue(
            target_guest_ids=["sarah"], scope=Scope.SINGLE,
            intent=Intent.INTRODUCE, temporal_intent=TemporalIntent.NOW,
            action=Action.SHOW, evidence_text=text,
        ), 1.0
    return _p


@pytest.fixture
def emissions() -> list[DecisionRecord]:
    return []


def test_split_correction_yields_one_take(emissions):
    """Two Deepgram finals in one utterance -> exactly one TAKE (Daniel)."""
    lane = CLane(
        parse_fn=_final_daniel_parse_fn(),
        emit=emissions.append,
        role_based=True, role_map=ROLE_MAP,
        initial_camera="CAM-HOST",
        camera_state_max_age_s=60.0,
    )
    lane.on_camera_state(_healthy_cams(), now=1.0)

    # Deepgram frame 1: partial finalise for "Please welcome Sarah..."
    lane.on_transcript_message({
        "type": "Results",
        "is_final": True, "speech_final": False,
        "audio_epoch": 1,
        "start": 0.0, "duration": 1.0,
        "channel": {"alternatives": [{
            "transcript": "Please welcome Sarah",
            "words": [
                {"word": "Please",  "start": 0.0, "end": 0.4, "confidence": 0.9},
                {"word": "welcome", "start": 0.4, "end": 0.8, "confidence": 0.9},
                {"word": "Sarah",   "start": 0.8, "end": 1.0, "confidence": 0.9},
            ],
        }]},
    }, now=1.1)

    # Deepgram frame 2: final commit with the correction; speech_final=True
    # closes the utterance so the assembler flushes one FinalUtterance.
    lane.on_transcript_message({
        "type": "Results",
        "is_final": True, "speech_final": True,
        "audio_epoch": 1,
        "start": 1.0, "duration": 1.5,
        "channel": {"alternatives": [{
            "transcript": "actually, Daniel.",
            "words": [
                {"word": "actually", "start": 1.0, "end": 1.5, "confidence": 0.9},
                {"word": "Daniel",   "start": 1.5, "end": 2.0, "confidence": 0.9},
            ],
        }]},
    }, now=1.6)

    takes = [r for r in emissions if r.action == "TAKE"]
    assert len(takes) == 1, (
        f"expected exactly one TAKE for the correction; got {len(takes)}: "
        f"{[(r.action, r.camera_id, r.reason) for r in emissions]}"
    )
    assert takes[0].camera_id == "CAM-GUEST"
    # The transcript span should show the joined text.
    assert "Daniel" in (takes[0].transcript_span or {}).get("text", "")


def test_late_cue_after_manual_hold_is_rejected_by_mode_revision(emissions):
    """A stale-revision cue arriving after HOLD stays on HOLD (STAY, not TAKE)."""
    lane = CLane(
        parse_fn=_stale_parse_fn(),
        emit=emissions.append,
        role_based=True, role_map=ROLE_MAP,
        initial_camera="CAM-HOST",
        camera_state_max_age_s=60.0,
    )
    lane.on_camera_state(_healthy_cams(), now=1.0)

    # Producer presses HOLD -> mode_revision bumps.
    lane.on_manual("HOLD", now=1.05)
    prev_rev = lane.mode_revision

    # A late Deepgram result arrives, but it was interpreted before the HOLD.
    # We inject it via on_transcript_message; the FinalUtterance carries the
    # mode_revision the queue captured at submit time. To simulate a stale
    # cue, we submit a FinalUtterance and then bump the session revision
    # under the queue by pressing HOLD again before drain.
    #
    # Simpler pathway: submit directly through the internal queue with an
    # older mode_revision. (This is what happens in production when the
    # parser was mid-flight during the manual HOLD.)
    lane._queue.submit(  # noqa: SLF001 -- deliberate for the test
        utterance="Sarah, come up.",
        mode_revision=prev_rev - 1,  # stale
        now=1.10,
        utterance_id="utt-late",
        created_at=1.09,
    )
    lane.tick(now=1.12)  # flushes the assembler + drains the queue

    # Every emission must NOT be a TAKE to CAM-GUEST.
    takes = [r for r in emissions if r.action == "TAKE"]
    assert not any(r.camera_id == "CAM-GUEST" for r in takes), (
        f"late cue was NOT rejected: {[(r.action, r.camera_id, r.reason) for r in emissions]}"
    )
